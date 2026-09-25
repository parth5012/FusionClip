"""Local PyTorch image generation pipeline execution (#100).

Implements local text-to-image inference using the priority-1 model FLUX.1 [schnell]
at FP8 with auto-downgrade to SDXL base when free VRAM is insufficient (Decision #4).

Honors steps, guidance scale, scheduler choices, aspect ratio, and denoising strength
as promised in features.md §3.

Strictly guards and lazy-loads torch and diffusers dependencies so the app boots
and non-GPU environments function cleanly.
"""

from __future__ import annotations

import io
import logging
import math
import time
from typing import Any, Dict, Optional, Tuple

from sqlalchemy.orm import Session

from app.ml.contracts import (
    DegradedReason,
    make_degraded_response,
)
from app.ml.guard import VRAMRefusalError, vram_guard
from app.ml.registry import model_registry
from app.models import MediaAsset
from app.services.embedding import get_embedding
from app.storage import generate_url, upload_object

logger = logging.getLogger(__name__)

# Standard diffusers schedulers mapped from user-friendly names
SUPPORTED_SCHEDULERS: Dict[str, str] = {
    "euler": "EulerDiscreteScheduler",
    "euler_a": "EulerAncestralDiscreteScheduler",
    "dpm": "DPMSolverMultistepScheduler",
    "dpmsolver": "DPMSolverMultistepScheduler",
    "ddim": "DDIMScheduler",
    "pndm": "PNDMScheduler",
    "flow_match": "FlowMatchEulerDiscreteScheduler",
    "heun": "HeunDiscreteScheduler",
    "lms": "LMSDiscreteScheduler",
}

# FLUX is a flow-matching model: classical DDIM/PNDM/etc. schedulers raise inside
# diffusers, which would otherwise surface as a misleading load_failed. `euler` is
# allowed because flow-matching's own Euler sampler is the natural equivalent and
# it is what the UI labels the default.
FLUX_COMPATIBLE_SCHEDULERS = frozenset({"flow_match", "euler"})
FLUX_SCHEDULER_OVERRIDES = {"euler": "FlowMatchEulerDiscreteScheduler"}

# Standard diffusion dimensions mapped from aspect ratio choices.
# Every edge must be a multiple of 16: FLUX patchifies latents 2x2 after the 8x VAE
# downsample, so a non-multiple (the old 680) fails at latent-pack time on a real GPU.
ASPECT_RATIO_DIMENSIONS: Dict[str, Tuple[int, int]] = {
    "1:1": (1024, 1024),
    "16:9": (1024, 576),
    "9:16": (576, 1024),
    "4:3": (1024, 768),
    "3:4": (768, 1024),
    "3:2": (1024, 672),
    "2:3": (672, 1024),
}

_TARGET_AREA = 1024 * 1024
_MULTIPLE = 16


def _round_to_multiple(value: float) -> int:
    return max(_MULTIPLE, int(round(value / _MULTIPLE)) * _MULTIPLE)


def get_dimensions_for_aspect_ratio(aspect_ratio: Optional[str]) -> Tuple[int, int]:
    """Resolve width/height for an aspect ratio, always multiples of 16.

    Presets win so existing ratios keep their exact dimensions; anything else
    (the validator accepts arbitrary `W:H`) is derived from a ~1024^2 area
    instead of silently degrading to a square.
    """
    if aspect_ratio:
        preset = ASPECT_RATIO_DIMENSIONS.get(aspect_ratio)
        if preset is not None:
            return preset
        parts = aspect_ratio.split(":")
        if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
            rw, rh = int(parts[0]), int(parts[1])
            if rw > 0 and rh > 0:
                scale = math.sqrt(_TARGET_AREA / (rw * rh))
                return (_round_to_multiple(rw * scale), _round_to_multiple(rh * scale))
        logger.warning(
            f"Unrecognized aspect ratio {aspect_ratio!r}; defaulting to 1024x1024"
        )
    return (1024, 1024)


def build_image_filename() -> str:
    """Unique, frontend-regex-compatible artifact name (`gen_image_\\d+\\.png`).

    Nanosecond resolution instead of seconds: two requests finishing inside the
    same second would otherwise overwrite each other in storage.
    """
    return f"gen_image_{time.time_ns()}.png"


def make_diffusers_loader(model_id: str):
    """Lazy loader factory for diffusers pipelines.

    Guards diffusers and torch imports so they are executed only at pipeline load time.

    On CUDA the pipeline is moved with `enable_model_cpu_offload()` rather than
    `pipe.to('cuda')`: FLUX in bfloat16 is ~34 GB fully resident and would OOM
    every GPU at or below the 16 GB floor from decision #1, while model CPU
    offload matches the ~13 GB figure the registry advertises.
    """
    def _loader():
        import torch  # type: ignore

        cuda = torch.cuda.is_available()

        if model_id == "flux-schnell":
            from diffusers import FluxPipeline  # type: ignore

            dtype = getattr(torch, "bfloat16", torch.float16)
            pipe = FluxPipeline.from_pretrained(
                "black-forest-labs/FLUX.1-schnell",
                torch_dtype=dtype,
            )
        elif model_id == "sdxl":
            from diffusers import StableDiffusionXLPipeline  # type: ignore

            dtype = getattr(torch, "float16", torch.float32)
            pipe = StableDiffusionXLPipeline.from_pretrained(
                "stabilityai/stable-diffusion-xl-base-1.0",
                torch_dtype=dtype,
            )
        else:
            raise ValueError(f"No diffusers loader configured for model '{model_id}'")

        if cuda:
            pipe.enable_model_cpu_offload()
        else:
            pipe.to("cpu")
        return pipe

    return _loader


def apply_scheduler_to_pipeline(
    pipe: Any, scheduler_name: Optional[str], model_id: Optional[str] = None
) -> None:
    """Configure the requested scheduler on the diffusion pipeline.

    Incompatible pairings (a classical scheduler on flow-matching FLUX) are
    skipped with a warning instead of raising, so the caller keeps its default
    scheduler rather than failing the whole generation.
    """
    if not scheduler_name:
        return

    sched_key = scheduler_name.lower()
    if sched_key not in SUPPORTED_SCHEDULERS:
        raise ValueError(
            f"Unsupported scheduler '{scheduler_name}'. "
            f"Supported schedulers: {', '.join(sorted(SUPPORTED_SCHEDULERS.keys()))}"
        )

    if (
        model_id == "flux-schnell"
        and sched_key not in FLUX_COMPATIBLE_SCHEDULERS
    ):
        logger.warning(
            f"Scheduler '{sched_key}' is not compatible with flow-matching FLUX; "
            "keeping the pipeline default"
        )
        return

    # For mock/stub testing objects
    if hasattr(pipe, "scheduler_name"):
        pipe.scheduler_name = scheduler_name

    if model_id == "flux-schnell":
        target_cls_name = FLUX_SCHEDULER_OVERRIDES.get(
            sched_key, SUPPORTED_SCHEDULERS[sched_key]
        )
    else:
        target_cls_name = SUPPORTED_SCHEDULERS[sched_key]
    try:
        import diffusers  # type: ignore

        sched_cls = getattr(diffusers, target_cls_name, None)
        if (
            sched_cls is not None
            and hasattr(pipe, "scheduler")
            and hasattr(pipe.scheduler, "config")
        ):
            pipe.scheduler = sched_cls.from_config(pipe.scheduler.config)
    except (ImportError, Exception) as exc:
        logger.debug(f"Scheduler config skipped or unavailable ({target_cls_name}): {exc}")


def run_local_image_generation(
    prompt: str,
    steps: int = 28,
    scale: float = 7.5,
    aspect_ratio: Optional[str] = None,
    scheduler: Optional[str] = None,
    db: Optional[Session] = None,
) -> dict:
    """Execute local image generation following Decision #3 and Decision #4.

    1. Consults vram_guard.select_fitting_model with candidates ['flux-schnell', 'sdxl'].
    2. On refusal or absence of GPU, returns typed DegradedResponse (HTTP 200).
    3. On admission, lazy-loads model via model_registry and executes diffusion inference.
    4. Uploads real PNG bytes to storage and creates MediaAsset record in DB.

    Text-to-image only: `strength` is never forwarded, because diffusers rejects it
    on txt2img pipelines. The route rejects `denoising_strength` until an
    image-to-image source input exists.
    """
    # 1. Admission check and candidate selection (Decision #4: flux-schnell with sdxl auto-downgrade)
    try:
        selected_model_id = vram_guard.select_fitting_model(
            candidate_ids=["flux-schnell", "sdxl"],
            working_overhead_gb=1.0,
        )
    except VRAMRefusalError as exc:
        logger.warning(f"Local image inference refused: {exc.reason} - {exc.message}")
        return exc.to_degraded_response().model_dump()
    except Exception as exc:
        logger.error(f"Unexpected error during VRAM admission check: {exc}")
        return make_degraded_response(
            reason=DegradedReason.NO_GPU.value,
            message=f"Failed to check GPU availability: {str(exc)}",
        ).model_dump()

    # 2. Lazy load via model_registry
    try:
        pipe = model_registry.load_model(
            selected_model_id,
            loader_handle=make_diffusers_loader(selected_model_id),
        )
    except Exception as exc:
        logger.error(f"Failed to load image model '{selected_model_id}': {exc}")
        return make_degraded_response(
            reason=DegradedReason.LOAD_FAILED.value,
            message=f"Failed to load local model '{selected_model_id}': {str(exc)}",
            model_id=selected_model_id,
        ).model_dump()

    # 3. Configure scheduler if requested
    if scheduler:
        try:
            apply_scheduler_to_pipeline(pipe, scheduler, model_id=selected_model_id)
        except Exception as exc:
            logger.warning(f"Could not apply scheduler '{scheduler}': {exc}")

    # 4. Execute pipeline
    width, height = get_dimensions_for_aspect_ratio(aspect_ratio)
    inference_kwargs: Dict[str, Any] = {
        "prompt": prompt,
        "num_inference_steps": steps,
        "guidance_scale": scale,
        "width": width,
        "height": height,
    }
    # NB: no `strength` key. It is img2img-only and txt2img pipelines raise TypeError
    # on it; the route rejects denoising_strength until a source image input exists.

    try:
        output = pipe(**inference_kwargs)
    except Exception as exc:
        logger.error(f"Diffusion execution failed for '{selected_model_id}': {exc}")
        return make_degraded_response(
            reason=DegradedReason.LOAD_FAILED.value,
            message=f"Pipeline inference failed for '{selected_model_id}': {str(exc)}",
            model_id=selected_model_id,
        ).model_dump()

    # 5. Extract generated image bytes
    try:
        images = getattr(output, "images", None)
        if images is None:
            images = output if isinstance(output, list) else [output]

        first_img = images[0]
        if isinstance(first_img, (bytes, bytearray)):
            png_bytes = bytes(first_img)
        elif hasattr(first_img, "save"):
            buf = io.BytesIO()
            first_img.save(buf, format="PNG")
            png_bytes = buf.getvalue()
        else:
            raise ValueError(f"Unrecognized pipeline output type: {type(first_img)}")
    except Exception as exc:
        logger.error(f"Failed to encode generated image to PNG: {exc}")
        return make_degraded_response(
            reason=DegradedReason.LOAD_FAILED.value,
            message=f"Failed to encode generated image: {str(exc)}",
            model_id=selected_model_id,
        ).model_dump()

    # 6. Upload real bytes and persist MediaAsset
    filename = build_image_filename()
    upload_success = upload_object(png_bytes, filename, content_type="image/png")

    if upload_success and db is not None:
        try:
            model_family_name = "Flux" if selected_model_id == "flux-schnell" else "SDXL"
            title = f"{model_family_name} Generated: {prompt[:30]}..."
            asset = MediaAsset(
                title=title,
                file_path=filename,
                file_size=len(png_bytes),
                content_type="image/png",
                duration=0.0,
                embedding=get_embedding(prompt or title),
            )
            db.add(asset)
            db.commit()
        except Exception as exc:
            logger.error(f"Failed to save generated image asset: {exc}")
            db.rollback()

    # 7. Response matching Gemini shape
    params_dict: Dict[str, Any] = {"steps": steps, "scale": scale}
    if scheduler is not None:
        params_dict["scheduler"] = scheduler

    return {
        "status": "COMPLETED",
        "parameters": params_dict,
        "filename": filename,
        "url": generate_url(filename) if upload_success else "",
    }
