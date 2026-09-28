"""Tests for the Background Removal endpoint and ML engine (#116).

Verifies Ticket #116 requirements and binding decisions from #115:
1. Two model tiers: rembg+u2net (default "Fast") and birefnet-general ("Quality" toggle).
2. Output is PNG (RGBA) only, alpha-correct end-to-end (never converted to RGB).
3. Produces additive derivative asset linked to source via source_path lineage.
4. Progress lands in Task system (Task row with name="bgremove" + Redis task_updates pub/sub).
5. Refusal/GPU absence returns degraded envelope at HTTP 200.
6. Offline stub segmentation engine in CI - no real model downloads.
7. Graceful degradation when dependencies are absent.
"""

from __future__ import annotations

import io
import json
import sys
from pathlib import Path
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app.database import Base
from app.main import app
from app.ml.contracts import DegradedReason
from app.ml.guard import NoGPUError, InsufficientVRAMError
from app.models import MediaAsset, Task
from app.storage import upload_object


# ---------------------------------------------------------------------------
# Test Helpers & Stub Segmentation Runner
# ---------------------------------------------------------------------------

def make_solid_color_png(width: int = 100, height: int = 100, color: tuple = (255, 0, 0)) -> bytes:
    """Create a test PNG image (RGB)."""
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def make_rgba_test_png(width: int = 100, height: int = 100) -> bytes:
    """Create a test PNG image with initial RGBA."""
    img = Image.new("RGBA", (width, height), color=(0, 128, 255, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class StubSegmentationRunner:
    """Offline stub segmentation engine for CI.

    Simulates subject isolation: turns the background transparent (alpha=0)
    around a circular foreground subject (alpha=255) with anti-aliased edge.
    Guarantees RGBA output with genuine alpha channel.
    """

    def __init__(self):
        self.call_history = []

    def __call__(self, image: Image.Image, tier: str = "fast") -> Image.Image:
        self.call_history.append({"size": image.size, "tier": tier, "mode": image.mode})
        w, h = image.size
        rgba = image.convert("RGBA")
        alpha_mask = Image.new("L", (w, h), 0)
        draw = ImageDraw.Draw(alpha_mask)
        margin_x, margin_y = max(1, w // 4), max(1, h // 4)
        draw.ellipse([margin_x, margin_y, w - margin_x, h - margin_y], fill=255)
        rgba.putalpha(alpha_mask)
        return rgba


@pytest.fixture()
def stub_runner():
    """Inject the stub segmentation runner and cleanly restore afterwards."""
    from app.ml.bgremove import set_bgremove_runner, reset_bgremove_runner

    stub = StubSegmentationRunner()
    set_bgremove_runner(stub)
    yield stub
    reset_bgremove_runner()


@pytest.fixture()
def sample_image_in_storage(stub_storage):
    """Seed a sample source image in test storage."""
    key = "uploads/subject.png"
    png_data = make_solid_color_png(120, 80, (200, 50, 50))
    stub_storage["uploaded"][key] = {"data": png_data, "content_type": "image/png"}
    return key


# ---------------------------------------------------------------------------
# Test Suite
# ---------------------------------------------------------------------------

def _walk_routes(routes):
    for route in routes:
        included = getattr(route, "original_router", None)
        nested = getattr(included, "routes", None) or getattr(route, "routes", None)
        if nested:
            yield from _walk_routes(nested)
        else:
            yield route


class TestBgRemoveEndpointBasics:
    """Route contract and registry verification."""

    def test_bgremove_route_registered(self, client: TestClient):
        """The /api/bgremove router is registered on the FastAPI app."""
        registered = {
            (route.path, method)
            for route in _walk_routes(app.routes)
            if isinstance(route, APIRoute)
            for method in route.methods
        }
        assert ("/api/bgremove", "POST") in registered
        assert ("/api/bgremove/presets", "GET") in registered
        assert ("/api/bgremove/status/{task_id}", "GET") in registered

        res = client.post("/api/bgremove", json={})
        assert res.status_code != 404


class TestBgRemoveExecution:
    """Core functional tests with stub segmentation runner."""

    def test_bgremove_fast_tier_default(
        self, client: TestClient, stub_runner, sample_image_in_storage, db_session
    ):
        """Default tier is 'fast' (rembg+u2net); returns COMPLETED with derivative asset."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage},
        )
        assert res.status_code == 200
        body = res.json()

        assert body["status"] == "COMPLETED"
        assert body["tier"] == "fast"
        assert body["model_id"] == "u2net"
        assert body["source_path"] == sample_image_in_storage
        assert "filename" in body
        assert body["filename"].startswith("bg_removed/")
        assert body["filename"].endswith(".png")
        assert "url" in body
        assert body["url"].startswith("http://test-minio/")
        assert "task_id" in body
        assert body["task_id"].startswith("bgremove_")

        # Verify stub runner was invoked
        assert len(stub_runner.call_history) == 1
        assert stub_runner.call_history[0]["tier"] == "fast"

    def test_bgremove_quality_tier_explicit(
        self, client: TestClient, stub_runner, sample_image_in_storage, monkeypatch
    ):
        """Selecting tier='quality' uses birefnet-general."""
        from app.ml.bgremove import vram_guard
        monkeypatch.setattr(
            vram_guard,
            "select_fitting_model",
            lambda candidate_ids, **kwargs: candidate_ids[0],
        )

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "quality"},
        )
        assert res.status_code == 200
        body = res.json()

        assert body["status"] == "COMPLETED"
        assert body["tier"] == "quality"
        assert body["model_id"] == "birefnet-general"
        assert stub_runner.call_history[0]["tier"] == "quality"

    def test_bgremove_quality_alias_param(
        self, client: TestClient, stub_runner, sample_image_in_storage, monkeypatch
    ):
        """quality='quality' alias is accepted."""
        from app.ml.bgremove import vram_guard
        monkeypatch.setattr(
            vram_guard,
            "select_fitting_model",
            lambda candidate_ids, **kwargs: candidate_ids[0],
        )

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "quality": "quality"},
        )
        assert res.status_code == 200
        assert res.json()["tier"] == "quality"

    def test_image_path_with_spaces_accepted(
        self, client: TestClient, stub_runner, stub_storage
    ):
        """Path with spaces (e.g. 'uploads/my photo.png') is a valid catalog row and accepted."""
        key = "uploads/my photo.png"
        stub_storage["uploaded"][key] = {
            "data": make_solid_color_png(64, 64),
            "content_type": "image/png",
        }

        res = client.post(
            "/api/bgremove",
            json={"image_path": key},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["source_path"] == key


class TestBgRemoveAlphaCorrectness:
    """Decision #2: Output must be strictly PNG (RGBA) with alpha channel preserved."""

    def test_output_is_strictly_rgba_png_with_alpha(
        self, client: TestClient, stub_runner, sample_image_in_storage, stub_storage
    ):
        """Derivative written to storage is RGBA PNG with non-trivial alpha."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "fast"},
        )
        assert res.status_code == 200
        filename = res.json()["filename"]

        assert filename in stub_storage["uploaded"]
        record = stub_storage["uploaded"][filename]
        assert record["content_type"] == "image/png"

        # Decode output bytes and assert mode is RGBA
        out_img = Image.open(io.BytesIO(record["data"]))
        assert out_img.format == "PNG"
        assert out_img.mode == "RGBA"

        # Check alpha channel exists and contains transparent pixels (0) and opaque pixels (255)
        alpha = out_img.getchannel("A")
        min_alpha, max_alpha = alpha.getextrema()
        assert min_alpha == 0, "Expected transparent background pixels (alpha=0)"
        assert max_alpha == 255, "Expected foreground subject pixels (alpha=255)"


class TestBgRemoveLineageAndPersistence:
    """Decision #3: Derivative asset stored with source_path lineage; original untouched."""

    def test_derivative_lineage_and_original_unmutated(
        self, client: TestClient, stub_runner, sample_image_in_storage, db_session, stub_storage
    ):
        """MediaAsset has source_path pointing to input; original object intact."""
        orig_bytes_before = stub_storage["uploaded"][sample_image_in_storage]["data"]

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage},
        )
        assert res.status_code == 200
        filename = res.json()["filename"]

        # Original storage object is completely unchanged
        assert stub_storage["uploaded"][sample_image_in_storage]["data"] == orig_bytes_before

        # Query MediaAsset catalog
        asset = db_session.query(MediaAsset).filter(MediaAsset.file_path == filename).one_or_none()
        assert asset is not None
        assert asset.source_path == sample_image_in_storage
        assert asset.content_type == "image/png"
        assert asset.file_size > 0
        assert "Background Removed" in asset.title


class TestBgRemoveTaskSystem:
    """Decision #4: Progress lands in Task table + Redis task_updates pub/sub."""

    def test_task_row_and_redis_pubsub_updated(
        self, client: TestClient, stub_runner, sample_image_in_storage, db_session, stub_redis, monkeypatch
    ):
        """Task row is created with COMPLETED status and pub/sub events are published."""
        published_events = []
        monkeypatch.setattr(
            stub_redis,
            "publish",
            lambda channel, msg: published_events.append((channel, json.loads(msg))),
        )

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage},
        )
        assert res.status_code == 200
        task_id = res.json()["task_id"]

        # Check DB Task record (name='bgremove' per SHOULD-FIX 3)
        db_task = db_session.query(Task).filter(Task.task_id == task_id).one_or_none()
        assert db_task is not None
        assert db_task.name == "bgremove"
        assert db_task.status == "COMPLETED"
        assert db_task.progress == 100
        assert db_task.error is None

        # Check Redis pubsub publishes
        task_updates = [payload for channel, payload in published_events if channel == "task_updates"]
        assert len(task_updates) >= 3, f"Expected >= 3 task_updates events, got {len(task_updates)}"
        progress_values = [frame["progress"] for frame in task_updates]
        assert all(frame["task_id"] == task_id for frame in task_updates)
        assert progress_values == sorted(progress_values), "Progress must be strictly non-decreasing"
        assert progress_values[-1] == 100
        assert task_updates[-1]["status"] == "COMPLETED"

        # Check status endpoint
        status_res = client.get(f"/api/bgremove/status/{task_id}")
        assert status_res.status_code == 200
        status_body = status_res.json()
        assert status_body["status"] == "COMPLETED"
        assert status_body["progress"] == 100
        assert status_body["output_path"] == res.json()["filename"]
        assert status_body["result_url"] is not None

    def test_task_list_type_filter_matches_bgremove(
        self, client: TestClient, stub_runner, sample_image_in_storage
    ):
        """Task.name='bgremove' enables /api/tasks/list?type=bgremove filtering (#116 fix 3)."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage},
        )
        assert res.status_code == 200
        task_id = res.json()["task_id"]

        list_res = client.get("/api/tasks/list?type=bgremove")
        assert list_res.status_code == 200
        tasks = list_res.json()["tasks"]
        matching = [t for t in tasks if t["task_id"] == task_id]
        assert len(matching) == 1
        assert matching[0]["name"] == "bgremove"


class TestBgRemoveRefusalsAndDegradedResponses:
    """Decision #4: CPU/VRAM refusal and uninstalled dependencies return degraded envelope at HTTP 200."""

    def test_quality_tier_no_gpu_returns_degraded_envelope_200(
        self, client: TestClient, sample_image_in_storage, monkeypatch
    ):
        """When quality tier is requested with no GPU, returns 200 degraded envelope."""
        from app.ml.bgremove import vram_guard

        def _raise_no_gpu(*args, **kwargs):
            raise NoGPUError(model_id="birefnet-general")

        monkeypatch.setattr(vram_guard, "select_fitting_model", _raise_no_gpu)

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "quality"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.NO_GPU.value
        assert body["model_id"] == "birefnet-general"

    def test_quality_tier_insufficient_vram_returns_degraded_envelope_200(
        self, client: TestClient, sample_image_in_storage, monkeypatch
    ):
        """When quality tier exceeds available VRAM, returns 200 degraded envelope."""
        from app.ml.bgremove import vram_guard

        def _raise_insufficient(*args, **kwargs):
            raise InsufficientVRAMError(
                model_id="birefnet-general",
                required_bytes=4 * (1024 ** 3),
                available_bytes=1 * (1024 ** 3),
                total_bytes=8 * (1024 ** 3),
            )

        monkeypatch.setattr(vram_guard, "select_fitting_model", _raise_insufficient)

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "quality"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.INSUFFICIENT_VRAM.value

    def test_quality_tier_weights_unavailable_returns_200_degraded(
        self, client: TestClient, sample_image_in_storage, monkeypatch
    ):
        """Quality tier with weights unavailable degrades gracefully to HTTP 200 load_failed (BLOCKER 2)."""
        from app.ml.bgremove import reset_bgremove_runner, vram_guard

        reset_bgremove_runner()
        # Admit via VRAM guard so execution proceeds to loader
        monkeypatch.setattr(
            vram_guard,
            "select_fitting_model",
            lambda candidate_ids, **kwargs: candidate_ids[0],
        )

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "quality"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert body["model_id"] == "birefnet-general"

    def test_quality_tier_with_stubbed_loader_returns_completed(
        self, client: TestClient, stub_runner, sample_image_in_storage, monkeypatch
    ):
        """When quality runner is present/loaded, tier='quality' completes successfully (BLOCKER 2)."""
        from app.ml.bgremove import vram_guard
        monkeypatch.setattr(
            vram_guard,
            "select_fitting_model",
            lambda candidate_ids, **kwargs: candidate_ids[0],
        )

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "quality"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["tier"] == "quality"
        assert body["model_id"] == "birefnet-general"

    def test_missing_rembg_package_returns_degraded_envelope_not_500(
        self, client: TestClient, sample_image_in_storage, monkeypatch
    ):
        """When real rembg is not installed, calling endpoint returns 200 degraded (not 500) (SHOULD-FIX 7)."""
        from app.ml.bgremove import reset_bgremove_runner
        reset_bgremove_runner()
        monkeypatch.setitem(sys.modules, "rembg", None)

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "fast"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value

    def test_storage_upload_failure_returns_degraded_envelope(
        self, client: TestClient, stub_runner, sample_image_in_storage, monkeypatch
    ):
        """When MinIO upload fails, returns degraded envelope and marks task failed."""
        monkeypatch.setattr("app.ml.bgremove.upload_object", lambda *args, **kwargs: False)

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value

    def test_db_commit_failure_rolls_back_and_deletes_orphaned_blob(
        self, client: TestClient, stub_runner, sample_image_in_storage, db_session, stub_storage, monkeypatch
    ):
        """When catalog commit fails, session is rolled back and storage blob is deleted (SHOULD-FIX 5 & 8)."""
        orig_add = db_session.add

        def _add_interceptor(instance):
            if isinstance(instance, MediaAsset):
                raise RuntimeError("Simulated DB failure on MediaAsset add")
            orig_add(instance)

        monkeypatch.setattr(db_session, "add", _add_interceptor)

        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value

        # Assert no orphaned .png remains in uploaded storage
        orphans = [k for k in stub_storage["uploaded"] if k.startswith("bg_removed/")]
        assert len(orphans) == 0, f"Found leaked blobs in storage: {orphans}"
        assert len(stub_storage["deleted"]) > 0


class TestBgRemoveSessionCaching:
    """SHOULD-FIX 4: ONNX session caching and test isolation."""

    def test_rembg_session_cached_and_resettable(self, monkeypatch):
        """rembg ONNX session is cached across requests and cleared on reset."""
        from app.ml import bgremove as bg_mod

        fake_rembg = MagicMock()
        mock_session = object()
        fake_rembg.new_session.return_value = mock_session
        monkeypatch.setitem(sys.modules, "rembg", fake_rembg)

        bg_mod.reset_bgremove_runner()
        sess1 = bg_mod.get_rembg_session()
        sess2 = bg_mod.get_rembg_session()
        assert sess1 is sess2
        assert fake_rembg.new_session.call_count == 1

        bg_mod.reset_bgremove_runner()
        sess3 = bg_mod.get_rembg_session()
        assert fake_rembg.new_session.call_count == 2
        bg_mod.reset_bgremove_runner()


class TestBgRemoveInputValidation:
    """Invalid requests must return HTTP 400 with actionable messages."""

    def test_invalid_tier_rejected_400(self, client: TestClient, sample_image_in_storage):
        """Invalid tier returns 400 with allowed tiers."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "ultra_hd"},
        )
        assert res.status_code == 400
        assert "Unsupported background removal tier" in res.json()["detail"]

    def test_bria_rmbg_specifically_refused(self, client: TestClient, sample_image_in_storage):
        """bria-rmbg (non-commercial CC BY-NC) must never be accepted."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": sample_image_in_storage, "tier": "bria-rmbg"},
        )
        assert res.status_code == 400

    def test_video_input_rejected_400(self, client: TestClient):
        """Video inputs return 400 with video_input_not_supported slug."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": "uploads/sample.mp4"},
        )
        assert res.status_code == 400
        assert "video_input_not_supported" in res.json()["detail"]

    def test_path_traversal_rejected_400(self, client: TestClient):
        """Relative traversal is refused."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": "../../secret.png"},
        )
        assert res.status_code == 400

    def test_missing_source_image_returns_400(self, client: TestClient, stub_runner):
        """Non-existent storage key returns 400 source_not_found (NIT 3)."""
        res = client.post(
            "/api/bgremove",
            json={"image_path": "uploads/does_not_exist.png"},
        )
        assert res.status_code == 400
        assert "source_not_found" in res.json()["detail"]

    def test_missing_image_path_in_payload_returns_422(self, client: TestClient):
        """Missing required image_path raises validation error."""
        res = client.post("/api/bgremove", json={})
        assert res.status_code == 422

    def test_oversize_input_image_capped_to_max_dimension(
        self, client: TestClient, stub_runner, stub_storage
    ):
        """Inputs exceeding 8192px on longest side are capped (LEARNINGS.md #201 9000x64 strip recipe) (NIT 4)."""
        key = "uploads/panorama_strip.png"
        buf = io.BytesIO()
        Image.new("RGB", (9000, 64), (30, 60, 90)).save(buf, format="PNG")
        stub_storage["uploaded"][key] = {"data": buf.getvalue(), "content_type": "image/png"}

        res = client.post(
            "/api/bgremove",
            json={"image_path": key},
        )
        assert res.status_code == 200
        assert len(stub_runner.call_history) == 1
        called_size = stub_runner.call_history[0]["size"]
        assert called_size[0] == 8192
        assert called_size[1] == int(64 * 8192 / 9000)


class TestBgRemovePresetsAndInfo:
    """Surface description for the frontend UI."""

    def test_presets_surface_contract(self, client: TestClient):
        """GET /api/bgremove/presets returns tiers, model mapping, and host requirements."""
        res = client.get("/api/bgremove/presets")
        assert res.status_code == 200
        body = res.json()
        assert "tiers" in body
        assert "fast" in body["tiers"]
        assert "quality" in body["tiers"]
        assert body["default_tier"] == "fast"
        assert body["models"]["fast"] == "u2net"
        assert body["models"]["quality"] == "birefnet-general"
        assert "birefnet" in body["descriptions"]["quality"]
        assert "requirements" in body

    def test_tiers_surface_alias(self, client: TestClient):
        """GET /api/bgremove/tiers returns identical contract to /presets."""
        res_presets = client.get("/api/bgremove/presets").json()
        res_tiers = client.get("/api/bgremove/tiers").json()
        assert res_presets == res_tiers

    def test_status_endpoint_not_found_returns_404(self, client: TestClient):
        """Querying status of a nonexistent task returns 404."""
        res = client.get("/api/bgremove/status/bgremove_nonexistent")
        assert res.status_code == 404

    def test_commercial_safety_bria_excluded(self):
        """Decision #1: bria-rmbg (CC BY-NC) must never enter supported models."""
        from app.ml.bgremove import describe_bgremove_surface, TIER_MODELS

        surface = describe_bgremove_surface()
        all_models = list(surface["models"].values()) + list(TIER_MODELS.values())
        for model in all_models:
            assert "bria" not in model.lower()
