"""Google Gemini integration.

Text generation goes through the raw generateContent REST endpoint (httpx);
Imagen/Veo/Files analysis use the ``google-genai`` SDK. All outbound calls
live here so routers and Celery tasks can resolve a key via the encrypted
secret store and hand it straight to these helpers. Neither the SDK nor httpx
is ever imported by callers, which keeps offline tests able to monkeypatch a
single module (``app.services.gemini``) or ``httpx.post`` instead of the whole
SDK surface.
"""

import io
import logging
import time
from typing import Any, Dict, Optional, Tuple

import httpx
from fastapi import HTTPException
from google import genai
from google.genai import types

logger = logging.getLogger(__name__)

TEXT_MODEL = "gemini-2.0-flash"
IMAGE_MODEL = "imagen-3.0-generate-002"
VIDEO_MODEL = "veo-3.0-generate-001"

DEFAULT_ANALYSIS_INSTRUCTION = (
    "Analyze the attached media file. Provide a transcript (if it contains "
    "speech or on-screen text), a concise summary, and extracted metadata "
    "(duration, dimensions, language, key topics). Respond as JSON with keys "
    "'transcript', 'summary', and 'metadata'."
)


def build_client(api_key: str) -> genai.Client:
    """Create a Google Generative Language API client for the given key."""
    return genai.Client(api_key=api_key)


def call_gemini_generate_content(
    api_key: str,
    model: str,
    contents: list,
    generation_config: Optional[dict] = None,
) -> dict:
    """Call the Gemini generateContent REST endpoint with error status mapping."""
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


def generate_text(api_key: str, prompt: str, model: str = TEXT_MODEL) -> str:
    """Generate text content from a prompt using Gemini (REST generateContent)."""
    data = call_gemini_generate_content(
        api_key,
        model,
        contents=[{"role": "user", "parts": [{"text": prompt}]}],
    )
    candidates = data.get("candidates", [])
    if not candidates or not candidates[0].get("content"):
        raise HTTPException(
            status_code=502, detail="Gemini returned an empty candidate list"
        )
    parts = candidates[0]["content"].get("parts", [])
    return "".join(part.get("text", "") for part in parts)


def _upload_media(client: genai.Client, data: bytes, mime_type: str, display_name: str):
    """Upload in-memory bytes to the Gemini Files API."""
    return client.files.upload(
        file=io.BytesIO(data),
        config=types.UploadFileConfig(mime_type=mime_type, display_name=display_name),
    )


def analyze_media(
    api_key: str,
    data: bytes,
    mime_type: str,
    filename: str,
    instruction: str = DEFAULT_ANALYSIS_INSTRUCTION,
    model: str = TEXT_MODEL,
) -> Tuple[str, dict]:
    """Upload a media file to Gemini and run a multimodal analysis pass.

    Returns ``(generated_text, file_metadata)`` where ``file_metadata``
    describes the uploaded Gemini File (name, URI, MIME type).
    """
    client = build_client(api_key)
    uploaded = _upload_media(client, data, mime_type, filename)
    file_uri = uploaded.uri
    if not file_uri:
        raise RuntimeError("Gemini upload returned no file URI")
    response = client.models.generate_content(
        model=model,
        contents=[
            instruction,
            types.Part.from_uri(file_uri=file_uri, mime_type=uploaded.mime_type),
        ],
    )
    metadata = {
        "gemini_file": uploaded.name,
        "gemini_uri": file_uri,
        "mime_type": uploaded.mime_type,
        "state": getattr(uploaded, "state", None),
    }
    return (response.text or ""), metadata


def generate_image(
    api_key: str, prompt: str, model: str = IMAGE_MODEL
) -> Tuple[bytes, str]:
    """Text-to-image via Imagen. Returns ``(image_bytes, mime_type)``."""
    client = build_client(api_key)
    response = client.models.generate_images(model=model, prompt=prompt)
    generated = response.generated_images[0] if response.generated_images else None
    if generated is None or generated.image is None:
        raise RuntimeError("Gemini image generation returned no image")
    image = generated.image
    image_bytes = image.image_bytes
    if not image_bytes:
        raise RuntimeError("Gemini image generation returned empty bytes")
    return image_bytes, image.mime_type or "image/png"


def generate_video(
    api_key: str,
    prompt: str,
    model: str = VIDEO_MODEL,
    timeout: int = 300,
    poll_interval: float = 5.0,
) -> dict:
    """Text-to-video via Veo, a long-running operation.

    Polls until the operation finishes or ``timeout`` seconds elapse. Returns a
    dict with ``status`` in {"COMPLETED", "PROCESSING", "FAILED"} plus
    ``uri``/``operation_name``/``metadata``/``error`` as applicable.
    """
    client = build_client(api_key)
    operation = client.models.generate_videos(model=model, prompt=prompt)
    started = time.monotonic()
    while not getattr(operation, "done", False):
        if time.monotonic() - started >= timeout:
            return {
                "status": "PROCESSING",
                "operation_name": getattr(operation, "name", None),
            }
        time.sleep(poll_interval)
        operation = client.operations.get(operation)

    operation_name = getattr(operation, "name", None)
    error = getattr(operation, "error", None)
    if error:
        message = getattr(error, "message", None) or str(error)
        return {"status": "FAILED", "operation_name": operation_name, "error": message}

    response = getattr(operation, "response", None) or getattr(operation, "result", None)
    videos = getattr(response, "generated_videos", None) or []
    uri = None
    mime_type = "video/mp4"
    if videos:
        video = videos[0]
        uri = getattr(video, "uri", None)
        mime_type = getattr(video, "mime_type", None) or mime_type
    return {
        "status": "COMPLETED",
        "operation_name": operation_name,
        "uri": uri,
        "metadata": {"mime_type": mime_type},
    }
