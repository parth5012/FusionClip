"""Multimedia generation endpoints (currently mocked provider output)."""

import logging
import time
import redis
import json
import uuid

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset, Task
from app.storage import generate_url, upload_object
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])

redis_client = redis.from_url(settings.REDIS_URL)

def is_colab_connected():
    return redis_client.get("colab:connected") == b"true"

def dispatch_gen_to_colab(task_type: str, parameters: dict, db: Session, timeout: int = 60, file_extension: str = "png", content_type: str = "image/png"):
    task_id = f"colab_gen_{task_type}_{uuid.uuid4().hex[:8]}"
    
    # Create Task in DB
    db_task = Task(task_id=task_id, name=task_type, status="PROCESSING", progress=0)
    db.add(db_task)
    db.commit()

    task_payload = {
        "type": "task_dispatch",
        "task_id": task_id,
        "task_type": task_type,
        "parameters": parameters
    }
    
    # Publish to WebSocket and push to HTTP queue
    redis_client.publish("colab_dispatches", json.dumps(task_payload))
    redis_client.rpush("colab_pending_tasks_http", json.dumps(task_payload))
    redis_client.expire("colab_pending_tasks_http", 3600)
    
    # Wait for result
    result_key = f"colab_task_result:{task_id}"
    start_time = time.time()
    while time.time() - start_time < timeout:
        res_data = redis_client.get(result_key)
        if res_data:
            res = json.loads(res_data)
            if res.get("status") == "SUCCESS":
                output = res.get("output", {})
                url = output.get("url", "")
                filename = output.get("filename", f"colab_{task_id}.{file_extension}")
                
                # Update DB task
                db_task.status = "COMPLETED"
                db_task.progress = 100
                db.commit()
                
                # Save as MediaAsset
                asset = MediaAsset(
                    title=f"Colab Generated {task_type}: {parameters.get('prompt', '')[:30]}...",
                    file_path=filename,
                    file_size=1024, # Mock/approx size if not reported
                    content_type=content_type,
                    duration=0.0
                )
                db.add(asset)
                db.commit()
                
                return {
                    "status": "COMPLETED",
                    "parameters": parameters,
                    "filename": filename,
                    "url": url,
                    "colab": True
                }
            else:
                # Update DB task to failed
                db_task.status = "FAILED"
                db_task.error = res.get("error", "Task failed on Colab")
                db.commit()
                raise HTTPException(status_code=500, detail=f"Colab execution failed: {db_task.error}")
        time.sleep(0.5)
        
    # Timeout reached
    db_task.status = "FAILED"
    db_task.error = "Execution timed out waiting for Colab connector"
    db.commit()
    raise HTTPException(status_code=504, detail="Colab execution timed out")


@router.post("/api/generate/text")
def generate_text(prompt: str = Query(...), db: Session = Depends(get_db)):
    """Simulates text storyboard generation via Gemini API."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="text_generation",
            parameters={"prompt": prompt},
            db=db,
            file_extension="txt",
            content_type="text/plain"
        )
    return {
        "status": "COMPLETED",
        "output": f"Generated content using Google Gemini prompt: '{prompt}'. This is a mock Gemini response outlining a video storyboard structure.",
    }


@router.post("/api/generate/audio")
def generate_audio(
    prompt: str = Query(...),
    type: str = Query("tts"),
    db: Session = Depends(get_db)
):
    """Simulated ElevenLabs audio synthesis."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="audio_generation",
            parameters={"prompt": prompt, "type": type},
            db=db,
            file_extension="mp3",
            content_type="audio/mpeg"
        )
    filename = f"gen_audio_{int(time.time())}.mp3"
    content = b"Mock elevenlabs generated audio bytes."
    upload_success = upload_object(content, filename, content_type="audio/mpeg")
    
    # Save media assets
    try:
        asset = MediaAsset(
            title=f"ElevenLabs Synthesized: {prompt[:30]}...",
            file_path=filename,
            file_size=len(content),
            content_type="audio/mpeg",
            duration=3.0
        )
        db.add(asset)
        db.commit()
    except Exception as e:
        logger.error(f"Failed save generated audio asset: {e}")
        db.rollback()

    return {
        "status": "COMPLETED",
        "type": type,
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
    }


@router.post("/api/generate/image")
def generate_image(
    prompt: str = Query(...),
    steps: int = Query(28),
    scale: float = Query(7.5),
    db: Session = Depends(get_db)
):
    """Simulated Local Flux sandbox image generation."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="image_generation",
            parameters={"prompt": prompt, "steps": steps, "scale": scale},
            db=db,
            file_extension="png",
            content_type="image/png"
        )
    filename = f"gen_image_{int(time.time())}.png"
    content = b"Mock local flux generated image bytes."
    upload_success = upload_object(content, filename, content_type="image/png")
    
    # Save media assets
    try:
        asset = MediaAsset(
            title=f"Flux Generated: {prompt[:30]}...",
            file_path=filename,
            file_size=len(content),
            content_type="image/png",
            duration=0.0
        )
        db.add(asset)
        db.commit()
    except Exception as e:
        logger.error(f"Failed save generated image asset: {e}")
        db.rollback()

    return {
        "status": "COMPLETED",
        "parameters": {"steps": steps, "scale": scale},
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
    }