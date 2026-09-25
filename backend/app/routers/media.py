"""Media library listing and search endpoints."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset
from app.services.embedding import (
    backfill_media_embeddings,
    compute_cosine_distance,
    get_embedding,
)
from app.storage import generate_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])


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
def list_media(db: Session = Depends(get_db)):
    assets = db.query(MediaAsset).all()
    return _serialize_catalog(db, assets)


@router.get("/api/media/search")
def search_media(
    query: str = Query(...),
    limit: int = Query(10),
    threshold: float = Query(0.2, description="Minimum relevance score threshold"),
    db: Session = Depends(get_db),
):
    """Semantic vector search across media assets with ILIKE text search fallback.

    Uses real 384-dimensional sentence-transformers embeddings (all-MiniLM-L6-v2).
    On PostgreSQL + pgvector, uses native vector distance ordering.
    On non-pgvector environments (e.g. SQLite tests), calculates semantic distance in Python.
    Falls back to case-insensitive title pattern matching (ILIKE) if no embeddings match or vector search fails.
    """
    try:
        query_embedding = get_embedding(query)

        dialect_name = db.bind.dialect.name if db.bind else ""
        if dialect_name == "postgresql":
            cosine_dist = MediaAsset.embedding.cosine_distance(query_embedding)
            rows = (
                db.query(MediaAsset, cosine_dist.label("dist"))
                .filter(MediaAsset.embedding.isnot(None))
                .order_by(cosine_dist)
                .limit(limit)
                .all()
            )
            ranked = [(asset, 1.0 - float(dist)) for asset, dist in rows]
        else:
            # SQLite / test fallback: calculate distance over assets with embeddings
            candidates = (
                db.query(MediaAsset).filter(MediaAsset.embedding.isnot(None)).all()
            )
            ranked = sorted(
                (
                    (asset, 1.0 - compute_cosine_distance(asset.embedding, query_embedding))
                    for asset in candidates
                ),
                key=lambda pair: pair[1],
                reverse=True,
            )[:limit]

        # Always include literal title matches (covers rows not yet backfilled).
        text_matches = (
            db.query(MediaAsset)
            .filter(MediaAsset.title.ilike(f"%{query}%"))
            .limit(limit)
            .all()
        )
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
        assets = (
            db.query(MediaAsset)
            .filter(MediaAsset.title.ilike(f"%{query}%"))
            .limit(limit)
            .all()
        )

        return _serialize_search(
            db, [(asset, 1.0) for asset in assets if 1.0 >= threshold]
        )


@router.post("/api/media/backfill-embeddings")
def backfill_embeddings_endpoint(db: Session = Depends(get_db)):
    """Backfill missing 384-dimensional embeddings for MediaAsset rows."""
    count = backfill_media_embeddings(db)
    return {"status": "ok", "backfilled": count}
