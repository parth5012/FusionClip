"""Tests for local ML inference foundation scaffold (#99).

Asserts:
1. Model registry: pinned roster, lazy loading, idempotent load/unload, VRAM cleanup.
2. VRAM guard: no-GPU detection, insufficient VRAM refusal with typed errors, overhead buffer, auto-downgrade.
3. Celery queue isolation: dedicated media.gpu queue and task routing distinct from CPU queues.
4. Degraded response contract: labeled honest fallback tier (degraded=True, machine-readable reason).
5. Health metrics endpoint: GET /api/tasks/gpu/health exposing per-model state, VRAM, and queue metrics.
"""

import pytest
from unittest.mock import MagicMock
from kombu import Queue

from app.celery_app import celery
from app.ml.contracts import (
    DegradedReason,
    DegradedResponse,
    FallbackTier,
    make_degraded_response,
)
from app.ml.guard import (
    InsufficientVRAMError,
    NoGPUError,
    VRAMGuard,
    VRAMRefusalError,
)
from app.ml.registry import (
    ModelMetadata,
    ModelRegistry,
)


class TestModelRegistry:
    @pytest.fixture(autouse=True)
    def clean_registry(self):
        """Ensure fresh registry for each test."""
        reg = ModelRegistry()
        yield reg
        reg.unload_all()

    def test_pinned_roster_loaded_by_default(self, clean_registry):
        """The pinned roster from Ticket #98 must be present by default:
        Flux-schnell -> SDXL -> XTTS v2 -> MusicGen -> SVD.
        """
        models = {m.model_id: m for m in clean_registry.list_models()}
        expected_ids = {"flux-schnell", "sdxl", "xtts-v2", "musicgen", "svd"}
        # Exact roster: nothing extra, nothing missing (Decision #4 pins the roster).
        assert set(models.keys()) == expected_ids
        # Decision #4 explicitly excludes FLUX.1 [dev] (BFL non-commercial license).
        assert "flux-dev" not in models

        # 1. Flux-schnell (image, FP8, ~13.0 GB, Apache-2.0)
        flux = models["flux-schnell"]
        assert flux.family == "image"
        assert flux.dtype_quant == "fp8"
        assert flux.approx_vram_gb >= 13.0
        assert flux.license == "Apache-2.0"

        # 2. SDXL (image, FP8, ~6.5 GB, OpenRAIL++-M)
        sdxl = models["sdxl"]
        assert sdxl.family == "image"
        assert sdxl.dtype_quant == "fp8"
        assert 6.0 <= sdxl.approx_vram_gb <= 8.0
        assert sdxl.license == "OpenRAIL++-M"

        # 3. XTTS v2 (voice, FP16, ~4.0 GB, CPML)
        xtts = models["xtts-v2"]
        assert xtts.family == "voice"
        assert 4.0 <= xtts.approx_vram_gb <= 6.0
        assert xtts.license == "CPML"

        # 4. MusicGen (audio, FP16, ~10.4 GB) - weights are CC-BY-NC-4.0, code MIT.
        # Registry records the *weights* license because that is what gates usage.
        musicgen = models["musicgen"]
        assert musicgen.family == "audio"
        assert musicgen.approx_vram_gb >= 10.0
        assert musicgen.license == "CC-BY-NC-4.0"

        # 5. SVD (video, FP16, ~16.0 GB resident / 8.0 GB offload)
        # Stability AI Community License - NOT OpenRAIL++-M (that is SDXL's).
        svd = models["svd"]
        assert svd.family == "video"
        assert svd.approx_vram_gb >= 16.0
        assert svd.offload_vram_gb == 8.0
        assert svd.license == "Stability-AI-Community"

    def test_lazy_loading(self, clean_registry):
        """Model loader handle is NOT called at registration or inquiry time."""
        mock_loader = MagicMock(return_value="dummy_model_instance")
        clean_registry.register(
            ModelMetadata(
                model_id="test-lazy-model",
                family="image",
                dtype_quant="fp16",
                approx_vram_gb=4.0,
                license="MIT",
            ),
            loader_handle=mock_loader,
        )

        assert not clean_registry.is_loaded("test-lazy-model")
        mock_loader.assert_not_called()

        # Reading metadata does not trigger loading
        meta = clean_registry.get("test-lazy-model")
        assert meta.model_id == "test-lazy-model"
        mock_loader.assert_not_called()

        # Calling load_model triggers the loader
        instance = clean_registry.load_model("test-lazy-model")
        assert instance == "dummy_model_instance"
        assert clean_registry.is_loaded("test-lazy-model")
        assert mock_loader.call_count == 1

    def test_idempotent_load(self, clean_registry):
        """Calling load_model multiple times returns cached instance without re-executing loader."""
        mock_loader = MagicMock(return_value={"pipeline": "flux"})
        clean_registry.register(
            ModelMetadata(
                model_id="test-idempotent",
                family="image",
                dtype_quant="fp8",
                approx_vram_gb=13.0,
                license="Apache-2.0",
            ),
            loader_handle=mock_loader,
        )

        first_call = clean_registry.load_model("test-idempotent")
        second_call = clean_registry.load_model("test-idempotent")

        assert first_call is second_call
        assert mock_loader.call_count == 1

    def test_idempotent_unload_and_vram_cleanup(self, clean_registry, monkeypatch):
        """Unload drops cached reference, marks unloaded, and calls empty_cache.

        `_empty_cuda_cache()` does a *function-local* `import torch`, so the only
        reliable seam is `sys.modules` - patching `app.ml.registry.torch` never runs.
        """
        import sys

        mock_empty_cache = MagicMock()
        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.empty_cache = mock_empty_cache
        monkeypatch.setitem(sys.modules, "torch", mock_torch)

        clean_registry.register(
            ModelMetadata(
                model_id="test-unload",
                family="image",
                dtype_quant="fp8",
                approx_vram_gb=6.0,
                license="MIT",
            ),
            loader_handle=lambda: "loaded_object",
        )

        # Unload on not-yet-loaded model is a safe no-op
        assert not clean_registry.unload_model("test-unload")
        assert not clean_registry.is_loaded("test-unload")

        # Load then unload
        clean_registry.load_model("test-unload")
        assert clean_registry.is_loaded("test-unload")

        unloaded = clean_registry.unload_model("test-unload")
        assert unloaded is True
        assert not clean_registry.is_loaded("test-unload")

        # VRAM really is reclaimed: cuda cache emptied exactly once for this unload
        mock_torch.cuda.empty_cache.assert_called_once()

        # Second unload is safe no-op
        assert not clean_registry.unload_model("test-unload")
        mock_torch.cuda.empty_cache.assert_called_once()

    def test_unload_all(self, clean_registry):
        """unload_all unloads every loaded model in the registry."""
        clean_registry.register(
            ModelMetadata(model_id="m1", family="audio", dtype_quant="fp16", approx_vram_gb=2.0, license="MIT"),
            loader_handle=lambda: "m1_obj",
        )
        clean_registry.register(
            ModelMetadata(model_id="m2", family="video", dtype_quant="fp16", approx_vram_gb=4.0, license="MIT"),
            loader_handle=lambda: "m2_obj",
        )

        clean_registry.load_model("m1")
        clean_registry.load_model("m2")
        assert clean_registry.is_loaded("m1")
        assert clean_registry.is_loaded("m2")

        count = clean_registry.unload_all()
        assert count == 2
        assert not clean_registry.is_loaded("m1")
        assert not clean_registry.is_loaded("m2")

    def test_unknown_model_raises_key_error(self, clean_registry):
        """Looking up or loading unregistered model raises KeyError."""
        with pytest.raises(KeyError):
            clean_registry.get("non-existent-model")
        with pytest.raises(KeyError):
            clean_registry.load_model("non-existent-model")

    def test_concurrent_load_runs_loader_once(self, clean_registry):
        """Two threads racing to lazy-load the same model must not both allocate.

        Without a lock, two Celery workers requesting an unloaded 13 GB model would
        each call the loader and immediately OOM a 16 GB GPU.
        """
        import threading
        import time

        calls = []
        barrier = threading.Barrier(2, timeout=5)

        def slow_loader():
            calls.append(1)
            time.sleep(0.15)
            return "race_instance"

        clean_registry.register(
            ModelMetadata(
                model_id="race-model",
                family="image",
                dtype_quant="fp8",
                approx_vram_gb=13.0,
                license="Apache-2.0",
            ),
            loader_handle=slow_loader,
        )

        results = []

        def worker():
            barrier.wait()
            results.append(clean_registry.load_model("race-model"))

        threads = [threading.Thread(target=worker) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)

        assert len(calls) == 1, f"loader executed {len(calls)} times, expected 1"
        assert len(results) == 2
        assert results[0] is results[1]

    def test_re_register_unloads_resident_model(self, clean_registry):
        """Re-registering an already-resident model must release its VRAM first."""
        import sys
        from unittest.mock import MagicMock, patch

        mock_torch = MagicMock()
        mock_torch.cuda.is_available.return_value = True

        meta = ModelMetadata(
            model_id="re-reg",
            family="image",
            dtype_quant="fp8",
            approx_vram_gb=6.0,
            license="MIT",
        )
        clean_registry.register(meta, loader_handle=lambda: "first")
        clean_registry.load_model("re-reg")
        assert clean_registry.is_loaded("re-reg")

        with patch.dict(sys.modules, {"torch": mock_torch}):
            clean_registry.register(meta, loader_handle=lambda: "second")

        assert not clean_registry.is_loaded("re-reg")
        mock_torch.cuda.empty_cache.assert_called_once()


class TestVRAMGuard:
    @pytest.fixture()
    def guard(self):
        reg = ModelRegistry()
        return VRAMGuard(registry=reg, default_overhead_gb=1.0)

    def test_detects_no_gpu_distinctly(self, guard, monkeypatch):
        """When host has no CUDA GPU, raises NoGPUError with reason='no_gpu'."""
        # Mock get_gpu_info to simulate no GPU available
        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": False,
                "device_name": None,
                "total_bytes": 0,
                "free_bytes": 0,
                "used_bytes": 0,
                "total_gb": 0.0,
                "free_gb": 0.0,
                "used_gb": 0.0,
                "vram_percent": 0.0,
            },
        )

        with pytest.raises(NoGPUError) as exc_info:
            guard.check_vram("flux-schnell")

        err = exc_info.value
        assert err.reason == DegradedReason.NO_GPU.value
        assert "no cuda gpu" in err.message.lower()

        # Contract conversion
        degraded = err.to_degraded_response()
        assert degraded.degraded is True
        assert degraded.reason == DegradedReason.NO_GPU.value
        assert degraded.fallback_tier == FallbackTier.REFUSAL.value

    def test_insufficient_vram_refusal(self, guard, monkeypatch):
        """When GPU free VRAM is less than model requirement + overhead, raises InsufficientVRAMError."""
        # Simulate 8 GB free out of 16 GB total
        free_bytes = int(8.0 * (1024 ** 3))
        total_bytes = int(16.0 * (1024 ** 3))

        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA GeForce RTX 4090",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": 16.0,
                "free_gb": 8.0,
                "used_gb": 8.0,
                "vram_percent": 50.0,
            },
        )

        # flux-schnell requires 13.0 GB + 1.0 GB overhead = 14.0 GB > 8.0 GB
        with pytest.raises(InsufficientVRAMError) as exc_info:
            guard.check_vram("flux-schnell", working_overhead_gb=1.0)

        err = exc_info.value
        assert err.reason == DegradedReason.INSUFFICIENT_VRAM.value
        assert err.model_id == "flux-schnell"
        assert err.required_bytes > free_bytes
        assert err.available_bytes == free_bytes

        # Verify degraded contract shape
        degraded = err.to_degraded_response()
        assert degraded.degraded is True
        assert degraded.reason == DegradedReason.INSUFFICIENT_VRAM.value
        assert degraded.model_id == "flux-schnell"
        assert degraded.vram_required_gb >= 14.0
        assert degraded.vram_available_gb == 8.0

    def test_sufficient_vram_admits_job(self, guard, monkeypatch):
        """When GPU has sufficient free VRAM, check_vram succeeds and returns admission info."""
        free_bytes = int(24.0 * (1024 ** 3))
        total_bytes = int(24.0 * (1024 ** 3))

        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 6000 Ada",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": 0,
                "total_gb": 24.0,
                "free_gb": 24.0,
                "used_gb": 0.0,
                "vram_percent": 0.0,
            },
        )

        res = guard.check_vram("flux-schnell", working_overhead_gb=1.0)
        assert res["admitted"] is True
        assert res["model_id"] == "flux-schnell"
        assert res["free_gb"] == 24.0

    def test_already_loaded_model_checks_overhead_only(self, guard, monkeypatch):
        """If model is already resident in VRAM, only the working overhead is required."""
        free_bytes = int(2.0 * (1024 ** 3))
        total_bytes = int(16.0 * (1024 ** 3))

        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4080",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": 16.0,
                "free_gb": 2.0,
                "used_gb": 14.0,
                "vram_percent": 87.5,
            },
        )

        # Mark flux-schnell as loaded
        guard.registry.register(
            ModelMetadata(
                model_id="flux-schnell",
                family="image",
                dtype_quant="fp8",
                approx_vram_gb=13.0,
                license="Apache-2.0",
            ),
            loader_handle=lambda: "dummy_instance",
        )
        guard.registry.load_model("flux-schnell")
        assert guard.registry.is_loaded("flux-schnell")

        # 2.0 GB free is enough for 1.0 GB overhead
        res = guard.check_vram("flux-schnell", working_overhead_gb=1.0)
        assert res["admitted"] is True
        assert res["already_loaded"] is True

    def test_auto_downgrade_selection(self, guard, monkeypatch):
        """Decision #4: select_fitting_model downgrades from Flux to SDXL if Flux won't fit."""
        # 8 GB free VRAM: Flux (13 + 1 = 14 GB) won't fit, SDXL (6.5 + 1 = 7.5 GB) fits!
        free_bytes = int(8.0 * (1024 ** 3))
        total_bytes = int(16.0 * (1024 ** 3))

        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4080",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": 16.0,
                "free_gb": 8.0,
                "used_gb": 8.0,
                "vram_percent": 50.0,
            },
        )

        selected = guard.select_fitting_model(["flux-schnell", "sdxl"], working_overhead_gb=1.0)
        assert selected == "sdxl"

        # 5 GB free VRAM: neither fits
        free_bytes_low = int(5.0 * (1024 ** 3))
        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4080",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes_low,
                "used_bytes": total_bytes - free_bytes_low,
                "total_gb": 16.0,
                "free_gb": 5.0,
                "used_gb": 11.0,
                "vram_percent": 68.75,
            },
        )

        with pytest.raises(InsufficientVRAMError):
            guard.select_fitting_model(["flux-schnell", "sdxl"], working_overhead_gb=1.0)

    @staticmethod
    def _fake_gpu(guard, monkeypatch, free_gb, total_gb):
        free_bytes = int(free_gb * (1024 ** 3))
        total_bytes = int(total_gb * (1024 ** 3))
        monkeypatch.setattr(
            guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4060 Ti",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": float(total_gb),
                "free_gb": float(free_gb),
                "used_gb": float(total_gb - free_gb),
                "vram_percent": round(((total_bytes - free_bytes) / total_bytes) * 100, 1),
            },
        )

    def test_unknown_model_is_model_not_found(self, guard, monkeypatch):
        """A KeyError from the registry must surface as a degraded model_not_found,
        never escape and crash the Celery worker into FAILURE state."""
        self._fake_gpu(guard, monkeypatch, free_gb=24.0, total_gb=24.0)

        with pytest.raises(VRAMRefusalError) as exc_info:
            guard.check_vram("flux-dev")
        # Must NOT be misclassified as no_gpu / insufficient_vram
        assert exc_info.value.reason == DegradedReason.MODEL_NOT_FOUND.value
        assert not isinstance(exc_info.value, NoGPUError)
        assert not isinstance(exc_info.value, InsufficientVRAMError)

    def test_select_fitting_model_empty_candidates_reason(self, guard, monkeypatch):
        """Empty candidate list with a GPU present must not report no_gpu."""
        self._fake_gpu(guard, monkeypatch, free_gb=24.0, total_gb=24.0)

        with pytest.raises(VRAMRefusalError) as exc_info:
            guard.select_fitting_model([])
        assert exc_info.value.reason == DegradedReason.MODEL_NOT_FOUND.value

    def test_select_fitting_model_skips_unknown_candidates(self, guard, monkeypatch):
        """An unregistered candidate must not abort selection of a later valid one."""
        self._fake_gpu(guard, monkeypatch, free_gb=8.0, total_gb=16.0)

        selected = guard.select_fitting_model(
            ["flux-dev", "flux-schnell", "sdxl"], working_overhead_gb=1.0
        )
        assert selected == "sdxl"

    def test_svd_admits_via_offload_on_16gb_floor(self, guard, monkeypatch):
        """Decision #1 sets the floor at 16 GB. SVD (16 GB resident) must still be
        admitted there via its 8 GB CPU-offload footprint, not unconditionally refused."""
        # ~15.2 GB usable on a nominal 16 GB card
        self._fake_gpu(guard, monkeypatch, free_gb=15.2, total_gb=16.0)

        res = guard.check_vram("svd", working_overhead_gb=1.0)
        assert res["admitted"] is True
        assert res["model_id"] == "svd"
        assert res["mode"] == "offload"
        assert res["required_gb"] <= 15.2

    def test_svd_still_refused_when_offload_also_fails(self, guard, monkeypatch):
        """Offload is not a magic bypass: refuse when even the offload footprint misses."""
        self._fake_gpu(guard, monkeypatch, free_gb=6.0, total_gb=16.0)

        with pytest.raises(InsufficientVRAMError) as exc_info:
            guard.check_vram("svd", working_overhead_gb=1.0)
        assert exc_info.value.reason == DegradedReason.INSUFFICIENT_VRAM.value


class TestCeleryGPUQueueIsolation:
    def test_gpu_queue_configured(self):
        """Celery config must define media.gpu queue alongside existing media.fast and media.heavy."""
        queue_names = {q.name for q in celery.conf.task_queues}
        assert "media.gpu" in queue_names
        assert "media.fast" in queue_names
        assert "media.heavy" in queue_names

    def test_gpu_task_routes_isolated(self):
        """GPU tasks route to media.gpu without polluting media.fast or media.heavy."""
        routes = celery.conf.task_routes
        assert routes.get("app.tasks.process_gpu_task") == {"queue": "media.gpu"}
        # Existing CPU routes preserved
        assert routes.get("app.tasks.process_media_fast") == {"queue": "media.fast"}
        assert routes.get("app.tasks.process_media_heavy") == {"queue": "media.heavy"}

    @staticmethod
    def _run_gpu_task(*args, **kwargs):
        from app.tasks import process_gpu_task

        runner = getattr(process_gpu_task, "run", None)
        if callable(runner):
            try:
                return runner(*args, **kwargs)
            except TypeError:
                pass
        return process_gpu_task(None, *args, **kwargs)

    def test_process_gpu_task_invokes_vram_guard(self, monkeypatch):
        """process_gpu_task checks VRAM guard before execution.

        The guard is imported *inside* the function body, so the seam that actually
        runs is `app.ml.guard.vram_guard` - patching `app.tasks.vram_guard` is a
        no-op and the test only passed by luck on GPU-less CI hosts.
        """
        from app.ml import guard as guard_module

        class MockGuard:
            def check_vram(self, model_id, **kwargs):
                raise NoGPUError(model_id=model_id)

        monkeypatch.setattr(guard_module, "vram_guard", MockGuard())

        res = self._run_gpu_task("flux-schnell", payload={"prompt": "test"})

        assert isinstance(res, dict)
        assert res["degraded"] is True
        assert res["reason"] == DegradedReason.NO_GPU.value

    def test_process_gpu_task_unknown_model_returns_degraded(self, monkeypatch):
        """An unknown model_id must yield a model_not_found degraded result, not a
        Celery FAILURE caused by an uncaught KeyError."""
        from app.ml import guard as guard_module
        from app.ml.registry import ModelRegistry

        # Real guard against a registry that genuinely lacks 'flux-dev'
        monkeypatch.setattr(
            guard_module,
            "vram_guard",
            type(guard_module.vram_guard)(registry=ModelRegistry()),
        )

        res = self._run_gpu_task("flux-dev", payload={})
        assert isinstance(res, dict)
        assert res["degraded"] is True
        assert res["reason"] == DegradedReason.MODEL_NOT_FOUND.value
        assert res["model_id"] == "flux-dev"


class TestDegradedContract:
    def test_degraded_response_shape(self):
        """Asserts DegradedResponse schema matches Decision #3 specification."""
        deg = make_degraded_response(
            reason=DegradedReason.INSUFFICIENT_VRAM.value,
            message="Cannot fit model into VRAM",
            model_id="svd",
            vram_required_gb=17.0,
            vram_available_gb=8.0,
            fallback_tier=FallbackTier.CLOUD_API.value,
            details={"offload_capable": True},
        )

        assert deg.degraded is True
        assert deg.reason == "insufficient_vram"
        assert deg.message == "Cannot fit model into VRAM"
        assert deg.model_id == "svd"
        assert deg.vram_required_gb == 17.0
        assert deg.vram_available_gb == 8.0
        assert deg.fallback_tier == "cloud_api"
        assert deg.details == {"offload_capable": True}

        # Serializes cleanly to dict/json
        data = deg.model_dump()
        assert data["degraded"] is True
        assert data["reason"] == "insufficient_vram"

    def test_rejects_byte_string_mock_payloads(self):
        """Decision #3 forbids 'Mock ... bytes' payloads - enforced at runtime.

        The old test fed a benign message into the constructor and asserted that
        message did not contain 'Mock ', i.e. it could never fail.
        """
        with pytest.raises(ValueError):
            make_degraded_response(
                reason=DegradedReason.NO_GPU.value,
                message="Mock image payload bytes",
                model_id="flux-schnell",
            )
        with pytest.raises(ValueError):
            make_degraded_response(
                reason=DegradedReason.INSUFFICIENT_VRAM.value,
                message="Mock elevenlabs generated audio bytes.",
                model_id="xtts-v2",
            )

        # Legitimate messages still construct fine and contain no mock payload
        deg = make_degraded_response(
            reason=DegradedReason.NO_GPU.value,
            message="GPU unavailable; fallback invoked",
            model_id="flux-schnell",
        )
        assert deg.degraded is True
        assert "Mock" not in deg.message


class TestGPUHealthEndpoint:
    def test_gpu_health_endpoint_success(self, client, monkeypatch):
        """GET /api/tasks/gpu/health returns 200 with GPU, model, and queue metrics."""
        from app.ml.guard import vram_guard

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(18.0 * (1024 ** 3)),
                "used_bytes": int(6.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 18.0,
                "used_gb": 6.0,
                "vram_percent": 25.0,
            },
        )

        res = client.get("/api/tasks/gpu/health")
        assert res.status_code == 200
        body = res.json()

        assert body["status"] == "healthy"
        assert body["gpu"]["available"] is True
        assert body["gpu"]["total_gb"] == 24.0
        assert body["gpu"]["free_gb"] == 18.0
        assert body["gpu"]["vram_percent"] == 25.0

        # All 5 pinned models present
        assert "flux-schnell" in body["models"]
        assert "sdxl" in body["models"]
        assert "xtts-v2" in body["models"]
        assert "musicgen" in body["models"]
        assert "svd" in body["models"]

        # Queue metrics
        assert body["queue"]["queue_name"] == "media.gpu"
        assert "depth" in body["queue"]
        # Task rows carry no queue column, so this counts in-flight tasks across ALL
        # queues - label must say so rather than implying it is media.gpu-specific.
        assert "active_tasks_total" in body["queue"]
        assert "running_count" not in body["queue"]

    def test_metrics_alias_removed(self, client):
        """The generic /api/tasks/metrics alias bound a GPU-only schema to a
        generic name and would collide with real CPU task metrics later."""
        assert client.get("/api/tasks/metrics").status_code == 404
        assert client.get("/api/tasks/gpu/health").status_code == 200

    def test_gpu_health_unavailable_state(self, client, monkeypatch):
        """When no GPU is present, health endpoint reports status='unavailable'."""
        from app.ml.guard import vram_guard

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": False,
                "device_name": None,
                "total_bytes": 0,
                "free_bytes": 0,
                "used_bytes": 0,
                "total_gb": 0.0,
                "free_gb": 0.0,
                "used_gb": 0.0,
                "vram_percent": 0.0,
            },
        )

        res = client.get("/api/tasks/gpu/health")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "unavailable"
        assert body["gpu"]["available"] is False
