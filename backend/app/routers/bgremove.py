"""Background Removal API router (#116).

Provides:
- POST /api/bgremove: Execute background removal producing an alpha-correct derivative asset.
- GET  /api/bgremove/presets: Describe tiers and models for the UI.
- GET  /api/bgremove/tiers: Alias for presets.
- GET  /api/bgremove/status/{task_id}: Check background removal task status.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.ml.bgremove import (
    MAX_IMAGE_PATH_LENGTH,
    SUPPORTED_TIERS,
    TIER_FAST,
    VIDEO_EXTENSIONS,
    describe_bgremove_surface,
    run_background_removal,
)
from app.models import MediaAsset, Task
from app.routers.generate import SAFE_REFERENCE_PATTERN
from app.storage import generate_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/bgremove", tags=["bgremove"])


class BgRemoveRequest(BaseModel):
    """Payload for background removal endpoint."""

    image_path: str = Field(
        ...,
        description="Relative catalog file_path of the source image in storage",
    )
    tier: Optional[str] = Field(
        default=None,
        description="Model tier: 'fast' (rembg+u2net) or 'quality' (birefnet-general)",
    )
    quality: Optional[str] = Field(
        default=None,
        description="Alias for tier: 'fast' or 'quality'",
    )


def _is_safe_image_path_chars(value: str) -> bool:
    """Character-class check against the shared SAFE_REFERENCE_PATTERN.

    Spaces are permitted (as documented in skin_enhance.py:125 and LEARNINGS.md #211):
    uploads keep user's original filenames as object keys (e.g. 'uploads/my photo.png').
    Checking value.replace(' ', '') keeps SAFE_REFERENCE_PATTERN the single source
    of truth for the character class while still refusing everything else.
    """
    return bool(SAFE_REFERENCE_PATTERN.match(value.replace(" ", "")))


def _validate_safe_image_path(value: str) -> str:
    """Validate relative image path against traversal and disallowed characters."""
    if not value or not value.strip():
        raise HTTPException(
            status_code=400,
            detail="image_path must be a non-empty string.",
        )

    val = value.strip()
    if (
        ".." in val
        or val.startswith("/")
        or "\\" in val
        or len(val) > MAX_IMAGE_PATH_LENGTH
        or not _is_safe_image_path_chars(val)
    ):
        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid image_path {val!r}: must be a non-empty relative catalog "
                "file_path (subfolders allowed) with no '..', no leading '/', no "
                "backslashes and no other special characters."
            ),
        )

    # Check for video extensions - background removal is image-only
    lower_val = val.lower()
    if any(lower_val.endswith(ext) for ext in VIDEO_EXTENSIONS):
        raise HTTPException(
            status_code=400,
            detail=(
                f"video_input_not_supported: Cannot remove background from video '{val}'. "
                "Background removal is supported for images only."
            ),
        )

    return val


@router.get("/presets")
def get_bgremove_presets() -> Dict[str, Any]:
    """Return available model tiers, models, and descriptions for the UI."""
    return describe_bgremove_surface()


@router.get("/tiers")
def get_bgremove_tiers() -> Dict[str, Any]:
    """Alias for /presets describing the background removal surface."""
    return describe_bgremove_surface()


@router.post("")
def remove_background(
    payload: BgRemoveRequest,
    db: Session = Depends(get_db),
):
    """Isolate subject, produce alpha-correct PNG derivative linked to source.

    Returns COMPLETED with derivative asset metadata on success, or a degraded
    envelope at HTTP 200 on GPU absence / VRAM refusal / missing weights.
    Client-side bad inputs (missing source, video format, path traversal, unknown
    tier) return HTTP 400 with a descriptive error.
    """
    image_path = _validate_safe_image_path(payload.image_path)

    # Resolve tier: accept tier or quality, defaulting to 'fast'
    raw_tier = payload.tier if payload.tier is not None else payload.quality
    tier = (raw_tier or TIER_FAST).strip().lower()

    if tier not in SUPPORTED_TIERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported background removal tier '{raw_tier}'. "
                f"Supported tiers: {', '.join(sorted(SUPPORTED_TIERS))}."
            ),
        )

    logger.info(f"Background removal requested: path='{image_path}' tier='{tier}'")

    return run_background_removal(
        image_path=image_path,
        tier=tier,
        db=db,
    )


@router.get("/status/{task_id}")
def get_bgremove_status(task_id: str, db: Session = Depends(get_db)):
    """Retrieve runtime progress and output details of a background removal task."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail=f"Task '{task_id}' not found")

    output_path = None
    result_url = None

    if db_task.status == "COMPLETED":
        if db_task.logs:
            try:
                import json
                logs_data = json.loads(db_task.logs)
                if isinstance(logs_data, dict) and "output" in logs_data:
                    output_path = logs_data["output"]
                    result_url = generate_url(output_path)
            except Exception:
                pass

        if not output_path and task_id.startswith("bgremove_"):
            task_token = task_id.split("_", 1)[-1]
            candidate = (
                db.query(MediaAsset)
                .filter(MediaAsset.file_path.contains(task_token))
                .first()
            )
            if candidate:
                output_path = candidate.file_path
                result_url = generate_url(candidate.file_path)

    return {
        "task_id": db_task.task_id,
        "name": db_task.name,
        "status": db_task.status,
        "progress": db_task.progress,
        "error": db_task.error,
        "logs": db_task.logs,
        "output_path": output_path,
        "result_url": result_url,
    }
