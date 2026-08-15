"""Multimedia generation endpoints (real Gemini, ElevenLabs, local
Flux/SDXL/XTTS/ChatTTS/MusicGen pipelines + Colab dispatch, mock fallback)."""

"""Multimedia generation endpoints (real Gemini, Colab dispatch, mock fallback)."""

import logging
import time
import redis
import json
import uuid
import mimetypes

from typing import List, Optional

from fastapi import APIRouter, Depends, Query, HTTPException, Request, File, UploadFile, Form
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import Configuration, MediaAsset, Task
from app.storage import generate_url, upload_object
from app.config import settings
from app.scratchpad import scratchpad
from app.schemas import (
    GenerationGeminiImageOut,
    GenerationGeminiVideoOut,
    GenerationTtsOut,
    GenerationVoiceListOut,
)
from app.tasks import parse_duration
from app.services import secrets as secret_store
from app.services import elevenlabs as elevenlabs_service
from app.services import gemini as gemini_service

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])

redis_client = redis.from_url(settings.REDIS_URL)

#: Client header consulted only when no key is stored server-side.
GEMINI_KEY_HEADER = "X-Gemini-Key"
ELEVENLABS_KEY_HEADER = "X-ElevenLabs-Key"


import io
import os
from typing import Optional
import torch
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from diffusers import FluxPipeline, StableDiffusionXLPipeline
from diffusers.schedulers import EulerDiscreteScheduler
from PIL import Image
from app.models import MediaAsset, Task

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


def _resolve_elevenlabs_key(db: Session, request: Optional[Request] = None) -> Optional[str]:
    """Return the ElevenLabs API key, mirroring :func:`_resolve_gemini_key`."""
    api_key = secret_store.get_secret("elevenlabs", db=db)
    if not api_key and request is not None:
        api_key = request.headers.get(ELEVENLABS_KEY_HEADER)
    return api_key or None


def _no_key_http_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "No Gemini API key configured. Add one via Settings > API Keys "
            f"(or pass an '{GEMINI_KEY_HEADER}' header)."
        ),
    )


def _no_elevenlabs_key_http_503() -> HTTPException:
    return HTTPException(
        status_code=503,
        detail=(
            "No ElevenLabs API key configured. Add one via Settings > API Keys "
            f"(or pass an '{ELEVENLABS_KEY_HEADER}' header)."
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
    request: Request,
    prompt: str = Query(...),
    type: str = Query("tts"),
    voice_id: Optional[str] = Query(None),
    stability: float = Query(0.5, ge=0.0, le=1.0),
    clarity: float = Query(0.75, ge=0.0, le=1.0),
    language: str = Query("en", description="Language code for local TTS"),
    speed: float = Query(1.0, description="Speech speed multiplier"),
    emotion: str = Query("neutral", description="Emotion: neutral, breathy, laughing, etc."),
    reference_audio: Optional[UploadFile] = File(None, description="Reference audio for local voice cloning"),
    use_chattts: bool = Query(False, description="Use ChatTTS (True) or XTTSv2 (False) for local TTS"),
    db: Session = Depends(get_db),
):
    """Audio synthesis.

    Preference order: Colab dispatch (when connected), real ElevenLabs (when
    key configured), local XTTS/ChatTTS (offloaded Colab models), mock fallback.
    """
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="audio_generation",
            parameters={
                "prompt": prompt,
                "type": type,
                "language": language,
                "speed": speed,
                "emotion": emotion,
                "use_chattts": use_chattts,
            },
            db=db,
            file_extension="mp3",
            content_type="audio/mpeg",
        )

    api_key = _resolve_elevenlabs_key(db, request)
    if api_key:
        try:
            audio = elevenlabs_service.synthesize(
                api_key,
                prompt,
                voice_id=voice_id or elevenlabs_service.DEFAULT_VOICE_ID,
                stability=stability,
                clarity=clarity,
            )
        except Exception as e:
            logger.error(f"ElevenLabs audio synthesis failed: {e}")
            raise HTTPException(status_code=502, detail=f"ElevenLabs audio synthesis failed: {e}")

        filename = f"gen_audio_{int(time.time())}.mp3"
        upload_success = upload_object(audio, filename, content_type="audio/mpeg")
        _save_asset(
            db,
            title=f"ElevenLabs Synthesized: {prompt[:30]}...",
            filename=filename,
            content_type="audio/mpeg",
            size=len(audio),
        )
        return {
            "status": "COMPLETED",
            "type": type,
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
        }

    try:
        return _generate_local_tts_audio(
            prompt, type, language, speed, emotion, reference_audio, use_chattts, db
        )
    except Exception as e:
        logger.warning(f"Local TTS unavailable, falling back to mock: {e}")

    filename = f"gen_audio_{int(time.time())}.mp3"
    content = b"Mock elevenlabs generated audio bytes."
    upload_success = upload_object(content, filename, content_type="audio/mpeg")
    _save_asset(
        db,
        title=f"ElevenLabs Synthesized: {prompt[:30]}...",
        filename=filename,
        content_type="audio/mpeg",
        size=len(content),
    )
    return {
        "status": "COMPLETED",
        "type": type,
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
    }

def _generate_local_tts_audio(
    prompt: str = Query(...),
    type: str = Query("tts"),
    language: str = Query("en", description="Language code for TTS"),
    speed: float = Query(1.0, description="Speech speed multiplier"),
    emotion: str = Query("neutral", description="Emotion: neutral, breathy, laughing, etc."),
    reference_audio: Optional[UploadFile] = File(None, description="Reference audio for voice cloning"),
    use_chattts: bool = Query(False, description="Use ChatTTS (True) or XTTS v2 (False)"),
    db: Session = Depends(get_db)
):
    """Local TTS and voice cloning using XTTS v2 or ChatTTS, or offload to Colab."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="audio_generation",
            parameters={
                "prompt": prompt, 
                "type": type,
                "language": language,
                "speed": speed,
                "emotion": emotion,
                "use_chattts": use_chattts
            },
            db=db,
            file_extension="mp3",
            content_type="audio/mpeg"
        )

    try:
        # Load TTS pipeline
        if use_chattts:
            tts_pipeline = load_chattts_pipeline()
        else:
            tts_pipeline = load_xtts_pipeline()

        # Voice cloning with reference audio
        if reference_audio:
            ref_audio_data = reference_audio.file.read()
            audio = tts_pipeline.tts(
                text=prompt,
                speaker_wav=ref_audio_data,
                language=language,
                speed=speed,
                emotion=emotion
            )
        # Standard TTS
        else:
            audio = tts_pipeline.tts(
                text=prompt,
                language=language,
                speed=speed,
                emotion=emotion
            )

        # Convert to MP3 bytes
        import numpy as np
        from scipy.io import wavfile
        import io as io_module

        # TTS returns numpy array (sample_rate, audio)
        if isinstance(audio, tuple):
            sample_rate, audio_data = audio
        else:
            sample_rate = 22050
            audio_data = audio

        # Convert to 16-bit PCM
        audio_int16 = (audio_data * 32767).astype(np.int16)

        # Write to WAV buffer
        wav_buffer = io_module.BytesIO()
        wavfile.write(wav_buffer, sample_rate, audio_int16)
        wav_bytes = wav_buffer.getvalue()

        # Upload to MinIO
        filename = f"gen_audio_{int(time.time())}.wav"
        upload_success = upload_object(wav_bytes, filename, content_type="audio/wav")

        # Calculate duration
        duration = len(audio_int16) / sample_rate

        # Save media asset
        asset = MediaAsset(
            title=f"{'ChatTTS' if use_chattts else 'XTTS'} Synthesized: {prompt[:30]}...",
            file_path=filename,
            file_size=len(wav_bytes),
            content_type="audio/wav",
            duration=duration
        )
        db.add(asset)
        db.commit()

        return {
            "status": "COMPLETED",
            "type": type,
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
            "colab": False
        }
    except Exception as e:
        logger.error(f"Failed to generate audio: {e}")
        raise HTTPException(status_code=500, detail=f"Audio generation failed: {e}")



@router.post("/api/generate/tts", response_model=GenerationTtsOut)
def generate_tts(
    request: Request,
    text: str = Query(...),
    voice_id: Optional[str] = Query(None, description="ElevenLabs voice id; defaults to the standard 'Rachel' preset"),
    stability: float = Query(0.5, ge=0.0, le=1.0),
    clarity: float = Query(0.75, ge=0.0, le=1.0),
    model: str = Query(elevenlabs_service.DEFAULT_MODEL),
    db: Session = Depends(get_db),
):
    """Text-to-speech via real ElevenLabs, persisted to MinIO.

    Preference order mirrors ``/api/generate/audio``: Colab dispatch when
    connected, real ElevenLabs when a key is configured, and a mock fallback
    otherwise so the client always receives a usable shape.
    """
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="audio_generation",
            parameters={"text": text, "voice_id": voice_id, "stability": stability, "clarity": clarity},
            db=db,
            file_extension="mp3",
            content_type="audio/mpeg",
        )

    api_key = _resolve_elevenlabs_key(db, request)
    resolved_voice = voice_id or elevenlabs_service.DEFAULT_VOICE_ID
    if not api_key:
        filename = f"gen_audio_{int(time.time())}.mp3"
        content = b"Mock elevenlabs generated audio bytes."
        upload_success = upload_object(content, filename, content_type="audio/mpeg")
        _save_asset(
            db,
            title=f"ElevenLabs Synthesized: {text[:30]}...",
            filename=filename,
            content_type="audio/mpeg",
            size=len(content),
            duration=3.0,
        )
        return {
            "status": "COMPLETED",
            "voice_id": resolved_voice,
            "model": model,
            "stability": stability,
            "clarity": clarity,
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
            "content_type": "audio/mpeg",
        }

    try:
        audio = elevenlabs_service.synthesize(
            api_key,
            text,
            voice_id=resolved_voice,
            stability=stability,
            clarity=clarity,
            model=model,
        )
    except Exception as e:
        logger.error(f"ElevenLabs TTS synthesis failed: {e}")
        raise HTTPException(status_code=502, detail=f"ElevenLabs TTS synthesis failed: {e}")

    filename = f"gen_tts_{int(time.time())}.mp3"
    upload_success = upload_object(audio, filename, content_type="audio/mpeg")
    _save_asset(
        db,
        title=f"ElevenLabs TTS: {text[:30]}...",
        filename=filename,
        content_type="audio/mpeg",
        size=len(audio),
    )
    return {
        "status": "COMPLETED",
        "voice_id": resolved_voice,
        "model": model,
        "stability": stability,
        "clarity": clarity,
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
        "content_type": "audio/mpeg",
    }



@router.get("/api/generate/voice-list", response_model=GenerationVoiceListOut)
def list_elevenlabs_voices(
    request: Request,
    db: Session = Depends(get_db),
):
    """List the voices available to the configured ElevenLabs account."""
    api_key = _resolve_elevenlabs_key(db, request)
    if not api_key:
        raise _no_elevenlabs_key_http_503()

    try:
        voices = elevenlabs_service.list_voices(api_key)
    except Exception as e:
        logger.error(f"ElevenLabs voice list fetch failed: {e}")
        raise HTTPException(status_code=502, detail=f"ElevenLabs voice list fetch failed: {e}")

    cloned = _list_cloned_voices(db)
    for entry in cloned:
        voices.append(entry)

    return {"status": "COMPLETED", "voices": voices}



@router.post("/api/generate/sound-effect")
def generate_sound_effect(
    request: Request,
    prompt: str = Form(..., description="Text prompt for the sound effect"),
    duration_seconds: Optional[float] = Form(None, description="Duration of the sound effect in seconds (0.5-30)"),
    db: Session = Depends(get_db),
):
    """Generate a sound effect from a text prompt using ElevenLabs."""
    api_key = _resolve_elevenlabs_key(db, request)
    if not api_key:
        raise _no_elevenlabs_key_http_503()

    try:
        audio_bytes = elevenlabs_service.generate_sound_effect(
            api_key,
            text=prompt,
            duration_seconds=duration_seconds,
        )
    except Exception as e:
        logger.error(f"ElevenLabs sound effect generation failed: {e}")
        raise HTTPException(status_code=502, detail=f"ElevenLabs sound effect generation failed: {e}")

    filename = f"sfx_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp3"
    upload_success = upload_object(audio_bytes, filename, content_type="audio/mpeg")
    _save_asset(
        db,
        title=f"Sound Effect: {prompt[:30]}...",
        filename=filename,
        content_type="audio/mpeg",
        size=len(audio_bytes),
    )

    return {
        "status": "COMPLETED",
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
    }


ALLOWED_CLONE_AUDIO_TYPES = {"audio/mpeg", "audio/mp3", "audio/wav", "audio/x-wav", "audio/ogg", "application/ogg"}



def _list_cloned_voices(db: Session) -> List[dict]:
    """Return cloned voices stored in the Configuration key/value store."""
    rows = db.query(Configuration).filter(Configuration.key.like("elevenlabs.voice.%")).all()
    voices = []
    for row in rows:
        voices.append(
            {
                "voice_id": row.value,
                "name": row.key.split("elevenlabs.voice.", 1)[-1],
                "labels": {"cloned": "true"},
                "category": "cloned",
                "preview_url": None,
            }
        )
    return voices



@router.post("/api/generate/voice-clone")
def clone_elevenlabs_voice(
    request: Request,
    file: UploadFile = File(...),
    voice_name: str = Form(...),
    db: Session = Depends(get_db),
):
    """Clone a voice from an uploaded audio sample using ElevenLabs.

    Validates the sample (audio mime type, <= 60s duration via ffprobe), clones
    via the ElevenLabs Instant Voice Cloning API, and stores the returned
    ``voice_id`` in the Configuration store under ``elevenlabs.voice.<name>``.
    """
    api_key = _resolve_elevenlabs_key(db, request)
    if not api_key:
        raise _no_elevenlabs_key_http_503()

    content_type = (file.content_type or "").lower()
    if content_type not in ALLOWED_CLONE_AUDIO_TYPES:
        raise HTTPException(status_code=400, detail="Invalid audio file format. Upload MP3, WAV, or OGG audio.")

    temp_path = scratchpad.get_temp_path(suffix=".mp3")
    try:
        with open(str(temp_path), "wb") as f:
            f.write(file.file.read())

        duration = parse_duration(str(temp_path))
        if duration > 60.0:
            raise HTTPException(status_code=400, detail="Audio sample exceeds 1 minute; upload a sample up to 60 seconds long.")

        try:
            voice_id = elevenlabs_service.clone_voice(
                api_key,
                str(temp_path),
                voice_name,
            )
        except Exception as e:
            logger.error(f"ElevenLabs voice cloning failed: {e}")
            raise HTTPException(status_code=502, detail=f"ElevenLabs voice cloning failed: {e}")

        key = f"elevenlabs.voice.{voice_name}"
        cfg = db.query(Configuration).filter(Configuration.key == key).first()
        if cfg:
            cfg.value = voice_id
        else:
            db.add(Configuration(key=key, value=voice_id))
        db.commit()

        data = file.file.read()
        data = data or b""
        stored_name = f"voice_clone_{int(time.time())}_{uuid.uuid4().hex[:8]}.mp3"
        upload_success = upload_object(data, stored_name, content_type="audio/mpeg")
        _save_asset(
            db,
            title=f"Voice Clone Sample: {voice_name}",
            filename=stored_name,
            content_type="audio/mpeg",
            size=len(data),
        )

        return {
            "status": "COMPLETED",
            "voice_id": voice_id,
            "name": voice_name,
            "filename": stored_name,
            "url": generate_url(stored_name) if upload_success else "",
        }
    finally:
        scratchpad.remove_path(temp_path)



@router.post("/api/generate/image")
def generate_image(
    prompt: str = Query(...),
    steps: int = Query(28),
    scale: float = Query(7.5),
    image_strength: float = Query(0.75, description="Denoising strength for img2img (0.0-1.0)"),
    init_image: Optional[UploadFile] = File(None, description="Initial image for img2img mode"),
    use_flux: bool = Query(True, description="Use Flux.1 (True) or SDXL (False)"),
    db: Session = Depends(get_db)
):
    """Generate images using local Flux.1/SDXL pipelines or offload to Colab."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="image_generation",
            parameters={
                "prompt": prompt, 
                "steps": steps, 
                "scale": scale,
                "image_strength": image_strength,
                "use_flux": use_flux
            },
            db=db,
            file_extension="png",
            content_type="image/png"
        )

    try:
        # Load pipeline
        if use_flux:
            pipeline = load_flux_pipeline()
        else:
            pipeline = load_sdxl_pipeline()

        # Image-to-image mode
        if init_image:
            init_image_data = Image.open(io.BytesIO(init_image.file.read()))
            image = pipeline(
                prompt=prompt,
                num_inference_steps=steps,
                guidance_scale=scale,
                strength=image_strength,
                image=init_image_data
            ).images[0]
        # Text-to-image mode
        else:
            image = pipeline(
                prompt=prompt,
                num_inference_steps=steps,
                guidance_scale=scale
            ).images[0]

        # Save image to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format="PNG")
        img_byte_arr = img_byte_arr.getvalue()

        # Upload to MinIO
        filename = f"gen_image_{int(time.time())}.png"
        upload_success = upload_object(img_byte_arr, filename, content_type="image/png")

        # Save media asset
        asset = MediaAsset(
            title=f"{'Flux' if use_flux else 'SDXL'} Generated: {prompt[:30]}...",
            file_path=filename,
            file_size=len(img_byte_arr),
            content_type="image/png",
            duration=0.0
        )
        db.add(asset)
        db.commit()

        return {
            "status": "COMPLETED",
            "parameters": {"steps": steps, "scale": scale, "use_flux": use_flux},
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
            "colab": False
        }
    except Exception as e:
        logger.error(f"Failed to generate image: {e}")
        raise HTTPException(status_code=500, detail=f"Image generation failed: {e}")



def load_flux_pipeline():
    """Load Flux.1 pipeline with caching."""
    global flux_pipeline
    if flux_pipeline is None:
        try:
            flux_pipeline = FluxPipeline.from_pretrained(
                "black-forest-labs/FLUX.1-schnell",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            if torch.cuda.is_available():
                flux_pipeline = flux_pipeline.to("cuda")
        except Exception as e:
            logger.error(f"Failed to load Flux pipeline: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load Flux pipeline: {e}")
    return flux_pipeline


def load_sdxl_pipeline():
    """Load SDXL pipeline with caching."""
    global sdxl_pipeline
    if sdxl_pipeline is None:
        try:
            sdxl_pipeline = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
                variant="fp16",
                use_safetensors=True
            )
            if torch.cuda.is_available():
                sdxl_pipeline = sdxl_pipeline.to("cuda")
        except Exception as e:
            logger.error(f"Failed to load SDXL pipeline: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load SDXL pipeline: {e}")
    return sdxl_pipeline


def load_xtts_pipeline():
    """Load XTTS v2 pipeline with caching."""
    global xtts_pipeline
    if xtts_pipeline is None:
        try:
            from TTS.api import TTS
            xtts_pipeline = TTS("tts_models/multilingual/multi-dataset/xtts_v2", gpu=torch.cuda.is_available())
        except Exception as e:
            logger.error(f"Failed to load XTTS pipeline: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load XTTS pipeline: {e}")
    return xtts_pipeline


def load_chattts_pipeline():
    """Load ChatTTS pipeline with caching."""
    global chattts_pipeline
    if chattts_pipeline is None:
        try:
            import ChatTTS
            chattts_pipeline = ChatTTS.Chat()
            chattts_pipeline.load(compile=False)
        except Exception as e:
            logger.error(f"Failed to load ChatTTS pipeline: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load ChatTTS pipeline: {e}")
    return chattts_pipeline


def load_musicgen_pipeline():
    """Load MusicGen pipeline with caching."""
    global musicgen_pipeline
    if musicgen_pipeline is None:
        try:
            from transformers import MusicgenForConditionalGeneration, AutoProcessor
            musicgen_pipeline = MusicgenForConditionalGeneration.from_pretrained(
                "facebook/musicgen-small",
                torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32
            )
            musicgen_processor = AutoProcessor.from_pretrained("facebook/musicgen-small")
            if torch.cuda.is_available():
                musicgen_pipeline = musicgen_pipeline.to("cuda")
        except Exception as e:
            logger.error(f"Failed to load MusicGen pipeline: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to load MusicGen pipeline: {e}")
    return musicgen_pipeline, musicgen_processor



@router.post("/api/generate/music")
def generate_music(
    prompt: str = Query(..., description="Text prompt describing the music genre and style"),
    genre: str = Query("ambient", description="Music genre (e.g., ambient, rock, jazz, electronic)"),
    style: str = Query("cinematic", description="Musical style (e.g., cinematic, upbeat, melancholic)"),
    duration: int = Query(30, description="Duration in seconds (10-300)"),
    tempo: int = Query(120, description="Tempo in BPM"),
    instrumentation: str = Query("piano", description="Primary instruments (comma-separated)"),
    db: Session = Depends(get_db)
):
    """Generate music using Meta's MusicGen via transformers, or offload to Colab."""
    if is_colab_connected():
        return dispatch_gen_to_colab(
            task_type="music_generation",
            parameters={
                "prompt": prompt,
                "genre": genre,
                "style": style,
                "duration": duration,
                "tempo": tempo,
                "instrumentation": instrumentation
            },
            db=db,
            file_extension="wav",
            content_type="audio/wav"
        )

    try:
        # Build full prompt combining all parameters
        full_prompt = f"{prompt}. Genre: {genre}. Style: {style}. Tempo: {tempo} BPM. Instruments: {instrumentation}."

        # Load MusicGen pipeline
        pipeline, processor = load_musicgen_pipeline()

        # Calculate max_new_tokens based on duration (approx 25 tokens per second)
        max_new_tokens = min(int(duration * 25.5), 1500)

        # Generate music
        inputs = processor(
            text=[full_prompt],
            padding=True,
            return_tensors="pt"
        )

        if torch.cuda.is_available():
            inputs = {k: v.to("cuda") for k, v in inputs.items()}

        audio = pipeline.generate(**inputs, max_new_tokens=max_new_tokens)
        audio_values = audio.sequences[0].cpu().numpy()

        # Convert to WAV bytes
        import numpy as np
        from scipy.io import wavfile

        sample_rate = pipeline.config.audio_encoder.sampling_rate
        audio_int16 = (audio_values * 32767).astype(np.int16)

        wav_buffer = io.BytesIO()
        wavfile.write(wav_buffer, sample_rate, audio_int16)
        wav_bytes = wav_buffer.getvalue()

        # Upload to MinIO
        filename = f"gen_music_{int(time.time())}.wav"
        upload_success = upload_object(wav_bytes, filename, content_type="audio/wav")

        # Calculate duration
        audio_duration = len(audio_int16) / sample_rate

        # Save media asset
        asset = MediaAsset(
            title=f"MusicGen: {prompt[:30]}...",
            file_path=filename,
            file_size=len(wav_bytes),
            content_type="audio/wav",
            duration=audio_duration
        )
        db.add(asset)
        db.commit()

        return {
            "status": "COMPLETED",
            "parameters": {
                "genre": genre,
                "style": style,
                "duration": duration,
                "tempo": tempo,
                "instrumentation": instrumentation
            },
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
            "colab": False
        }
    except Exception as e:
        logger.error(f"Failed to generate music: {e}")
        raise HTTPException(status_code=500, detail=f"Music generation failed: {e}")

