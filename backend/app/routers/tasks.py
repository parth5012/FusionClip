"""Celery task dispatch, status polling task-update WebSocket feed."""

import asyncio
import json
import logging
from datetime import datetime, timezone
from typing import Optional, List


import redis
import uuid
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session
from sqlalchemy import desc, func
from pydantic import BaseModel

from app.celery_app import celery
from app.config import settings
from app.tasks import process_multimedia_task, process_upscale_task, exponential_backoff
from app.deps import get_db
from app.models import Task

logger = logging.getLogger(__name__)

redis_client = redis.from_url(settings.REDIS_URL)
router = APIRouter(tags=["tasks"])

ALLOWED_TASK_TYPES = frozenset(
    {"transcode", "thumbnail", "waveform", "audio_extract", "upscale", "video_upscale"}
)


@router.post("/api/tasks/process")
def run_processing_pipeline(
    path: str = Query(..., description="Key of the object to process"),
    task_type: str = Query(
        "transcode",
        description="Pipeline type: transcode, audio_extract, thumbnail, waveform, upscale, video_upscale",
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
    temporal_strength: Optional[float] = Query(
        None, description="video_upscale: motion-aware temporal blend 0..1 (0 = off)"
    ),
):
    """Dispatch long-running celery worker multimedia task processing pipeline."""
    if task_type not in ALLOWED_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Allowed types: {sorted(ALLOWED_TASK_TYPES)}",
        )
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
    if temporal_strength is not None:
        kwargs["temporal_strength"] = temporal_strength
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


RUNNING_STATUSES = frozenset({"PROCESSING", "PROGRESS", "RUNNING", "RETRYING"})
PENDING_STATUSES = frozenset({"PENDING", "PENDING_RETRY", "QUEUED", "WAITING"})
FAILED_STATUSES = frozenset({"FAILED", "FAILURE"})
COMPLETED_STATUSES = frozenset({"COMPLETED", "SUCCESS"})


class TaskCountsResponse(BaseModel):
    running: int = 0
    pending: int = 0
    failed: int = 0
    completed: int = 0


@router.get("/api/tasks/counts", response_model=TaskCountsResponse)
def get_task_counts(db: Session = Depends(get_db)):
    """Retrieve running/pending/failed/completed counts across DB and Celery Redis queues."""
    status_counts = (
        db.query(func.upper(Task.status), func.count(Task.id))
        .group_by(func.upper(Task.status))
        .all()
    )
    running = 0
    pending = 0
    failed = 0
    completed = 0
    for raw_status, count in status_counts:
        if not raw_status:
            continue
        status = raw_status.strip()
        if status in RUNNING_STATUSES:
            running += count
        elif status in PENDING_STATUSES:
            pending += count
        elif status in FAILED_STATUSES:
            failed += count
        elif status in COMPLETED_STATUSES:
            completed += count

    # Redis Celery broker queue backlog
    redis_pending = 0
    if redis_client:
        celery_queues = ["celery", "media.fast", "media.heavy"]
        for q in celery_queues:
            try:
                q_len = redis_client.llen(q)
                if q_len:
                    redis_pending += int(q_len)
            except Exception as e:
                logger.warning(f"Failed to inspect Redis queue length for '{q}': {e}")
    pending += redis_pending

    return TaskCountsResponse(
        running=running,
        pending=pending,
        failed=failed,
        completed=completed,
    )


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
            else:
                await asyncio.sleep(0.01)
    except WebSocketDisconnect:
        logger.info("WebSocket connection disconnected")
    except Exception as e:
        logger.warning(f"WebSocket tasks connection error: {e}")
    finally:
        try:
            pubsub.unsubscribe("task_updates")
            pubsub.close()
        except Exception:
            pass


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

