"""Tests for the Magnific-style upscaler pipeline (map #56 decisions)."""

import io

import pytest
from PIL import Image

from app.upscaler import (
    DEFAULT_GUIDANCE_SCALE,
    FRACTALITY_GUIDANCE_SCALE,
    UpscaleParams,
    apply_fractality,
    apply_hdr,
    tile_upscale,
    upscale_image_bytes,
    run_upscale_task,
)


def _png_bytes(width=64, height=48, color=(90, 120, 200)):
    buf = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buf, format="PNG")
    return buf.getvalue()


class TestUpscaleParams:
    def test_defaults_match_panel(self):
        p = UpscaleParams()
        assert p.denoise == 0.35
        assert p.controlnet_weight == 0.8
        assert p.guidance_scale == DEFAULT_GUIDANCE_SCALE

    def test_fractality_bumps_guidance(self):
        assert UpscaleParams(fractality=0.5).guidance_scale == FRACTALITY_GUIDANCE_SCALE

    def test_colab_payload_contains_all_controls(self):
        p = UpscaleParams(
            denoise=0.5,
            controlnet_weight=0.9,
            hdr=0.4,
            fractality=0.6,
            prompt="ultra detailed skin pores",
        )
        payload = p.as_colab_parameters()
        assert payload["denoise"] == 0.5
        assert payload["controlnet_weight"] == 0.9
        assert payload["hdr"] == 0.4
        assert payload["fractality"] == 0.6
        assert payload["prompt"] == "ultra detailed skin pores"
        assert payload["guidance_scale"] == FRACTALITY_GUIDANCE_SCALE


class TestPostProcessing:
    def test_apply_hdr_returns_image(self):
        img = Image.new("RGB", (32, 32), (100, 100, 100))
        out = apply_hdr(img, 0.5)
        assert out.size == img.size
        assert out.mode == "RGB"

    def test_apply_hdr_zero_is_identity(self):
        img = Image.new("RGB", (32, 32), (100, 100, 100))
        assert apply_hdr(img, 0).tobytes() == img.tobytes()

    def test_apply_fractality_zero_is_identity(self):
        img = Image.new("RGB", (32, 32), (100, 100, 100))
        assert apply_fractality(img, 0).tobytes() == img.tobytes()

    def test_apply_fractality_changes_pixels(self):
        img = Image.new("RGB", (64, 64), (100, 100, 100))
        out = apply_fractality(img, 1.0)
        assert out.tobytes() != img.tobytes()


class TestTileUpscale:
    def test_output_is_scaled(self):
        img = Image.new("RGB", (40, 30), (10, 20, 30))
        out = tile_upscale(img, 4.0)
        assert out.size == (160, 120)

    def test_scale_one_is_identity_size(self):
        img = Image.new("RGB", (40, 30))
        assert tile_upscale(img, 1.0).size == (40, 30)


class TestUpscaleImageBytes:
    def test_returns_larger_png(self):
        result = upscale_image_bytes(_png_bytes(), UpscaleParams(), scale=2.0)
        img = Image.open(io.BytesIO(result))
        assert img.format == "PNG"
        assert img.size == (128, 96)

    def test_accepts_full_param_set(self):
        result = upscale_image_bytes(
            _png_bytes(),
            UpscaleParams(denoise=0.5, controlnet_weight=0.9, hdr=0.6, fractality=0.5, prompt="texture"),
            scale=2.0,
        )
        assert Image.open(io.BytesIO(result)).size == (128, 96)


class TestRunUpscaleTask:
    def test_download_upload_flow(self, stub_storage, db_session):
        stub_storage["downloaded"]["originals/photo.png"] = _png_bytes()
        result = run_upscale_task("originals/photo.png", UpscaleParams(hdr=0.5), task_id="t-1", scale=2.0)

        assert result["status"] == "COMPLETED"
        assert result["original_object"] == "originals/photo.png"
        assert result["processed_name"] == "processed/upscaled_photo.png"
        assert result["processed_url"].startswith("http://test-minio/")
        assert "processed/upscaled_photo.png" in stub_storage["uploaded"]

    def test_missing_source_raises(self, stub_storage):
        with pytest.raises(RuntimeError, match="Failed to download"):
            run_upscale_task("nope.png", UpscaleParams(), task_id="t-2")

