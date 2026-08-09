"""Celery task dispatch, status polling and the task-update WebSocket feed."""

import asyncio
import logging

import redis
import uuid
from celery.result import AsyncResult
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, Depends
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.celery_app import celery
from app.config import settings
from app.tasks import process_multimedia_task, process_upscale_task
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
):
    """Dispatch long-running celery worker multimedia task processing pipeline."""
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

