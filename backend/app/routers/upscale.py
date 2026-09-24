"""Upscaler API Router (#94).

Dedicated endpoint for Magnific-style generative tile upscaling.
"""

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset, Task
from app.services.upscaler import (
    CONTENT_CATEGORIES,
    PRESET_DEFINITIONS,
    execute_upscale_job,
    map_creativity_to_denoise,
    map_resemblance_to_controlnet,
)
from app.storage import generate_url

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/upscale", tags=["upscale"])

ALLOWED_SCALES = {2, 4, 8, 16}


class UpscaleRequest(BaseModel):
    image_path: str = Field(..., description="Path or key of the image object in MinIO")
    scale: int = Field(4, description="Upscale factor: 2, 4, 8, or 16")
    preset: Optional[str] = Field("vivid", description="Preset: subtle, vivid, wild, or custom")
    creativity: Optional[float] = Field(None, description="Creativity level [-10..+10]")
    resemblance: Optional[float] = Field(None, description="Resemblance level [-10..+10]")
    fractality: Optional[float] = Field(None, description="Fractality level [-10..+10]")
    hdr: Optional[float] = Field(None, description="HDR / contrast level [-10..+10]")
    category: Optional[str] = Field("universal", description="Content category")
    prompt: Optional[str] = Field(None, description="Optional prompt guidance")


@router.post("")
def trigger_upscale(
    payload: UpscaleRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
):
    """Trigger a Magnific-style generative tile upscale."""
    if payload.scale not in ALLOWED_SCALES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scale factor {payload.scale}. Allowed: {sorted(ALLOWED_SCALES)}",
        )

    preset_name = (payload.preset or "vivid").lower()
    if preset_name not in PRESET_DEFINITIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid preset '{payload.preset}'. Allowed presets: {list(PRESET_DEFINITIONS.keys())}",
        )
    preset_defaults = PRESET_DEFINITIONS[preset_name]

    creativity = payload.creativity if payload.creativity is not None else float(preset_defaults["creativity"])
    resemblance = payload.resemblance if payload.resemblance is not None else float(preset_defaults["resemblance"])
    fractality = payload.fractality if payload.fractality is not None else float(preset_defaults["fractality"])
    hdr = payload.hdr if payload.hdr is not None else float(preset_defaults["hdr"])

    for name, val in [
        ("creativity", creativity),
        ("resemblance", resemblance),
        ("fractality", fractality),
        ("hdr", hdr),
    ]:
        if val < -10.0 or val > 10.0:
            raise HTTPException(
                status_code=400,
                detail=f"Slider '{name}' value {val} must be between -10 and +10.",
            )

    category = (payload.category or "universal").lower()
    if category not in CONTENT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{payload.category}'. Allowed: {list(CONTENT_CATEGORIES.keys())}",
        )

    task_id = f"upscale_{uuid.uuid4().hex[:12]}"
    clean_stem = Path(payload.image_path).stem
    output_path = f"upscaled/{clean_stem}_{payload.scale}x_{task_id[:6]}.png"

    db_task = Task(
        task_id=task_id,
        name=f"upscale: {Path(payload.image_path).name} ({payload.scale}x)",
        status="PROCESSING",
        progress=0,
        logs=f"Queued {payload.scale}x upscale using {preset_name} preset and {category} category",
    )
    db.add(db_task)
    db.commit()

    # Dispatch to background task or thread
    background_tasks.add_task(
        execute_upscale_job,
        task_id=task_id,
        image_path=payload.image_path,
        scale=payload.scale,
        creativity=creativity,
        resemblance=resemblance,
        fractality=fractality,
        hdr=hdr,
        category=category,
        prompt=payload.prompt,
        output_path=output_path,
    )

    return {
        "message": "Upscale processing initiated successfully",
        "task_id": task_id,
        "status": "PROCESSING",
        "scale": payload.scale,
        "preset": preset_name,
        "category": category,
        "output_path": output_path,
        "parameters": {
            "creativity": creativity,
            "resemblance": resemblance,
            "fractality": fractality,
            "hdr": hdr,
            "denoise": map_creativity_to_denoise(creativity),
            "controlnet_scale": map_resemblance_to_controlnet(resemblance),
        },
    }


@router.get("/status/{task_id}")
def get_upscale_task_status(task_id: str, db: Session = Depends(get_db)):
    """Retrieve runtime progress and details of an upscale task."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail=f"Upscale task '{task_id}' not found")

    result_url = None
    output_path = None

    if db_task.status == "COMPLETED":
        # Check if output media asset exists
        asset = db.query(MediaAsset).filter(MediaAsset.title.contains(task_id[:6])).first()
        if asset:
            output_path = asset.file_path
            result_url = generate_url(asset.file_path)

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


@router.get("/presets")
def get_upscale_presets():
    """List available fidelity presets and their slider configurations."""
    return {"presets": PRESET_DEFINITIONS}


@router.get("/categories")
def get_upscale_categories():
    """List supported content categories and their enhancement prompts."""
    return {"categories": CONTENT_CATEGORIES}
