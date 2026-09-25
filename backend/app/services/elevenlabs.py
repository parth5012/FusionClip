"""ElevenLabs integration.

Speech synthesis and sound effects go through the raw ElevenLabs REST
endpoints (httpx); voice cloning/listing use the ``elevenlabs`` SDK. All
outbound calls live here so routers and Celery tasks can resolve a key via
the encrypted secret store and hand it straight to these helpers. Neither the
SDK nor httpx is ever imported by callers, which keeps offline tests able to
monkeypatch a single module (``app.services.elevenlabs``) or ``httpx.post``
instead of the whole SDK surface.
"""

import logging
import os
from typing import Dict, List, NoReturn, Optional

import httpx
from fastapi import HTTPException
from elevenlabs import ElevenLabs, VoiceSettings

logger = logging.getLogger(__name__)

#: Well-known preset voice present on every ElevenLabs account ("Rachel").
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
AUDIO_CONTENT_TYPE = "audio/mpeg"
VOICE_CLONE_TIMEOUT = 300  # 5 minutes for cloning process


def build_client(api_key: str) -> ElevenLabs:
    """Create an ElevenLabs client for the given key."""
    return ElevenLabs(api_key=api_key)


def synthesize(
    api_key: str,
    text: str,
    voice_id: str = DEFAULT_VOICE_ID,
    stability: float = 0.5,
    clarity: float = 0.75,
    model: str = DEFAULT_MODEL,
) -> bytes:
    """Synthesize speech and return raw audio bytes (REST text-to-speech).

    ``clarity`` maps to the API's ``similarity_boost`` voice setting (its
    former name in older SDK versions); it controls how closely the output
    matches the selected voice. Higher ``stability`` produces flatter, more
    monotone speech.
    """
    url = (
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
        f"?output_format={DEFAULT_OUTPUT_FORMAT}"
    )
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload: Dict = {
        "text": text,
        "model_id": model,
        "voice_settings": {
            "stability": stability,
            "similarity_boost": clarity,
            "style": 0.0,
            "use_speaker_boost": True,
        },
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


def clone_voice(
    api_key: str,
    audio_file_path: str,
    voice_name: str,
    timeout: int = VOICE_CLONE_TIMEOUT,
) -> str:
    """Clone a voice from a local audio file and return the voice ID."""
    client = build_client(api_key)
    if not os.path.exists(audio_file_path):
        raise ValueError(f"Audio file not found: {audio_file_path}")
    voice = client.voices.ivc.create(
        name=voice_name,
        files=[audio_file_path],
    )
    return voice.voice_id


def list_voices(api_key: str) -> List[Dict]:
    """Return the account's available voices as plain dicts."""
    client = build_client(api_key)
    response = client.voices.get_all()
    voices = []
    for voice in getattr(response, "voices", None) or []:
        voices.append(
            {
                "voice_id": getattr(voice, "voice_id", None),
                "name": getattr(voice, "name", None),
                "labels": getattr(voice, "labels", None) or {},
                "category": getattr(voice, "category", None),
                "preview_url": getattr(voice, "preview_url", None),
            }
        )
    return voices


def generate_sound_effect(
    api_key: str,
    text: str,
    duration_seconds: Optional[float] = None,
) -> bytes:
    """Generate a sound effect from a text prompt and return raw audio bytes (REST)."""
    url = f"https://api.elevenlabs.io/v1/sound-generation?output_format={DEFAULT_OUTPUT_FORMAT}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
    }
    payload: Dict = {
        "text": text,
        "model_id": "eleven_text_to_sound_v2",
    }
    if duration_seconds is not None:
        payload["duration_seconds"] = duration_seconds

    try:
        resp = httpx.post(url, headers=headers, json=payload, timeout=30.0)
    except Exception as exc:
        logger.error(f"ElevenLabs sound-generation request failed: {exc}")
        raise HTTPException(
            status_code=502, detail="Failed to connect to ElevenLabs API"
        ) from exc

    if resp.status_code == 200:
        return resp.content

    _handle_elevenlabs_error(resp)


def _handle_elevenlabs_error(resp: httpx.Response) -> NoReturn:
    """Map an ElevenLabs REST error response onto an HTTPException."""
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
