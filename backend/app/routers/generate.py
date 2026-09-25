"""Multimedia generation endpoints (real Gemini & ElevenLabs APIs with mock fallback)."""

import base64
import io
import json
import logging
import os
import re
import time
import uuid
from typing import Any, Dict, NoReturn, Optional

import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_db
from app.ml.contracts import DegradedReason, make_degraded_response
from app.ml.audio import SUPPORTED_AUDIO_TYPES, run_local_audio_generation
from app.ml.image import SUPPORTED_SCHEDULERS, run_local_image_generation
from app.models import MediaAsset, Task
from app.services.embedding import get_embedding
from app.services.secrets import get_secret
from app.storage import generate_url, upload_object

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])

redis_client = redis.from_url(settings.REDIS_URL)

SAFE_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")

# Aspect ratios are `W:H` with integer parts, e.g. '16:9'. The generic safe-identifier
# pattern rejects ':', which made GenerationPanel's default '16:9' 400 before any
# provider was consulted. Deliberately NOT a relaxation of SAFE_IDENTIFIER_PATTERN so
# provider/scheduler stay injection-proof.
ASPECT_RATIO_PATTERN = re.compile(r"^\d{1,4}:\d{1,4}$")


def _validate_safe_identifier(val: Optional[str], param_name: str) -> None:
    if val is not None:
        if len(val) > 64 or not SAFE_IDENTIFIER_PATTERN.match(val):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {param_name}: must contain only alphanumeric, dot, underscore, or dash characters and be <= 64 chars",
            )


def _validate_aspect_ratio(val: Optional[str]) -> None:
    """Accept `W:H` integer ratios only; reject everything else with 400."""
    if val is None:
        return
    if not ASPECT_RATIO_PATTERN.match(val):
        raise HTTPException(
            status_code=400,
            detail=(
                "Invalid aspect_ratio: must be an integer ratio like '16:9' "
                "(digits, one colon, each part <= 9999)"
            ),
        )
    width, height = (int(p) for p in val.split(":"))
    if width < 1 or height < 1:
        raise HTTPException(
            status_code=400,
            detail="Invalid aspect_ratio: both parts must be >= 1",
        )


SAFE_REFERENCE_PATTERN = re.compile(r"^[A-Za-z0-9._/-]+$")


def _validate_safe_reference(val: Optional[str], param_name: str = "reference") -> None:
    if val is not None:
        if (
            not val
            or not val.strip()
            or ".." in val
            or val.startswith("/")
            or "\\" in val
            or len(val) > 256
            or not SAFE_REFERENCE_PATTERN.match(val)
        ):
            raise HTTPException(
                status_code=400,
                detail=f"Invalid {param_name}: must be non-empty relative path without '..', backslashes, or illegal characters",
            )


def is_colab_connected():
    return redis_client.get("colab:connected") == b"true"


def dispatch_gen_to_colab(
    task_type: str,
    parameters: dict,
    db: Session,
    timeout: int = 60,
    file_extension: str = "png",
    content_type: str = "image/png",
):
    task_id = f"colab_gen_{task_type}_{uuid.uuid4().hex[:8]}"

    # Create Task in DB
    db_task = Task(task_id=task_id, name=task_type, status="PROCESSING", progress=0)
    db.add(db_task)
    db.commit()

    task_payload = {
        "type": "task_dispatch",
        "task_id": task_id,
        "task_type": task_type,
        "parameters": parameters,
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
                prompt_text = parameters.get("prompt") or ""
                title = f"Colab Generated {task_type}: {prompt_text[:30]}..."
                asset = MediaAsset(
                    title=title,
                    file_path=filename,
                    file_size=1024,  # Mock/approx size if not reported
                    content_type=content_type,
                    duration=0.0,
                    embedding=get_embedding(prompt_text or title),
                )
                db.add(asset)
                db.commit()

                return {
                    "status": "COMPLETED",
                    "parameters": parameters,
                    "filename": filename,
                    "url": url,
                    "colab": True,
                }
            else:
                # Update DB task to failed
                db_task.status = "FAILED"
                db_task.error = res.get("error", "Task failed on Colab")
                db.commit()
                raise HTTPException(
                    status_code=500, detail=f"Colab execution failed: {db_task.error}"
                )
        time.sleep(0.5)

    # Timeout reached
    db_task.status = "FAILED"
    db_task.error = "Execution timed out waiting for Colab connector"
    db.commit()
    raise HTTPException(status_code=504, detail="Colab execution timed out")


def call_gemini_generate_content(
    api_key: str,
    model: str,
    contents: list,
    generation_config: Optional[dict] = None,
) -> dict:
    """Call Google Gemini generateContent endpoint with error status mapping."""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    headers = {
        "x-goog-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload: Dict[str, Any] = {"contents": contents}
    if generation_config:
        payload["generationConfig"] = generation_config

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    except Exception as exc:
        logger.error(f"Gemini request failed: {exc}")
        raise HTTPException(
            status_code=502, detail="Failed to connect to Google Gemini API"
        ) from exc

    if resp.status_code == 200:
        return resp.json()

    err_body = {}
    try:
        err_body = resp.json()
    except Exception:
        pass

    err_msg = ""
    if isinstance(err_body, dict):
        err_msg = err_body.get("error", {}).get("message", resp.text)
    else:
        err_msg = str(err_body)

    if resp.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail=(
                "Gemini authentication failed: invalid or expired API key. "
                "Note standard keys were deprecated September 2026."
            ),
        )
    elif resp.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail=f"Gemini rate limit or quota exceeded (RESOURCE_EXHAUSTED): {err_msg}",
        )
    elif resp.status_code in (400, 403, 404):
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"Gemini API error ({resp.status_code}): {err_msg}",
        )
    else:
        raise HTTPException(
            status_code=502,
            detail=f"Gemini service error ({resp.status_code}): {err_msg}",
        )


def call_elevenlabs_tts(
    api_key: str,
    text: str,
    voice_id: str = "21m00Tcm4TlvDq8ikWAM",
    model_id: str = "eleven_multilingual_v2",
) -> bytes:
    """Call ElevenLabs text-to-speech endpoint returning raw audio bytes."""
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}?output_format=mp3_44100_128"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": model_id,
    }

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    except Exception as exc:
        logger.error(f"ElevenLabs TTS request failed: {exc}")
        raise HTTPException(
            status_code=502, detail="Failed to connect to ElevenLabs API"
        ) from exc

    if resp.status_code == 200:
        return resp.content

    _handle_elevenlabs_error(resp)


def call_elevenlabs_sfx(
    api_key: str,
    text: str,
    duration_seconds: float = 5.0,
) -> bytes:
    """Call ElevenLabs sound-generation endpoint returning raw audio bytes."""
    url = "https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_128"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload = {
        "text": text,
        "model_id": "eleven_text_to_sound_v2",
        "duration_seconds": duration_seconds,
    }

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    except Exception as exc:
        logger.error(f"ElevenLabs SFX request failed: {exc}")
        raise HTTPException(
            status_code=502, detail="Failed to connect to ElevenLabs API"
        ) from exc

    if resp.status_code == 200:
        return resp.content

    _handle_elevenlabs_error(resp)


def _handle_elevenlabs_error(resp: httpx.Response) -> NoReturn:
    err_body = {}
    try:
        err_body = resp.json()
    except Exception:
        pass

    detail_obj = err_body.get("detail", {}) if isinstance(err_body, dict) else {}
    if isinstance(detail_obj, dict):
        err_msg = detail_obj.get("message", resp.text)
    else:
        err_msg = str(detail_obj or resp.text)

    if resp.status_code == 401:
        raise HTTPException(
            status_code=401,
            detail=f"ElevenLabs authentication failed: invalid API key. {err_msg}",
        )
    elif resp.status_code == 429:
        raise HTTPException(
            status_code=429,
            detail=f"ElevenLabs concurrency or quota limit exceeded: {err_msg}",
        )
    elif resp.status_code in (400, 422):
        raise HTTPException(
            status_code=resp.status_code,
            detail=f"ElevenLabs error ({resp.status_code}): {err_msg}",
        )
    else:
        raise HTTPException(
            status_code=502,
            detail=f"ElevenLabs service error ({resp.status_code}): {err_msg}",
        )


@router.post("/api/generate/text")
def generate_text(
    prompt: str = Query(...),
    model: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Generate text via Gemini API, Colab worker, or mock fallback."""
    _validate_safe_identifier(model, "model")
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="text_generation",
            parameters={"prompt": prompt, "model": model},
            db=db,
            file_extension="txt",
            content_type="text/plain",
        )

    gemini_key = get_secret("gemini", db)
    if gemini_key:
        data = call_gemini_generate_content(
            api_key=gemini_key,
            model=model or "gemini-3.8-flash",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
        )
        candidates = data.get("candidates", [])
        if not candidates or not candidates[0].get("content"):
            raise HTTPException(
                status_code=502, detail="Gemini returned an empty candidate list"
            )
        parts = candidates[0]["content"].get("parts", [])
        text_output = "".join(part.get("text", "") for part in parts)
        return {
            "status": "COMPLETED",
            "output": text_output,
        }

    return {
        "status": "COMPLETED",
        "output": f"Generated content using Google Gemini prompt: '{prompt}'. This is a mock Gemini response outlining a video storyboard structure.",
    }


@router.post("/api/generate/audio")
def generate_audio(
    prompt: str = Query(...),
    type: str = Query("tts"),
    voice_id: Optional[str] = Query(None),
    duration: Optional[float] = Query(None),
    reference: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    db: Session = Depends(get_db),
):
    """Generate audio via ElevenLabs API, Colab worker, or local PyTorch pipeline."""
    _validate_safe_identifier(voice_id, "voice_id")
    _validate_safe_identifier(type, "type")
    _validate_safe_identifier(provider, "provider")
    _validate_safe_reference(reference, "reference")

    if duration is not None:
        if duration < 0.5 or duration > 30.0:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid duration: must be between 0.5 and 30.0 seconds, got {duration}",
            )

    if type not in SUPPORTED_AUDIO_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported audio type '{type}'. Supported types: {', '.join(sorted(SUPPORTED_AUDIO_TYPES))}",
        )

    if type == "voice_clone":
        if not reference or not reference.strip():
            raise HTTPException(
                status_code=400,
                detail="voice_clone requires a 'reference' parameter specifying an existing audio file path",
            )

    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="audio_generation",
            parameters={
                "prompt": prompt,
                "type": type,
                "voice_id": voice_id,
                "duration": duration,
                "reference": reference,
            },
            db=db,
            file_extension="mp3",
            content_type="audio/mpeg",
        )

    ELEVENLABS_AUDIO_TYPES = frozenset({"tts", "voice", "sfx"})
    if provider != "local" and type in ELEVENLABS_AUDIO_TYPES:
        eleven_key = get_secret("elevenlabs", db)
        if eleven_key:
            if type == "sfx":
                content = call_elevenlabs_sfx(
                    api_key=eleven_key,
                    text=prompt,
                    duration_seconds=duration if duration is not None else 5.0,
                )
                filename = f"eleven_sfx_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
            else:
                content = call_elevenlabs_tts(
                    api_key=eleven_key,
                    text=prompt,
                    voice_id=voice_id or "21m00Tcm4TlvDq8ikWAM",
                )
                filename = f"eleven_tts_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"

            upload_success = upload_object(content, filename, content_type="audio/mpeg")
            if not upload_success:
                logger.error(f"Failed to upload ElevenLabs audio asset '{filename}' to storage")
                return make_degraded_response(
                    reason=DegradedReason.LOAD_FAILED.value,
                    message="Failed to upload generated audio to storage",
                ).model_dump()

            try:
                title = f"ElevenLabs {'SFX' if type == 'sfx' else 'TTS'}: {prompt[:30]}..."
                asset = MediaAsset(
                    title=title,
                    file_path=filename,
                    file_size=len(content),
                    content_type="audio/mpeg",
                    duration=3.0,
                    embedding=get_embedding(prompt or title),
                )
                db.add(asset)
                db.commit()
            except Exception as e:
                logger.error(f"Failed to save generated audio asset: {e}")
                db.rollback()

            return {
                "status": "COMPLETED",
                "type": type,
                "filename": filename,
                "url": generate_url(filename),
            }

    # Local ML pipeline path (XTTS v2 voice / voice clone + MusicGen audio / sfx)
    return run_local_audio_generation(
        prompt=prompt,
        type=type,
        voice_id=voice_id,
        duration=duration,
        reference=reference,
        db=db,
    )


@router.post("/api/generate/image")
def generate_image(
    prompt: str = Query(...),
    steps: int = Query(28),
    scale: float = Query(7.5),
    aspect_ratio: Optional[str] = Query(None),
    provider: Optional[str] = Query(None),
    scheduler: Optional[str] = Query(None),
    denoising_strength: Optional[float] = Query(None),
    db: Session = Depends(get_db),
):
    """Generate image via Gemini Nano Banana, Colab worker, or local PyTorch pipeline."""
    _validate_aspect_ratio(aspect_ratio)
    _validate_safe_identifier(provider, "provider")
    _validate_safe_identifier(scheduler, "scheduler")

    if scheduler is not None and scheduler.lower() not in SUPPORTED_SCHEDULERS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported scheduler '{scheduler}'. Supported schedulers: {', '.join(sorted(SUPPORTED_SCHEDULERS.keys()))}",
        )

    if steps < 1 or steps > 150:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid steps: must be between 1 and 150, got {steps}",
        )

    if scale < 0.0 or scale > 30.0:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid scale: must be between 0.0 and 30.0, got {scale}",
        )

    if denoising_strength is not None and (denoising_strength < 0.0 or denoising_strength > 1.0):
        raise HTTPException(
            status_code=400,
            detail=f"Invalid denoising_strength: must be between 0.0 and 1.0, got {denoising_strength}",
        )

    # `strength` is img2img-only: diffusers txt2img pipelines raise TypeError on it,
    # and this route has no source-image input yet. Accepting the value and quietly
    # dropping it would be worse than refusing, so refuse with an actionable message.
    if denoising_strength is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "denoising_strength requires a source image; image-to-image input "
                "is not available on /api/generate/image yet. Omit the parameter "
                "for text-to-image."
            ),
        )

    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="image_generation",
            parameters={
                "prompt": prompt,
                "steps": steps,
                "scale": scale,
                "aspect_ratio": aspect_ratio,
                "provider": provider,
                "scheduler": scheduler,
            },
            db=db,
            file_extension="png",
            content_type="image/png",
        )

    # When provider is explicitly set to local, never fall through to Gemini cloud API
    if provider != "local":
        gemini_key = get_secret("gemini", db)
        if gemini_key:
            data = call_gemini_generate_content(
                api_key=gemini_key,
                model="gemini-3.1-flash-image",
                contents=[{"role": "user", "parts": [{"text": prompt}]}],
                generation_config={
                    "responseModalities": ["IMAGE"],
                    **({"imageConfig": {"aspectRatio": aspect_ratio}} if aspect_ratio else {}),
                },
            )
            candidates = data.get("candidates", [])
            if not candidates or not candidates[0].get("content"):
                raise HTTPException(
                    status_code=502, detail="Gemini returned an empty candidate list"
                )
            parts = candidates[0]["content"].get("parts", [])

            img_bytes = None
            for part in parts:
                inline_data = part.get("inlineData") or part.get("inline_data")
                if inline_data and "data" in inline_data:
                    img_bytes = base64.b64decode(inline_data["data"])
                    break

            if not img_bytes:
                raise HTTPException(
                    status_code=502,
                    detail="Gemini did not return image data in candidate parts",
                )

            filename = f"gemini_img_{int(time.time())}_{uuid.uuid4().hex[:6]}.png"
            upload_success = upload_object(img_bytes, filename, content_type="image/png")
            if not upload_success:
                logger.error(f"Failed to upload Gemini image asset '{filename}' to storage")
                return make_degraded_response(
                    reason=DegradedReason.LOAD_FAILED.value,
                    message="Failed to upload generated image to storage",
                ).model_dump()

            try:
                title = f"Gemini Image: {prompt[:30]}..."
                asset = MediaAsset(
                    title=title,
                    file_path=filename,
                    file_size=len(img_bytes),
                    content_type="image/png",
                    duration=0.0,
                    embedding=get_embedding(prompt or title),
                )
                db.add(asset)
                db.commit()
            except Exception as e:
                logger.error(f"Failed to save generated image asset: {e}")
                db.rollback()

            return {
                "status": "COMPLETED",
                "parameters": {"steps": steps, "scale": scale},
                "filename": filename,
                "url": generate_url(filename),
            }

    # Local ML pipeline path (priority-1: flux-schnell with sdxl auto-downgrade)
    return run_local_image_generation(
        prompt=prompt,
        steps=steps,
        scale=scale,
        aspect_ratio=aspect_ratio,
        scheduler=scheduler,
        db=db,
    )


@router.post("/api/generate/video")
def generate_video(
    source: str = Query(..., description="Conditioning image file path in catalog/storage"),
    num_frames: int = Query(14, description="Number of video frames to generate (2..25)"),
    fps: int = Query(7, description="Framerate of generated video (1..30)"),
    db: Session = Depends(get_db),
):
    """Generate short video from conditioning image via Stable Video Diffusion (SVD) (#102)."""
    _validate_safe_reference(source, "source")

    if num_frames < 2 or num_frames > 25:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid num_frames: must be between 2 and 25, got {num_frames}",
        )

    if fps < 1 or fps > 30:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid fps: must be between 1 and 30, got {fps}",
        )

    from app.storage import download_object
    source_bytes = download_object(source)
    if source_bytes is None:
        raise HTTPException(
            status_code=400,
            detail=f"Source image '{source}' not found or unreadable in storage",
        )

    from PIL import Image
    try:
        probe = Image.open(io.BytesIO(source_bytes))
        probe.verify()
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Source image '{source}' is unreadable or corrupt: {exc}",
        )

    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="video_generation",
            parameters={
                "op": "image_to_video",
                "source": source,
                "num_frames": num_frames,
                "fps": fps,
            },
            db=db,
            timeout=300,
            file_extension="mp4",
            content_type="video/mp4",
        )

    from app.tasks import process_gpu_task
    celery_task = process_gpu_task.delay(
        "svd",
        {
            "op": "image_to_video",
            "source": source,
            "num_frames": num_frames,
            "fps": fps,
        },
    )

    return {
        "task_id": celery_task.id,
        "status": "PENDING",
        "type": "video",
        "source": source,
        "num_frames": num_frames,
        "fps": fps,
    }

