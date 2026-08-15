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
