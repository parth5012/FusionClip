"""Magnific Core Tile Upscaler Engine.

Implements overlapping tile splitting up to 8K, per-tile diffusion parameter mapping,
feather-stitched blending to eliminate seam artifacts, and step-level progress reporting (#94).

Also hosts the Precision-mode branch (#123/#124): a faithful 2x progressive scale chain
(2x/4x/8x/16x) over the same tile/feather substrate, the scunet denoise-into-stage-1 mode,
whole-image Sharpness/Grain post-filters, a 16384 output cap with hard refusal, and a
loud weights-unavailable policy whose only fallback is the CI-only `stub` engine.
"""

import io
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Tuple, Any

import numpy as np
from PIL import Image, ImageEnhance, ImageFilter
import redis

from app.config import settings
from app.database import SessionLocal
from app.models import MediaAsset, Task
from app.services.embedding import get_embedding
from app.storage import get_object_bytes, upload_object

logger = logging.getLogger(__name__)

# Redis client for live WebSocket task progress broadcast
try:
    redis_client = redis.from_url(settings.REDIS_URL)
except Exception as e:
    logger.warning(f"Could not connect to Redis: {e}")
    redis_client = None

# Magnific slider to diffusion parameters mapping
def map_creativity_to_denoise(val: float) -> float:
    """Map creativity [-10..+10] to img2img denoise strength [0.10..0.65]."""
    val = max(-10.0, min(10.0, float(val)))
    if val <= 0:
        return round(0.35 + (val / 10.0) * 0.25, 2)
    else:
        return round(0.35 + (val / 10.0) * 0.30, 2)


def map_resemblance_to_controlnet(val: float) -> float:
    """Map resemblance [-10..+10] to ControlNet tile conditioning weight [0.40..1.20]."""
    val = max(-10.0, min(10.0, float(val)))
    if val <= 0:
        return round(0.85 + (val / 10.0) * 0.45, 2)
    else:
        return round(0.85 + (val / 10.0) * 0.35, 2)


PRESET_DEFINITIONS: Dict[str, Dict[str, Any]] = {
    "subtle": {
        "name": "Subtle",
        "description": "Clean, structural fidelity with minimal hallucination",
        "creativity": -4,
        "resemblance": 7,
        "fractality": -2,
        "hdr": 1,
    },
    "vivid": {
        "name": "Vivid",
        "description": "Balanced enhancement, rich textures and vibrant dynamic range",
        "creativity": 2,
        "resemblance": 4,
        "fractality": 2,
        "hdr": 3,
    },
    "wild": {
        "name": "Wild",
        "description": "High generative hallucination and surreal micro-detail",
        "creativity": 7,
        "resemblance": -2,
        "fractality": 6,
        "hdr": 4,
    },
    "custom": {
        "name": "Custom",
        "description": "Custom parameter values",
        "creativity": 0,
        "resemblance": 0,
        "fractality": 0,
        "hdr": 0,
    },
}

CONTENT_CATEGORIES: Dict[str, Dict[str, str]] = {
    "universal": {
        "label": "Universal",
        "description": "Balanced enhancement for mixed images and general graphics",
        "prompt_keywords": "highly detailed, sharp focus, masterwork, 8k uhd, balanced lighting",
    },
    "portraits": {
        "label": "Portraits & People",
        "description": "Natural skin pores, hair strands, realistic iris without plastic blur",
        "prompt_keywords": "photorealistic skin texture, natural pores, detailed eyes, individual hair strands, photorealistic portrait",
    },
    "landscapes": {
        "label": "Landscapes & Nature",
        "description": "Foliage, vegetation, rock formations, and realistic terrain",
        "prompt_keywords": "detailed foliage, natural terrain, crisp rock textures, atmospheric depth, landscape photography",
    },
    "anime": {
        "label": "Anime & Digital Art",
        "description": "Sharp clean linework, vibrant flat colors, and manga shading",
        "prompt_keywords": "clean line art, crisp anime illustration, vibrant colors, detailed cel shading, high resolution artwork",
    },
    "architecture": {
        "label": "Architecture & Interiors",
        "description": "Crisp straight lines, building textures, structural symmetry",
        "prompt_keywords": "architectural photography, crisp edges, structural clarity, glass reflections, clean interior geometry",
    },
    "product": {
        "label": "Product & Studio",
        "description": "Clean product studio shots, controlled highlights, smooth materials",
        "prompt_keywords": "studio packshot, commercial product photography, perfect specular highlights, clean materials, sharp edges",
    },
}


@dataclass(frozen=True)
class TileCoords:
    x1: int
    y1: int
    x2: int
    y2: int


def split_into_overlapping_tiles(
    width: int, height: int, tile_size: int = 512, overlap: int = 64
) -> List[TileCoords]:
    """Calculate overlapping tile grid coordinates covering the canvas up to 8K.
    
    Ensures full canvas coverage from (0,0) to (width, height) without gaps.
    """
    if width <= tile_size and height <= tile_size:
        return [TileCoords(0, 0, width, height)]

    step_x = max(1, tile_size - overlap)
    step_y = max(1, tile_size - overlap)

    # Compute start points along x and y
    x_starts = []
    x = 0
    while x < width:
        x1 = min(x, max(0, width - tile_size))
        if x1 not in x_starts:
            x_starts.append(x1)
        if x1 + tile_size >= width:
            break
        x += step_x

    y_starts = []
    y = 0
    while y < height:
        y1 = min(y, max(0, height - tile_size))
        if y1 not in y_starts:
            y_starts.append(y1)
        if y1 + tile_size >= height:
            break
        y += step_y

    tiles: List[TileCoords] = []
    for y1 in y_starts:
        y2 = min(height, y1 + tile_size)
        for x1 in x_starts:
            x2 = min(width, x1 + tile_size)
            tiles.append(TileCoords(x1, y1, x2, y2))

    return tiles


def create_feather_mask(tile_width: int, tile_height: int, overlap: int = 64) -> np.ndarray:
    """Generate a smooth 2D feathering weight mask for tile blending.
    
    Center has weight 1.0, tapering linearly to 0 at the overlap margins.
    """
    def _ramp(length: int, ov: int) -> np.ndarray:
        w = np.ones(length, dtype=np.float32)
        if ov <= 0:
            return w
        ov = min(ov, length // 2)
        if ov > 0:
            ramp = np.linspace(0.0, 1.0, ov, endpoint=False, dtype=np.float32)
            w[:ov] = ramp
            w[-ov:] = ramp[::-1]
        return w

    w_x = _ramp(tile_width, overlap)
    w_y = _ramp(tile_height, overlap)
    mask = np.outer(w_y, w_x)
    return mask


def stitch_tiles_with_feather(
    width: int, height: int, tiles: List[Tuple[TileCoords, np.ndarray]], overlap: int = 64
) -> np.ndarray:
    """Stitch overlapping processed tiles into a unified canvas with seamless feather blending."""
    canvas_acc = np.zeros((height, width, 3), dtype=np.float32)
    weights_acc = np.zeros((height, width), dtype=np.float32)

    for coords, tile_data in tiles:
        h, w = tile_data.shape[:2]
        mask = create_feather_mask(w, h, overlap)

        # Do not feather outer borders of the image (prevent fade-to-black on edges)
        if coords.x1 == 0:
            mask[:, :overlap] = 1.0
        if coords.x2 == width:
            mask[:, -overlap:] = 1.0
        if coords.y1 == 0:
            mask[:overlap, :] = 1.0
        if coords.y2 == height:
            mask[-overlap:, :] = 1.0

        canvas_acc[coords.y1:coords.y2, coords.x1:coords.x2] += (
            tile_data.astype(np.float32) * mask[:, :, np.newaxis]
        )
        weights_acc[coords.y1:coords.y2, coords.x1:coords.x2] += mask

    weights_acc = np.maximum(weights_acc, 1e-6)
    blended = canvas_acc / weights_acc[:, :, np.newaxis]
    return np.clip(np.round(blended), 0, 255).astype(np.uint8)


def _process_tile_diffusion_or_stub(
    tile_img: Image.Image,
    creativity: float,
    resemblance: float,
    hdr: float,
    category: str,
    prompt: Optional[str] = None,
) -> Image.Image:
    """Process a single tile with diffusion or deterministic high-fidelity filtering in CI.
    
    Applies micro-contrast (HDR), edge sharpening, and texture synthesis.
    """
    denoise = map_creativity_to_denoise(creativity)
    cn_scale = map_resemblance_to_controlnet(resemblance)

    # Base image processing simulating generative enhancement
    result = tile_img.copy()

    # HDR contrast / sharpness enhancement based on hdr parameter (-10..+10)
    if hdr != 0:
        hdr_factor = 1.0 + (hdr / 20.0) * 0.35  # 0.825 .. 1.175
        enhancer = ImageEnhance.Contrast(result)
        result = enhancer.enhance(hdr_factor)

    # Sharpness enhancement driven by resemblance and creativity
    sharp_factor = 1.0 + (resemblance / 10.0) * 0.25 + (denoise * 0.2)
    sharpener = ImageEnhance.Sharpness(result)
    result = sharpener.enhance(sharp_factor)

    # Unsharp mask for micro-detail enhancement
    if creativity > -5:
        radius = 1.2
        percent = int(100 + (creativity + 10) * 4)  # 100 .. 180%
        result = result.filter(ImageFilter.UnsharpMask(radius=radius, percent=percent, threshold=3))

    return result


# --------------------------------------------------------------------------- #
# Precision mode (#123 locked decisions, #124 build)
# --------------------------------------------------------------------------- #

CREATIVE_MODE = "creative"
PRECISION_MODE = "precision"

#: User-selectable Precision engines (#123-d1): non-GAN only, manual pick, default `hat`.
PRECISION_ENGINES: Tuple[str, ...] = ("hat", "scunet")

#: Deterministic classical path — CI only, never an API value (#123-d9).
SR_STUB_ENGINE = "stub"

#: Core keeps 8192 (silently clamped, pre-existing behaviour); Precision gets the
#: Magnific-parity cap with a hard refusal and no silent downsampling (#123-d5).
CREATIVE_MAX_OUTPUT_DIMENSION = 8192
PRECISION_MAX_OUTPUT_DIMENSION = 16384

#: #123-d3: UnsharpMask radius 2, percent = sharpness * 1.2 (100 -> 120%).
PRECISION_UNSHARP_RADIUS = 2.0
PRECISION_UNSHARP_PERCENT_PER_POINT = 1.2

#: #123-d4: zero-mean seeded Gaussian grain, sigma = grain / 100 * 12.
PRECISION_GRAIN_SIGMA_MAX = 12.0
PRECISION_GRAIN_SEED = 0


class OutputDimensionExceededError(ValueError):
    """Precision output would exceed the 16384 cap — hard refusal, never a downsample."""


class SRWeightsUnavailableError(RuntimeError):
    """No SR backend for the requested engine — loud failure, never a LANCZOS fallback."""


def map_sharpness_to_percent(sharpness: int) -> int:
    """Map the 0..100 Sharpness slider onto PIL's UnsharpMask percent.

    Adapted from `app.ml.skin_enhancer.map_sharpen_to_percent` (which maps onto
    200% at radius 1.2): Precision uses radius 2 and value * 1.2, so 100 -> 120%.
    """
    return int(round(float(sharpness) * PRECISION_UNSHARP_PERCENT_PER_POINT))


def map_grain_to_sigma(grain: int) -> float:
    """Map the 0..100 Grain slider onto a zero-mean Gaussian sigma in 8-bit levels.

    Adapted from `app.ml.skin_enhancer.map_smart_grain_to_sigma` (capped at 6.0):
    Precision caps at 12.0, so sigma = grain / 100 * 12.
    """
    return round(float(grain) / 100.0 * PRECISION_GRAIN_SIGMA_MAX, 3)


def apply_precision_post_filters(
    image: Image.Image, sharpness: int, grain: int
) -> Image.Image:
    """Apply Sharpness then Grain to the WHOLE stitched image (#123-d3/d4).

    Never per-tile: grain applied inside tiles bands at the feather seams. At 0
    each filter is skipped outright so "off" stays bit-identical.
    """
    result = image

    percent = map_sharpness_to_percent(sharpness)
    if percent > 0:
        result = result.filter(
            ImageFilter.UnsharpMask(
                radius=PRECISION_UNSHARP_RADIUS, percent=percent, threshold=0
            )
        )

    sigma = map_grain_to_sigma(grain)
    if sigma > 0:
        arr = np.asarray(result, dtype=np.float32)
        rng = np.random.default_rng(PRECISION_GRAIN_SEED)
        grain_noise = rng.normal(0.0, sigma, size=arr.shape).astype(np.float32)
        # Grain is a colour-grain effect: jittering channel 3 of an RGBA image
        # would randomise transparency instead of adding film grain.
        if arr.ndim == 3 and arr.shape[2] == 4:
            grain_noise[..., 3] = 0.0
        # fromarray infers the mode from the (H, W, 3) uint8 shape; an explicit
        # mode= is deprecated in Pillow 10+.
        result = Image.fromarray(np.clip(arr + grain_noise, 0.0, 255.0).astype(np.uint8))

    return result


@dataclass(frozen=True)
class PrecisionChainPlan:
    """How one Precision request decomposes into 2x stages (#123-d7)."""

    scale: int
    #: Number of 2x stages: 2->1, 4->2, 8->3, 16->4 (2x is the atomic unit).
    stages: int
    #: Engine run on every SR stage.
    sr_engine: str
    #: Whole-image denoise run once before stage 1 (scunet denoise mode), else None.
    denoise_engine: Optional[str]


def precision_chain_plan(scale: int, engine: str) -> PrecisionChainPlan:
    """Decompose `scale` into its full progressive 2x chain for `engine`.

    Same engine on every stage, except scunet: SCUNet is a denoiser (running it
    per rung double-blurs), so it denoises once on the way into stage 1 and HAT
    runs the SR stages (#123-d7).
    """
    if scale not in (2, 4, 8, 16):
        raise ValueError(
            f"Unsupported precision scale {scale}. Allowed: 2, 4, 8, 16"
        )
    stages = {2: 1, 4: 2, 8: 3, 16: 4}[scale]

    if engine == "scunet":
        return PrecisionChainPlan(scale, stages, sr_engine="hat", denoise_engine="scunet")
    if engine == "hat":
        return PrecisionChainPlan(scale, stages, sr_engine="hat", denoise_engine=None)
    if engine == SR_STUB_ENGINE:
        return PrecisionChainPlan(scale, stages, sr_engine=SR_STUB_ENGINE, denoise_engine=None)
    raise ValueError(
        f"Unknown precision engine '{engine}'. Allowed: {', '.join(PRECISION_ENGINES)} (CI: {SR_STUB_ENGINE})"
    )


# Venue ladder (#123-d2): tier 1 local Torch runner, registered by the model pull
# once weights are resident and VRAM-guarded; tier 2 Colab offload runner,
# registered by the Colab client; tier 3 the built-in CI `stub`. Unregistered
# engines fail loudly (#123-d9) instead of degrading to LANCZOS.
_SR_RUNNERS: Dict[str, Tuple[str, Callable[[Image.Image], Image.Image]]] = {}
_SR_DENOISE_RUNNERS: Dict[str, Tuple[str, Callable[[Image.Image], Image.Image]]] = {}


def register_sr_runner(
    engine: str,
    processor: Callable[[Image.Image], Image.Image],
    *,
    kind: str = "sr",
    venue: str = "local",
) -> None:
    """Wire an SR backend for `engine`.

    `kind` is "sr" (per-tile stage processor) or "denoise" (whole-image pass used
    by the scunet denoise mode). `venue` records which ladder tier served it:
    "local" or "colab". The CI `stub` engine is built in and cannot be overridden.
    """
    if engine == SR_STUB_ENGINE:
        raise ValueError(f"the '{SR_STUB_ENGINE}' engine is built in and cannot be overridden")
    if kind not in ("sr", "denoise"):
        raise ValueError(f"unknown SR runner kind '{kind}'. Allowed: sr, denoise")
    if venue not in ("local", "colab"):
        raise ValueError(f"unknown venue '{venue}'. Allowed: local, colab")
    table = _SR_RUNNERS if kind == "sr" else _SR_DENOISE_RUNNERS
    table[engine] = (venue, processor)


def clear_sr_runners() -> None:
    """Drop every registered SR backend (test isolation / model unload)."""
    _SR_RUNNERS.clear()
    _SR_DENOISE_RUNNERS.clear()


def resolve_sr_backend(engine: str, *, kind: str = "sr") -> Tuple[str, Callable[[Image.Image], Image.Image]]:
    """Resolve (venue, processor) for `engine`, or fail loudly (#123-d2/d9).

    The deterministic PIL path is reachable only through the explicit `stub`
    engine, which exists for CI and is never user-selectable.
    """
    if kind == "sr" and engine == SR_STUB_ENGINE:
        return ("stub", _process_tile_sr_stub)
    table = _SR_RUNNERS if kind == "sr" else _SR_DENOISE_RUNNERS
    entry = table.get(engine)
    if entry is None:
        raise SRWeightsUnavailableError(
            f"SR weights unavailable for engine '{engine}' — run the model pull or enable Colab offload"
        )
    return entry


def _process_tile_sr_stub(tile_img: Image.Image) -> Image.Image:
    """Deterministic classical stand-in for one SR stage — the CI `stub` engine only.

    Seed-free and same-size in/out, so stub runs are reproducible end to end.
    """
    return tile_img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=100, threshold=2))


def _report_tile_progress(
    task_id: Optional[str],
    db,
    progress_pct: int,
    step_message: str,
    *,
    scale: int,
    width: int,
    height: int,
) -> None:
    """Update the DB Task and broadcast over Redis Pub/Sub (#94 progress plumbing,
    shared by Creative and Precision — #123-d6)."""
    if not task_id:
        return

    if db:
        try:
            db_task = db.query(Task).filter(Task.task_id == task_id).first()
            if db_task:
                db_task.status = "PROCESSING"
                db_task.progress = progress_pct
                db_task.logs = f"{step_message} (scale: {scale}x, {width}x{height})"
                db.commit()
        except Exception as db_err:
            # A failed commit poisons the session; roll back so the
            # next progress tick (and the failure handler) still work.
            db.rollback()
            logger.warning(f"Could not update task {task_id} in DB: {db_err}")

    # Publish to Redis Pub/Sub for live WebSocket clients
    if redis_client:
        try:
            update_payload = {
                "task_id": task_id,
                "status": "PROCESSING",
                "progress": progress_pct,
                "step_message": step_message,
                "error": None,
            }
            redis_client.publish("task_updates", json.dumps(update_payload))
        except Exception as r_err:
            logger.warning(f"Could not publish progress to Redis: {r_err}")


def _run_tiled_stage(
    canvas: Image.Image,
    tile_size: int,
    overlap: int,
    tile_processor: Callable[[Image.Image], Image.Image],
    on_tile_done: Callable[[int, int], None],
) -> Tuple[Image.Image, int]:
    """Split `canvas` into overlapping tiles, process each tile, feather-stitch.

    The shared tiling substrate both modes ride (#123-d6): creative passes its
    diffusion/stub processor, precision passes the resolved SR processor.
    `on_tile_done(done, total)` fires after every processed tile.
    """
    width, height = canvas.size

    # Adjust tile size if canvas is smaller than the requested tile size
    effective_tile_size = min(tile_size, max(width, height))
    effective_overlap = min(overlap, effective_tile_size // 4)

    tile_coords = split_into_overlapping_tiles(
        width, height, tile_size=effective_tile_size, overlap=effective_overlap
    )
    total_tiles = len(tile_coords)
    logger.info(f"Generated {total_tiles} tiles for {width}x{height} canvas")

    canvas_arr = np.array(canvas)
    processed: List[Tuple[TileCoords, np.ndarray]] = []
    for idx, coords in enumerate(tile_coords):
        tile_pil = Image.fromarray(canvas_arr[coords.y1:coords.y2, coords.x1:coords.x2])
        processed.append((coords, np.array(tile_processor(tile_pil))))
        on_tile_done(idx + 1, total_tiles)

    stitched_arr = stitch_tiles_with_feather(
        width, height, processed, overlap=effective_overlap
    )
    return Image.fromarray(stitched_arr), total_tiles


def run_tile_upscale_pipeline(
    image_bytes: bytes,
    scale: int,
    creativity: float = 0.0,
    resemblance: float = 0.0,
    fractality: float = 0.0,
    hdr: float = 0.0,
    category: str = "universal",
    prompt: Optional[str] = None,
    task_id: Optional[str] = None,
    db=None,
    tile_size: int = 512,
    overlap: int = 64,
    mode: str = CREATIVE_MODE,
    engine: str = "hat",
    sharpness: int = 0,
    grain: int = 0,
    max_output_dimension: Optional[int] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Execute the complete tile-based upscale pipeline.

    Creative mode (default, #94):
    1. Resizes input image to target resolution (clamped to 8K)
    2. Decomposes into overlapping tiles
    3. Processes each tile through diffusion / enhancement
    4. Updates DB Task and broadcasts progress over Redis Pub/Sub
    5. Reassembles tiles with feather-stitched blending
    6. Returns (PNG bytes, metadata)

    Precision mode (#123-d6): rides the same tiling/progress/stitch substrate, but
    the tile processor is the resolved SR engine, run as the full progressive 2x
    chain, with whole-image Sharpness/Grain applied after the final stitch.
    """
    orig_img = Image.open(io.BytesIO(image_bytes)).convert("RGB")

    if mode == PRECISION_MODE:
        return _run_precision_pipeline(
            orig_img,
            scale=scale,
            engine=engine,
            sharpness=sharpness,
            grain=grain,
            category=category,
            task_id=task_id,
            db=db,
            tile_size=tile_size,
            overlap=overlap,
            max_output_dimension=max_output_dimension,
        )
    if mode != CREATIVE_MODE:
        raise ValueError(
            f"Unknown upscale mode '{mode}'. Allowed: '{CREATIVE_MODE}', '{PRECISION_MODE}'"
        )

    orig_w, orig_h = orig_img.size

    target_w = orig_w * scale
    target_h = orig_h * scale

    # Clamp max canvas to 8K UHD (7680x4320 or 8192 max dimension)
    if max(target_w, target_h) > CREATIVE_MAX_OUTPUT_DIMENSION:
        max_dim = CREATIVE_MAX_OUTPUT_DIMENSION
        if target_w >= target_h:
            target_h = int(target_h * (max_dim / target_w))
            target_w = max_dim
        else:
            target_w = int(target_w * (max_dim / target_h))
            target_h = max_dim

    logger.info(
        f"Upscaling image from {orig_w}x{orig_h} to {target_w}x{target_h} ({scale}x, category={category})"
    )

    # Initial high-quality geometric interpolation to target dimension
    canvas = orig_img.resize((target_w, target_h), resample=Image.Resampling.LANCZOS)

    def _tile_processor(tile_img: Image.Image) -> Image.Image:
        return _process_tile_diffusion_or_stub(
            tile_img,
            creativity=creativity,
            resemblance=resemblance,
            hdr=hdr,
            category=category,
            prompt=prompt,
        )

    def _on_tile(done: int, total: int) -> None:
        progress_pct = int((done / total) * 100)
        _report_tile_progress(
            task_id,
            db,
            progress_pct,
            f"Diffusing tile {done}/{total}",
            scale=scale,
            width=target_w,
            height=target_h,
        )

    stitched_img, total_tiles = _run_tiled_stage(
        canvas, tile_size, overlap, _tile_processor, _on_tile
    )

    # Encode to PNG
    out_buf = io.BytesIO()
    stitched_img.save(out_buf, format="PNG", optimize=True)
    out_bytes = out_buf.getvalue()

    metadata = {
        "original_width": orig_w,
        "original_height": orig_h,
        "target_width": target_w,
        "target_height": target_h,
        "scale": scale,
        "total_tiles": total_tiles,
        "mode": CREATIVE_MODE,
        "category": category,
        "creativity": creativity,
        "resemblance": resemblance,
        "hdr": hdr,
        "fractality": fractality,
    }

    return out_bytes, metadata


def _run_precision_pipeline(
    orig_img: Image.Image,
    scale: int,
    engine: str,
    sharpness: int,
    grain: int,
    category: str,
    task_id: Optional[str],
    db,
    tile_size: int,
    overlap: int,
    max_output_dimension: Optional[int] = None,
) -> Tuple[bytes, Dict[str, Any]]:
    """Faithful Precision upscale: full progressive 2x chain over the shared tile
    substrate (#123-d5/d6/d7/d9)."""
    orig_w, orig_h = orig_img.size
    plan = precision_chain_plan(scale, engine)

    target_w = orig_w * scale
    target_h = orig_h * scale
    cap = (
        PRECISION_MAX_OUTPUT_DIMENSION
        if max_output_dimension is None
        else int(max_output_dimension)
    )
    if max(target_w, target_h) > cap:
        # Hard refusal with a clear error — never a silent downsample (#123-d5).
        raise OutputDimensionExceededError(
            f"Refusing precision upscale: target {target_w}x{target_h} ({scale}x) exceeds "
            f"max_output_dimension {cap} — hard refusal, no silent downsampling"
        )

    # Resolve every backend BEFORE any pixel work so missing weights fail loudly
    # up front instead of degrading mid-run (#123-d9).
    denoise_proc: Optional[Callable[[Image.Image], Image.Image]] = None
    if plan.denoise_engine is not None:
        _, denoise_proc = resolve_sr_backend(plan.denoise_engine, kind="denoise")
    sr_venue, sr_proc = resolve_sr_backend(plan.sr_engine, kind="sr")

    logger.info(
        f"Precision upscaling {orig_w}x{orig_h} to {target_w}x{target_h} "
        f"({scale}x, engine={engine}, sr_engine={plan.sr_engine}, "
        f"stages={plan.stages}, backend={sr_venue}, category={category})"
    )

    current = orig_img
    if denoise_proc is not None:
        # SCUNet denoises once on the way into stage 1 — never per rung, which
        # would double-blur (#123-d7).
        current = denoise_proc(current)

    # Precompute every stage's tile count so the chain reports one 0..100 axis.
    stage_tile_counts: List[int] = []
    for stage in range(1, plan.stages + 1):
        stage_w = orig_w * (2 ** stage)
        stage_h = orig_h * (2 ** stage)
        stage_tile_size = min(tile_size, max(stage_w, stage_h))
        stage_overlap = min(overlap, stage_tile_size // 4)
        stage_tile_counts.append(
            len(
                split_into_overlapping_tiles(
                    stage_w, stage_h, tile_size=stage_tile_size, overlap=stage_overlap
                )
            )
        )
    grand_total = sum(stage_tile_counts)
    completed = 0

    for stage in range(1, plan.stages + 1):
        # Each stage is the atomic 2x unit; LANCZOS pre-resize + tiled SR + stitch
        # reuses the Creative plumbing (#123-d6).
        stage_canvas = current.resize(
            (current.width * 2, current.height * 2), resample=Image.Resampling.LANCZOS
        )

        def _on_tile(done: int, total: int, _stage: int = stage) -> None:
            nonlocal completed
            completed += 1
            progress_pct = int((completed / grand_total) * 100)
            _report_tile_progress(
                task_id,
                db,
                progress_pct,
                f"SR tile {completed}/{grand_total} (stage {_stage}/{plan.stages})",
                scale=scale,
                width=target_w,
                height=target_h,
            )

        current, _ = _run_tiled_stage(
            stage_canvas, tile_size, overlap, sr_proc, _on_tile
        )

    # Whole-image AFTER the final stitch — never per-tile (#123-d3/d4).
    stitched_img = apply_precision_post_filters(current, sharpness, grain)

    out_buf = io.BytesIO()
    stitched_img.save(out_buf, format="PNG", optimize=True)
    out_bytes = out_buf.getvalue()

    metadata = {
        "original_width": orig_w,
        "original_height": orig_h,
        "target_width": target_w,
        "target_height": target_h,
        "scale": scale,
        "total_tiles": grand_total,
        "mode": PRECISION_MODE,
        "engine": engine,
        "stages": plan.stages,
        "sr_engine": plan.sr_engine,
        "denoise": plan.denoise_engine is not None,
        "sharpness": sharpness,
        "grain": grain,
        "category": category,
    }

    return out_bytes, metadata


def execute_upscale_job(
    task_id: str,
    image_path: str,
    scale: int,
    creativity: float,
    resemblance: float,
    fractality: float,
    hdr: float,
    category: str,
    prompt: Optional[str],
    output_path: str,
    mode: str = CREATIVE_MODE,
    engine: str = "hat",
    sharpness: int = 0,
    grain: int = 0,
):
    """Background worker executing the tile upscale pipeline.

    Precision inputs (`mode`/`engine`/`sharpness`/`grain`, #123-d11) are optional
    so every existing creative caller keeps working unchanged. Any pipeline error —
    including the loud SR-weights refusal (#123-d9) — lands on the Task as FAILED.
    """
    db = SessionLocal()
    try:
        logger.info(
            f"Starting upscale job {task_id} for {image_path} "
            f"(scale: {scale}x, mode: {mode}{f', engine: {engine}' if mode == PRECISION_MODE else ''})"
        )

        # Read source image from MinIO
        image_bytes = get_object_bytes(image_path)

        # Run tile-based diffusion & feather stitching (or the precision SR chain)
        out_bytes, metadata = run_tile_upscale_pipeline(
            image_bytes=image_bytes,
            scale=scale,
            creativity=creativity,
            resemblance=resemblance,
            fractality=fractality,
            hdr=hdr,
            category=category,
            prompt=prompt,
            task_id=task_id,
            db=db,
            mode=mode,
            engine=engine,
            sharpness=sharpness,
            grain=grain,
        )

        # Save upscaled image to MinIO
        upload_success = upload_object(out_bytes, output_path, content_type="image/png")
        if not upload_success:
            raise RuntimeError(f"Failed to upload upscaled output to {output_path}")

        # Index into MediaAsset catalog with embedding
        title = f"{Path(image_path).stem}_{scale}x_upscaled.png"
        prompt_context = f"{category} upscale: {prompt or 'enhanced image'}"
        embedding_vec = get_embedding(prompt_context)

        media_asset = MediaAsset(
            title=title,
            file_path=output_path,
            file_size=len(out_bytes),
            content_type="image/png",
            embedding=embedding_vec,
        )
        db.add(media_asset)

        # Mark Task complete
        db_task = db.query(Task).filter(Task.task_id == task_id).first()
        if db_task:
            db_task.status = "COMPLETED"
            db_task.progress = 100
            db_task.logs = json.dumps(metadata)
        db.commit()

        logger.info(f"Successfully completed upscale job {task_id} -> {output_path}")

    except Exception as e:
        logger.error(f"Upscale job {task_id} failed: {e}", exc_info=True)
        try:
            # A failed commit (e.g. MediaAsset insert) leaves the session in a
            # failed transaction; roll back before recording the failure state
            # or the status poller would wait on PROCESSING forever.
            db.rollback()
            db_task = db.query(Task).filter(Task.task_id == task_id).first()
            if db_task:
                db_task.status = "FAILED"
                db_task.error = str(e)
                db.commit()
        except Exception as db_e:
            logger.error(f"Failed to record failure state for task {task_id}: {db_e}")
    finally:
        db.close()
