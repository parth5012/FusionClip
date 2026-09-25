"""Local PyTorch video generation pipeline execution (#102).

Implements local image-to-video generation using Stable Video Diffusion (SVD)
img2vid-xt through the local ML scaffold.

Honors source image conditioning, num_frames, fps, and monotonic frame-level progress.
Encapsulates torch and diffusers imports in lazy loaders so the backend boots
cleanly without GPU or diffusers dependencies.
Video encoding is performed via the system ffmpeg binary using subprocess.
"""

from __future__ import annotations

import io
import logging
import os
import re
import subprocess
import tempfile
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from PIL import Image
from sqlalchemy.orm import Session

from app.ml.contracts import (
    DegradedReason,
    make_degraded_response,
)
from app.ml.guard import VRAMRefusalError, vram_guard
from app.ml.registry import INFERENCE_LOCK, model_registry
from app.models import MediaAsset
from app.services.embedding import get_embedding
from app.storage import generate_url, upload_object

logger = logging.getLogger(__name__)


class VideoEncodingError(RuntimeError):
    """Raised when ffmpeg video encoding fails with a non-zero exit code."""
    pass


def build_video_filename() -> str:
    """Unique, frontend-regex-compatible artifact name (`gen_video_\\d+\\.mp4`).

    Nanosecond resolution instead of seconds to avoid storage collisions.
    """
    return f"gen_video_{time.time_ns()}.mp4"


def video_progress(stage: str, value: int, total: int) -> Tuple[int, str]:
    """Calculate monotonic progress percentage (0..99) and status text for UI display.

    - Stage 'denoise' maps to 0..79%.
    - Stage 'encode' maps to 80..99%.
    Capped strictly at 99% so Celery task stays in PROGRESS state until final return.
    """
    if stage == "denoise":
        tot = max(1, total)
        val = max(0, min(value, tot))
        percent = int(79 * (val / tot))
        percent = max(0, min(79, percent))
        status = f"Generating video: denoising step {val}/{tot}"
        return percent, status
    elif stage == "encode":
        tot = max(1, total)
        val = max(0, min(value, tot))
        percent = min(99, 80 + int(20 * val / tot))
        percent = max(80, percent)
        status = f"Encoding frame {val}/{tot}"
        return percent, status
    else:
        return 0, f"Processing video: {stage}"


def make_video_loader(model_id: str = "svd"):
    """Lazy loader factory for Stable Video Diffusion pipeline.

    Guards diffusers and torch imports so they are executed only at pipeline load time.
    Uses enable_model_cpu_offload() on CUDA to fit within the 8 GB offload profile.
    """
    def _loader():
        if model_id != "svd":
            raise ValueError(f"No video loader configured for model '{model_id}'")

        import torch  # type: ignore

        cuda = torch.cuda.is_available()

        from diffusers import StableVideoDiffusionPipeline  # type: ignore

        dtype = getattr(torch, "float16", torch.float32)
        pipe = StableVideoDiffusionPipeline.from_pretrained(
            "stabilityai/stable-video-diffusion-img2vid-xt",
            torch_dtype=dtype,
        )

        if cuda:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cpu")
        return pipe

    return _loader


def encode_frames_to_mp4(
    pil_frames: List[Image.Image],
    fps: int,
    progress_cb: Optional[Callable[[int, str], None]] = None,
) -> bytes:
    """Encode PIL images into an H.264 MP4 using the system ffmpeg binary.

    Scrapes stderr for encoded frame progress and invokes progress_cb.
    """
    if not pil_frames:
        raise ValueError("No frames provided for video encoding")

    total_frames = len(pil_frames)
    with tempfile.TemporaryDirectory() as tmp_dir:
        for idx, frame in enumerate(pil_frames):
            frame_path = os.path.join(tmp_dir, f"frame_{idx:05d}.png")
            frame.save(frame_path, format="PNG")

        out_mp4 = os.path.join(tmp_dir, "out.mp4")
        cmd = [
            "ffmpeg",
            "-y",
            "-framerate",
            str(fps),
            "-i",
            os.path.join(tmp_dir, "frame_%05d.png"),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            out_mp4,
        ]

        logger.info(f"Running ffmpeg encode: {' '.join(cmd)}")
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )

        frame_regex = re.compile(r"frame=\s*(\d+)")
        buf = ""
        stderr_lines = []
        while True:
            ch = process.stderr.read(1)
            if not ch:
                break
            buf += ch
            if ch in ("\r", "\n"):
                stderr_lines.append(buf)
                match = frame_regex.search(buf)
                if match and progress_cb is not None:
                    frame_idx = int(match.group(1))
                    pct, status_text = video_progress("encode", frame_idx, total_frames)
                    progress_cb(pct, status_text)
                buf = ""

        process.wait()
        if process.returncode != 0:
            err_details = "".join(stderr_lines).strip()
            raise VideoEncodingError(
                f"FFmpeg encoding failed with exit code {process.returncode}: {err_details}"
            )

        if progress_cb is not None:
            pct, status_text = video_progress("encode", total_frames, total_frames)
            progress_cb(pct, status_text)

        with open(out_mp4, "rb") as f:
            return f.read()


def run_local_image_to_video(
    source: bytes,
    *,
    num_frames: int = 14,
    fps: int = 7,
    progress_cb: Optional[Callable[[int, str], None]] = None,
    db: Optional[Session] = None,
    source_name: Optional[str] = None,
) -> dict:
    """Execute local SVD image-to-video inference.

    1. Admission check via vram_guard under INFERENCE_LOCK for 'svd'.
    2. Decodes and verifies conditioning image bytes (raises ValueError if corrupt).
    3. Lazy-loads 'svd' model pipeline via model_registry.
    4. Runs diffusion inference with step progress reporting (0..79%).
    5. Encodes frames to MP4 using ffmpeg binary with frame progress reporting (80..99%).
    6. Uploads MP4 to storage and creates MediaAsset catalog record in DB.
    7. Returns typed response dictionary.
    """
    with INFERENCE_LOCK:
        # 1. Admission check via VRAM guard
        try:
            vram_guard.check_vram("svd")
        except VRAMRefusalError as exc:
            logger.warning(f"Local video inference refused: {exc.reason} - {exc.message}")
            return exc.to_degraded_response().model_dump()
        except Exception as exc:
            logger.error(f"Unexpected error during VRAM admission check: {exc}")
            return make_degraded_response(
                reason=DegradedReason.NO_GPU.value,
                message=f"Failed to check GPU availability: {str(exc)}",
                model_id="svd",
            ).model_dump()

        # 2. Decode conditioning image bytes
        try:
            probe = Image.open(io.BytesIO(source))
            probe.verify()
            conditioning_image = Image.open(io.BytesIO(source)).convert("RGB")
        except Exception as exc:
            logger.warning(f"Unreadable source image: {exc}")
            raise ValueError(f"Unreadable or corrupt source image: {str(exc)}") from exc

        # 3. Lazy load model via model_registry
        try:
            pipe = model_registry.load_model(
                "svd",
                loader_handle=make_video_loader("svd"),
            )
        except Exception as exc:
            logger.error(f"Failed to load video model 'svd': {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Failed to load local model 'svd': {str(exc)}",
                model_id="svd",
            ).model_dump()

        # 4. Execute diffusion inference
        total_denoise_steps = 25
        call_kwargs: Dict[str, Any] = {
            "image": conditioning_image,
            "num_frames": num_frames,
            "fps": fps,
        }

        if progress_cb is not None:
            def _step_callback(pipeline: Any, step_idx: Any, timestep: Any, callback_kwargs: Any = None):
                step = step_idx + 1 if isinstance(step_idx, int) else 1
                pct, status_text = video_progress("denoise", step, total_denoise_steps)
                progress_cb(pct, status_text)
                return callback_kwargs or {}

            call_kwargs["callback_on_step_end"] = _step_callback

        try:
            output = pipe(**call_kwargs)
        except Exception as exc:
            logger.error(f"Pipeline inference failed for 'svd': {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Pipeline inference failed for 'svd': {str(exc)}",
                model_id="svd",
            ).model_dump()

        # 5. Extract frames and encode to MP4
        try:
            frames = getattr(output, "frames", None)
            if frames is None:
                pil_frames = output if isinstance(output, list) else [output]
            elif len(frames) > 0 and isinstance(frames[0], list):
                pil_frames = frames[0]
            else:
                pil_frames = frames

            mp4_bytes = encode_frames_to_mp4(pil_frames, fps, progress_cb=progress_cb)
        except Exception as exc:
            logger.error(f"Failed to encode video frames: {exc}")
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Failed to encode video frames: {str(exc)}",
                model_id="svd",
            ).model_dump()

        # 6. Upload real MP4 bytes and persist MediaAsset
        filename = build_video_filename()
        upload_success = upload_object(mp4_bytes, filename, content_type="video/mp4")

        if upload_success and db is not None:
            try:
                title_source = source_name or "image-to-video"
                title = f"Local SVD: {title_source[:30]}..."
                duration_val = round(float(num_frames) / float(fps), 2)
                asset = MediaAsset(
                    title=title,
                    file_path=filename,
                    file_size=len(mp4_bytes),
                    content_type="video/mp4",
                    duration=duration_val,
                    embedding=get_embedding(title),
                )
                db.add(asset)
                db.commit()
            except Exception as exc:
                logger.error(f"Failed to save generated video asset: {exc}")
                db.rollback()

        # 7. Response matching typed contract
        return {
            "status": "COMPLETED",
            "type": "video",
            "filename": filename,
            "url": generate_url(filename) if upload_success else "",
            "num_frames": num_frames,
            "fps": fps,
        }
