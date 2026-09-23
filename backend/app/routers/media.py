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


def _serialize_asset(asset: MediaAsset) -> dict:
    return {
        "id": asset.id,
        "title": asset.title,
        "file_path": asset.file_path,
        "file_size": asset.file_size,
        "content_type": asset.content_type,
        "duration": asset.duration,
        "url": generate_url(asset.file_path) if asset.file_path else "",
        "created_at": asset.created_at.isoformat() if asset.created_at else None,
    }


@router.get("/api/media")
def list_media(db: Session = Depends(get_db)):
    assets = db.query(MediaAsset).all()
    return [_serialize_asset(asset) for asset in assets]


@router.get("/api/media/search")
def search_media(
    query: str = Query(...),
    limit: int = Query(10),
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
            assets = (
                db.query(MediaAsset)
                .filter(MediaAsset.embedding.isnot(None))
                .order_by(MediaAsset.embedding.cosine_distance(query_embedding))
                .limit(limit)
                .all()
            )
        else:
            # SQLite / test fallback: calculate distance over assets with embeddings
            candidates = (
                db.query(MediaAsset).filter(MediaAsset.embedding.isnot(None)).all()
            )
            if candidates:
                candidates_ranked = sorted(
                    candidates,
                    key=lambda a: compute_cosine_distance(a.embedding, query_embedding),
                )
                assets = candidates_ranked[:limit]
            else:
                assets = []

        # If vector search yielded no results (e.g. rows without embeddings), fallback to ILIKE
        if not assets:
            assets = (
                db.query(MediaAsset)
                .filter(MediaAsset.title.ilike(f"%{query}%"))
                .limit(limit)
                .all()
            )
    except Exception as db_err:
        logger.warning(f"Vector search failed, falling back to text search: {db_err}")
        db.rollback()
        assets = (
            db.query(MediaAsset)
            .filter(MediaAsset.title.ilike(f"%{query}%"))
            .limit(limit)
            .all()
        )

    return [_serialize_asset(asset) for asset in assets]


@router.post("/api/media/backfill-embeddings")
def backfill_embeddings_endpoint(db: Session = Depends(get_db)):
    """Backfill missing 384-dimensional embeddings for MediaAsset rows."""
    count = backfill_media_embeddings(db)
    return {"status": "ok", "backfilled": count}
