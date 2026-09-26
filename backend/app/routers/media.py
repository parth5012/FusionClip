"""Media library listing and search endpoints."""

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset, Tag
from app.schemas import AssetTagsUpdate, TagCreate, TagOut

import re
import uuid
from pathlib import Path
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Response, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset, SubtitleTrack
from app.schemas import SubtitleExtractOut, SubtitleTrackOut
from app.services.embedding import (
    backfill_media_embeddings,
    compute_cosine_distance,
    get_embedding,
)
from app.services.subtitles import (
    extract_and_save_embedded_subtitles,
    validate_and_prepare_subtitle,
)
from app.storage import delete_object, generate_url, get_object_bytes, upload_object

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])

def _parse_tag_filters(tag: Optional[List[str]], tags: Optional[str]) -> List[str]:
    result = []
    if tag:
        for t in tag:
            if t:
                for sub in t.split(","):
                    cleaned = sub.strip()
                    if cleaned and cleaned not in result:
                        result.append(cleaned)
    if tags:
        for sub in tags.split(","):
            cleaned = sub.strip()
            if cleaned and cleaned not in result:
                result.append(cleaned)
    return result

def _serialize_asset(asset: MediaAsset, upscaled_children: list = None, score: float = None) -> dict:
    res = {
        "id": asset.id,
        "title": asset.title,
        "file_path": asset.file_path,
        "file_size": asset.file_size,
        "content_type": asset.content_type,
        "duration": asset.duration,
        "url": generate_url(asset.file_path) if asset.file_path else "",
        # Before/after comparison support (#58): expose the original this
        # asset was derived from, plus any upscaled outputs derived from it.
        "source_path": asset.source_path,
        "source_url": generate_url(asset.source_path) if asset.source_path else None,
        "upscaled_assets": [
            {
                "id": child.id,
                "title": child.title,
                "file_path": child.file_path,
                "url": generate_url(child.file_path) if child.file_path else "",
            }
            for child in (upscaled_children or [])
        ],
        "tags": [
            {"id": t.id, "name": t.name}
            for t in (getattr(asset, "tags", None) or [])
        ],
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }
    if score is not None:
        res["score"] = score
    return res

def _serialize_catalog(db, assets) -> list:
    """Serialize a list of assets, attaching each asset's upscaled outputs."""
    if not assets:
        return []
    by_path = {asset.file_path: asset for asset in assets}
    children: dict = {}
    for asset in assets:
        if asset.source_path and asset.source_path in by_path:
            children.setdefault(asset.source_path, []).append(asset)
    return [
        _serialize_asset(asset, children.get(asset.file_path, [])) for asset in assets
    ]

def _serialize_search(db, ranked) -> list:
    """Serialize ranked (asset, score) pairs with upscaled-output children."""
    if not ranked:
        return []
    paths = [asset.file_path for asset, _ in ranked]
    children: dict = {}
    for child in db.query(MediaAsset).filter(MediaAsset.source_path.in_(paths)).all():
        children.setdefault(child.source_path, []).append(child)
    return [
        _serialize_asset(asset, children.get(asset.file_path, []), score=score)
        for asset, score in ranked
    ]

@router.get("/api/media")
def list_media(
    tag: Optional[List[str]] = Query(None),
    tags: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    query = db.query(MediaAsset)
    filter_tags = _parse_tag_filters(tag, tags)
    for t_name in filter_tags:
        query = query.filter(MediaAsset.tags.any(func.lower(Tag.name) == t_name.lower()))
    assets = query.all()
    return _serialize_catalog(db, assets)

@router.get("/api/media/search")
def search_media(
    query: str = Query(...),
    limit: int = Query(10),
    threshold: float = Query(0.2, description="Minimum relevance score threshold"),
    tag: Optional[List[str]] = Query(None),
    tags: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Semantic vector search across media assets with ILIKE text search fallback.

    Uses real 384-dimensional sentence-transformers embeddings (all-MiniLM-L6-v2).
    On PostgreSQL + pgvector, uses native vector distance ordering.
    On non-pgvector environments (e.g. SQLite tests), calculates semantic distance in Python.
    Falls back to case-insensitive title pattern matching (ILIKE) if no embeddings match or vector search fails.
    """
    filter_tags = _parse_tag_filters(tag, tags)
    try:
        query_embedding = get_embedding(query)

        dialect_name = db.bind.dialect.name if db.bind else ""
        if dialect_name == "postgresql":
            cosine_dist = MediaAsset.embedding.cosine_distance(query_embedding)
            q = (
                db.query(MediaAsset, cosine_dist.label("dist"))
                .filter(MediaAsset.embedding.isnot(None))
            )
            for t_name in filter_tags:
                q = q.filter(MediaAsset.tags.any(func.lower(Tag.name) == t_name.lower()))
            rows = (
                q.order_by(cosine_dist)
                .limit(limit)
                .all()
            )
            ranked = [(asset, 1.0 - float(dist)) for asset, dist in rows]
        else:
            # SQLite / test fallback: calculate distance over assets with embeddings
            q = db.query(MediaAsset).filter(MediaAsset.embedding.isnot(None))
            for t_name in filter_tags:
                q = q.filter(MediaAsset.tags.any(func.lower(Tag.name) == t_name.lower()))
            candidates = q.all()
            ranked = sorted(
                (
                    (asset, 1.0 - compute_cosine_distance(asset.embedding, query_embedding))
                    for asset in candidates
                ),
                key=lambda pair: pair[1],
                reverse=True,
            )[:limit]

        # Always include literal title matches (covers rows not yet backfilled).
        t_query = db.query(MediaAsset).filter(MediaAsset.title.ilike(f"%{query}%"))
        for t_name in filter_tags:
            t_query = t_query.filter(MediaAsset.tags.any(func.lower(Tag.name) == t_name.lower()))
        text_matches = t_query.limit(limit).all()

        merged = {asset.id: (asset, score) for asset, score in ranked}
        for asset in text_matches:
            if asset.id in merged:
                prev_asset, prev_score = merged[asset.id]
                merged[asset.id] = (prev_asset, max(prev_score, 1.0))
            else:
                merged[asset.id] = (asset, 1.0)
        results = [pair for pair in merged.values() if pair[1] >= threshold]
        results.sort(key=lambda pair: pair[1], reverse=True)
        return _serialize_search(db, results[:limit])
    except Exception as db_err:
        logger.warning(f"Vector search failed, falling back to text search: {db_err}")
        db.rollback()
        q = db.query(MediaAsset).filter(MediaAsset.title.ilike(f"%{query}%"))
        for t_name in filter_tags:
            q = q.filter(MediaAsset.tags.any(func.lower(Tag.name) == t_name.lower()))
        assets = q.limit(limit).all()

        return _serialize_search(
            db, [(asset, 1.0) for asset in assets if 1.0 >= threshold]
        )

# --- Tag CRUD Endpoints ---------------------------------------------------

def _get_or_create_tag(db: Session, name: str) -> Tag:
    clean_name = name.strip()
    lower_name = clean_name.lower()
    tag = db.query(Tag).filter(func.lower(Tag.name) == lower_name).first()
    if tag:
        return tag
    try:
        with db.begin_nested():
            tag = Tag(name=clean_name)
            db.add(tag)
            db.flush()
            return tag
    except IntegrityError:
        tag = db.query(Tag).filter(func.lower(Tag.name) == lower_name).first()
        if tag:
            return tag
        raise

@router.get("/api/tags", response_model=List[TagOut])
def list_tags(db: Session = Depends(get_db)):
    """List all tags in alphabetical order."""
    tags = db.query(Tag).order_by(Tag.name.asc()).all()
    return [{"id": t.id, "name": t.name} for t in tags]

@router.post("/api/tags", response_model=TagOut, status_code=201)
def create_tag(payload: TagCreate, db: Session = Depends(get_db)):
    """Create a tag or return existing tag idempotently."""
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Tag name cannot be empty")
    tag = _get_or_create_tag(db, clean_name)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        tag = db.query(Tag).filter(func.lower(Tag.name) == clean_name.lower()).first()
        if not tag:
            raise
    else:
        db.refresh(tag)
    return {"id": tag.id, "name": tag.name}

@router.delete("/api/tags/{tag_id}")
def delete_tag(tag_id: int, db: Session = Depends(get_db)):
    """Delete a tag globally, removing it from all associated media assets."""
    tag = db.query(Tag).filter(Tag.id == tag_id).first()
    if not tag:
        raise HTTPException(status_code=404, detail="Tag not found")
    db.delete(tag)
    db.commit()
    return {"message": "Tag deleted", "id": tag_id}

@router.get("/api/media/{asset_id}/tags", response_model=List[TagOut])
def get_asset_tags(asset_id: int, db: Session = Depends(get_db)):
    """Get all tags for a specific media asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    return [{"id": t.id, "name": t.name} for t in (asset.tags or [])]

@router.post("/api/media/{asset_id}/tags", status_code=201)
def add_asset_tag(asset_id: int, payload: TagCreate, db: Session = Depends(get_db)):
    """Add a tag inline to a media asset, creating the tag if it doesn't exist."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    clean_name = payload.name.strip()
    if not clean_name:
        raise HTTPException(status_code=400, detail="Tag name cannot be empty")
    tag = _get_or_create_tag(db, clean_name)
    if tag not in asset.tags:
        asset.tags.append(tag)
        try:
            db.commit()
        except IntegrityError:
            db.rollback()
            asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
        else:
            db.refresh(asset)
    return {
        "id": tag.id,
        "name": tag.name,
        "asset_id": asset.id,
        "tags": [{"id": t.id, "name": t.name} for t in asset.tags],
    }

@router.delete("/api/media/{asset_id}/tags/{tag_id}")
def remove_asset_tag(asset_id: int, tag_id: int, db: Session = Depends(get_db)):
    """Remove a tag from a specific media asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")
    tag_to_remove = next((t for t in asset.tags if t.id == tag_id), None)
    if tag_to_remove:
        asset.tags.remove(tag_to_remove)
        db.commit()
        db.refresh(asset)
    return {
        "message": "Tag removed from asset",
        "asset_id": asset.id,
        "tag_id": tag_id,
        "tags": [{"id": t.id, "name": t.name} for t in asset.tags],
    }

@router.put("/api/media/{asset_id}/tags")
def set_asset_tags(asset_id: int, payload: AssetTagsUpdate, db: Session = Depends(get_db)):
    """Replace all tags on a media asset with the provided tag list."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail="Media asset not found")

    new_tags = []
    seen = set()
    for name in payload.tags:
        clean_name = name.strip()
        if not clean_name:
            continue
        lower_name = clean_name.lower()
        if lower_name in seen:
            continue
        seen.add(lower_name)
        tag = _get_or_create_tag(db, clean_name)
        new_tags.append(tag)

    asset.tags = new_tags
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    else:
        db.refresh(asset)
    return {
        "asset_id": asset.id,
        "tags": [{"id": t.id, "name": t.name} for t in asset.tags],
    }

@router.post("/api/media/backfill-embeddings")
def backfill_embeddings_endpoint(
    max_rows: int = 1000, db: Session = Depends(get_db)
):
    """Backfill missing 384-dimensional embeddings for MediaAsset rows.

    ``max_rows`` caps how many rows a single request may process so an
    unauthenticated call cannot synchronously re-embed the whole table.
    """
    if max_rows < 1 or max_rows > 10000:
        raise HTTPException(
            status_code=400, detail="max_rows must be between 1 and 10000"
        )
    count = backfill_media_embeddings(db, max_rows=max_rows)
    return {"status": "ok", "backfilled": count}

# --- Subtitle endpoints (#109) --------------------------------------------

def _serialize_subtitle(track: SubtitleTrack) -> dict:
    return {
        "id": track.id,
        "asset_id": track.asset_id,
        "label": track.label,
        "language": track.language,
        "file_path": track.file_path,
        "url": f"/api/media/{track.asset_id}/subtitles/{track.id}/content",
        "format": track.format,
        "track_type": track.track_type,
        "created_at": track.created_at.isoformat() if track.created_at else None,
    }

@router.get("/api/media/{asset_id}/subtitles", response_model=List[SubtitleTrackOut])
def list_asset_subtitles(asset_id: int, db: Session = Depends(get_db)):
    """List all subtitle tracks (embedded and sidecar) associated with a media asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"MediaAsset {asset_id} not found")

    tracks = db.query(SubtitleTrack).filter(SubtitleTrack.asset_id == asset_id).all()
    return [_serialize_subtitle(t) for t in tracks]

@router.post("/api/media/{asset_id}/subtitles", response_model=SubtitleTrackOut)
async def upload_asset_subtitle(
    asset_id: int,
    file: UploadFile = File(...),
    label: Optional[str] = Form(None),
    language: Optional[str] = Form(None),
    db: Session = Depends(get_db),
):
    """Upload a sidecar subtitle file (.vtt or .srt) for a media asset."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"MediaAsset {asset_id} not found")

    file_bytes = await file.read()
    vtt_content, format_type = validate_and_prepare_subtitle(file.filename or "subtitles.vtt", file_bytes)

    # Derive label from filename if omitted
    stem = Path(file.filename or "subtitles").stem
    track_label = label.strip() if label and label.strip() else stem
    track_lang = language.strip() if language and language.strip() else None

    # Upload to MinIO with unique token to prevent collisions (#109)
    safe_stem = re.sub(r"[^a-zA-Z0-9_-]", "_", stem)
    unique_token = uuid.uuid4().hex[:8]
    s3_key = f"subtitles/{asset_id}/sidecar_{safe_stem}_{unique_token}.vtt"
    success = upload_object(vtt_content.encode("utf-8"), s3_key, content_type="text/vtt")
    if not success:
        raise HTTPException(status_code=500, detail="Failed to upload subtitle file to storage")

    track = SubtitleTrack(
        asset_id=asset.id,
        label=track_label,
        language=track_lang,
        file_path=s3_key,
        format=format_type,
        track_type="sidecar",
    )
    db.add(track)
    db.commit()
    db.refresh(track)

    return _serialize_subtitle(track)

@router.post("/api/media/{asset_id}/subtitles/extract", response_model=SubtitleExtractOut)
def extract_asset_subtitles(asset_id: int, db: Session = Depends(get_db)):
    """Extract embedded subtitle tracks from the video asset into WebVTT tracks."""
    asset = db.query(MediaAsset).filter(MediaAsset.id == asset_id).first()
    if not asset:
        raise HTTPException(status_code=404, detail=f"MediaAsset {asset_id} not found")

    tracks = extract_and_save_embedded_subtitles(db, asset)
    return {
        "message": f"Successfully extracted {len(tracks)} subtitle tracks" if tracks else "No embedded subtitle tracks found",
        "extracted_count": len(tracks),
        "tracks": [_serialize_subtitle(t) for t in tracks],
    }

@router.delete("/api/media/{asset_id}/subtitles/{track_id}")
def delete_asset_subtitle(asset_id: int, track_id: int, db: Session = Depends(get_db)):
    """Delete a subtitle track from an asset."""
    track = (
        db.query(SubtitleTrack)
        .filter(SubtitleTrack.id == track_id, SubtitleTrack.asset_id == asset_id)
        .first()
    )
    if not track:
        raise HTTPException(status_code=404, detail=f"Subtitle track {track_id} not found for asset {asset_id}")

    try:
        delete_object(track.file_path)
    except Exception as e:
        logger.warning(f"Failed to delete subtitle object {track.file_path} from storage: {e}")

    db.delete(track)
    db.commit()
    return {"message": "Subtitle track deleted successfully"}

@router.get("/api/media/{asset_id}/subtitles/{track_id}/content")
def get_subtitle_content(asset_id: int, track_id: int, db: Session = Depends(get_db)):
    """Serve subtitle WebVTT content directly with CORS headers."""
    track = (
        db.query(SubtitleTrack)
        .filter(SubtitleTrack.id == track_id, SubtitleTrack.asset_id == asset_id)
        .first()
    )
    if not track:
        raise HTTPException(status_code=404, detail=f"Subtitle track {track_id} not found for asset {asset_id}")

    try:
        content = get_object_bytes(track.file_path)
    except Exception:
        raise HTTPException(status_code=404, detail="Subtitle file not found in storage")

    return Response(content=content, media_type="text/vtt; charset=utf-8")
