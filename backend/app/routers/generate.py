"""Multimedia generation endpoints (currently mocked provider output)."""

import logging
import time

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.deps import get_db
from app.models import MediaAsset
from app.storage import generate_url, upload_object

logger = logging.getLogger(__name__)

router = APIRouter(tags=["generate"])


@router.post("/api/generate/text")
def generate_text(prompt: str = Query(...)):
    # Simulates text storyboard generation with Gemini API
    return {
        "status": "COMPLETED",
        "output": f"Generated content using Google Gemini for prompt: '{prompt}'. This is a mock Gemini AI response outlining video storyboard structure.",
    }


@router.post("/api/generate/audio")
def generate_audio(
    prompt: str = Query(...),
    type: str = Query("tts"),
    db: Session = Depends(get_db),
):
    # Simulated ElevenLabs audio synthesis
    filename = f"gen_audio_{int(time.time())}.mp3"
    content = b"Mock elevenlabs generated audio bytes."
    upload_success = upload_object(content, filename, content_type="audio/mpeg")

    # Save to media assets
    try:
        asset = MediaAsset(
            title=f"ElevenLabs Synthesized: {prompt[:30]}...",
            file_path=filename,
            file_size=len(content),
            content_type="audio/mpeg",
            duration=3.0,
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
    # Simulated Local Flux sandbox image generation
    filename = f"gen_image_{int(time.time())}.png"
    content = b"Mock local flux generated image bytes."
    upload_success = upload_object(content, filename, content_type="image/png")

    # Save to media assets
    try:
        asset = MediaAsset(
            title=f"Flux Generated: {prompt[:30]}...",
            file_path=filename,
            file_size=len(content),
            content_type="image/png",
            duration=0.0,
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
