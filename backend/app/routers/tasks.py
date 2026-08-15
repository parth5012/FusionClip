"""Celery task dispatch, status polling and the task-update WebSocket feed."""

import asyncio
import logging
from typing import Optional

import redis
from celery.result import AsyncResult
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from app.celery_app import celery
from app.config import settings
from app.tasks import process_multimedia_task

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
