"""Tests for the Magnific Core Tile Upscaler engine and /api/upscale endpoint (#94)."""

import io
import pytest
from PIL import Image
import numpy as np

from app.services.upscaler import (
    map_creativity_to_denoise,
    map_resemblance_to_controlnet,
    split_into_overlapping_tiles,
    create_feather_mask,
    stitch_tiles_with_feather,
    run_tile_upscale_pipeline,
    PRESET_DEFINITIONS,
    CONTENT_CATEGORIES,
    TileCoords,
)
from app.models import Task, MediaAsset
from app.storage import upload_object


class TestUpscalerParameterMapping:
    def test_creativity_to_denoise_bounds_and_center(self):
        assert map_creativity_to_denoise(-10) == pytest.approx(0.10, abs=0.01)
        assert map_creativity_to_denoise(0) == pytest.approx(0.35, abs=0.01)
        assert map_creativity_to_denoise(10) == pytest.approx(0.65, abs=0.01)

    def test_resemblance_to_controlnet_bounds_and_center(self):
        assert map_resemblance_to_controlnet(-10) == pytest.approx(0.40, abs=0.01)
        assert map_resemblance_to_controlnet(0) == pytest.approx(0.85, abs=0.01)
        assert map_resemblance_to_controlnet(10) == pytest.approx(1.20, abs=0.01)

    def test_presets_registered(self):
        assert "subtle" in PRESET_DEFINITIONS
        assert "vivid" in PRESET_DEFINITIONS
        assert "wild" in PRESET_DEFINITIONS
        assert "custom" in PRESET_DEFINITIONS

        # Subtle should be conservative (-4 creativity, +7 resemblance)
        subtle = PRESET_DEFINITIONS["subtle"]
        assert subtle["creativity"] == -4
        assert subtle["resemblance"] == 7

        # Wild should be highly hallucinated (+7 creativity, -2 resemblance)
        wild = PRESET_DEFINITIONS["wild"]
        assert wild["creativity"] == 7
        assert wild["resemblance"] == -2

    def test_categories_registered(self):
        expected = {"universal", "portraits", "landscapes", "anime", "architecture", "product"}
        assert set(CONTENT_CATEGORIES.keys()) == expected
        assert len(CONTENT_CATEGORIES["portraits"]["prompt_keywords"]) > 0


class TestTileDecompositionAndFeatherStitching:
    def test_split_tiles_covers_entire_canvas(self):
        # 1000x800 canvas with 512x512 tiles and 64px overlap
        width, height = 1000, 800
        tile_size = 512
        overlap = 64

        tiles = split_into_overlapping_tiles(width, height, tile_size=tile_size, overlap=overlap)
        assert len(tiles) > 1

        # Check all tiles are within boundaries
        for t in tiles:
            assert 0 <= t.x1 < t.x2 <= width
            assert 0 <= t.y1 < t.y2 <= height
            assert t.x2 - t.x1 <= tile_size
            assert t.y2 - t.y1 <= tile_size

        # Check corners and boundaries are completely covered
        has_top_left = any(t.x1 == 0 and t.y1 == 0 for t in tiles)
        has_bottom_right = any(t.x2 == width and t.y2 == height for t in tiles)
        assert has_top_left
        assert has_bottom_right

    def test_up_to_8k_canvas_tiling(self):
        # 7680x4320 (8K UHD) with 1024x1024 tiles
        tiles = split_into_overlapping_tiles(7680, 4320, tile_size=1024, overlap=128)
        assert len(tiles) > 10
        # Verify last tile reaches edge
        assert max(t.x2 for t in tiles) == 7680
        assert max(t.y2 for t in tiles) == 4320

    def test_feather_mask_properties(self):
        mask = create_feather_mask(256, 256, overlap=32)
        assert mask.shape == (256, 256)
        # Center should be 1.0
        assert mask[128, 128] == pytest.approx(1.0, abs=0.05)
        # Edges should taper toward 0
        assert mask[0, 128] < 0.2
        assert mask[255, 128] < 0.2
        assert mask[128, 0] < 0.2
        assert mask[128, 255] < 0.2
        # No NaNs or infs
        assert not np.isnan(mask).any()
        assert not np.isinf(mask).any()

    def test_feather_reconstruction_seamless(self):
        # Create a gradient test image
        img_arr = np.zeros((400, 500, 3), dtype=np.uint8)
        for y in range(400):
            for x in range(500):
                img_arr[y, x] = [x % 256, y % 256, (x + y) % 256]

        tiles_coords = split_into_overlapping_tiles(500, 400, tile_size=256, overlap=32)
        extracted_tiles = []
        for c in tiles_coords:
            tile_data = img_arr[c.y1:c.y2, c.x1:c.x2]
            extracted_tiles.append((c, tile_data))

        reconstructed = stitch_tiles_with_feather(500, 400, extracted_tiles, overlap=32)

        # Check dimension and shape
        assert reconstructed.shape == (400, 500, 3)
        # Mean absolute error across all pixels should be virtually zero (< 1.0 intensity step)
        mae = np.mean(np.abs(reconstructed.astype(float) - img_arr.astype(float)))
        assert mae < 1.0


class TestUpscalePipelineEngine:
    def test_run_tile_upscale_pipeline_execution(self, db_session):
        # Create a small 64x64 test image
        img = Image.new("RGB", (64, 64), color=(120, 80, 200))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw_bytes = buf.getvalue()

        task_id = "test-upscale-job-1"
        db_task = Task(task_id=task_id, name="upscale: test.png", status="PROCESSING", progress=0)
        db_session.add(db_task)
        db_session.commit()

        # Run 2x upscale with stubbed diffusion
        result_bytes, metadata = run_tile_upscale_pipeline(
            image_bytes=raw_bytes,
            scale=2,
            creativity=2,
            resemblance=4,
            fractality=1,
            hdr=2,
            category="portraits",
            prompt="high fidelity",
            task_id=task_id,
            db=db_session,
            tile_size=128,
            overlap=16,
        )

        assert len(result_bytes) > 0
        out_img = Image.open(io.BytesIO(result_bytes))
        assert out_img.size == (128, 128)
        assert metadata["target_width"] == 128
        assert metadata["target_height"] == 128
        assert metadata["total_tiles"] >= 1

        # Check task progress updated in DB
        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.status == "PROCESSING"
        assert db_task.progress == 100


class TestUpscaleEndpoint:
    def test_upscale_endpoint_missing_parameters_rejected(self, client):
        # Empty body
        res = client.post("/api/upscale", json={})
        assert res.status_code == 422

    def test_upscale_endpoint_invalid_scale_rejected(self, client):
        res = client.post(
            "/api/upscale",
            json={"image_path": "uploads/test.png", "scale": 3},  # only 2, 4, 8, 16 allowed
        )
        assert res.status_code == 400
        assert "Invalid scale factor" in res.json()["detail"]

    def test_upscale_endpoint_invalid_slider_range_rejected(self, client):
        res = client.post(
            "/api/upscale",
            json={"image_path": "uploads/test.png", "scale": 4, "creativity": 15},  # > 10
        )
        assert res.status_code == 400
        assert "must be between -10 and +10" in res.json()["detail"]

    def test_upscale_endpoint_successful_dispatch(self, client, db_session, monkeypatch):
        # Upload a dummy image into storage
        img = Image.new("RGB", (32, 32), color=(50, 100, 150))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        upload_object(buf.getvalue(), "test_upscale_source.png", "image/png")

        res = client.post(
            "/api/upscale",
            json={
                "image_path": "test_upscale_source.png",
                "scale": 2,
                "preset": "vivid",
                "category": "portraits",
                "prompt": "studio lighting",
            },
        )
        assert res.status_code == 200
        data = res.json()
        assert "task_id" in data
        assert data["status"] in ["QUEUED", "PROCESSING"]
        assert data["scale"] == 2
        assert "output_path" in data

        # Check task status endpoint
        task_id = data["task_id"]
        status_res = client.get(f"/api/upscale/status/{task_id}")
        assert status_res.status_code == 200
        status_data = status_res.json()
        assert status_data["task_id"] == task_id
