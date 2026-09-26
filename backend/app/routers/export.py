"""Batch asset export router.

Endpoints:
- POST /api/export/batch: Enqueue a background Celery task to zip selected assets + derivatives.
- GET /api/export/{task_id}: Get export job status and presigned download URL when complete.
- GET /api/export/status/{task_id}: Alias for status polling.
- GET /api/export/download/{task_id}: Get download URL for a completed export.
"""

import uuid
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset, Task
from app.schemas import AssetBatchExportIn, AssetBatchExportOut, ExportStatusOut
from app.storage import generate_url
from app.tasks import export_assets_zip

router = APIRouter(tags=["export"])


@router.post("/api/export/batch", response_model=AssetBatchExportOut)
def export_batch_assets(payload: AssetBatchExportIn, db: Session = Depends(get_db)):
    """Dispatch an async background job to zip the requested assets and their derivatives."""
    if not payload.asset_ids:
        raise HTTPException(
            status_code=400,
            detail="No assets selected for export. At least one asset id must be provided.",
        )

    # Validate that all requested assets exist in the database
    assets = db.query(MediaAsset).filter(MediaAsset.id.in_(payload.asset_ids)).all()
    found_ids = {a.id for a in assets}
    missing_ids = [aid for aid in payload.asset_ids if aid not in found_ids]
    if missing_ids:
        raise HTTPException(
            status_code=400,
            detail=f"Asset id(s) not found: {missing_ids}",
        )

    task_id = str(uuid.uuid4())
    db_task = Task(
        task_id=task_id,
        name="batch_export",
        status="PENDING",
        progress=0,
    )
    db.add(db_task)
    db.commit()

    export_assets_zip.apply_async(
        args=[payload.asset_ids, payload.include_derivatives],
        task_id=task_id,
    )

    return AssetBatchExportOut(
        message="Batch export initiated successfully",
        task_id=task_id,
        status="PENDING",
    )


@router.get("/api/export/{task_id}", response_model=ExportStatusOut)
@router.get("/api/export/status/{task_id}", response_model=ExportStatusOut)
def get_export_status(task_id: str, db: Session = Depends(get_db)):
    """Retrieve runtime progress and presigned download URL for an export job."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    download_url: Optional[str] = None
    filename: Optional[str] = None
    if db_task.status == "COMPLETED":
        export_key = f"exports/export_{task_id}.zip"
        download_url = generate_url(export_key)
        filename = f"export_{task_id}.zip"

    return ExportStatusOut(
        task_id=task_id,
        status=db_task.status,
        progress=db_task.progress,
        download_url=download_url,
        filename=filename,
        error=db_task.error,
    )


@router.get("/api/export/download/{task_id}")
def get_export_download(task_id: str, db: Session = Depends(get_db)):
    """Get presigned download URL for a completed export task."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Export task not found")

    if db_task.status != "COMPLETED":
        raise HTTPException(
            status_code=400,
            detail=f"Export task is {db_task.status}, not completed",
        )

    export_key = f"exports/export_{task_id}.zip"
    download_url = generate_url(export_key)
    return {
        "task_id": task_id,
        "download_url": download_url,
        "filename": f"export_{task_id}.zip",
    }
