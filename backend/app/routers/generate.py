"""Multimedia generation endpoints (real Gemini, Colab dispatch, mock fallback)."""

import logging
import time
import redis
import json
import uuid
import mimetypes

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request, File, UploadFile
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset, Task
from app.storage import generate_url, upload_object
from app.config import settings
from app.schemas import GenerationGeminiImageOut, GenerationGeminiVideoOut
from app.services import secrets as secret_store
from app.services import gemini as gemini_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])

redis_client = redis.from_url(settings.REDIS_URL)

#: Client header consulted only when no key is stored server-side.
GEMINI_KEY_HEADER = "X-Gemini-Key"


def _resolve_gemini_key(db: Session, request: Optional[Request] = None) -> Optional[str]:
    """Return the Gemini API key: encrypted secret store first, then header.

    The stored key is the canonical source (Celery workers have no request
    context); the ``X-Gemini-Key`` header is only a fallback so clients can
    provide a key without persisting it.
    """
    api_key = secret_store.get_secret("gemini", db=db)
    if not api_key and request is not None:
        api_key = request.headers.get(GEMINI_KEY_HEADER)
    return api_key or None


def _no_key_http_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "No Gemini API key configured. Add one via Settings > API Keys "
            f"(or pass an '{GEMINI_KEY_HEADER}' header)."
        ),
    )


def _save_asset(db: Session, title: str, filename: str, content_type: str, size: int, duration: float = 0.0):
    """Persist a generated media asset, tolerating storage/DB hiccups."""
    try:
        asset = MediaAsset(
            title=title,
            file_path=filename,
            file_size=size,
            content_type=content_type,
            duration=duration,
        )
        db.add(asset)
        db.commit()
    except Exception as e:
        logger.error(f"Failed to save generated asset {filename}: {e}")
        db.rollback()


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
def generate_text(
    request: Request,
    prompt: str = Query(...),
    files: List[UploadFile] = File(default=[]),
    db: Session = Depends(get_db),
):
    """Gemini text/multimodal generation.

    Preference order: Colab dispatch (when connected) -> real Gemini (when a
    key is configured) -> legacy mock fallback. Attaching media files triggers
    the Gemini Files API multimodal analysis pipeline.
    """
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="text_generation",
            parameters={"prompt": prompt},
            db=db,
            file_extension="txt",
            content_type="text/plain"
        )

    api_key = _resolve_gemini_key(db, request)
    if not api_key:
        return {
            "status": "COMPLETED",
            "output": f"Generated content using Google Gemini prompt: '{prompt}'. This is a mock Gemini response outlining a video storyboard structure.",
        }

    if files:
        return _analyze_files(api_key, prompt, files, db)

    if not prompt:
        raise HTTPException(status_code=400, detail="A prompt is required when no files are attached")

    try:
        text = gemini_service.generate_text(api_key, prompt)
    except Exception as e:
        logger.error(f"Gemini text generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Gemini text generation failed: {e}")
    return {"status": "COMPLETED", "output": text}


def _analyze_files(api_key: str, prompt: str, files: List[UploadFile], db: Session) -> dict:
    """Run the file upload -> Gemini Files API -> analysis pipeline.

    Each file is persisted to MinIO (so it lands in the media catalog) and
    handed to Gemini for transcript/summary/metadata extraction.
    """
    instruction = prompt or gemini_service.DEFAULT_ANALYSIS_INSTRUCTION
    outputs = []
    analyzed = []
    for upload in files:
        data = upload.file.read()
        original_name = upload.filename or f"media_{uuid.uuid4().hex[:8]}"
        content_type = upload.content_type or mimetypes.guess_type(original_name)[0] or "application/octet-stream"
        if not data:
            continue

        stored_name = f"gemini_analysis_{int(time.time())}_{uuid.uuid4().hex[:8]}_{original_name}"
        upload_success = upload_object(data, stored_name, content_type=content_type)

        try:
            text, gem_meta = gemini_service.analyze_media(
                api_key, data, content_type, original_name, instruction
            )
        except Exception as e:
            logger.error(f"Gemini multimodal analysis failed for {original_name}: {e}")
            raise HTTPException(status_code=502, detail=f"Gemini multimodal analysis failed for {original_name}: {e}")

        outputs.append(text)
        analyzed.append({
            "filename": stored_name,
            "original_name": original_name,
            "content_type": content_type,
            "url": generate_url(stored_name) if upload_success else "",
            "gemini_file": gem_meta.get("gemini_file"),
            "gemini_uri": gem_meta.get("gemini_uri"),
        })
        _save_asset(
            db,
            title=f"Gemini Analyzed: {original_name}",
            filename=stored_name,
            content_type=content_type,
            size=len(data),
        )

    return {
        "status": "COMPLETED",
        "output": "\n\n".join(outputs),
        "metadata": {"provider": "gemini", "model": gemini_service.TEXT_MODEL, "files_analyzed": len(analyzed)},
        "analyzed_files": analyzed,
    }


@router.post("/api/generate/gemini/image", response_model=GenerationGeminiImageOut)
def generate_gemini_image(
    request: Request,
    prompt: str = Query(...),
    model: str = Query(gemini_service.IMAGE_MODEL),
    db: Session = Depends(get_db),
):
    """Text-to-image via a Gemini Imagen model, persisted to MinIO."""
    api_key = _resolve_gemini_key(db, request)
    if not api_key:
        raise _no_key_http_503()

    try:
        image_bytes, mime_type = gemini_service.generate_image(api_key, prompt, model=model)
    except Exception as e:
        logger.error(f"Gemini image generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Gemini image generation failed: {e}")

    ext = (mimetypes.guess_extension(mime_type) or ".png").lstrip(".")
    filename = f"gen_gemini_image_{int(time.time())}.{ext}"
    upload_success = upload_object(image_bytes, filename, content_type=mime_type)
    _save_asset(
        db,
        title=f"Gemini Image: {prompt[:30]}...",
        filename=filename,
        content_type=mime_type,
        size=len(image_bytes),
    )
    return {
        "status": "COMPLETED",
        "prompt": prompt,
        "model": model,
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
        "content_type": mime_type,
    }


@router.post("/api/generate/gemini/video", response_model=GenerationGeminiVideoOut)
def generate_gemini_video(
    request: Request,
    prompt: str = Query(...),
    model: str = Query(gemini_service.VIDEO_MODEL),
    timeout: int = Query(300, ge=1),
    db: Session = Depends(get_db),
):
    """Text-to-video via a Gemini Veo model (long-running operation)."""
    api_key = _resolve_gemini_key(db, request)
    if not api_key:
        raise _no_key_http_503()

    try:
        result = gemini_service.generate_video(api_key, prompt, model=model, timeout=timeout)
    except Exception as e:
        logger.error(f"Gemini video generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"Gemini video generation failed: {e}")

    metadata = {
        "model": model,
        "prompt": prompt,
        "operation_name": result.get("operation_name"),
        **result.get("metadata", {}),
    }
    if result.get("error"):
        metadata["error"] = result["error"]

    uri = result.get("uri") or ""
    filename = f"gen_gemini_video_{int(time.time())}.mp4" if result.get("status") == "COMPLETED" else None
    return {
        "status": result.get("status", "PROCESSING"),
        "prompt": prompt,
        "model": model,
        "metadata": metadata,
        "url": uri,
        "filename": filename,
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