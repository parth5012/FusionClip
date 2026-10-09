"""Tests for the Magnific Core Tile Upscaler engine and /api/upscale endpoint (#94).

Also covers the Precision-mode contract from #123/#124: the 2x progressive chain,
the scunet denoise-into-stage-1 mode, Sharpness/Grain whole-image filters, the
16384 output cap, and the loud weights-unavailable policy with a CI-only `stub`
engine standing in for the real SR models.
"""

import io
import pytest
from PIL import Image, ImageFilter
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
    CREATIVE_MAX_OUTPUT_DIMENSION,
    OutputDimensionExceededError,
    PRECISION_MAX_OUTPUT_DIMENSION,
    SRWeightsUnavailableError,
    apply_precision_post_filters,
    clear_sr_runners,
    execute_upscale_job,
    map_grain_to_sigma,
    map_sharpness_to_percent,
    precision_chain_plan,
    register_sr_runner,
    register_standard_sr_runners,
    resolve_sr_backend,
)
from app.models import Task, MediaAsset
from app.storage import upload_object


@pytest.fixture(autouse=True)
def _clean_sr_runners():
    """The SR runner registry is module-level state; isolate every test."""
    clear_sr_runners()
    from app.ml.registry import model_registry
    model_registry.reset()
    yield
    clear_sr_runners()
    from app.ml.registry import model_registry
    model_registry.reset()


def _png_bytes(size=(64, 64), color=(90, 140, 200)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _gradient_image(size=(32, 32)) -> Image.Image:
    """An image with real edges so UnsharpMask has something to bite on."""
    w, h = size
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[..., 0] = np.linspace(0, 255, w, dtype=np.uint8)[None, :]
    arr[..., 1] = np.linspace(0, 255, h, dtype=np.uint8)[:, None]
    arr[..., 2] = 128
    return Image.fromarray(arr)


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


# --------------------------------------------------------------------------- #
# Precision mode (#123 locked decisions, #124 build)
# --------------------------------------------------------------------------- #

class TestPrecisionSliderMapping:
    """#123-d3/d4: Sharpness 0-100 -> UnsharpMask percent = value * 1.2 (radius 2);
    Grain 0-100 -> zero-mean seeded Gaussian sigma = value / 100 * 12."""

    @pytest.mark.parametrize(
        "value,expected",
        [(0, 0), (15, 18), (50, 60), (83, 100), (100, 120)],
    )
    def test_sharpness_to_percent_formula(self, value, expected):
        assert map_sharpness_to_percent(value) == expected

    @pytest.mark.parametrize(
        "value,expected",
        [(0, 0.0), (25, 3.0), (50, 6.0), (100, 12.0)],
    )
    def test_grain_to_sigma_formula(self, value, expected):
        assert map_grain_to_sigma(value) == pytest.approx(expected)


class TestPrecisionPostFilters:
    """#123-d3/d4: applied whole-image AFTER stitching, skipped entirely at 0."""

    def test_zero_sliders_are_bit_identical(self):
        img = _gradient_image()
        out = apply_precision_post_filters(img, sharpness=0, grain=0)
        assert np.array_equal(np.array(out), np.array(img))

    def test_sharpness_changes_edge_pixels(self):
        img = _gradient_image()
        out = apply_precision_post_filters(img, sharpness=60, grain=0)
        assert not np.array_equal(np.array(out), np.array(img))

    def test_grain_is_seeded_deterministic(self):
        img = Image.new("RGB", (48, 48), color=(128, 128, 128))
        first = np.array(apply_precision_post_filters(img, sharpness=0, grain=50))
        second = np.array(apply_precision_post_filters(img, sharpness=0, grain=50))
        assert np.array_equal(first, second)

    def test_grain_is_zero_mean_gaussian(self):
        img = Image.new("RGB", (48, 48), color=(128, 128, 128))
        out = np.array(apply_precision_post_filters(img, sharpness=0, grain=50))
        noise = out.astype(np.float32) - 128.0
        assert abs(float(noise.mean())) < 1.0  # sigma=6 over ~7k samples

    def test_both_filters_together_run(self):
        img = _gradient_image()
        out = apply_precision_post_filters(img, sharpness=40, grain=25)
        assert out.size == img.size
        assert not np.array_equal(np.array(out), np.array(img))

    def test_grain_never_jitters_alpha_channel(self):
        img = Image.new("RGBA", (48, 48), color=(128, 128, 128, 200))
        out = np.array(apply_precision_post_filters(img, sharpness=0, grain=100))
        assert out.shape[2] == 4
        assert np.all(out[..., 3] == 200)


class TestPrecisionChainPlan:
    """#123-d7: always the full progressive 2x chain; scunet denoises into stage 1
    only while hat runs the SR stages (SCUNet per rung double-blurs)."""

    @pytest.mark.parametrize(
        "scale,stages", [(2, 1), (4, 2), (8, 3), (16, 4)]
    )
    def test_chain_stage_math(self, scale, stages):
        plan = precision_chain_plan(scale, "hat")
        assert plan.stages == stages
        assert 2 ** plan.stages == scale  # every stage is the atomic 2x unit

    def test_hat_runs_every_sr_stage_without_denoise(self):
        plan = precision_chain_plan(16, "hat")
        assert plan.sr_engine == "hat"
        assert plan.denoise_engine is None
        assert plan.stages == 4

    @pytest.mark.parametrize("scale", [2, 4, 8, 16])
    def test_scunet_denoises_into_stage1_and_hat_runs_sr_stages(self, scale):
        plan = precision_chain_plan(scale, "scunet")
        assert plan.denoise_engine == "scunet"
        assert plan.sr_engine == "hat"
        assert plan.stages == {2: 1, 4: 2, 8: 3, 16: 4}[scale]

    def test_stub_engine_plans_the_ci_path(self):
        plan = precision_chain_plan(4, "stub")
        assert plan.sr_engine == "stub"
        assert plan.denoise_engine is None

    def test_unsupported_scale_and_engine_rejected(self):
        with pytest.raises(ValueError):
            precision_chain_plan(3, "hat")
        with pytest.raises(ValueError):
            precision_chain_plan(4, "giga")


class TestPrecisionOutputCap:
    """#123-d5: Precision cap 16384 with hard refusal (no silent downsampling);
    Core (creative) keeps its 8192 clamp."""

    def test_precision_refuses_output_above_16384(self):
        # 1025 * 16 = 16400 > 16384
        raw = _png_bytes(size=(1025, 64))
        with pytest.raises(OutputDimensionExceededError) as excinfo:
            run_tile_upscale_pipeline(
                image_bytes=raw, scale=16, mode="precision", engine="stub"
            )
        message = str(excinfo.value)
        assert str(PRECISION_MAX_OUTPUT_DIMENSION) in message
        assert "16400" in message

    def test_precision_runs_at_or_below_cap(self):
        raw = _png_bytes(size=(64, 64))
        out_bytes, metadata = run_tile_upscale_pipeline(
            image_bytes=raw, scale=16, mode="precision", engine="stub"
        )
        out = Image.open(io.BytesIO(out_bytes))
        assert out.size == (1024, 1024)  # well under 16384

    def test_precision_cap_is_exactly_inclusive(self):
        # 4 * 16 = 64 == the cap exactly -> allowed (cheap boundary via override)
        raw = _png_bytes(size=(4, 4))
        out_bytes, _ = run_tile_upscale_pipeline(
            image_bytes=raw,
            scale=16,
            mode="precision",
            engine="stub",
            max_output_dimension=64,
        )
        assert Image.open(io.BytesIO(out_bytes)).size == (64, 64)

        raw_oversized = _png_bytes(size=(5, 4))
        with pytest.raises(OutputDimensionExceededError):
            run_tile_upscale_pipeline(
                image_bytes=raw_oversized,
                scale=16,
                mode="precision",
                engine="stub",
                max_output_dimension=64,
            )

    def test_creative_mode_still_clamps_to_8192(self):
        # 1700 * 16 = 27200 wide -> legacy creative clamp, not a refusal
        raw = _png_bytes(size=(1700, 64))
        out_bytes, metadata = run_tile_upscale_pipeline(
            image_bytes=raw, scale=16, tile_size=256, overlap=32
        )
        out = Image.open(io.BytesIO(out_bytes))
        assert out.size[0] == CREATIVE_MAX_OUTPUT_DIMENSION
        assert out.size[0] < 27200  # clamped, not refused


class TestSRWeightsUnavailablePolicy:
    """#123-d9: missing weights fail loudly with the exact message — never a
    silent LANCZOS degradation. #123-d2: the venue ladder is local -> colab -> fail."""

    def test_hat_weights_missing_fails_loudly(self):
        raw = _png_bytes(size=(32, 32))
        with pytest.raises(SRWeightsUnavailableError) as excinfo:
            run_tile_upscale_pipeline(
                image_bytes=raw, scale=2, mode="precision", engine="hat"
            )
        assert str(excinfo.value) == (
            "SR weights unavailable for engine 'hat' — run the model pull or "
            "enable Colab offload"
        )

    def test_scunet_weights_missing_fails_loudly(self):
        raw = _png_bytes(size=(32, 32))
        with pytest.raises(SRWeightsUnavailableError) as excinfo:
            run_tile_upscale_pipeline(
                image_bytes=raw, scale=2, mode="precision", engine="scunet"
            )
        assert "engine 'scunet'" in str(excinfo.value)

    def test_failure_happens_before_any_pixel_work(self):
        # Weights resolve up front: the loud error must precede progress writes.
        raw = _png_bytes(size=(32, 32))
        with pytest.raises(SRWeightsUnavailableError):
            run_tile_upscale_pipeline(
                image_bytes=raw, scale=2, mode="precision", engine="hat",
                task_id="never-created", db=None,
            )

    def test_local_venue_resolves_when_runner_registered(self):
        register_sr_runner("hat", lambda img: img, venue="local")
        venue, processor = resolve_sr_backend("hat")
        assert venue == "local"
        assert processor is not None

    def test_colab_offload_venue_resolves_when_runner_registered(self):
        register_sr_runner("hat", lambda img: img, venue="colab")
        venue, processor = resolve_sr_backend("hat")
        assert venue == "colab"

    def test_standard_loaders_resolve_without_error(self):
        """Assert resolve_sr_backend('hat') does not raise SRWeightsUnavailableError when standard loaders are registered (#150)."""
        from app.ml.registry import model_registry

        hat_meta = model_registry.get("hat")
        mock_model = lambda img: img.filter(ImageFilter.SHARPEN)
        model_registry.register(hat_meta, loader_handle=lambda: mock_model)

        register_standard_sr_runners()
        venue, processor = resolve_sr_backend("hat")
        assert venue == "local"
        assert callable(processor)

        test_tile = Image.new("RGB", (32, 32), (100, 100, 100))
        out_tile = processor(test_tile)
        assert out_tile.size == (32, 32)

    def test_standard_loaders_fail_loudly_upfront_when_weights_absent(self):
        """Standard runners fail loudly up front in resolve_sr_backend when loader is not bound (#123-d9)."""
        from app.ml.registry import model_registry

        # Reset hat entry to have no loader
        hat_meta = model_registry.get("hat")
        model_registry.register(hat_meta, loader_handle=None)

        register_standard_sr_runners()
        with pytest.raises(SRWeightsUnavailableError) as exc_info:
            resolve_sr_backend("hat")
        assert "SR weights unavailable for engine 'hat'" in str(exc_info.value)

    def test_precision_job_marks_task_failed_with_loud_error(self, client, stub_storage):
        import app.storage as storage

        storage.upload_object(_png_bytes(size=(32, 32)), "precision_weights.png", "image/png")
        res = client.post(
            "/api/upscale",
            json={"image_path": "precision_weights.png", "scale": 2, "mode": "precision"},
        )
        assert res.status_code == 200
        status = client.get(f"/api/upscale/status/{res.json()['task_id']}").json()
        assert status["status"] == "FAILED"
        assert "SR weights unavailable for engine 'hat'" in (status["error"] or "")


class TestPrecisionStubEngine:
    """The deterministic classical path exists only as the explicit CI `stub`
    engine (#123-d2/d9): selectable in the pipeline, never by API users."""

    def test_stub_engine_runs_the_full_chain(self):
        raw = _png_bytes(size=(64, 64))
        out_bytes, metadata = run_tile_upscale_pipeline(
            image_bytes=raw, scale=4, mode="precision", engine="stub",
            sharpness=15, grain=0, tile_size=256, overlap=32,
        )
        out = Image.open(io.BytesIO(out_bytes))
        assert out.size == (256, 256)
        assert metadata["mode"] == "precision"
        assert metadata["engine"] == "stub"
        assert metadata["stages"] == 2
        assert metadata["target_width"] == 256

    def test_stub_engine_output_is_deterministic(self):
        raw = _png_bytes(size=(48, 48))
        first, _ = run_tile_upscale_pipeline(
            image_bytes=raw, scale=2, mode="precision", engine="stub",
            sharpness=10, grain=10, tile_size=256, overlap=32,
        )
        second, _ = run_tile_upscale_pipeline(
            image_bytes=raw, scale=2, mode="precision", engine="stub",
            sharpness=10, grain=10, tile_size=256, overlap=32,
        )
        assert first == second

    def test_stub_engine_cannot_be_overridden_by_registration(self):
        with pytest.raises(ValueError):
            register_sr_runner("stub", lambda img: img)
        # and the built-in stub still resolves
        venue, _ = resolve_sr_backend("stub")
        assert venue == "stub"


class TestScunetDenoiseMode:
    """#123-d7 evidence: SCUNet runs exactly once on the way into stage 1 and
    never again; the SR stages (hat) run once per tile of every rung."""

    @staticmethod
    def _spy_runners(calls):
        def hat_proc(tile):
            calls.append(("sr", tile.size))
            return tile

        def scunet_proc(img):
            calls.append(("denoise", img.size))
            return img

        register_sr_runner("hat", hat_proc)
        register_sr_runner("scunet", scunet_proc, kind="denoise")

    def test_scunet_denoises_once_then_hat_runs_two_stages(self):
        calls = []
        self._spy_runners(calls)
        raw = _png_bytes(size=(64, 64))
        run_tile_upscale_pipeline(
            image_bytes=raw, scale=4, mode="precision", engine="scunet",
            tile_size=256, overlap=32,
        )
        denoise_calls = [c for c in calls if c[0] == "denoise"]
        sr_calls = [c for c in calls if c[0] == "sr"]
        assert len(denoise_calls) == 1
        assert denoise_calls[0][1] == (64, 64)  # original size, before stage 1
        assert calls[0][0] == "denoise"  # denoise happens on the way in
        # Stage canvases are the full progressive chain: 64 -> 128 -> 256
        assert [size for _, size in sr_calls] == [(128, 128), (256, 256)]

    def test_hat_engine_never_invokes_the_denoiser(self):
        calls = []
        self._spy_runners(calls)
        raw = _png_bytes(size=(64, 64))
        run_tile_upscale_pipeline(
            image_bytes=raw, scale=4, mode="precision", engine="hat",
            tile_size=256, overlap=32,
        )
        assert all(kind == "sr" for kind, _ in calls)
        assert [size for _, size in calls] == [(128, 128), (256, 256)]

    def test_scunet_single_stage_never_blurs_twice(self):
        # 2x = one stage: denoise once, exactly one SR pass — no second rung.
        calls = []
        self._spy_runners(calls)
        raw = _png_bytes(size=(64, 64))
        run_tile_upscale_pipeline(
            image_bytes=raw, scale=2, mode="precision", engine="scunet",
            tile_size=256, overlap=32,
        )
        assert sum(1 for kind, _ in calls if kind == "denoise") == 1
        assert sum(1 for kind, _ in calls if kind == "sr") == 1


class TestPrecisionProgressReporting:
    """#124: precision rides the same DB Task + Redis progress plumbing as creative."""

    def test_precision_pipeline_reports_stage_progress(self, db_session):
        raw = _png_bytes(size=(64, 64))
        task_id = "test-precision-progress"
        db_session.add(Task(task_id=task_id, name="upscale: p.png", status="PROCESSING", progress=0))
        db_session.commit()

        _, metadata = run_tile_upscale_pipeline(
            image_bytes=raw, scale=4, mode="precision", engine="stub",
            task_id=task_id, db=db_session, tile_size=64, overlap=16,
        )

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.status == "PROCESSING"
        assert db_task.progress == 100
        assert "stage 2/2" in (db_task.logs or "")
        assert metadata["total_tiles"] > 0


class TestPrecisionJobEndToEnd:
    """execute_upscale_job carries the precision inputs through to the pipeline."""

    def test_job_completes_with_stub_engine(self, db_session, monkeypatch, stub_storage):
        import app.storage as storage

        monkeypatch.setattr(
            "app.services.upscaler.get_embedding", lambda text: [0.0] * 384, raising=False
        )
        storage.upload_object(_png_bytes(size=(32, 32)), "precision_job.png", "image/png")
        db_session.add(
            Task(task_id="upscale_precision_job1", name="upscale: p.png", status="PROCESSING", progress=0)
        )
        db_session.commit()

        execute_upscale_job(
            task_id="upscale_precision_job1",
            image_path="precision_job.png",
            scale=2,
            creativity=0.0,
            resemblance=0.0,
            fractality=0.0,
            hdr=0.0,
            category="universal",
            prompt=None,
            output_path="upscaled/precision_job_2x_token.png",
            mode="precision",
            engine="stub",
            sharpness=15,
            grain=0,
        )

        db_task = db_session.query(Task).filter(Task.task_id == "upscale_precision_job1").first()
        assert db_task.status == "COMPLETED"
        assert db_task.progress == 100
        assert "upscaled/precision_job_2x_token.png" in stub_storage["uploaded"]

    def test_job_fails_loudly_without_weights(self, db_session, stub_storage):
        import app.storage as storage

        storage.upload_object(_png_bytes(size=(32, 32)), "precision_job_fail.png", "image/png")
        db_session.add(
            Task(task_id="upscale_precision_job2", name="upscale: p.png", status="PROCESSING", progress=0)
        )
        db_session.commit()

        execute_upscale_job(
            task_id="upscale_precision_job2",
            image_path="precision_job_fail.png",
            scale=2,
            creativity=0.0,
            resemblance=0.0,
            fractality=0.0,
            hdr=0.0,
            category="universal",
            prompt=None,
            output_path="upscaled/precision_job_fail_2x_token.png",
            mode="precision",
            engine="hat",
            sharpness=0,
            grain=0,
        )

        db_task = db_session.query(Task).filter(Task.task_id == "upscale_precision_job2").first()
        assert db_task.status == "FAILED"
        assert "SR weights unavailable for engine 'hat'" in (db_task.error or "")
        # Loud failure — nothing was written, no silent degradation.
        assert "upscaled/precision_job_fail_2x_token.png" not in stub_storage["uploaded"]
