"""Tests for local image generation endpoint and priority-1 model pipeline (#100).

Tests:
1. Complete removal of legacy placeholder string 'Mock local flux generated image bytes'.
2. Degraded refusal contract (HTTP 200 with degraded: true + reason) when no GPU is available.
3. Degraded refusal when free VRAM is insufficient to admit even the auto-downgrade candidate.
4. Auto-downgrade model selection: selects 'sdxl' when 'flux-schnell' cannot fit.
5. Primary model selection: selects 'flux-schnell' when sufficient VRAM is available.
6. Parameter validation and forwarding: steps, scale, scheduler, aspect_ratio, denoising_strength.
7. Local path execution: uploads real image bytes to storage and persists MediaAsset in DB.
8. Gemini cloud path preservation: provider != 'local' with gemini_key routes to Gemini.
9. Colab compute connector preservation: connected Colab worker routes to Colab.
10. Runtime load failure handling: returns degraded envelope with reason 'load_failed'.
"""

import base64
from pathlib import Path
import pytest
import httpx

from app.ml.contracts import DegradedReason, FallbackTier
from app.ml.guard import vram_guard
from app.ml.registry import model_registry
from app.models import MediaAsset
from app.services.secrets import set_secret


REPO_ROOT = Path(__file__).resolve().parents[2]


class TestMockStringElimination:
    def test_mock_string_completely_removed_from_codebase(self):
        """Binding Decision #3: The string 'Mock local flux generated image bytes'
        must no longer exist anywhere in the codebase.
        """
        forbidden = "Mock local flux generated image bytes"
        backend_dir = REPO_ROOT / "backend"

        found_in = []
        for path in backend_dir.rglob("*.py"):
            if path == Path(__file__).resolve():
                continue
            try:
                content = path.read_text(encoding="utf-8")
                if forbidden in content:
                    found_in.append(str(path.relative_to(REPO_ROOT)))
            except (OSError, UnicodeDecodeError):
                continue

        assert not found_in, (
            f"Forbidden mock payload string '{forbidden}' found in: {found_in}"
        )


class TestLocalImageRefusal:
    def test_degraded_refusal_when_no_gpu(self, client, monkeypatch):
        """When host has no CUDA GPU, local image generation returns degraded contract."""
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

        res = client.post("/api/generate/image?prompt=A+serene+mountain+lake&provider=local")
        assert res.status_code == 200
        body = res.json()

        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.NO_GPU.value
        assert "no cuda gpu" in body["message"].lower()
        assert body["fallback_tier"] == FallbackTier.REFUSAL.value
        assert "Mock" not in body["message"]

    def test_degraded_refusal_when_insufficient_vram(self, client, monkeypatch):
        """When GPU free VRAM is insufficient for flux-schnell (14GB) and sdxl (7.5GB),
        returns degraded contract with reason 'insufficient_vram'.
        """
        total_bytes = int(16.0 * (1024 ** 3))
        free_bytes = int(4.0 * (1024 ** 3))
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4080",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": 16.0,
                "free_gb": 4.0,
                "used_gb": 12.0,
                "vram_percent": 75.0,
            },
        )

        res = client.post("/api/generate/image?prompt=A+sunset+beach&provider=local")
        assert res.status_code == 200
        body = res.json()

        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.INSUFFICIENT_VRAM.value
        assert body["model_id"] == "flux-schnell"
        assert body["vram_available_gb"] == 4.0
        assert body["fallback_tier"] == FallbackTier.REFUSAL.value
        assert "Mock" not in body["message"]


class TestModelSelectionAndExecution:
    def test_auto_downgrade_selects_sdxl_when_flux_wont_fit(
        self, client, monkeypatch, db_session, stub_storage
    ):
        """Decision #4: When 8 GB VRAM is free, flux-schnell (~14 GB) cannot fit,
        so vram_guard auto-downgrades to sdxl (~7.5 GB), loads it, and produces an asset.
        """
        total_bytes = int(16.0 * (1024 ** 3))
        free_bytes = int(8.0 * (1024 ** 3))
        monkeypatch.setattr(
            vram_guard,
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

        fake_png = b"\x89PNG\r\n\x1a\nfake-sdxl-image-bytes"
        called_models = []

        class FakeSDXLPipeline:
            def __call__(self, **kwargs):
                called_models.append("sdxl")
                return [fake_png]

        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda model_id, loader_handle=None: FakeSDXLPipeline() if model_id == "sdxl" else None,
        )

        res = client.post("/api/generate/image?prompt=A+cyberpunk+car&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert "sdxl" in called_models
        assert body["filename"].startswith("gen_image_")
        assert body["filename"].endswith(".png")

        # Verify real bytes stored and MediaAsset created in DB
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_png
        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .first()
        )
        assert asset is not None
        assert "SDXL" in asset.title
        assert asset.file_size == len(fake_png)
        assert asset.content_type == "image/png"

    def test_flux_schnell_primary_selection_when_vram_sufficient(
        self, client, monkeypatch, db_session, stub_storage
    ):
        """When 20 GB free VRAM is available, priority-1 model flux-schnell is selected and executed."""
        total_bytes = int(24.0 * (1024 ** 3))
        free_bytes = int(20.0 * (1024 ** 3))
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": total_bytes,
                "free_bytes": free_bytes,
                "used_bytes": total_bytes - free_bytes,
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        fake_png = b"\x89PNG\r\n\x1a\nfake-flux-image-bytes"
        called_models = []

        class FakeFluxPipeline:
            def __call__(self, **kwargs):
                called_models.append("flux-schnell")
                return [fake_png]

        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda model_id, loader_handle=None: FakeFluxPipeline() if model_id == "flux-schnell" else None,
        )

        res = client.post("/api/generate/image?prompt=A+majestic+eagle&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert "flux-schnell" in called_models

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .first()
        )
        assert asset is not None
        assert "Flux" in asset.title
        assert asset.file_size == len(fake_png)
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_png


class TestParametersAndValidation:
    def test_parameter_validations(self, client):
        """Invalid scheduler, steps, scale, or denoising_strength must return HTTP 400."""
        # Unsafe scheduler identifier
        res = client.post("/api/generate/image?prompt=test&scheduler=bad;injection")
        assert res.status_code == 400
        assert "Invalid scheduler" in res.json()["detail"]

        # Unsupported scheduler name
        res = client.post("/api/generate/image?prompt=test&scheduler=unknown_sampler")
        assert res.status_code == 400
        assert "Unsupported scheduler" in res.json()["detail"]

        # Invalid steps (out of range)
        res = client.post("/api/generate/image?prompt=test&steps=0")
        assert res.status_code == 400
        assert "steps" in res.json()["detail"]

        # Invalid scale (negative)
        res = client.post("/api/generate/image?prompt=test&scale=-1.0")
        assert res.status_code == 400
        assert "scale" in res.json()["detail"]

        # Invalid denoising_strength (> 1.0)
        res = client.post("/api/generate/image?prompt=test&denoising_strength=1.5")
        assert res.status_code == 400
        assert "denoising_strength" in res.json()["detail"]

    def test_frontend_default_aspect_ratio_is_accepted(self, client):
        """Regression: GenerationPanel.tsx defaults aspectRatio to '16:9' and api.ts
        always sends it, so the shared safe-identifier pattern (no colon) was making
        the image tab's default request 400 before any provider was even consulted.
        """
        for ratio in ("16:9", "1:1", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9"):
            res = client.post(
                "/api/generate/image",
                params={"prompt": "test", "aspect_ratio": ratio, "provider": "local"},
            )
            assert res.status_code != 400, f"{ratio} unexpectedly rejected: {res.text}"

    def test_aspect_ratio_still_rejects_unsafe_identifiers(self, client):
        """Narrowing the validator to accept 'N:N' must not reopen injection."""
        for bad in ("16:9;rm -rf", "../etc/passwd", "16:9 OR 1=1", "$(id)", "a:b:c"):
            res = client.post(
                "/api/generate/image",
                params={"prompt": "test", "aspect_ratio": bad, "provider": "local"},
            )
            assert res.status_code == 400, f"{bad!r} unexpectedly accepted"
            assert "aspect_ratio" in res.json()["detail"]

    def test_scheduler_steps_scale_and_dimensions_forwarded(
        self, client, monkeypatch, stub_storage
    ):
        """features.md §3: steps, scale (guidance), scheduler, aspect_ratio, and denoising_strength
        are parsed, sanitized, and forwarded to the diffusion pipeline.
        """
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        captured_kwargs = {}

        class FakePipeline:
            scheduler_name = None

            def __call__(self, **kwargs):
                captured_kwargs.update(kwargs)
                return [b"\x89PNG\r\n\x1a\ncustom-params-png"]

        fake_pipe = FakePipeline()
        monkeypatch.setattr(model_registry, "load_model", lambda mid, **k: fake_pipe)

        res = client.post(
            "/api/generate/image"
            "?prompt=Portrait+of+a+knight"
            "&steps=42"
            "&scale=8.0"
            "&aspect_ratio=16:9"
            "&scheduler=euler"
            "&provider=local"
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["parameters"]["steps"] == 42
        assert body["parameters"]["scale"] == 8.0
        assert body["parameters"]["scheduler"] == "euler"

        # Forwarded to diffusers pipeline
        assert captured_kwargs["prompt"] == "Portrait of a knight"
        assert captured_kwargs["num_inference_steps"] == 42
        assert captured_kwargs["guidance_scale"] == 8.0
        assert captured_kwargs["width"] == 1024
        assert captured_kwargs["height"] == 576
        # Text-to-image diffusers pipelines reject `strength` outright
        assert "strength" not in captured_kwargs
        assert fake_pipe.scheduler_name == "euler"

    def test_denoising_strength_requires_a_source_image(self, client):
        """`strength` is an img2img-only kwarg. With no source-image input wired on
        this route yet, accepting the param and forwarding it would raise TypeError
        inside diffusers and surface as a bogus load_failed; accepting it and
        silently dropping it would be worse. Reject it explicitly instead.
        """
        res = client.post(
            "/api/generate/image",
            params={
                "prompt": "test",
                "denoising_strength": 0.65,
                "provider": "local",
            },
        )
        assert res.status_code == 400
        assert "denoising_strength" in res.json()["detail"]

    def test_txt2img_kwargs_never_contain_strength(self, client, monkeypatch, stub_storage):
        """Guard the fix: no `strength` key may reach a txt2img pipeline call."""
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        captured = {}

        class FakePipe:
            def __call__(self, **kwargs):
                captured.update(kwargs)
                return [b"\x89PNG\r\n\x1a\nx"]

        monkeypatch.setattr(model_registry, "load_model", lambda mid, **k: FakePipe())

        res = client.post(
            "/api/generate/image", params={"prompt": "t", "provider": "local"}
        )
        assert res.status_code == 200
        assert "strength" not in captured


class TestRoutePreservation:
    def test_gemini_cloud_branch_intact(self, client, db_session, monkeypatch, stub_storage):
        """Existing Gemini cloud branch remains unchanged when provider != 'local'."""
        set_secret("gemini", "AIza-test-image-key", db=db_session)
        fake_png = b"\x89PNG\r\n\x1a\ngemini-png-bytes"
        fake_b64 = base64.b64encode(fake_png).decode("ascii")

        def mock_post(url, *args, **kwargs):
            return httpx.Response(
                200,
                json={
                    "candidates": [
                        {
                            "content": {
                                "parts": [
                                    {
                                        "inlineData": {
                                            "mimeType": "image/png",
                                            "data": fake_b64,
                                        }
                                    }
                                ]
                            }
                        }
                    ]
                },
                request=httpx.Request("POST", url),
            )

        monkeypatch.setattr(httpx, "post", mock_post)

        res = client.post("/api/generate/image?prompt=Cloud+gemini+art&provider=gemini")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["filename"].startswith("gemini_img_")
        assert stub_storage["uploaded"][body["filename"]]["data"] == fake_png

    def test_colab_dispatch_branch_intact(self, client, stub_redis):
        """Existing Colab dispatch remains untouched when Colab worker is connected."""
        stub_redis.set("colab:connected", "true")
        import app.routers.generate as gen_router

        orig = gen_router.dispatch_gen_to_colab
        dispatched = {}

        def mock_dispatch(task_type, parameters, db, **kwargs):
            dispatched["task_type"] = task_type
            dispatched["parameters"] = parameters
            return {
                "status": "COMPLETED",
                "colab": True,
                "filename": "colab_generated.png",
                "url": "http://colab/image.png",
            }

        gen_router.dispatch_gen_to_colab = mock_dispatch
        try:
            res = client.post("/api/generate/image?prompt=Colab+test+art")
            assert res.status_code == 200
            assert res.json()["colab"] is True
            assert dispatched["task_type"] == "image_generation"
        finally:
            gen_router.dispatch_gen_to_colab = orig


class TestPipelineRuntimeFailure:
    def test_load_or_inference_error_returns_degraded_load_failed(self, client, monkeypatch):
        """If pipeline loading or execution raises an unexpected runtime exception,
        it surfaces the typed degraded contract with reason 'load_failed', never a 500 crash.
        """
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )

        def failing_loader(mid, **kwargs):
            raise RuntimeError("CUDA driver internal error")

        monkeypatch.setattr(model_registry, "load_model", failing_loader)

        res = client.post("/api/generate/image?prompt=Failing+run&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "CUDA driver internal error" in body["message"]


class TestReviewFindings:
    """Regression tests for the #100 code-review gate (blockers/major/minor)."""

    @pytest.mark.parametrize(
        "ratio",
        ["1:1", "16:9", "9:16", "4:3", "3:4", "3:2", "2:3", "21:9", "7:5", "100:33"],
    )
    def test_dimensions_are_vae_compatible(self, ratio):
        """Blocker/major: FLUX patchifies latents 2x2 after an 8x VAE downsample, so
        width and height must be multiples of 16. 680 (old 3:2 entry) is not.
        Also covers ratios not in the preset table, which must not silently
        degrade to a square 1024x1024.
        """
        from app.ml.image import get_dimensions_for_aspect_ratio

        width, height = get_dimensions_for_aspect_ratio(ratio)
        assert width % 16 == 0, f"{ratio} -> width {width} not divisible by 16"
        assert height % 16 == 0, f"{ratio} -> height {height} not divisible by 16"
        assert width >= 16 and height >= 16
        if ratio == "16:9":
            assert (width, height) == (1024, 576)
        if ratio == "1:1":
            assert (width, height) == (1024, 1024)
        if ratio != "1:1":
            assert (width, height) != (1024, 1024), "unknown ratio fell back to square"

    def test_flux_loader_never_resides_whole_model_in_vram(self, monkeypatch):
        """Blocker: FLUX in bfloat16 is ~34 GB resident. `pipe.to('cuda')` OOMs on
        every GPU at or below the 16 GB floor from decision #1. Model CPU offload
        is the only configuration that fits the roster's 13 GB figure.
        """
        import sys
        import types
        from unittest.mock import MagicMock

        from app.ml.image import make_diffusers_loader

        fake_torch = types.ModuleType("torch")
        fake_torch.bfloat16 = "bfloat16"
        fake_torch.float16 = "float16"
        fake_torch.float32 = "float32"
        fake_torch.cuda = MagicMock()
        fake_torch.cuda.is_available.return_value = True

        created = []

        class FakeFluxPipeline:
            @classmethod
            def from_pretrained(cls, *args, **kwargs):
                inst = cls()
                inst.to_calls = []
                inst.offload_calls = 0
                created.append(inst)
                return inst

            def to(self, *args, **kwargs):
                self.to_calls.append((args, kwargs))
                return self

            def enable_model_cpu_offload(self, *args, **kwargs):
                self.offload_calls += 1
                return None

        fake_diffusers = types.ModuleType("diffusers")
        fake_diffusers.FluxPipeline = FakeFluxPipeline
        fake_diffusers.StableDiffusionXLPipeline = FakeFluxPipeline

        monkeypatch.setitem(sys.modules, "torch", fake_torch)
        monkeypatch.setitem(sys.modules, "diffusers", fake_diffusers)

        make_diffusers_loader("flux-schnell")()

        assert len(created) == 1
        pipe = created[0]
        assert pipe.offload_calls == 1, "expected enable_model_cpu_offload()"
        assert pipe.to_calls == [], f"pipe.to() must not be used on CUDA: {pipe.to_calls}"

    def test_flux_skips_classical_schedulers(self, minor_guard=None):
        """Minor: FLUX is a flow-matching model. Installing DDIM/PNDM/etc. raises
        inside diffusers and would masquerade as load_failed."""
        from app.ml.image import apply_scheduler_to_pipeline

        class FakePipe:
            scheduler_name = None

        pipe = FakePipe()
        apply_scheduler_to_pipeline(pipe, "ddim", model_id="flux-schnell")
        assert pipe.scheduler_name is None, "incompatible scheduler was installed"

        apply_scheduler_to_pipeline(pipe, "flow_match", model_id="flux-schnell")
        assert pipe.scheduler_name == "flow_match"

        # SDXL is a classical diffusion model: DDIM stays valid there.
        pipe2 = FakePipe()
        apply_scheduler_to_pipeline(pipe2, "ddim", model_id="sdxl")
        assert pipe2.scheduler_name == "ddim"

    def test_generated_filenames_do_not_collide(self):
        """Nit: second-resolution names collide when two requests finish in the
        same second. The frontend regex only requires digits, so ns is safe."""
        from app.ml.image import build_image_filename

        names = {build_image_filename() for _ in range(200)}
        assert len(names) == 200, "filename collision detected"
        import re

        for n in names:
            assert re.fullmatch(r"gen_image_\d+\.png", n), n


class TestCodeRabbitFixesImage:
    """Tests for CodeRabbit PR #130 review findings (B3, B4)."""

    def test_b3_local_image_upload_failure_returns_degraded_and_does_not_persist(
        self, client, monkeypatch, db_session
    ):
        """B3 Call Site 1: Forced upload_object -> False in local image path returns degraded response and does not persist."""
        fake_png = b"\x89PNG\r\n\x1a\nfake-flux-image-bytes"
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: lambda **kw: [fake_png],
        )

        import app.ml.image as img_mod
        monkeypatch.setattr(img_mod, "upload_object", lambda *a, **kw: False)

        initial_count = db_session.query(MediaAsset).count()
        res = client.post("/api/generate/image?prompt=A+cyberpunk+city&provider=local")
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") != "COMPLETED", "Upload failure must not report COMPLETED"
        assert body.get("degraded") is True
        assert body.get("reason") == DegradedReason.LOAD_FAILED.value
        assert "storage" in body.get("message", "").lower() or "upload" in body.get("message", "").lower()
        assert db_session.query(MediaAsset).count() == initial_count, "MediaAsset must not be persisted on upload failure"

    def test_b3_gemini_image_upload_failure_returns_degraded_and_does_not_persist(
        self, client, monkeypatch, db_session
    ):
        """B3 Call Site 2: Forced upload_object -> False in cloud/Gemini image path returns degraded response and does not persist."""
        import base64
        import app.routers.generate as gen_router
        from app.services.secrets import set_secret

        set_secret("gemini", "test-gemini-key", db_session)

        fake_png_bytes = b"\x89PNG\r\n\x1a\ngemini-fake-png"
        fake_b64 = base64.b64encode(fake_png_bytes).decode("utf-8")
        gemini_response = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"inlineData": {"mimeType": "image/png", "data": fake_b64}}
                        ]
                    }
                }
            ]
        }
        monkeypatch.setattr(
            gen_router, "call_gemini_generate_content", lambda **kw: gemini_response
        )
        monkeypatch.setattr(gen_router, "upload_object", lambda *a, **kw: False)

        initial_count = db_session.query(MediaAsset).count()
        res = client.post("/api/generate/image?prompt=Cloud+gemini+art&provider=gemini")
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") != "COMPLETED", "Upload failure must not report COMPLETED"
        assert body.get("degraded") is True
        assert body.get("reason") == DegradedReason.LOAD_FAILED.value
        assert db_session.query(MediaAsset).count() == initial_count, "MediaAsset must not be persisted on upload failure"

    def test_b4_flux_defaults_used_when_no_explicit_steps_or_scale(
        self, client, monkeypatch, stub_storage
    ):
        """B4: FLUX.1-schnell defaults to 4 steps and 0.0 guidance scale when none specified."""
        captured_kwargs = {}

        class FakeFluxPipe:
            def __call__(self, **kwargs):
                captured_kwargs.update(kwargs)
                return [b"\x89PNG\r\n\x1a\nflux-png"]

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: FakeFluxPipe(),
        )

        res = client.post("/api/generate/image?prompt=Flux+defaults&provider=local")
        assert res.status_code == 200
        assert captured_kwargs.get("num_inference_steps") == 4, "FLUX.1-schnell must use 4 steps by default"
        assert captured_kwargs.get("guidance_scale") == 0.0, "FLUX.1-schnell must use guidance_scale=0.0 by default"

    def test_b4_flux_explicit_steps_and_scale_forwarded(
        self, client, monkeypatch, stub_storage
    ):
        """B4: Caller can explicitly override steps and scale for FLUX.1-schnell."""
        captured_kwargs = {}

        class FakeFluxPipe:
            def __call__(self, **kwargs):
                captured_kwargs.update(kwargs)
                return [b"\x89PNG\r\n\x1a\nflux-png"]

        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 4090",
                "total_bytes": int(24.0 * (1024 ** 3)),
                "free_bytes": int(20.0 * (1024 ** 3)),
                "used_bytes": int(4.0 * (1024 ** 3)),
                "total_gb": 24.0,
                "free_gb": 20.0,
                "used_gb": 4.0,
                "vram_percent": 16.7,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: FakeFluxPipe(),
        )

        res = client.post("/api/generate/image?prompt=Flux+custom&steps=8&scale=1.5&provider=local")
        assert res.status_code == 200
        assert captured_kwargs.get("num_inference_steps") == 8
        assert captured_kwargs.get("guidance_scale") == 1.5

    def test_b4_sdxl_defaults_preserved(
        self, client, monkeypatch, stub_storage
    ):
        """B4: SDXL path keeps 28 steps and 7.5 guidance scale defaults."""
        captured_kwargs = {}

        class FakeSDXLPipe:
            def __call__(self, **kwargs):
                captured_kwargs.update(kwargs)
                return [b"\x89PNG\r\n\x1a\nsdxl-png"]

        # 10 GB free VRAM: FLUX doesn't fit (needs 14GB), SDXL fits (needs 8GB)
        monkeypatch.setattr(
            vram_guard,
            "get_gpu_info",
            lambda device=0: {
                "available": True,
                "device_name": "NVIDIA RTX 3080",
                "total_bytes": int(10.0 * (1024 ** 3)),
                "free_bytes": int(10.0 * (1024 ** 3)),
                "used_bytes": 0,
                "total_gb": 10.0,
                "free_gb": 10.0,
                "used_gb": 0.0,
                "vram_percent": 0.0,
            },
        )
        monkeypatch.setattr(
            model_registry,
            "load_model",
            lambda mid, **k: FakeSDXLPipe(),
        )

        res = client.post("/api/generate/image?prompt=SDXL+defaults&provider=local")
        assert res.status_code == 200
        assert captured_kwargs.get("num_inference_steps") == 28, "SDXL must keep 28 steps by default"
        assert captured_kwargs.get("guidance_scale") == 7.5, "SDXL must keep guidance_scale=7.5 by default"

