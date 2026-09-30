"""Upscaler API Router (#94).

Dedicated endpoint for Magnific-style generative tile upscaling.

Two modes (#123-d11): `creative` (default — the generative slider contract above)
and `precision` (faithful SR chain with `engine`/`sharpness`/`grain`, #124).
Precision-only and Creative-only controls are rejected with a 422 on the wrong
mode — never silently ignored.
"""

import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field, ValidationError
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
from app.tasks import process_upscale_task

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
    mode: Literal["creative", "precision"] = Field(
        "creative",
        description="creative (default, generative sliders) or precision (faithful SR chain)",
    )
    # Precision-only (#123-d11): left as None (not their defaults) so the router
    # can 422 them when mode='creative' instead of silently ignoring them.
    engine: Optional[Literal["hat", "scunet"]] = Field(
        None,
        description="Precision-only SR engine (default 'hat'). Rejected when mode='creative'.",
    )
    sharpness: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Precision-only Sharpness 0-100 (UnsharpMask). Rejected when mode='creative'.",
    )
    grain: Optional[int] = Field(
        None,
        ge=0,
        le=100,
        description="Precision-only Grain 0-100 (seeded Gaussian). Rejected when mode='creative'.",
    )


class LegacyUpscaleRequest(BaseModel):
    """Celery-dispatch request shape (moved here from app.routers.tasks /api/upscale)."""

    denoising_strength: float = 0.35
    controlnet_weight: float = 1.25
    preset: str = "Portraits"
    preview: bool = False


@router.post("")
async def trigger_upscale(
    request: Request,
    background_tasks: BackgroundTasks,
    path: Optional[str] = Query(
        None, description="Legacy Celery dispatch: key of the image object to upscale"
    ),
    db: Session = Depends(get_db),
):
    """Trigger a Magnific-style tile upscale.

    With a ``path`` query parameter this preserves the legacy Celery dispatch
    flow (Task row + process_upscale_task.delay, creative mode only). Without it
    the JSON body drives the local tile-upscale pipeline in either `creative`
    (default) or `precision` (faithful SR chain, #124) mode.
    """
    raw_body = {}
    if (request.headers.get("content-type") or "").split(";")[0].strip() == "application/json":
        try:
            parsed = await request.json()
            if isinstance(parsed, dict):
                raw_body = parsed
        except Exception:
            raw_body = {}

    if path is not None:
        # The legacy Celery dispatch carries no Precision inputs — accepting them
        # here would silently drop them, which #123-d11 forbids.
        legacy_mode = raw_body.get("mode")
        legacy_precision_fields = [
            name for name in ("engine", "sharpness", "grain") if name in raw_body
        ]
        if legacy_mode not in (None, "creative") or legacy_precision_fields:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Precision mode and its controls (engine/sharpness/grain) are not "
                    "supported on the legacy Celery dispatch (?path=); POST a JSON body instead"
                ),
            )
        legacy = LegacyUpscaleRequest(**raw_body)
        task_id = f"upscale_{uuid.uuid4().hex[:8]}"
        db_task = Task(task_id=task_id, name="upscale", status="PROCESSING", progress=0)
        db.add(db_task)
        db.commit()
        process_upscale_task.apply_async(args=[task_id, path, legacy.model_dump()], task_id=task_id)
        return {
            "message": "Upscale task initiated successfully",
            "task_id": task_id,
            "status": "PROCESSING",
        }

    try:
        payload = UpscaleRequest.model_validate(raw_body)
    except ValidationError as e:
        raise HTTPException(status_code=422, detail=e.errors())
    if payload.scale not in ALLOWED_SCALES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scale factor {payload.scale}. Allowed: {sorted(ALLOWED_SCALES)}",
        )

    mode = payload.mode
    preset_name: Optional[str] = None
    engine: Optional[str] = None
    sharpness = 0
    grain = 0
    parameters: Dict[str, Any]

    if mode == "precision":
        # d8: Creativity/Resemblance/Fractality/HDR are Creative-only — reject
        # them rather than silently ignoring them.
        creative_controls = [
            name
            for name in ("creativity", "resemblance", "fractality", "hdr")
            if getattr(payload, name) is not None
        ]
        if creative_controls:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{', '.join(creative_controls)} are Creative-only controls and are "
                    "rejected when mode='precision'"
                ),
            )
        engine = payload.engine or "hat"  # d10: manual pick, default hat
        sharpness = payload.sharpness if payload.sharpness is not None else 0
        grain = payload.grain if payload.grain is not None else 0
        # Presets (clean/filmic, #142) are UI-side and not validated here yet.
        creativity = resemblance = fractality = hdr = 0.0
        parameters = {"sharpness": sharpness, "grain": grain}
    else:
        # d11: engine/sharpness/grain are Precision-only — reject them in
        # creative mode instead of silently ignoring them.
        precision_controls = [
            name for name in ("engine", "sharpness", "grain") if getattr(payload, name) is not None
        ]
        if precision_controls:
            raise HTTPException(
                status_code=422,
                detail=(
                    f"{', '.join(precision_controls)} are Precision-only controls and are "
                    "rejected when mode='creative'"
                ),
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
        parameters = {
            "creativity": creativity,
            "resemblance": resemblance,
            "fractality": fractality,
            "hdr": hdr,
            "denoise": map_creativity_to_denoise(creativity),
            "controlnet_scale": map_resemblance_to_controlnet(resemblance),
        }

    category = (payload.category or "universal").lower()
    if category not in CONTENT_CATEGORIES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid category '{payload.category}'. Allowed: {list(CONTENT_CATEGORIES.keys())}",
        )

    # Unique per-job token: task_id[:6] used to collapse to the shared
    # "upscal" prefix for every task, so concurrent jobs on the same source
    # overwrote each other's output and status lookups cross-linked (#96).
    task_token = uuid.uuid4().hex[:12]
    task_id = f"upscale_{task_token}"
    clean_stem = Path(payload.image_path).stem
    output_path = f"upscaled/{clean_stem}_{payload.scale}x_{task_token}.png"

    if mode == "precision":
        queued_log = (
            f"Queued {payload.scale}x precision upscale ({engine} engine, "
            f"sharpness {sharpness}, grain {grain}, {category} category)"
        )
    else:
        queued_log = f"Queued {payload.scale}x upscale using {preset_name} preset and {category} category"

    db_task = Task(
        task_id=task_id,
        name=f"upscale: {Path(payload.image_path).name} ({payload.scale}x)",
        status="PROCESSING",
        progress=0,
        logs=queued_log,
    )
    db.add(db_task)
    db.commit()

    # Dispatch to background task or thread
    job_kwargs: Dict[str, Any] = dict(
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
        mode=mode,
    )
    if mode == "precision":
        job_kwargs.update(engine=engine, sharpness=sharpness, grain=grain)
    background_tasks.add_task(execute_upscale_job, **job_kwargs)

    response: Dict[str, Any] = {
        "message": "Upscale processing initiated successfully",
        "task_id": task_id,
        "status": "PROCESSING",
        "scale": payload.scale,
        "mode": mode,
        "engine": engine,  # None in creative mode — no SR engine is involved
        "preset": preset_name,
        "category": category,
        "output_path": output_path,
        "parameters": parameters,
    }
    return response


@router.get("/status/{task_id}")
def get_upscale_task_status(task_id: str, db: Session = Depends(get_db)):
    """Retrieve runtime progress and details of an upscale task."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail=f"Upscale task '{task_id}' not found")

    result_url = None
    output_path = None

    if db_task.status == "COMPLETED" and task_id.startswith("upscale_"):
        # Resolve THIS task's output asset via the unique token embedded in
        # the object key — never via title, which is shared across jobs.
        # Only upscale tasks carry a token, and the router builds keys as
        # upscaled/{stem}_{scale}x_{token}.png — match that exact suffix so an
        # unrelated asset containing the token substring can never be returned.
        task_token = task_id.split("_", 1)[-1]
        candidates = (
            db.query(MediaAsset)
            .filter(MediaAsset.file_path.contains(task_token))
            .all()
        )
        asset = next(
            (
                candidate
                for candidate in candidates
                if candidate.file_path.endswith(f"_{task_token}.png")
            ),
            None,
        )
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
