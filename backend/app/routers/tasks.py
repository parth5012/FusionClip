"""Celery task dispatch, status polling and the task-update WebSocket feed."""

import asyncio
import logging

import redis
from celery.result import AsyncResult
from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.config import settings
from app.deps import get_db
from app.ml.guard import vram_guard
from app.ml.registry import model_registry
from app.models import Task
from app.schemas import (
    GPUHealthResponse,
    GPUQueueMetrics,
    GPUVRAMMetrics,
    ModelHealthInfo,
)
from app.tasks import process_multimedia_task

logger = logging.getLogger(__name__)

redis_client = redis.from_url(settings.REDIS_URL)

router = APIRouter(tags=["tasks"])

ALLOWED_TASK_TYPES = frozenset({"transcode", "thumbnail", "waveform", "audio_extract"})


@router.post("/api/tasks/process")
def run_processing_pipeline(
    path: str = Query(..., description="Key of the object to process"),
    task_type: str = Query(
        "transcode", description="Pipeline type: transcode, audio_extract, thumbnail, waveform"
    ),
):
    """Dispatch long-running celery worker multimedia task processing pipeline."""
    if task_type not in ALLOWED_TASK_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid task_type '{task_type}'. Allowed types: {sorted(ALLOWED_TASK_TYPES)}",
        )
    task = process_multimedia_task.delay(path, task_type)
    return {
        "message": "Processing pipeline initiated successfully",
        "task_id": task.id,
        "status": task.status,
    }


@router.get("/api/tasks/status/{task_id}")
def get_task_status(task_id: str):
    """Retrieve runtime state and progress of the background running Celery job."""
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


@router.get("/api/tasks/gpu/health", response_model=GPUHealthResponse)
def get_gpu_health(db: Session = Depends(get_db)):
    """Retrieve health metrics for local GPU compute, model states, and GPU task queue (#99)."""
    gpu_info = vram_guard.get_gpu_info()
    models_dict = {}
    for meta in model_registry.list_models():
        models_dict[meta.model_id] = ModelHealthInfo(
            model_id=meta.model_id,
            family=meta.family,
            dtype_quant=meta.dtype_quant,
            approx_vram_gb=meta.approx_vram_gb,
            license=meta.license,
            loaded=model_registry.is_loaded(meta.model_id),
            description=meta.description,
        )

    # Queue metrics from redis
    depth = 0
    try:
        depth = redis_client.llen("media.gpu") or 0
    except Exception as e:
        logger.warning(f"Could not read media.gpu queue depth: {e}")

    # In-flight task count from DB. Task rows carry no queue column, so this is
    # the total across every queue, not media.gpu alone.
    active_tasks_total = 0
    try:
        active_tasks_total = db.query(Task).filter(Task.status == "PROCESSING").count()
    except Exception as e:
        logger.warning(f"Could not read active task count: {e}")

    # Health status based on GPU presence and memory pressure
    if not gpu_info["available"]:
        status = "unavailable"
    elif gpu_info["vram_percent"] > 95.0:
        status = "degraded"
    else:
        status = "healthy"

    return GPUHealthResponse(
        status=status,
        gpu=GPUVRAMMetrics(
            available=gpu_info["available"],
            device_name=gpu_info["device_name"],
            total_gb=gpu_info["total_gb"],
            free_gb=gpu_info["free_gb"],
            used_gb=gpu_info["used_gb"],
            vram_percent=gpu_info["vram_percent"],
        ),
        models=models_dict,
        queue=GPUQueueMetrics(
            queue_name="media.gpu",
            depth=depth,
            active_tasks_total=active_tasks_total,
        ),
    )


@router.websocket("/api/ws/tasks")
async def websocket_tasks_endpoint(websocket: WebSocket):
    await websocket.accept()
    logger.info("WebSocket connection accepted for tasks subscription")

    # Subscribe to Redis channels
    pubsub = redis_client.pubsub()
    pubsub.subscribe("task_updates")

    try:
        while True:
            # Check for pubsub updates
            message = pubsub.get_message(ignore_subscribe_messages=True)
            if message:
                data = message.get("data")
                if data:
                    if isinstance(data, bytes):
                        data = data.decode("utf-8")
                    await websocket.send_text(data)
            # Yield control to prevent blocking loop
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
    except Exception as e:
        logger.error(f"WebSocket encountered error: {e}")
    finally:
        pubsub.unsubscribe("task_updates")
        pubsub.close()
