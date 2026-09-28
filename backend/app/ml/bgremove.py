"""Background Removal engine for subject isolation (#116).

Implements Ticket #116 requirements and binding decisions from #115:
1. Two model tiers:
   - Fast tier (default): rembg with u2net (Apache-2.0, CPU-friendly)
   - Quality tier: birefnet-general (MIT, best hair/soft edges)
2. Strictly PNG (RGBA) output with alpha transparency preserved end-to-end.
   Never convert to RGB.
3. Produces an additive derivative asset linked to the original via
   MediaAsset.source_path lineage. Original asset is never mutated.
4. Progress lands in the existing Task system (Task table + Redis task_updates pub/sub).
5. VRAM/GPU refusal returns the standard degraded envelope at HTTP 200.
6. Pluggable runner interface for stubbed offline execution in CI.
"""

from __future__ import annotations

import io
import json
import logging
import re
import threading
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from fastapi import HTTPException
from PIL import Image, ImageOps
from sqlalchemy.orm import Session

from app.ml.contracts import (
    DegradedReason,
    FallbackTier,
    make_degraded_response,
)
from app.ml.guard import (
    NoGPUError,
    VRAMGuard,
    VRAMRefusalError,
    vram_guard,
)
from app.ml.registry import (
    INFERENCE_LOCK,
    ModelMetadata,
    model_registry,
)
from app.models import MediaAsset, Task
from app.services.embedding import get_embedding
from app.storage import delete_object, download_object, generate_url, upload_object

try:
    from app.routers.tasks import redis_client
except ImportError:
    redis_client = None

logger = logging.getLogger(__name__)

# Constants
OUTPUT_PREFIX = "bg_removed"
DEFAULT_OUTPUT_STEM = "isolated"
MAX_INPUT_DIMENSION = 8192
MAX_IMAGE_PATH_LENGTH = 256
UNSAFE_STEM_CHARS = re.compile(r"[^A-Za-z0-9_-]")
VIDEO_EXTENSIONS = (".mp4", ".mov", ".avi", ".mkv", ".webm")

TIER_FAST = "fast"
TIER_QUALITY = "quality"
SUPPORTED_TIERS = {TIER_FAST, TIER_QUALITY}

TIER_MODELS = {
    TIER_FAST: "u2net",
    TIER_QUALITY: "birefnet-general",
}

# Quality-tier weights. `trust_remote_code=True` executes the Hub repository's own
# modelling code, so both the repository and the exact revision it is fetched from
# are pinned here (CWE-494, CodeRabbit on PR #139). "birefnet-general" is the
# upstream *checkpoint* name for the general-use weights; the Hub repo that hosts
# them (and the AutoModelForImageSegmentation auto_map) is ZhengPeng7/BiRefNet -
# ZhengPeng7/BiRefNet-general does not exist and answers 401.
BIREFNET_REPO_ID = "ZhengPeng7/BiRefNet"
# Immutable commit sha, not a branch: bump deliberately after reviewing upstream.
BIREFNET_REVISION = "e2bf8e4460fc8fa32bba5ea4d94b3233d367b0e4"

# Register bgremove models into global registry if not already present
BGREMOVE_ROSTER: List[ModelMetadata] = [
    ModelMetadata(
        model_id="u2net",
        family="image",
        dtype_quant="fp32",
        approx_vram_gb=1.0,
        license="Apache-2.0",
        description="U2-Net background removal via rembg (Fast tier, CPU/GPU)",
    ),
    ModelMetadata(
        model_id="birefnet-general",
        family="image",
        dtype_quant="fp16",
        approx_vram_gb=3.5,
        license="MIT",
        description="BiRefNet general background removal (Quality tier, fine edge/hair matting)",
    ),
]

existing_ids = {m.model_id for m in model_registry.list_models()}
for meta in BGREMOVE_ROSTER:
    if meta.model_id not in existing_ids:
        model_registry.register(meta)


# ---------------------------------------------------------------------------
# Typed Exceptions
# ---------------------------------------------------------------------------

class BgRemoveModelUnavailable(Exception):
    """Raised when model weights or required dependencies for a tier are unavailable."""

    def __init__(
        self,
        message: str,
        model_id: str,
        reason: str = DegradedReason.LOAD_FAILED.value,
    ):
        super().__init__(message)
        self.message = message
        self.model_id = model_id
        self.reason = reason


# ---------------------------------------------------------------------------
# Pluggable Runner Interface & Cached Model Sessions
# ---------------------------------------------------------------------------

BgRemoveRunner = Callable[[Image.Image, str], Image.Image]

_custom_runner: Optional[BgRemoveRunner] = None
_runner_lock = threading.Lock()

_rembg_session = None
_rembg_session_lock = threading.Lock()

_birefnet_model = None
_birefnet_lock = threading.Lock()


def set_bgremove_runner(runner: Optional[BgRemoveRunner]) -> None:
    """Set a custom segmentation runner (e.g. stub for offline tests)."""
    global _custom_runner
    with _runner_lock:
        _custom_runner = runner


def reset_bgremove_runner() -> None:
    """Reset custom runner and cached model instances for test isolation."""
    global _custom_runner, _rembg_session, _birefnet_model
    with _runner_lock:
        _custom_runner = None
    with _rembg_session_lock:
        _rembg_session = None
    with _birefnet_lock:
        _birefnet_model = None


def get_bgremove_runner() -> BgRemoveRunner:
    """Get active segmentation runner (custom stub if set, else default)."""
    with _runner_lock:
        if _custom_runner is not None:
            return _custom_runner
    return _default_bgremove_runner


def get_rembg_session():
    """Lazy-load and cache the rembg ONNX session (u2net) behind a lock.

    Avoids graph re-parse and weight reload on every request.
    Resettable by reset_bgremove_runner() for test isolation.
    """
    global _rembg_session
    if _rembg_session is not None:
        return _rembg_session
    with _rembg_session_lock:
        if _rembg_session is not None:
            return _rembg_session
        try:
            import rembg
        except ImportError as exc:
            raise BgRemoveModelUnavailable(
                message=(
                    f"rembg is not installed on this host: {exc}. "
                    "Install rembg to enable the fast background remover."
                ),
                model_id=TIER_MODELS[TIER_FAST],
            ) from exc

        try:
            _rembg_session = rembg.new_session("u2net")
            return _rembg_session
        except Exception as exc:
            raise BgRemoveModelUnavailable(
                message=f"Failed to initialize rembg u2net session: {exc}",
                model_id=TIER_MODELS[TIER_FAST],
            ) from exc


def get_birefnet_model():
    """Lazy load the BiRefNet model pipeline for high-precision subject matting.

    Intended loader:
      Uses HuggingFace transformers AutoModelForImageSegmentation:
      model = AutoModelForImageSegmentation.from_pretrained(
          BIREFNET_REPO_ID,
          revision=BIREFNET_REVISION,
          trust_remote_code=True,
      )
      model.to("cuda" if torch.cuda.is_available() else "cpu")
      model.eval()

    If PyTorch/transformers are absent, or if the model weights cannot be loaded,
    raises BgRemoveModelUnavailable so the request degrades to HTTP 200 load_failed.
    """
    global _birefnet_model
    if _birefnet_model is not None:
        return _birefnet_model

    with _birefnet_lock:
        if _birefnet_model is not None:
            return _birefnet_model
        try:
            import torch
            from transformers import AutoModelForImageSegmentation
        except ImportError as exc:
            raise BgRemoveModelUnavailable(
                message=(
                    f"PyTorch and transformers must be installed for birefnet-general: {exc}"
                ),
                model_id=TIER_MODELS[TIER_QUALITY],
            ) from exc

        try:
            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = AutoModelForImageSegmentation.from_pretrained(
                BIREFNET_REPO_ID,
                revision=BIREFNET_REVISION,
                trust_remote_code=True,
            )
            model.to(device)
            model.eval()
            _birefnet_model = model
            return _birefnet_model
        except Exception as exc:
            raise BgRemoveModelUnavailable(
                message=f"birefnet-general model weights unavailable on host: {exc}",
                model_id=TIER_MODELS[TIER_QUALITY],
            ) from exc


def _default_bgremove_runner(image: Image.Image, tier: str = TIER_FAST) -> Image.Image:
    """Real segmentation runner. Strictly lazy imports packages.

    Raises BgRemoveModelUnavailable if required packages/weights are absent.
    """
    if tier == TIER_FAST:
        import rembg
        session = get_rembg_session()
        result = rembg.remove(image, session=session)
        if result.mode != "RGBA":
            result = result.convert("RGBA")
        return result

    elif tier == TIER_QUALITY:
        model = get_birefnet_model()
        # In real forward pass:
        # Preprocessing -> Model forward pass -> Alpha matte compositing
        import torch
        from torchvision import transforms

        transform = transforms.Compose([
            transforms.Resize((1024, 1024)),
            transforms.ToTensor(),
            transforms.Normalize(mean=[0.485, 0.456, 0.406], std=[0.229, 0.224, 0.225]),
        ])
        orig_w, orig_h = image.size
        rgb_img = image.convert("RGB")
        input_tensor = transform(rgb_img).unsqueeze(0)
        device = next(model.parameters()).device
        input_tensor = input_tensor.to(device)

        with torch.no_grad():
            preds = model(input_tensor)[-1].sigmoid().cpu()
        pred = preds[0].squeeze()
        pred_pil = transforms.ToPILImage()(pred).resize((orig_w, orig_h), Image.Resampling.BILINEAR)

        out_rgba = image.convert("RGBA")
        out_rgba.putalpha(pred_pil)
        return out_rgba

    raise ValueError(f"Unknown tier '{tier}'")


# ---------------------------------------------------------------------------
# Path & Image Helpers
# ---------------------------------------------------------------------------

def _sanitize_output_stem(source_path: str) -> str:
    """Clean stem to safe alphanumeric + underscore chars."""
    stem = UNSAFE_STEM_CHARS.sub("_", Path(source_path).stem).strip("._")
    return stem or DEFAULT_OUTPUT_STEM


def build_bgremove_filename(source_path: str, token: Optional[str] = None) -> str:
    """Construct unique output key: bg_removed/<stem>_<12_hex>.png.

    The 12-hex unique token prevents collisions across concurrent operations.
    """
    tok = token or uuid.uuid4().hex[:12]
    return f"{OUTPUT_PREFIX}/{_sanitize_output_stem(source_path)}_{tok}.png"


def _cap_dimension(image: Image.Image) -> Image.Image:
    """Rescale if longest edge exceeds MAX_INPUT_DIMENSION (8192px)."""
    width, height = image.size
    longest = max(width, height)
    if longest <= MAX_INPUT_DIMENSION:
        return image
    scale = MAX_INPUT_DIMENSION / longest
    if width >= height:
        target = (MAX_INPUT_DIMENSION, int(height * scale))
    else:
        target = (int(width * scale), MAX_INPUT_DIMENSION)
    logger.info(f"Capping image dimension from {image.size} to {target}")
    return image.resize(target, Image.Resampling.LANCZOS)


def _load_source_image(image_path: str) -> Image.Image:
    """Fetch image bytes from storage and decode to PIL Image.

    Uses download_object (following skin_enhancer.py:1217) which returns None
    for missing keys instead of leaking backend botocore exceptions.
    """
    raw = download_object(image_path)
    if raw is None:
        raise HTTPException(
            status_code=400,
            detail=f"source_not_found: Source image '{image_path}' was not found in storage.",
        )

    try:
        img = Image.open(io.BytesIO(raw))
        img = ImageOps.exif_transpose(img)
        # Convert paletted or grayscale images to RGBA/RGB
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA")
        img.load()
        return img
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"source_unreadable: Source image '{image_path}' is unreadable or corrupt: {exc}",
        )


# ---------------------------------------------------------------------------
# Task & PubSub Progress Reporting
# ---------------------------------------------------------------------------

def _publish_task_update(
    task_id: str,
    percent: int,
    status: str = "PROCESSING",
    error: Optional[str] = None,
    step_message: Optional[str] = None,
) -> None:
    """Publish real-time progress to Redis task_updates channel for WebSockets."""
    if redis_client is not None:
        try:
            payload = {
                "task_id": task_id,
                "status": status,
                "progress": percent,
                "step_message": step_message,
                "error": error,
            }
            redis_client.publish("task_updates", json.dumps(payload))
        except Exception as exc:
            logger.warning(f"Could not publish bgremove progress to Redis: {exc}")


# ---------------------------------------------------------------------------
# Main Execution Pipeline
# ---------------------------------------------------------------------------

def run_background_removal(
    image_path: str,
    tier: str = TIER_FAST,
    db: Optional[Session] = None,
    task_id: Optional[str] = None,
) -> dict:
    """Execute background removal producing an alpha-correct derivative asset.

    Steps:
    1. Resolve source image from storage, validate format, cap dimensions.
    2. Check VRAM/GPU guard for admission (especially on Quality tier).
    3. Initialize Task record and publish initial progress.
    4. Execute subject isolation using the active runner.
    5. Encode strictly as RGBA PNG (preserving alpha channel end-to-end).
    6. Upload derivative to storage under bg_removed/<stem>_<token>.png.
    7. Persist MediaAsset record with source_path pointing to input (lineage).
    8. Update Task record to COMPLETED (100%) and publish progress.
    9. Return COMPLETED result or degraded response at HTTP 200 on refusal/failure.
    """
    tier = (tier or TIER_FAST).strip().lower()
    if tier not in SUPPORTED_TIERS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unsupported background removal tier '{tier}'. "
                f"Supported tiers: {', '.join(sorted(SUPPORTED_TIERS))}."
            ),
        )

    model_id = TIER_MODELS[tier]
    task_token = task_id.split("_", 1)[-1] if (task_id and "_" in task_id) else uuid.uuid4().hex[:12]
    task_id = task_id or f"bgremove_{task_token}"

    # 1. Source resolution (outside lock)
    source_image = _load_source_image(image_path)
    source_image = _cap_dimension(source_image)

    # 2. VRAM Guard admission check
    if tier == TIER_QUALITY:
        try:
            model_id = vram_guard.select_fitting_model(
                candidate_ids=[model_id],
                working_overhead_gb=0.5,
            )
        except VRAMRefusalError as exc:
            logger.warning(f"BgRemove quality tier refused: {exc.reason} - {exc.message}")
            if db is not None:
                db_task = Task(
                    task_id=task_id,
                    name="bgremove",
                    status="FAILED",
                    progress=0,
                    error=exc.message,
                    logs=f"Refused: {exc.message}",
                )
                db.add(db_task)
                db.commit()
            _publish_task_update(task_id, 0, status="FAILED", error=exc.message)
            return exc.to_degraded_response().model_dump()
        except Exception as exc:
            logger.error(f"Unexpected error during VRAM admission check: {exc}")
            return make_degraded_response(
                reason=DegradedReason.NO_GPU.value,
                message=f"Failed to check GPU availability: {exc}",
                model_id=model_id,
            ).model_dump()

    # 3. Initialize Task row in DB (name="bgremove" for type filter support)
    db_task = None
    if db is not None:
        db_task = Task(
            task_id=task_id,
            name="bgremove",
            status="PROCESSING",
            progress=0,
            logs=f"Started background removal for {image_path} using {model_id} ({tier})",
        )
        db.add(db_task)
        db.commit()
    _publish_task_update(task_id, 10, "PROCESSING", step_message="Starting subject isolation")

    # 4. Run segmentation inside INFERENCE_LOCK
    runner = get_bgremove_runner()
    try:
        with INFERENCE_LOCK:
            _publish_task_update(task_id, 30, "PROCESSING", step_message="Segmenting foreground subject")
            output_image = runner(source_image, tier)
    except BgRemoveModelUnavailable as exc:
        logger.warning(f"Background removal model unavailable: {exc.message}")
        if db is not None and db_task is not None:
            db_task.status = "FAILED"
            db_task.error = exc.message
            db.commit()
        _publish_task_update(task_id, 0, "FAILED", error=exc.message)
        return make_degraded_response(
            reason=exc.reason,
            message=exc.message,
            model_id=exc.model_id,
        ).model_dump()
    except Exception as exc:
        logger.error(f"Background removal inference failed: {exc}", exc_info=True)
        if db is not None and db_task is not None:
            db_task.status = "FAILED"
            db_task.error = str(exc)
            db.commit()
        _publish_task_update(task_id, 0, "FAILED", error=str(exc))
        return make_degraded_response(
            reason=DegradedReason.LOAD_FAILED.value,
            message=f"Background removal failed: {exc}",
            model_id=model_id,
        ).model_dump()

    # 5. Ensure strictly RGBA output (alpha correct, NEVER convert to RGB)
    if output_image.mode != "RGBA":
        output_image = output_image.convert("RGBA")

    # 6. Encode strictly as PNG bytes
    out_buf = io.BytesIO()
    output_image.save(out_buf, format="PNG", optimize=True)
    png_bytes = out_buf.getvalue()

    # 7. Upload derivative to storage
    filename = build_bgremove_filename(image_path, token=task_token)
    _publish_task_update(task_id, 75, "PROCESSING", step_message="Uploading derivative to storage")
    if not upload_object(png_bytes, filename, content_type="image/png"):
        logger.error(f"Failed to upload isolated image '{filename}' to storage")
        if db is not None and db_task is not None:
            db_task.status = "FAILED"
            db_task.error = "Storage upload failed"
            db.commit()
        _publish_task_update(task_id, 0, "FAILED", error="Storage upload failed")
        return make_degraded_response(
            reason=DegradedReason.LOAD_FAILED.value,
            message="Failed to upload isolated image to storage",
            model_id=model_id,
        ).model_dump()

    # 8. Record MediaAsset in catalog with source_path lineage
    if db is not None:
        try:
            title = f"Background Removed: {Path(image_path).stem} ({tier})"
            asset = MediaAsset(
                title=title,
                file_path=filename,
                file_size=len(png_bytes),
                content_type="image/png",
                duration=0.0,
                # Lineage: pairs source and derivative without mutating source
                source_path=image_path,
                embedding=get_embedding(title),
            )
            db.add(asset)

            # Update Task row to COMPLETED
            if db_task is not None:
                db_task.status = "COMPLETED"
                db_task.progress = 100
                db_task.logs = json.dumps({
                    "output": filename,
                    "tier": tier,
                    "model_id": model_id,
                    "width": output_image.width,
                    "height": output_image.height,
                })
            db.commit()
        except Exception as exc:
            logger.error(f"Failed to save background-removed asset to catalog: {exc}")
            db.rollback()
            # Clean up orphaned storage blob to avoid leaking objects in MinIO (#116 review fix 5)
            try:
                delete_object(filename)
            except Exception as del_err:
                logger.warning(
                    f"Failed to delete orphaned derivative '{filename}' from storage: {del_err}"
                )

            if db_task is not None:
                try:
                    db_task.status = "FAILED"
                    db_task.error = f"Catalog persistence error: {exc}"
                    db.commit()
                except Exception:
                    pass
            _publish_task_update(task_id, 0, "FAILED", error=str(exc))
            return make_degraded_response(
                reason=DegradedReason.LOAD_FAILED.value,
                message=f"Failed to save asset to catalog: {exc}",
                model_id=model_id,
            ).model_dump()

    _publish_task_update(task_id, 100, "COMPLETED", step_message="Subject isolation complete")

    # 9. Return COMPLETED result
    return {
        "status": "COMPLETED",
        "task_id": task_id,
        "filename": filename,
        "url": generate_url(filename),
        "source_path": image_path,
        "tier": tier,
        "model_id": model_id,
        "content_type": "image/png",
        "image_size": [output_image.width, output_image.height],
    }


def describe_bgremove_surface() -> Dict[str, Any]:
    """Machine-readable description of background removal surface for frontend."""
    return {
        "tiers": sorted(list(SUPPORTED_TIERS)),
        "default_tier": TIER_FAST,
        "models": dict(TIER_MODELS),
        "descriptions": {
            TIER_FAST: "rembg + u2net (Apache-2.0, fast CPU/GPU subject isolation)",
            TIER_QUALITY: (
                "birefnet-general (MIT, best hair and soft-edge matting; "
                "requires birefnet-general weights to be installed on host)"
            ),
        },
        "requirements": {
            TIER_FAST: "rembg package and u2net model weights",
            TIER_QUALITY: "torch, transformers, and birefnet-general weights installed on host",
        },
    }
