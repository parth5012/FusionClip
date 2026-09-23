"""Multimedia generation endpoints (real Gemini & ElevenLabs APIs with mock fallback)."""

import base64
import json
import logging
import time
import uuid
from typing import Any, Dict, NoReturn, Optional

import httpx
import redis
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.config import settings
from app.deps import get_db
from app.models import MediaAsset, Task
from app.services.embedding import get_embedding
from app.services.secrets import get_secret
from app.storage import generate_url, upload_object

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])

redis_client = redis.from_url(settings.REDIS_URL)


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
def generate_text(prompt: str = Query(...), db: Session = Depends(get_db)):
    """Generate text via Gemini API, Colab worker, or mock fallback."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="text_generation",
            parameters={"prompt": prompt},
            db=db,
            file_extension="txt",
            content_type="text/plain",
        )

    gemini_key = get_secret("gemini", db)
    if gemini_key:
        data = call_gemini_generate_content(
            api_key=gemini_key,
            model="gemini-3.8-flash",
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
    db: Session = Depends(get_db),
):
    """Generate audio via ElevenLabs API, Colab worker, or mock fallback."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="audio_generation",
            parameters={"prompt": prompt, "type": type},
            db=db,
            file_extension="mp3",
            content_type="audio/mpeg",
        )

    eleven_key = get_secret("elevenlabs", db)
    if eleven_key:
        if type == "sfx":
            content = call_elevenlabs_sfx(api_key=eleven_key, text=prompt)
            filename = f"eleven_sfx_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"
        else:
            content = call_elevenlabs_tts(api_key=eleven_key, text=prompt)
            filename = f"eleven_tts_{int(time.time())}_{uuid.uuid4().hex[:6]}.mp3"

        upload_success = upload_object(content, filename, content_type="audio/mpeg")

        if upload_success:
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
            "url": generate_url(filename) if upload_success else "",
        }

    filename = f"gen_audio_{int(time.time())}.mp3"
    content = b"Mock elevenlabs generated audio bytes."
    upload_success = upload_object(content, filename, content_type="audio/mpeg")

    # Save media assets
    try:
        title = f"ElevenLabs Synthesized: {prompt[:30]}..."
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
        "url": generate_url(filename) if upload_success else "",
    }


@router.post("/api/generate/image")
def generate_image(
    prompt: str = Query(...),
    steps: int = Query(28),
    scale: float = Query(7.5),
    db: Session = Depends(get_db),
):
    """Generate image via Gemini Nano Banana, Colab worker, or mock fallback."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="image_generation",
            parameters={"prompt": prompt, "steps": steps, "scale": scale},
            db=db,
            file_extension="png",
            content_type="image/png",
        )

    gemini_key = get_secret("gemini", db)
    if gemini_key:
        data = call_gemini_generate_content(
            api_key=gemini_key,
            model="gemini-3.1-flash-image",
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
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

        if upload_success:
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
            "url": generate_url(filename) if upload_success else "",
        }

    filename = f"gen_image_{int(time.time())}.png"
    content = b"Mock local flux generated image bytes."
    upload_success = upload_object(content, filename, content_type="image/png")

    # Save media assets
    try:
        title = f"Flux Generated: {prompt[:30]}..."
        asset = MediaAsset(
            title=title,
            file_path=filename,
            file_size=len(content),
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
        "url": generate_url(filename) if upload_success else "",
    }

