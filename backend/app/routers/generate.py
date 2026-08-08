"""Multimedia generation endpoints (local Flux/SDXL + Colab offload)."""

import logging
import time
import redis
import json
import uuid
import io
import os
from typing import Optional

import torch
from fastapi import APIRouter, Depends, Query, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from diffusers import FluxPipeline, StableDiffusionXLPipeline
from diffusers.schedulers import EulerDiscreteScheduler
from PIL import Image

from app.deps import get_db
from app.models import MediaAsset, Task
from app.storage import generate_url, upload_object
from app.config import settings

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])

redis_client = redis.from_url(settings.REDIS_URL)

# Cache pipelines to avoid reloading models
flux_pipeline = None
sdxl_pipeline = None
xtts_pipeline = None
chattts_pipeline = None
musicgen_pipeline = None
musicgen_processor = None

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