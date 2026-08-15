"""Celery task dispatch, status polling task-update WebSocket feed."""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional, List


import redis
import uuid
from celery.result import AsyncResult
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import desc
from pydantic import BaseModel

from app.celery_app import celery
from app.config import settings
from app.tasks import process_multimedia_task, process_upscale_task, exponential_backoff
from app.deps import get_db
from app.models import Task

logger = logging.getLogger(__name__)

redis_client = redis.from_url(settings.REDIS_URL)
router = APIRouter(tags=["tasks"])


@router.post("/api/tasks/process")
def run_processing_pipeline(
    path: str = Query(..., description="Key of the object to process"),
    task_type: str = Query(
        "transcode", description="Generation pipeline: transcode, audio_extract, upscale"
    ),
    denoise: Optional[float] = Query(
        None, description="Upscale: Denoising Strength (Creativity)"
    ),
    controlnet_weight: Optional[float] = Query(
        None, description="Upscale: ControlNet Weight (Resemblance)"
    ),
    hdr: Optional[float] = Query(None, description="Upscale: HDR post-pass strength"),
    fractality: Optional[float] = Query(
        None, description="Upscale: Fractality noise + guidance bump"
    ),
    prompt: Optional[str] = Query(
        None, description="Upscale: optional img2img positive prompt"
    ),
):
    """Dispatch long-running celery worker multimedia task processing pipeline."""
    kwargs = {}
    if denoise is not None:
        kwargs["denoise"] = denoise
    if controlnet_weight is not None:
        kwargs["controlnet_weight"] = controlnet_weight
    if hdr is not None:
        kwargs["hdr"] = hdr
    if fractality is not None:
        kwargs["fractality"] = fractality
    if prompt is not None:
        kwargs["prompt"] = prompt
    task = process_multimedia_task.delay(path, task_type, **kwargs)
    return {
        "message": "Processing pipeline initiated successfully",
        "task_id": task.id,
        "status": task.status,
    }


@router.get("/api/tasks/status/{task_id}")
def get_task_status(task_id: str):
    """Retrieve runtime state progress background running Celery job."""
    res = AsyncResult(task_id, app=celery)

    response = {
        "id": task_id,
        "state": res.state,
        "info": None,
    }

    if res.state == "PROGRESS":
        response["info"] = res.info
    elif res.state == "SUCCESS":
        response["info"] = res.result
    elif res.state == "FAILURE":
        response["info"] = str(res.result)

    return response


@router.get("/api/tasks/list")
def list_tasks(
    page: int = Query(1, ge=1, description="Page number"),
    page_size: int = Query(50, ge=1, le=200, description="Items per page"),
    status: str = None,
    task_type: str = None,
    search: str = None,
    db: Session = Depends(get_db),
):
    """List persisted tasks with optional filtering pagination and search."""
    query = db.query(Task)

    if status:
        query = query.filter(Task.status == status.upper())
    if task_type:
        query = query.filter(Task.name == task_type)
    if search:
        query = query.filter(
            Task.error.contains(search) | Task.traceback.contains(search)
        )

    total = query.count()
    tasks = (
        query.order_by(Task.created_at.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "tasks": [
            {
                "id": t.id,
                "task_id": t.task_id,
                "name": t.name,
                "status": t.status,
                "progress": t.progress,
                "error": t.error,
                "logs": t.logs,
                "traceback": t.traceback,
                "error_type": t.error_type,
                "retry_count": t.retry_count,
                "max_retries": t.max_retries,
                "last_retry_at": t.last_retry_at.isoformat() if t.last_retry_at else None,
                "created_at": t.created_at.isoformat() if t.created_at else None,
                "updated_at": t.updated_at.isoformat() if t.updated_at else None,
            }
            for t in tasks
        ],
    }


@router.post("/api/tasks/{task_id}/retry")
def retry_task(task_id: str, db: Session = Depends(get_db)):
    """Manually retry failed task."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    if db_task.status != "FAILED":
        raise HTTPException(status_code=400, detail="Only failed tasks can be retried")

    # Reset task status for retry
    db_task.status = "PENDING"
    db_task.progress = 0
    db_task.error = None
    db_task.last_retry_at = datetime.now(timezone.utc)
    db_task.retry_count = db_task.retry_count + 1
    db.commit()

    # Re-dispatch task
    result = process_multimedia_task.delay(
        object_name=db_task.name,
        task_type=db_task.name
    )

    logger.info(f"Manual retry task {task_id} dispatched {result.id}")

    return {
        "message": "Task retry initiated",
        "original_task_id": task_id,
        "new_task_id": result.id,
        "retry_count": db_task.retry_count,
    }


@router.websocket("/api/ws/tasks")
async def websocket_tasks_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted for tasks subscription")

    pubsub = redis_client.pubsub()
    pubsub.subscribe("task_updates")

    try:
        while True:
            message = pubsub.get_message(ignore_subscribe_messages=True)
            if message:
                data = message.get("data")
                if isinstance(data, bytes):
                    data = data.decode()
                data = json.loads(data)
                await websocket.send_json(data)
    except WebSocketDisconnect:
        logger.info("WebSocket connection disconnected")
    finally:
        pubsub.unsubscribe("task_updates")
        pubsub.close()


class UpscaleRequest(BaseModel):
    denoising_strength: float = 0.35
    controlnet_weight: float = 1.25
    preset: str = "Portraits"
    preview: bool = False


@router.post("/api/upscale")
def run_upscale_pipeline(
    path: str = Query(..., description="Key of the image object to upscale"),
    request: UpscaleRequest = None,
    db: Session = Depends(get_db)
):
    """Orchestrate upscale task: creates database entry and dispatches Celery task."""
    task_id = f"upscale_{uuid.uuid4().hex[:8]}"

    # Create database task record
    db_task = Task(task_id=task_id, name="upscale", status="PROCESSING", progress=0)
    db.add(db_task)
    db.commit()

    params = request.dict() if request else {}
    process_upscale_task.delay(task_id, path, params)

    return {
        "message": "Upscale task initiated successfully",
        "task_id": task_id,
        "status": "PROCESSING",
    }


class TaskListItem(BaseModel):
    id: int
    task_id: str
    name: str
    status: str
    progress: int
    error: Optional[str] = None
    error_type: Optional[str] = None
    traceback: Optional[str] = None
    retry_count: int
    max_retries: int
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class TaskListResponse(BaseModel):
    tasks: List[TaskListItem]
    total: int
    page: int
    page_size: int


class ErrorTypesResponse(BaseModel):
    error_types: List[str]


class RetryResponse(BaseModel):
    message: str
    task_id: str


@router.get("/api/tasks/list", response_model=TaskListResponse)
def list_tasks(
    page: int = Query(1, ge=1),
    page_size: int = Query(25, ge=1, le=100),
    status_filter: Optional[str] = Query(None, alias="status"),
    task_type: Optional[str] = Query(None, alias="type"),
    search: Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """List tasks with pagination, filtering, and search."""
    query = db.query(Task)

    if status_filter:
        query = query.filter(Task.status == status_filter)
    if task_type:
        query = query.filter(Task.name == task_type)
    if search:
        query = query.filter(
            Task.name.contains(search) | Task.error.contains(search)
        )

    total = query.count()
    tasks = query.order_by(desc(Task.created_at)).offset((page - 1) * page_size).limit(page_size).all()

    return TaskListResponse(
        tasks=[
            TaskListItem(
                id=t.id,
                task_id=t.task_id,
                name=t.name,
                status=t.status,
                progress=t.progress,
                error=t.error,
                error_type=t.error_type,
                traceback=t.traceback,
                retry_count=t.retry_count,
                max_retries=t.max_retries,
                created_at=t.created_at.isoformat() if t.created_at else None,
                updated_at=t.updated_at.isoformat() if t.updated_at else None,
            )
            for t in tasks
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/api/tasks/errors/types", response_model=ErrorTypesResponse)
def get_error_types():
    """Return available error type categories."""
    return ErrorTypesResponse(error_types=["OOM", "timeout", "validation", "runtime"])


@router.post("/api/tasks/{task_id}/retry", response_model=RetryResponse)
def retry_task(task_id: str, db: Session = Depends(get_db)):
    """Manually retry a failed task."""
    db_task = db.query(Task).filter(Task.task_id == task_id).first()
    if not db_task:
        raise HTTPException(status_code=404, detail="Task not found")

    if db_task.status not in ("FAILED", "PENDING_RETRY"):
        raise HTTPException(status_code=400, detail=f"Cannot retry task in {db_task.status} status")

    db_task.status = "PROCESSING"
    db_task.error = None
    db_task.error_type = None
    db_task.traceback = None
    db_task.retry_count = 0
    db_task.last_retry_at = datetime.utcnow()
    db.commit()

    if db_task.name == "upscale":
        process_multimedia_task.delay("", "transcode")
    else:
        process_multimedia_task.delay("", db_task.name)

    return RetryResponse(message="Task queued for retry", task_id=task_id)

