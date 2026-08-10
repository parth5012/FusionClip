"""ElevenLabs integration built on the ``elevenlabs`` SDK.

All outbound calls live here so routers and Celery tasks can resolve a key via
the encrypted secret store and hand it straight to these helpers. The SDK is
never imported by callers, which keeps offline tests able to monkeypatch a
single module (``app.services.elevenlabs``) instead of the whole SDK surface.
"""

import logging
from typing import Dict, List

from elevenlabs import ElevenLabs, VoiceSettings

logger = logging.getLogger(__name__)

#: Well-known preset voice present on every ElevenLabs account ("Rachel").
DEFAULT_VOICE_ID = "21m00Tcm4TlvDq8ikWAM"
DEFAULT_MODEL = "eleven_multilingual_v2"
DEFAULT_OUTPUT_FORMAT = "mp3_44100_128"
AUDIO_CONTENT_TYPE = "audio/mpeg"


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
    """Synthesize speech and return raw audio bytes.

    ``clarity`` maps to the SDK's ``similarity_boost`` voice setting (its former
    name in older SDK versions); it controls how closely the output matches the
    selected voice. Higher ``stability`` produces flatter, more monotone speech.
    """
    client = build_client(api_key)
    voice_settings = VoiceSettings(
        stability=stability,
        similarity_boost=clarity,
        style=0.0,
        use_speaker_boost=True,
    )
    stream = client.text_to_speech.convert(
        voice_id=voice_id,
        output_format=DEFAULT_OUTPUT_FORMAT,
        text=text,
        model_id=model,
        voice_settings=voice_settings,
    )
    return b"".join(stream)


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
