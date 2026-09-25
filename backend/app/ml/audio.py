"""Local PyTorch audio generation pipeline execution (#101).

Implements local text-to-speech, zero-shot voice cloning (Coqui XTTS v2),
and text-to-music / SFX (MusicGen large: facebook/musicgen-large, 10.4 GB, FP16 on CUDA)
through the local ML scaffold.

Honors prompt, type, voice_id, duration, and reference audio sample.
Strictly guards and lazy-loads torch, transformers, and TTS dependencies so the app
boots cleanly in non-GPU and torch-free environments.
"""

from __future__ import annotations

import io
import logging
import os
import tempfile
import time
import wave
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.ml.contracts import (
    DegradedReason,
    make_degraded_response,
)
from app.ml.guard import VRAMRefusalError, vram_guard
from app.ml.registry import INFERENCE_LOCK, model_registry
from app.models import MediaAsset
from app.services.embedding import get_embedding
from app.storage import download_object, generate_url, upload_object

logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_TYPES = frozenset({"tts", "voice", "voice_clone", "sfx", "music"})


def build_audio_filename() -> str:
    """Unique, frontend-regex-compatible artifact name (`gen_audio_\\d+\\.wav`).

    Nanosecond resolution instead of seconds: two requests finishing inside the
    same second would otherwise overwrite each other in storage.
    """
    return f"gen_audio_{time.time_ns()}.wav"


class MusicgenPipeline:
    """Wrapper around HuggingFace MusicGen model and processor."""

    def __init__(self, model: Any, processor: Any, device: str = "cpu"):
        self.model = model
        self.processor = processor
        self.device = device

    def __call__(self, prompt: str, duration: Optional[float] = None, **kwargs: Any) -> bytes:
        dur = float(duration) if duration is not None and duration > 0 else 15.0
        # MusicGen frame rate is 50 tokens per second
        max_new_tokens = int(dur * 50)
        inputs = self.processor(text=[prompt], padding=True, return_tensors="pt")
        inputs = {k: v.to(self.device) for k, v in inputs.items()}
        try:
            import torch  # type: ignore

            inference_ctx = torch.inference_mode()
        except (ImportError, Exception):
            import contextlib

            inference_ctx = contextlib.nullcontext()

        with inference_ctx:
            audio_values = self.model.generate(**inputs, max_new_tokens=max_new_tokens)

        encoder_cfg = getattr(getattr(self.model, "config", None), "audio_encoder", None)
        sampling_rate = getattr(encoder_cfg, "sampling_rate", 32000)

        import numpy as np  # type: ignore
        waveform = audio_values[0].cpu().numpy()
        if waveform.ndim > 1:
            waveform = waveform[0]

        int16_waveform = (np.clip(waveform, -1.0, 1.0) * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        import scipy.io.wavfile  # type: ignore
        scipy.io.wavfile.write(buf, sampling_rate, int16_waveform)
        return buf.getvalue()


def make_audio_loader(model_id: str):
    """Lazy loader factory for audio pipelines.

    Guards TTS, transformers, and torch imports so they are executed only at pipeline load time.
    """
    def _loader():
        if model_id not in ("xtts-v2", "musicgen"):
            raise ValueError(f"No audio loader configured for model '{model_id}'")

        import torch  # type: ignore

        cuda = torch.cuda.is_available()
        device = "cuda" if cuda else "cpu"

        if model_id == "xtts-v2":
            from TTS.api import TTS  # type: ignore

            tts = TTS(model_name="tts_models/multilingual/multi-dataset/xtts_v2")
            if cuda:
                tts.to("cuda")
            return tts
        elif model_id == "musicgen":
            from transformers import AutoProcessor, MusicgenForConditionalGeneration  # type: ignore

            processor = AutoProcessor.from_pretrained("facebook/musicgen-large")
            model_kwargs: Dict[str, Any] = {}
            if cuda:
                model_kwargs["torch_dtype"] = torch.float16
            model = MusicgenForConditionalGeneration.from_pretrained(
                "facebook/musicgen-large", **model_kwargs
            )
            model.to(device)
            return MusicgenPipeline(model=model, processor=processor, device=device)
        else:
            raise ValueError(f"No audio loader configured for model '{model_id}'")

    return _loader


def _extract_wav_bytes(output: Any) -> bytes:
    """Normalize various model output types (bytes, list of bytes, numpy, torch) to WAV bytes."""
    if isinstance(output, (bytes, bytearray)):
        return bytes(output)
    if isinstance(output, list) and len(output) > 0:
        first = output[0]
        if isinstance(first, (bytes, bytearray)):
            return bytes(first)
    if hasattr(output, "cpu"):
        output = getattr(output, "cpu")().numpy()
    if hasattr(output, "ndim"):
        import numpy as np  # type: ignore
        arr = np.asarray(output)
        if arr.ndim > 1:
            arr = arr[0]
        int16_arr = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16)
        buf = io.BytesIO()
        import scipy.io.wavfile  # type: ignore
        scipy.io.wavfile.write(buf, 32000, int16_arr)
        return buf.getvalue()
    raise ValueError(f"Unrecognized audio pipeline output type: {output.__class__.__name__}")


def run_local_audio_generation(
    prompt: str,
    type: str = "tts",
    voice_id: Optional[str] = None,
    duration: Optional[float] = None,
    reference: Optional[str] = None,
    db: Optional[Session] = None,
) -> dict:
    """Execute local audio generation following Decision #3 and Decision #4.

    1. Selects model candidate via vram_guard:
       - 'tts', 'voice', 'voice_clone' -> ['xtts-v2']
       - 'sfx', 'music' -> ['musicgen']
    2. On refusal or absence of GPU, returns typed DegradedResponse (HTTP 200).
    3. On admission, lazy-loads model via model_registry and executes inference.
    4. Uploads real WAV bytes to storage and creates MediaAsset record in DB.
    5. Returns completed response dict with markers (voice_clone marker if applicable).
    """
    if type in ("tts", "voice", "voice_clone"):
        candidates = ["xtts-v2"]
    elif type in ("sfx", "music"):
        candidates = ["musicgen"]
    else:
        return make_degraded_response(
            reason=DegradedReason.MODEL_NOT_FOUND.value,
            message=f"Unsupported audio type '{type}'. Supported types: {', '.join(sorted(SUPPORTED_AUDIO_TYPES))}",
        ).model_dump()

    with INFERENCE_LOCK:
        # Invariant: INFERENCE_LOCK serializes admission and inference so eviction
        # cannot occur while another request is mid-inference.
        ref_bytes = None
        if reference:
            ref_bytes = download_object(reference)
            if ref_bytes is None and os.path.isfile(reference):
                try:
                    with open(reference, "rb") as f:
                        ref_bytes = f.read()
                except Exception:
                    pass
            if ref_bytes is None:
                raise HTTPException(
                    status_code=400,
                    detail=f"Reference audio '{reference}' not found or unreadable in storage",
                )

        # 1. Admission check via VRAM guard
        try:
            selected_model_id = vram_guard.select_fitting_model(
                candidate_ids=candidates,
                working_overhead_gb=1.0,
            )
        except VRAMRefusalError as exc:
            logger.warning(f"Local audio inference refused: {exc.reason} - {exc.message}")
            return exc.to_degraded_response().model_dump()
        except Exception as exc:
            logger.error(f"Unexpected error during VRAM admission check: {exc}")
            return make_degraded_response(
                reason=DegradedReason.NO_GPU.value,
                message=f"Failed to check GPU availability: {str(exc)}",
            ).model_dump()

        # 2. Lazy load via model_registry
        try:
            model_instance = model_registry.load_model(
                selected_model_id,
                loader_handle=make_audio_loader(selected_model_id),
            )
        except Exception as exc:
            logger.error(f"Failed to load audio model '{selected_model_id}': {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Failed to load local model '{selected_model_id}': {str(exc)}",
                model_id=selected_model_id,
            ).model_dump()

        # 3. Execute inference
        ref_tmp_path = None
        try:
            if reference and ref_bytes is not None:
                with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as ref_tmp:
                    ref_tmp.write(ref_bytes)
                    ref_tmp_path = ref_tmp.name

            if selected_model_id == "xtts-v2":
                if hasattr(model_instance, "tts_to_file"):
                    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                        tmp_path = tmp.name
                    try:
                        if ref_tmp_path:
                            model_instance.tts_to_file(
                                text=prompt,
                                speaker_wav=ref_tmp_path,
                                language="en",
                                file_path=tmp_path,
                            )
                        else:
                            speaker = None
                            if hasattr(model_instance, "speakers") and model_instance.speakers:
                                if voice_id and voice_id in model_instance.speakers:
                                    speaker = voice_id
                                else:
                                    speaker = model_instance.speakers[0]
                            if speaker:
                                model_instance.tts_to_file(
                                    text=prompt,
                                    speaker=speaker,
                                    language="en",
                                    file_path=tmp_path,
                                )
                            else:
                                model_instance.tts_to_file(
                                    text=prompt,
                                    language="en",
                                    file_path=tmp_path,
                                )
                        with open(tmp_path, "rb") as f:
                            wav_bytes = f.read()
                    finally:
                        if os.path.exists(tmp_path):
                            os.remove(tmp_path)
                elif callable(model_instance):
                    call_kwargs: Dict[str, Any] = {
                        "prompt": prompt,
                        "type": type,
                        "voice_id": voice_id,
                        "duration": duration,
                        "reference": reference,
                    }
                    if ref_tmp_path:
                        call_kwargs["speaker_wav"] = ref_tmp_path
                    output = model_instance(**call_kwargs)
                    wav_bytes = _extract_wav_bytes(output)
                else:
                    raise ValueError(f"Unrecognized XTTS model instance type: {model_instance.__class__.__name__}")
            elif selected_model_id == "musicgen":
                if callable(model_instance):
                    output = model_instance(prompt=prompt, duration=duration)
                    wav_bytes = _extract_wav_bytes(output)
                else:
                    raise ValueError(f"Unrecognized MusicGen model instance type: {model_instance.__class__.__name__}")
            else:
                raise ValueError(f"Unknown model_id '{selected_model_id}'")
        except HTTPException:
            raise
        except Exception as exc:
            logger.error(f"Audio execution failed for '{selected_model_id}': {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Pipeline inference failed for '{selected_model_id}': {str(exc)}",
                model_id=selected_model_id,
            ).model_dump()
        finally:
            if ref_tmp_path and os.path.exists(ref_tmp_path):
                os.remove(ref_tmp_path)

        # 4. Upload real WAV bytes
        filename = build_audio_filename()
        upload_success = upload_object(wav_bytes, filename, content_type="audio/wav")

        # 5. Determine duration
        duration_val = 3.0
        try:
            with wave.open(io.BytesIO(wav_bytes), "rb") as wf:
                frames = wf.getnframes()
                rate = wf.getframerate()
                if rate > 0:
                    duration_val = round(frames / float(rate), 2)
        except Exception:
            if duration is not None and duration > 0:
                duration_val = float(duration)

        # 6. Persist MediaAsset in DB
        if upload_success and db is not None:
            try:
                if type == "voice_clone":
                    title = f"Voice Clone: {prompt[:30]}..."
                elif type in ("sfx", "music"):
                    title = f"MusicGen Generated: {prompt[:30]}..."
                else:
                    title = f"XTTS Generated: {prompt[:30]}..."

                asset = MediaAsset(
                    title=title,
                    file_path=filename,
                    file_size=len(wav_bytes),
                    content_type="audio/wav",
                    duration=duration_val,
                    embedding=get_embedding(prompt or title),
                )
                db.add(asset)
                db.commit()
            except Exception as exc:
                logger.error(f"Failed to save generated audio asset: {exc}")
                db.rollback()

        # 7. Construct markers
        markers: List[Dict[str, Any]] = []
        if type == "voice_clone":
            markers.append(
                {
                    "time": 0.0,
                    "label": f"voice clone: {reference}",
                    "kind": "voice_clone",
                }
            )

        return {
            "status": "COMPLETED",
            "type": type,
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
            "markers": markers,
        }
