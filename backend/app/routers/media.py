"""Media library listing and search endpoints."""

import logging

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset
from app.storage import generate_url

logger = logging.getLogger(__name__)

router = APIRouter(tags=["media"])


def _serialize_asset(asset: MediaAsset, upscaled_children: list = None, score: float = None) -> dict:
    return {
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
    # Vector semantic search with fallback to standard text search
    try:
        from app.tasks import CLIPEmbedder
        query_embedding = CLIPEmbedder.embed_text(query)

        cosine_dist = MediaAsset.embedding.cosine_distance(query_embedding)
        vector_results = (
            db.query(MediaAsset, cosine_dist.label("dist"))
            .filter(MediaAsset.embedding != None)
            .order_by(cosine_dist)
            .limit(limit * 2)
            .all()
        )

        text_matches = (
            db.query(MediaAsset)
            .filter(MediaAsset.title.ilike(f"%{query}%"))
            .limit(limit * 2)
            .all()
        )

        candidates = {}
        for asset, dist in vector_results:
            sim = 1.0 - float(dist)
            candidates[asset.id] = {
                "asset": asset,
                "semantic_score": sim,
                "text_score": 0.0
            }

        for asset in text_matches:
            if asset.id not in candidates:
                sim = 0.0
                if asset.embedding is not None:
                    sim = 0.5
                candidates[asset.id] = {
                    "asset": asset,
                    "semantic_score": sim,
                    "text_score": 1.0
                }
            else:
                candidates[asset.id]["text_score"] = 1.0

        hybrid_results = []
        for info in candidates.values():
            score = 0.7 * info["semantic_score"] + 0.3 * info["text_score"]
            hybrid_results.append((info["asset"], score))

        filtered_results = [
            (asset, score) for asset, score in hybrid_results
            if score >= threshold
        ]
        filtered_results.sort(key=lambda x: x[1], reverse=True)
        
        return [_serialize_asset(asset, score=score) for asset, score in filtered_results[:limit]]

    except Exception as db_err:
        logger.warning(f"Vector search failed, falling back to text search: {db_err}")
        db.rollback()
        assets = (
            db.query(MediaAsset)
            .filter(MediaAsset.title.ilike(f"%{query}%"))
            .limit(limit)
            .all()
        )

    return _serialize_catalog(db, assets)

