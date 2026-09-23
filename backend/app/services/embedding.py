"""Embedding service for semantic media search (#80).

Uses local sentence-transformers all-MiniLM-L6-v2 (384 dimensions)
via fastembed (ONNX runtime on CPU) or sentence_transformers.
"""

from __future__ import annotations

import logging
import math
from typing import TYPE_CHECKING, List, Optional

if TYPE_CHECKING:
    from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

EMBEDDING_DIM = 384
MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"

_model_instance = None


def get_model():
    """Lazy-load and cache the embedding model."""
    global _model_instance
    if _model_instance is not None:
        return _model_instance

    try:
        from fastembed import TextEmbedding

        _model_instance = TextEmbedding(MODEL_NAME)
        logger.info(f"Loaded embedding model via fastembed: {MODEL_NAME}")
        return _model_instance
    except Exception as fe_err:
        logger.warning(f"Could not initialize fastembed model: {fe_err}")

    try:
        from sentence_transformers import SentenceTransformer

        _model_instance = SentenceTransformer(MODEL_NAME)
        logger.info(f"Loaded embedding model via sentence-transformers: {MODEL_NAME}")
        return _model_instance
    except Exception as st_err:
        logger.warning(f"Could not initialize sentence-transformers model: {st_err}")

    return None


def get_embedding(text: str) -> List[float]:
    """Generate a normalized 384-dimensional embedding for the given text."""
    clean_text = (text or "").strip()
    if not clean_text:
        return [0.0] * EMBEDDING_DIM

    model = get_model()
    if model is not None:
        try:
            # fastembed
            if hasattr(model, "embed"):
                embeddings = list(model.embed([clean_text]))
                if embeddings:
                    vec = [float(x) for x in embeddings[0]]
                    # Ensure exact dimension
                    if len(vec) == EMBEDDING_DIM:
                        return _normalize(vec)
            # sentence_transformers
            elif hasattr(model, "encode"):
                arr = model.encode(clean_text)
                vec = [float(x) for x in arr]
                if len(vec) == EMBEDDING_DIM:
                    return _normalize(vec)
        except Exception as err:
            logger.error(f"Failed to generate model embedding: {err}")

    # Fallback: deterministic unit vector for graceful degradation / offline test runs
    return _deterministic_fallback_embedding(clean_text)


def _normalize(vec: List[float]) -> List[float]:
    norm = math.sqrt(sum(x * x for x in vec))
    if norm < 1e-9:
        return vec
    return [x / norm for x in vec]


def _deterministic_fallback_embedding(text: str) -> List[float]:
    """Deterministic 384-dim pseudo-embedding derived from hash for offline fallback."""
    import hashlib

    hasher = hashlib.sha256(text.encode("utf-8"))
    digest = hasher.digest()
    vec = []
    for i in range(EMBEDDING_DIM):
        byte_val = digest[i % len(digest)]
        # Mix with position
        val = math.sin((byte_val + i) * 0.1)
        vec.append(val)
    return _normalize(vec)


def compute_cosine_distance(v1: List[float], v2: List[float]) -> float:
    """Compute cosine distance (1.0 - cosine_similarity). Lower is closer."""
    dot = sum(a * b for a, b in zip(v1, v2))
    norm1 = math.sqrt(sum(a * a for a in v1))
    norm2 = math.sqrt(sum(b * b for b in v2))
    if norm1 < 1e-9 or norm2 < 1e-9:
        return 1.0
    sim = dot / (norm1 * norm2)
    # Clip between -1.0 and 1.0 to guard against precision float errors
    sim = max(-1.0, min(1.0, sim))
    return 1.0 - sim


def compute_l2_distance(v1: List[float], v2: List[float]) -> float:
    """Compute Euclidean (L2) distance."""
    return math.sqrt(sum((a - b) ** 2 for a, b in zip(v1, v2)))


def backfill_media_embeddings(db: Session, batch_size: int = 100) -> int:
    """Backfill missing embeddings for existing MediaAsset rows using their title."""
    from app.models import MediaAsset

    unembedded = (
        db.query(MediaAsset)
        .filter(MediaAsset.embedding.is_(None))
        .limit(batch_size)
        .all()
    )
    total_updated = 0
    while unembedded:
        for asset in unembedded:
            text = asset.title or asset.file_path or ""
            asset.embedding = get_embedding(text)
            total_updated += 1
        db.commit()

        # Fetch next batch
        unembedded = (
            db.query(MediaAsset)
            .filter(MediaAsset.embedding.is_(None))
            .limit(batch_size)
            .all()
        )

    return total_updated
