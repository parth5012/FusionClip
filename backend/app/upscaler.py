"""Magnific-style generative upscaler pipeline (CPU fallback + Colab params).

Implements the decisions recorded on the wayfinder map #56:

- HDR (#57/#61): a zero-GPU PIL post-pass — UnsharpMask + Contrast.
- Fractality (#57/#61): pre-tile Gaussian noise injection plus a
  ``guidance_scale`` bump (7 → 12) when enabled, forwarded to the Colab
  worker so the notebook's diffusion pipeline applies it during sampling.
- Prompt guidance (#59): an optional text prompt threaded through the task
  dispatch as an img2img positive prompt for each tile pass.

When a Colab worker is connected the parameters are forwarded as-is and the
notebook is expected to run the actual SDXL/Flux + ControlNet Tile inference
(see ``guide/Colab guide.md``). When no worker is available this module runs
a deterministic tile-based Lanczos upscale with feather blending plus the
HDR / Fractality post-processing so the pipeline stays functional offline.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from typing import Optional

from PIL import Image, ImageChops, ImageEnhance, ImageFilter

from app.storage import download_bytes, generate_url, upload_object

logger = logging.getLogger(__name__)

# Diffusion defaults used when the user does not override them in the panel.
DEFAULT_DENOISE = 0.35
DEFAULT_CONTROLNET_WEIGHT = 0.8
DEFAULT_GUIDANCE_SCALE = 7.0
FRACTALITY_GUIDANCE_SCALE = 12.0

# Tile pass parameters for the CPU fallback renderer.
TILE_SIZE = 512
TILE_OVERLAP = 64
MAX_OUTPUT_DIMENSION = 8192


@dataclass
class UpscaleParams:
    """Parameters for a single upscale run (mirrors the panel controls)."""

    denoise: float = DEFAULT_DENOISE
    controlnet_weight: float = DEFAULT_CONTROLNET_WEIGHT
    hdr: float = 0.0
    fractality: float = 0.0
    prompt: str = ""

    @property
    def guidance_scale(self) -> float:
        """Fractality bumps guidance 7 → 12 per the #61 decision."""
        if self.fractality and self.fractality > 0:
            return FRACTALITY_GUIDANCE_SCALE
        return DEFAULT_GUIDANCE_SCALE

    def as_colab_parameters(self) -> dict:
        """Payload forwarded to the Colab diffusion worker."""
        return {
            "denoise": self.denoise,
            "controlnet_weight": self.controlnet_weight,
            "guidance_scale": self.guidance_scale,
            "hdr": self.hdr,
            "fractality": self.fractality,
            "prompt": self.prompt,
        }


def _gaussian_noise_layer(size: tuple[int, int], amount: float) -> Image.Image:
    """Per-pixel Gaussian noise image blended at ``amount`` intensity."""
    # PIL effect_noise generates normal-distributed noise in a single channel.
    noise = Image.effect_noise(size, 32).convert("RGB")
    noise = ImageEnhance.Color(noise).enhance(0.5)
    noise = Image.blend(Image.new("RGB", size, (128, 128, 128)), noise, 1.0)
    # Shift to -1..1 around mid-gray and scale by amount.
    scaled = Image.eval(noise, lambda p: max(0, min(255, int(128 + (p - 128) * amount * 2))))
    return scaled


def apply_fractality(image: Image.Image, amount: float) -> Image.Image:
    """Pre-tile Gaussian noise injection (Fractality control)."""
    if not amount or amount <= 0:
        return image
    noise = _gaussian_noise_layer(image.size, min(amount, 1.0))
    return ImageChops.overlay(image, noise)


def apply_hdr(image: Image.Image, amount: float) -> Image.Image:
    """Zero-GPU HDR post-pass: UnsharpMask + Contrast (per #61)."""
    if not amount or amount <= 0:
        return image
    amount = min(amount, 1.0)
    sharpened = image.filter(
        ImageFilter.UnsharpMask(radius=2, percent=int(100 + amount * 100), threshold=2)
    )
    return ImageEnhance.Contrast(sharpened).enhance(1.0 + 0.3 * amount)


def _feather_blend(tile: Image.Image, canvas: Image.Image, x: int, y: int, mask: Image.Image) -> None:
    """Paste a tile onto the canvas using a feathered mask (edge blending)."""
    # Edge tiles are cropped smaller than the full mask — crop the mask to match.
    tile_mask = mask.crop((0, 0, tile.width, tile.height))
    canvas.paste(tile, (x, y), tile_mask)


def _tile_mask(size: tuple[int, int]) -> Image.Image:
    """Feather mask: opaque core, soft gradient on the overlap border."""
    width, height = size
    mask = Image.new("L", size, 255)
    feather = TILE_OVERLAP
    draw_mask = mask.load()
    for yy in range(height):
        for xx in range(width):
            edge = min(
                min(xx, width - 1 - xx),
                min(yy, height - 1 - yy),
            )
            if edge < feather:
                draw_mask[xx, yy] = int(255 * edge / feather)
    return mask


def tile_upscale(image: Image.Image, scale: float) -> Image.Image:
    """Tile-based Lanczos upscale with feather-stitched overlap blending.

    Splits the source into overlapping patches, upscales each patch with
    Lanczos, and pastes them back with a feathered mask to avoid seams. This
    is the CPU fallback for the ControlNet Tile pipeline that runs on Colab.
    """
    scale = max(1.0, float(scale))
    src_w, src_h = image.size
    out_w = min(int(src_w * scale), MAX_OUTPUT_DIMENSION)
    out_h = min(int(src_h * scale), MAX_OUTPUT_DIMENSION)
    out = Image.new("RGB", (out_w, out_h))

    tile_w, tile_h = TILE_SIZE, TILE_SIZE
    step = tile_w - TILE_OVERLAP
    mask = _tile_mask((tile_w, tile_h))

    y = 0
    while y < src_h:
        x = 0
        while x < src_w:
            box = image.crop((x, y, min(x + tile_w, src_w), min(y + tile_h, src_h)))
            # Lanczos upscale of this tile to the output coordinate space.
            dst_x0 = int(x * scale)
            dst_y0 = int(y * scale)
            dst_x1 = min(int((x + box.width) * scale), out_w)
            dst_y1 = min(int((y + box.height) * scale), out_h)
            tile_up = box.resize((dst_x1 - dst_x0, dst_y1 - dst_y0), Image.LANCZOS)
            _feather_blend(tile_up, out, dst_x0, dst_y0, mask)
            x += step
        y += step
    return out


def upscale_image_bytes(image_bytes: bytes, params: UpscaleParams, scale: float = 4.0) -> bytes:
    """Run the full CPU fallback pipeline and return PNG bytes."""
    image = Image.open(io.BytesIO(image_bytes))
    if image.mode != "RGB":
        image = image.convert("RGB")

    image = apply_fractality(image, params.fractality)
    upscaled = tile_upscale(image, scale)
    upscaled = apply_hdr(upscaled, params.hdr)

    buf = io.BytesIO()
    upscaled.save(buf, format="PNG")
    return buf.getvalue()


def run_upscale_task(
    object_name: str,
    params: UpscaleParams,
    task_id: str,
    scale: float = 4.0,
) -> dict:
    """Download an asset, run the CPU upscale fallback, upload the result.

    Used when no Colab worker is connected. The result object is written back
    to storage under ``processed/upscaled_<name>`` and its URL returned, so
    the Celery task can record a MediaAsset linking back to the original.
    """
    logger.info("Running local CPU upscale fallback for %s", object_name)
    image_bytes = download_bytes(object_name)
    if not image_bytes:
        raise RuntimeError(f"Failed to download source object {object_name}")

    output_bytes = upscale_image_bytes(image_bytes, params, scale=scale)
    base_name = object_name.split("/")[-1]
    stem, _, ext = base_name.rpartition(".")
    output_name = f"processed/upscaled_{stem}.{ext if ext else 'png'}"

    ok = upload_object(output_bytes, output_name, content_type="image/png")
    if not ok:
        raise RuntimeError(f"Failed to upload upscaled output {output_name}")

    return {
        "status": "COMPLETED",
        "task_id": task_id,
        "original_object": object_name,
        "processed_url": generate_url(output_name),
        "processed_name": output_name,
        "params": params.as_colab_parameters(),
        "colab": False,
    }

import logging
import time
import numpy as np
from PIL import Image
from typing import Callable, Optional, Tuple, List

logger = logging.getLogger(__name__)

def calculate_tile_size(width: int, height: int, available_vram_gb: float) -> int:
    """
    Calculate the optimal tile size based on the input image resolution and available VRAM.
    VRAM guide:
    - < 8GB: 512px
    - 8GB to 12GB: 768px
    - > 12GB: 1024px
    """
    if available_vram_gb < 8.0:
        base_size = 512
    elif available_vram_gb < 12.0:
        base_size = 768
    else:
        base_size = 1024
    
    # If the image is smaller than the calculated size, cap it at the image dimensions
    max_dim = max(width, height)
    if max_dim < base_size:
        # Round up index to multiple of 64 for Stable Diffusion compatibility
        return max(64, ((max_dim + 63) // 64) * 64)
    
    return base_size

def generate_feather_mask(
    width: int,
    height: int,
    feather_px: int,
    left_overlap: bool,
    right_overlap: bool,
    top_overlap: bool,
    bottom_overlap: bool
) -> np.ndarray:
    """
    Generates a 2D float weight mask of shape (height, width).
    Weights are 1.0 in the middle and decrease linearly to 0.0 near the edges that have overlaps.
    """
    mask = np.ones((height, width), dtype=np.float32)
    if feather_px <= 0:
        return mask
    
    x_ramp = np.arange(width, dtype=np.float32)
    x_weight = np.ones_like(x_ramp)
    if left_overlap:
        x_weight = np.minimum(x_weight, x_ramp / feather_px)
    if right_overlap:
        x_weight = np.minimum(x_weight, (width - 1 - x_ramp) / feather_px)
    x_weight = np.clip(x_weight, 0.0, 1.0)
    
    y_ramp = np.arange(height, dtype=np.float32)
    y_weight = np.ones_like(y_ramp)
    if top_overlap:
        y_weight = np.minimum(y_weight, y_ramp / feather_px)
    if bottom_overlap:
        y_weight = np.minimum(y_weight, (height - 1 - y_ramp) / feather_px)
    y_weight = np.clip(y_weight, 0.0, 1.0)
    
    return np.outer(y_weight, x_weight)

def default_mock_process_tile(tile: Image.Image, upscale_factor: float, **kwargs) -> Image.Image:
    """
    Fallback mock tile processing that resizes the tile using bilinear/bicubic scaling
    and adds a slight contrast/noise adjustment to simulate upscaled high-frequency detail.
    """
    w, h = tile.size
    new_w, new_h = int(w * upscale_factor), int(h * upscale_factor)
    upscaled = tile.resize((new_w, new_h), Image.Resampling.BICUBIC)
    
    # Add a mock high-frequency detail simulation (adds a tiny bit of grain or contrast)
    arr = np.array(upscaled, dtype=np.float32)
    # Give a tiny touch of high-pass enhancement to simulate Magnific upscaler detail
    noise = np.random.normal(0, 1.0, arr.shape).astype(np.float32)
    enhanced = np.clip(arr + noise, 0, 255).astype(np.uint8)
    return Image.fromarray(enhanced)

class TileUpscaler:
    def __init__(
        self,
        tile_size: Optional[int] = None,
        overlap: float = 0.25,
        available_vram_gb: float = 16.0
    ):
        self.preset_tile_size = tile_size
        self.overlap_ratio = overlap
        self.available_vram_gb = available_vram_gb

    def upscale(
        self,
        image: Image.Image,
        upscale_factor: float = 2.0,
        process_tile_fn: Optional[Callable[[Image.Image, float], Image.Image]] = None,
        progress_callback: Optional[Callable[[int, str], None]] = None,
        **kwargs
    ) -> Image.Image:
        """
        Splits high-res image into overlapping patches, processes each patch via process_tile_fn,
        and stitches them back using gradient alpha feather blending.
        """
        width, height = image.size
        
        # Calculate/retrieve optimal tile size
        if self.preset_tile_size is not None:
            tile_size = self.preset_tile_size
        else:
            tile_size = calculate_tile_size(width, height, self.available_vram_gb)
        
        overlap_px = int(tile_size * self.overlap_ratio)
        step_size = tile_size - overlap_px
        if step_size <= 0:
            step_size = tile_size // 2  # prevent infinite loop if overlap >= 1.0
        
        logger.info(f"Tiled Upscale Config: tile_size={tile_size}, overlap_px={overlap_px}, step_size={step_size}")
        
        # Determine tile boundaries
        tiles_coords = []  # List of tuples: (x_start, y_start, x_end, y_end)
        
        y = 0
        while y < height:
            y_end = min(y + tile_size, height)
            y_start = max(0, y_end - tile_size)
            
            x = 0
            while x < width:
                x_end = min(x + tile_size, width)
                x_start = max(0, x_end - tile_size)
                
                tiles_coords.append((x_start, y_start, x_end, y_end))
                
                if x_end >= width:
                    break
                x += step_size
            
            if y_end >= height:
                break
            y += step_size
        
        num_tiles = len(tiles_coords)
        logger.info(f"Splitting image into {num_tiles} overlapping tiles")
        
        # Stitched dimensions
        out_w = int(width * upscale_factor)
        out_h = int(height * upscale_factor)
        
        # Initialize output image accumulator and weight mask accumulator
        # We accumulate floats to avoid truncation and allow proper dividing
        output_acc = np.zeros((out_h, out_w, 3), dtype=np.float32)
        weight_acc = np.zeros((out_h, out_w), dtype=np.float32)
        
        tile_processor = process_tile_fn if process_tile_fn is not None else default_mock_process_tile
        
        # Process each tile
        for idx, (x_start, y_start, x_end, y_end) in enumerate(tiles_coords):
            tile_box = (x_start, y_start, x_end, y_end)
            tile_image = image.crop(tile_box)
            
            # Process tile (returns upscaled PIL Image)
            processed_tile = tile_processor(tile_image, upscale_factor, **kwargs)
            
            # Convert to numpy array of shapes (tile_height * S, tile_width * S, 3)
            tile_arr = np.array(processed_tile, dtype=np.float32)
            
            # Calculate output coordinates
            ox_start = int(x_start * upscale_factor)
            oy_start = int(y_start * upscale_factor)
            ox_end = ox_start + tile_arr.shape[1]
            oy_end = oy_start + tile_arr.shape[0]
            
            # Clip bounds to output size to avoid precision error issues at right/bottom edges
            oy_end = min(oy_end, out_h)
            ox_end = min(ox_end, out_w)
            
            tile_w = ox_end - ox_start
            tile_h = oy_end - oy_start
            
            # Trim the tile array if boundary rounding exceeded output canvas dimensions
            tile_arr = tile_arr[:tile_h, :tile_w, :3]
            
            # Determine overlap boundary directions
            left_overlap = (x_start > 0)
            right_overlap = (x_end < width)
            top_overlap = (y_start > 0)
            bottom_overlap = (y_end < height)
            
            # Generate 2D feathering mask for this tile
            feather_px = int(overlap_px * upscale_factor)
            mask = generate_feather_mask(
                width=tile_w,
                height=tile_h,
                feather_px=feather_px,
                left_overlap=left_overlap,
                right_overlap=right_overlap,
                top_overlap=top_overlap,
                bottom_overlap=bottom_overlap
            )
            
            # Accumulate weight and weighted colors
            output_acc[oy_start:oy_end, ox_start:ox_end, :] += tile_arr * mask[:, :, np.newaxis]
            weight_acc[oy_start:oy_end, ox_start:ox_end] += mask
            
            # Report progress
            if progress_callback is not None:
                percent = int(((idx + 1) / num_tiles) * 100)
                progress_callback(percent, f"Processed tile {idx + 1}/{num_tiles}")
        
        # Avoid division by zero: where weight is 0 (should not happen if tiles cover the whole canvas), set to 1
        num_zeros = np.sum(weight_acc == 0)
        if num_zeros > 0:
            logger.warning(f"Found {num_zeros} pixels in weight accumulator with value 0. Normalizing to fallback weight 1.")
            weight_acc[weight_acc == 0] = 1.0
            
        # Divide output accumulated images by weight mask to get average blended colors
        final_arr = output_acc / weight_acc[:, :, np.newaxis]
        final_arr = np.clip(final_arr, 0.0, 255.0).astype(np.uint8)
        
        return Image.fromarray(final_arr)
