"""Tests for the skin-enhance endpoint, engines, and preset table (#112).

Tests:
1. Safe import: app.ml.skin_enhancer imports with no torch / gfpgan / facexlib / diffusers.
2. Flexible preset table is the verbatim Magnific `optimized_for` set and is a pure function.
3. Slider mapping: skin_detail is mode-aware, sharpen/smart_grain are 0..100 post-filters.
4. Request validation refuses out-of-range / non-integer / non-finite / unknown values with
   HTTP 400, and accepts a subfolder asset key while still refusing traversal.
5. Video input is refused with HTTP 400 and a named reason (#111 decision 6).
6. No face detected is refused with HTTP 400 and a reason that says so (#111 decision 4);
   an out-of-canvas detector box is clamped in, and one with too little visible area is
   still dropped.
7. Honest degradation: no GPU / insufficient VRAM / engine failure / storage or catalog
   write failure return the typed envelope at HTTP 200, never a 500 and never placeholder
   bytes (#111 decision 8), and never a filename for an object with no catalog row.
8. Derivative output lands on a sanitised skin_enhanced/<stem>_<token>.png with
   source_path lineage and a unique token, so two concurrent jobs on one source cannot
   overwrite (#96).
9. Background outside every face box is pixel-identical to the source (face-crop only),
   and source bytes come from storage only - never the server's local filesystem.
10. Engine loaders build *working* adapters with heavy imports confined to the closure:
    each test calls the adapter's method, not just the constructor. The fakes they use are
    the contract mirrors in tests/test_skin_engine_contracts.py, not locally invented
    stand-ins - the distinction is the whole point of the #138 fix.
11. Lock scope: admission, model load, inference and post-filters run inside
    INFERENCE_LOCK; the storage upload does not.

The real third-party API contracts live in tests/test_skin_engine_contracts.py. They used
to be implied by the fakes in this file, which is how every mode of this endpoint shipped
non-functional behind a green suite.
"""

import io
import re
import sys
import types
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageFilter

from app.ml.contracts import DegradedReason, FallbackTier
from app.ml.guard import vram_guard
from app.ml.registry import model_registry
from app.models import MediaAsset


REPO_ROOT = Path(__file__).resolve().parents[2]


def _gpu(free_gb: float, total_gb: float = 24.0):
    """Full get_gpu_info dict shape, as guard.get_gpu_info returns it."""
    total = int(total_gb * (1024 ** 3))
    free = int(free_gb * (1024 ** 3))
    return {
        "available": True,
        "device_name": "NVIDIA RTX 4090",
        "total_bytes": total,
        "free_bytes": free,
        "used_bytes": total - free,
        "total_gb": total_gb,
        "free_gb": free_gb,
        "used_gb": round(total_gb - free_gb, 2),
        "vram_percent": round(((total_gb - free_gb) / total_gb) * 100, 1),
    }


NO_GPU = {
    "available": False,
    "device_name": None,
    "total_bytes": 0,
    "free_bytes": 0,
    "used_bytes": 0,
    "total_gb": 0.0,
    "free_gb": 0.0,
    "used_gb": 0.0,
    "vram_percent": 0.0,
}


def png_bytes(size=(96, 96), color=(120, 90, 60)) -> bytes:
    """A real, decodable PNG so the executor's decode step is genuinely exercised."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def gradient_png(width=64, height=64) -> bytes:
    """A deterministic per-pixel gradient: any pasted-back edit becomes visible."""
    arr = np.zeros((height, width, 3), dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            arr[y, x] = ((x * 4) % 256, (y * 4) % 256, ((x + y) * 2) % 256)
    buf = io.BytesIO()
    Image.fromarray(arr).save(buf, format="PNG")
    return buf.getvalue()


class FakeFaceEngine:
    """Duck-typed stand-in for the real GFPGAN / DiffBIR adapter.

    Records every restore call so tests can assert the mode-aware parameter mapping,
    and rewrites each crop to a flat colour so a paste-back is trivially observable.
    """

    def __init__(self, faces=((8, 8, 56, 56),), raises=None):
        self._faces = list(faces)
        self._raises = raises
        self.restore_calls = []
        self.crop_sizes = []
        self.detect_calls = 0

    def detect_faces(self, image):
        self.detect_calls += 1
        return list(self._faces)

    def restore_face(self, crop, **params):
        if self._raises is not None:
            raise self._raises
        self.restore_calls.append(dict(params))
        self.crop_sizes.append(crop.size)
        return Image.new("RGB", crop.size, (255, 0, 0))


class FakeBatchFaceEngine:
    """Duck-typed stand-in for an engine that can restore a whole request in one call.

    DiffBIR is the only real one: its CLI takes a *folder*, and every invocation loads
    SwinIR + the conditional diffusion model + SD 2.1 from scratch, so N per-face calls
    on a group shot mean N model loads. This fake exists so the executor's *dispatch* can
    be asserted without a subprocess, a GPU or a DiffBIR checkout.

    `drop_results` is the dishonest engine: it hands back fewer images than it was given,
    which is what the executor's own guard is there to catch.
    """

    def __init__(self, faces=((8, 8, 56, 56),), raises=None, drop_results=0):
        self._faces = list(faces)
        self._raises = raises
        self._drop_results = drop_results
        self.batch_calls = []
        self.restore_calls = []

    def detect_faces(self, image):
        return list(self._faces)

    def restore_face(self, crop, **params):
        self.restore_calls.append(dict(params))
        return Image.new("RGB", crop.size, (255, 0, 0))

    def restore_faces(self, crops, **params):
        if self._raises is not None:
            raise self._raises
        self.batch_calls.append({"params": dict(params), "sizes": [c.size for c in crops]})
        return [Image.new("RGB", crop.size, (0, 255, 0)) for crop in crops][
            : len(crops) - self._drop_results
        ]


def _install_source(storage, name="portrait.png", data=None):
    storage["uploaded"][name] = {
        "data": data if data is not None else png_bytes(),
        "content_type": "image/png",
    }
    return name


def _install_engine(monkeypatch, engine, gpu_free_gb=24.0):
    monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: _gpu(gpu_free_gb))
    monkeypatch.setattr(model_registry, "load_model", lambda mid, **kw: engine)
    return engine


class TestSafeImport:
    def test_module_imports_without_torch_or_enhancer_packages(self, monkeypatch):
        """The app must boot on a machine with no torch, gfpgan, facexlib or diffusers,
        so none of them may be imported at module scope."""
        import importlib

        saved = sys.modules.pop("app.ml.skin_enhancer", None)
        saved_parent = getattr(sys.modules.get("app.ml"), "skin_enhancer", None)

        try:
            for name in ("torch", "gfpgan", "facexlib", "diffusers"):
                monkeypatch.setitem(sys.modules, name, None)

            mod = importlib.import_module("app.ml.skin_enhancer")
            assert hasattr(mod, "run_skin_enhancement")
            assert hasattr(mod, "build_skin_filename")
            assert hasattr(mod, "FLEXIBLE_PRESETS")
        finally:
            if saved is not None:
                sys.modules["app.ml.skin_enhancer"] = saved
            if "app.ml" in sys.modules and saved_parent is not None:
                setattr(sys.modules["app.ml"], "skin_enhancer", saved_parent)


class TestFlexiblePresetTable:
    def test_preset_names_are_verbatim_magnific_optimized_for(self):
        """#111 decision 3: the five Magnific `optimized_for` names ship unrenamed
        because this map is explicitly chasing Magnific parity."""
        from app.ml.skin_enhancer import FLEXIBLE_PRESETS

        assert set(FLEXIBLE_PRESETS) == {
            "enhance_skin",
            "improve_lighting",
            "enhance_everything",
            "transform_to_real",
            "no_make_up",
        }

    def test_every_preset_is_a_prompt_guidance_and_noise_tuple(self):
        """#111 decision 3: each preset is hardcoded (prompt, guidance-scale,
        condition-noise). No captioner, so the table is assertable without a GPU."""
        from app.ml.skin_enhancer import FLEXIBLE_PRESETS

        for name, preset in FLEXIBLE_PRESETS.items():
            assert preset["prompt"].strip(), f"{name} has an empty prompt"
            assert preset["guidance_scale"] > 0.0, f"{name} guidance must be positive"
            assert 0.0 <= preset["condition_noise"] <= 1.0, f"{name} noise out of range"
            assert preset["description"].strip(), f"{name} needs a UI description"

    def test_default_preset_is_enhance_skin(self):
        """#111 decision 3: enhance_skin is the documented default."""
        from app.ml.skin_enhancer import DEFAULT_FLEXIBLE_PRESET, get_flexible_preset

        assert DEFAULT_FLEXIBLE_PRESET == "enhance_skin"
        assert get_flexible_preset(None)["prompt"] == get_flexible_preset(
            "enhance_skin"
        )["prompt"]

    def test_get_flexible_preset_is_pure(self):
        """A static table accessed through a pure function: same input, same output,
        no I/O, no registry access, no GPU."""
        from app.ml.skin_enhancer import get_flexible_preset

        assert get_flexible_preset("improve_lighting") == get_flexible_preset(
            "improve_lighting"
        )

    def test_unknown_preset_raises_with_allowed_names(self):
        """An unrecognized preset must name the allowed set, not silently fall back."""
        from app.ml.skin_enhancer import get_flexible_preset

        with pytest.raises(ValueError) as exc:
            get_flexible_preset("remove_all_wrinkles")
        message = str(exc.value)
        assert "remove_all_wrinkles" in message
        for name in ("enhance_skin", "improve_lighting", "no_make_up"):
            assert name in message


class TestSliderMapping:
    def test_skin_detail_default_is_80(self):
        """#111 decision 4: the wire default for skin_detail is 80."""
        from app.ml.skin_enhancer import DEFAULT_SKIN_DETAIL
        from app.routers.skin_enhance import SkinEnhanceRequest

        assert DEFAULT_SKIN_DETAIL == 80
        assert SkinEnhanceRequest(image_path="a.png").skin_detail == 80

    def test_skin_detail_in_faithful_is_texture_retention(self):
        """#111 decision 2: in Faithful, skin_detail is a post-filter
        texture-retention strength, not a diffusion parameter."""
        from app.ml.skin_enhancer import map_skin_detail_to_texture_retention

        assert map_skin_detail_to_texture_retention(0) == 0.0
        assert map_skin_detail_to_texture_retention(100) == 1.0
        assert map_skin_detail_to_texture_retention(80) == pytest.approx(0.8)
        values = [map_skin_detail_to_texture_retention(v) for v in range(0, 101)]
        assert values == sorted(values), "mapping must be monotonic"

    def test_skin_detail_in_creative_and_flexible_is_guidance_scale(self):
        """#111 decision 2: in Creative/Flexible, skin_detail maps to DiffBIR's
        guidance scale, anchored so the default 80 reproduces the preset's own value."""
        from app.ml.skin_enhancer import map_skin_detail_to_guidance

        assert map_skin_detail_to_guidance(80, 3.0) == pytest.approx(3.0)
        assert map_skin_detail_to_guidance(100, 3.0) == pytest.approx(3.75)
        # 0 means "off"; DiffBIR's guidance floor is 1.0 (no meaningful prompt pull),
        # so the derived value floors there. The *input* range is what must 400.
        assert map_skin_detail_to_guidance(0, 3.0) == pytest.approx(1.0)
        values = [map_skin_detail_to_guidance(v, 3.0) for v in range(0, 101)]
        assert values == sorted(values), "mapping must be monotonic"

    def test_skin_detail_default_reproduces_each_preset_guidance(self):
        """At the default slider position the preset's own guidance must survive,
        otherwise the preset table's guidance column would be dead weight."""
        from app.ml.skin_enhancer import (
            FLEXIBLE_PRESETS,
            map_skin_detail_to_guidance,
        )

        for name, preset in FLEXIBLE_PRESETS.items():
            assert map_skin_detail_to_guidance(80, preset["guidance_scale"]) == pytest.approx(
                preset["guidance_scale"]
            ), f"{name} guidance is not reachable from the default slider"

    def test_sharp_and_grain_map_to_unipolar_zero_to_hundred(self):
        """#111 decision 2/4: sharpen and smart_grain are PIL post-filters applied in
        every mode, unipolar 0 (off) to 100 (max). There is no negative sharpen."""
        from app.ml.skin_enhancer import (
            SLIDER_MAX,
            SLIDER_MIN,
            map_sharpen_to_percent,
            map_smart_grain_to_sigma,
        )

        assert (SLIDER_MIN, SLIDER_MAX) == (0, 100)
        assert map_sharpen_to_percent(0) == 0.0
        assert map_sharpen_to_percent(100) > 0.0
        assert map_smart_grain_to_sigma(0) == 0.0
        assert map_smart_grain_to_sigma(100) > 0.0
        # Unipolar: doubling the slider doubles the effect, no sign flip anywhere.
        assert map_sharpen_to_percent(50) == pytest.approx(map_sharpen_to_percent(100) / 2)
        assert map_smart_grain_to_sigma(50) == pytest.approx(map_smart_grain_to_sigma(100) / 2)


class TestPostFilters:
    def test_zero_post_filters_are_a_pixel_exact_identity(self):
        """Magnific's 0 means "off" for every post-filter, so at 0 the image must come
        back bit-identical rather than through a lossy no-op filter."""
        from app.ml.skin_enhancer import apply_skin_post_filters

        src = Image.fromarray(np.random.RandomState(7).randint(0, 255, (32, 32, 3), dtype=np.uint8))
        out = apply_skin_post_filters(src, sharpen=0, smart_grain=0)
        assert np.array_equal(np.array(out), np.array(src))

    def test_sharpen_increases_edge_contrast(self):
        """sharpen must actually sharpen, not just alter pixel values."""
        from app.ml.skin_enhancer import apply_skin_post_filters

        base = np.zeros((32, 32, 3), dtype=np.uint8)
        base[:, 16:] = 200
        src = Image.fromarray(base)

        out = apply_skin_post_filters(src, sharpen=100, smart_grain=0)
        arr = np.array(out).astype(float)
        src_arr = np.array(src).astype(float)
        src_edge = abs(np.diff(src_arr, axis=1)).mean()
        out_edge = abs(np.diff(arr, axis=1)).mean()
        assert out_edge > src_edge, "sharpen=100 must widen the edge transition"

    def test_smart_grain_is_zero_mean_and_does_not_shift_exposure(self):
        """Grain simulates film, it does not brighten or darken the image."""
        from app.ml.skin_enhancer import apply_skin_post_filters

        base = np.full((64, 64, 3), 128, dtype=np.uint8)
        src = Image.fromarray(base)
        out = np.array(apply_skin_post_filters(src, sharpen=0, smart_grain=100)).astype(float)
        assert abs(out.mean() - 128.0) < 3.0, "grain must stay zero-mean"
        assert out.std() > 0.5, "grain=100 must actually add noise"

    def test_texture_retention_at_zero_is_identity(self):
        """Faithful-mode skin_detail=0 must not post-process the GAN output at all."""
        from app.ml.skin_enhancer import apply_texture_retention

        src = Image.fromarray(np.random.RandomState(3).randint(0, 255, (24, 24, 3), dtype=np.uint8))
        out = apply_texture_retention(src, src, strength=0.0)
        assert np.array_equal(np.array(out), np.array(src))

    def test_texture_retention_reinjects_detail_from_the_source_crop(self):
        """skin_detail in Faithful exists to put the *source's* micro-texture back: the
        GAN reconstructs a plausible face, which means it averages away pores. A local
        unsharp of the already-smoothed output cannot recover them, so the high-pass
        band is taken from the source crop and added to the restored one."""
        from app.ml.skin_enhancer import TEXTURE_RADIUS, apply_texture_retention

        # A 2px checkerboard is pure high frequency - exactly what a smoothing
        # generator destroys and what texture retention is supposed to bring back.
        checker = np.full((64, 64, 3), 128, dtype=np.uint8)
        checker[::2, ::2] = 176
        checker[1::2, 1::2] = 80
        source = Image.fromarray(checker)
        # What the engine hands back: the same crop, low frequencies only.
        restored = source.filter(ImageFilter.GaussianBlur(radius=TEXTURE_RADIUS))

        def high_freq_energy(img):
            a = np.asarray(img, dtype=float)
            return abs(a - a.mean()).mean()

        assert high_freq_energy(restored) < high_freq_energy(source) * 0.5, (
            "precondition: the restored crop really is the smoothed one"
        )
        out = apply_texture_retention(source, restored, 1.0)
        assert high_freq_energy(out) > high_freq_energy(restored) * 2.0, (
            "the source's texture must come back onto the restored crop"
        )

    def test_texture_retention_reads_the_source_not_the_restored_crop(self):
        """The decisive case: with a flat base, unsharp-masking the base itself can only
        return flat. Any texture in the output therefore came from the source crop."""
        from app.ml.skin_enhancer import apply_texture_retention

        stripes = np.zeros((64, 64, 3), dtype=np.uint8)
        stripes[:, ::2] = 220
        stripes[:, 1::2] = 40
        source = Image.fromarray(stripes)
        flat = Image.new("RGB", (64, 64), (128, 128, 128))

        out = apply_texture_retention(source, flat, 1.0)
        arr = np.asarray(out, dtype=float)
        assert arr.std() > 10.0, "texture must be re-injected from the source crop"
        # The stripes are vertical, so columns alternate and rows do not.
        assert abs(np.diff(arr, axis=1)).mean() > abs(np.diff(arr, axis=0)).mean()

        # And at strength 0 it is still a pure no-op on the restored crop.
        assert np.array_equal(
            np.array(apply_texture_retention(source, flat, 0.0)), np.array(flat)
        )


class TestRequestValidation:
    def test_unknown_mode_is_refused(self, client, stub_storage):
        """An unrecognized mode must be named, never silently treated as faithful."""
        _install_source(stub_storage)
        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "magic"}
        )
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "magic" in detail
        assert "faithful" in detail and "creative" in detail and "flexible" in detail

    def test_out_of_range_slider_is_400_not_a_silent_clamp(self, client, stub_storage):
        """#111 decision 4: a clamped sharpen=999 produces output the user cannot explain,
        so out-of-range values are refused with 400 and an actionable message."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        for field in ("sharpen", "smart_grain", "skin_detail"):
            for value in (-1, 101, 1000):
                res = client.post(
                    "/api/skin-enhance",
                    json={"image_path": "portrait.png", field: value},
                )
                assert res.status_code == 400, f"{field}={value} was not refused"
                detail = res.json()["detail"]
                assert field in detail
                assert "0" in detail and "100" in detail

    def test_fractional_slider_is_refused(self, client, stub_storage):
        """The wire format is a 0-100 *integer* range; silently truncating 12.5 to 12
        would be a silent clamp by another name."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "sharpen": 12.5}
        )
        assert res.status_code == 400
        assert "sharpen" in res.json()["detail"]

    def test_non_finite_slider_is_400_not_500(self, client, stub_storage):
        """`NaN` and `Infinity` are emitted by Python's json.dumps and `1e999` is
        plain JSON that parses to `inf`; Starlette's parser accepts all three, then
        `int(float('nan'))` / `int(float('inf'))` raise rather than return. An
        unhandled ValueError/OverflowError there answers 500 for what is plainly the
        caller's fault; #111 decision 4 says 400. Sent as a raw body because httpx
        refuses to *encode* a non-finite float - a real client does not."""
        import json as _json

        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        payloads = [
            {"sharpen": _json.dumps(float("nan"))},
            {"sharpen": _json.dumps(float("inf"))},
            {"smart_grain": _json.dumps(float("-inf"))},
            {"skin_detail": "1e999"},
            {"skin_detail": "-1e999"},
        ]
        for extra in payloads:
            field = next(iter(extra))
            body = '{"image_path": "portrait.png", ' + ", ".join(
                f'"{k}": {v}' for k, v in extra.items()
            ) + "}"
            res = client.post(
                "/api/skin-enhance",
                content=body,
                headers={"content-type": "application/json"},
            )
            assert res.status_code == 400, f"{body} answered {res.status_code}"
            detail = res.json()["detail"]
            assert field in detail
            assert "whole number" in detail or "out of range" in detail

        # A finite fractional value must keep its own distinct message, so the
        # non-finite branch did not swallow the ordinary case.
        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "sharpen": 12.5}
        )
        assert res.status_code == 400
        assert "whole number" in res.json()["detail"]

    def test_subfolder_asset_key_is_accepted_and_traversal_is_still_refused(
        self, client, monkeypatch, stub_storage
    ):
        """#111's chosen integration is a per-asset action in FileManager, which is a
        directory browser: the keys users click are `upscaled/...`, `uploads/...`,
        `processed/...`. A validator that forbids `/` refuses every one of them, so
        this pins slashes as allowed while traversal stays refused."""
        stub_storage["uploaded"]["upscaled/foo.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        _install_engine(monkeypatch, FakeFaceEngine())

        res = client.post("/api/skin-enhance", json={"image_path": "upscaled/foo.png"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["source_path"] == "upscaled/foo.png"
        assert body["filename"].startswith("skin_enhanced/foo_")

        for bad in ("../../etc/passwd", "/etc/passwd", "..\\secret.png", "upscaled/../.."):
            res = client.post("/api/skin-enhance", json={"image_path": bad})
            assert res.status_code == 400, f"{bad!r} was accepted"

    def test_preset_outside_flexible_is_refused(self, client, stub_storage):
        """`optimized_for` is a Flexible-only surface. Accepting it in Faithful and
        dropping it would leave the user believing the preset applied."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        for mode in ("faithful", "creative"):
            res = client.post(
                "/api/skin-enhance",
                json={"image_path": "portrait.png", "mode": mode, "preset": "no_make_up"},
            )
            assert res.status_code == 400
            detail = res.json()["detail"]
            assert "flexible" in detail.lower()
            assert "no_make_up" in detail

    def test_unknown_preset_in_flexible_is_refused(self, client, stub_storage):
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        res = client.post(
            "/api/skin-enhance",
            json={
                "image_path": "portrait.png",
                "mode": "flexible",
                "preset": "make_me_model",
            },
        )
        assert res.status_code == 400
        assert "make_me_model" in res.json()["detail"]

    def test_unsafe_image_path_is_refused(self, client, stub_storage):
        """image_path becomes a storage key, so traversal must be refused up front."""
        for bad in ("../../etc/passwd", "/etc/passwd", "..\\secret.png"):
            res = client.post("/api/skin-enhance", json={"image_path": bad})
            assert res.status_code == 400, f"{bad!r} was accepted"

    def test_missing_image_path_is_a_client_error(self, client):
        """image_path is required, so an empty body never reaches the enhancer."""
        res = client.post("/api/skin-enhance", json={})
        assert res.status_code in (400, 422)
        assert "image_path" in res.text


class TestVideoRefusal:
    def test_video_asset_is_refused_with_a_named_reason(self, client, db_session, stub_storage):
        """#111 decision 6: video is out of scope for v1 and must be refused with a named
        reason, not silently ignored - a user with a portrait video must be told."""
        stub_storage["uploaded"]["clip.mp4"] = {
            "data": b"\x00\x00\x00\x18ftypmp42",
            "content_type": "video/mp4",
        }
        db_session.add(
            MediaAsset(
                title="clip",
                file_path="clip.mp4",
                file_size=16,
                content_type="video/mp4",
            )
        )
        db_session.commit()

        res = client.post("/api/skin-enhance", json={"image_path": "clip.mp4"})
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "video_input_not_supported" in detail
        assert "image" in detail.lower()

    def test_video_path_without_a_catalog_row_is_still_refused(self, client, stub_storage):
        """The content-type check cannot depend on a MediaAsset row existing."""
        stub_storage["uploaded"]["clip.mov"] = {"data": b"\x00", "content_type": "video/quicktime"}
        res = client.post("/api/skin-enhance", json={"image_path": "clip.mov"})
        assert res.status_code == 400
        assert "video_input_not_supported" in res.json()["detail"]


class TestInputResolution:
    def test_missing_source_is_refused(self, client, stub_storage):
        res = client.post("/api/skin-enhance", json={"image_path": "nope.png"})
        assert res.status_code == 400
        assert "nope.png" in res.json()["detail"]

    def test_undecodable_source_is_refused(self, client, stub_storage):
        stub_storage["uploaded"]["broken.png"] = {
            "data": b"this is definitely not a png",
            "content_type": "image/png",
        }
        res = client.post("/api/skin-enhance", json={"image_path": "broken.png"})
        assert res.status_code == 400
        assert "broken.png" in res.json()["detail"]

    def test_source_is_never_read_from_the_local_filesystem(
        self, client, monkeypatch, stub_storage, tmp_path
    ):
        """`image_path` is caller-controlled, so a `os.path.isfile(image_path)` +
        `open(image_path)` fallback turns this endpoint into an arbitrary local file
        reader relative to the server's CWD - and it can then be re-uploaded to
        storage as a PNG derivative. app/routers/upscale.py loads strictly from
        storage; this must too."""
        import app.ml.skin_enhancer as skin_mod

        (tmp_path / "portrait.png").write_bytes(png_bytes())
        monkeypatch.chdir(tmp_path)
        monkeypatch.setattr(skin_mod, "download_object", lambda *a, **k: None)

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 400, f"local file was read instead of a 400: {res.text}"
        assert "source_not_found" in res.json()["detail"]
        assert stub_storage["uploaded"] == {}, "nothing may be written to storage"


class TestNoFaceRefusal:
    def test_no_face_returns_400_saying_so(self, client, monkeypatch, stub_storage):
        """#111 decision 4: face-crop only means a picture with no face has nothing to
        enhance. Returning 200 with an untouched copy would be a lie."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        _install_engine(monkeypatch, FakeFaceEngine(faces=[]))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 400
        detail = res.json()["detail"]
        assert "no_face_detected" in detail
        assert "face" in detail.lower()

    def test_tiny_faces_are_not_counted_as_enhanceable(
        self, client, monkeypatch, stub_storage
    ):
        """Below the alignment floor there are no usable landmarks, so such a box is
        not a face we can enhance; it must not be silently passed to the engine."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(size=(64, 64)),
            "content_type": "image/png",
        }
        engine = _install_engine(monkeypatch, FakeFaceEngine(faces=[(0, 0, 4, 4)]))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 400
        assert "no_face_detected" in res.json()["detail"]
        assert engine.restore_calls == []


class TestFaceBoxClamping:
    """S3FD returns boxes a few pixels outside the canvas for tight crops and selfies
    (x0 = -4, y1 = height + 2). Dropping those turns a valid portrait into a
    `no_face_detected` 400, so they are clamped into the canvas and the alignment
    floor is re-applied to the clamped box."""

    def test_box_overhanging_the_canvas_is_clamped_and_enhanced(
        self, client, monkeypatch, stub_storage
    ):
        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(size=(64, 64)),
            "content_type": "image/png",
        }
        engine = _install_engine(monkeypatch, FakeFaceEngine(faces=[(-4, -6, 60, 70)]))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["faces_enhanced"] == 1
        assert body["faces_skipped"] == 0
        assert body["face_boxes"] == [[0, 0, 60, 64]]
        # The engine is handed the clamped crop, and paste-back stays in-canvas.
        assert engine.crop_sizes == [(60, 64)]

    def test_box_that_clamps_below_the_floor_is_still_dropped(
        self, client, monkeypatch, stub_storage
    ):
        """Clamping is not a bypass of MIN_FACE_DIMENSION: a box whose visible part is
        20px wide is still not alignable, so it is dropped and counted, not restored."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(size=(64, 64)),
            "content_type": "image/png",
        }
        engine = _install_engine(monkeypatch, FakeFaceEngine(faces=[(-40, 0, 20, 40)]))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 400
        assert "no_face_detected" in res.json()["detail"]
        assert engine.restore_calls == []

    def test_fully_outside_the_canvas_box_is_dropped(self, client, monkeypatch, stub_storage):
        """A box entirely off-canvas clamps to zero area; it must not come back as a
        0x0 crop handed to the engine."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(size=(64, 64)),
            "content_type": "image/png",
        }
        engine = _install_engine(monkeypatch, FakeFaceEngine(faces=[(100, 100, 140, 140)]))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 400
        assert engine.restore_calls == []


class TestDegradedContract:
    def test_no_gpu_returns_degraded_envelope(self, client, monkeypatch, stub_storage):
        """#111 decision 8: no GPU returns the labeled degraded envelope at HTTP 200
        exactly like run_local_image_generation - never a 500, never placeholder bytes."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: NO_GPU)

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.NO_GPU.value
        assert body["fallback_tier"] == FallbackTier.REFUSAL.value
        assert "filename" not in body
        assert "Mock" not in body["message"]

    def test_insufficient_vram_returns_degraded_envelope(self, client, monkeypatch, stub_storage):
        """DiffBIR needs 8 GB plus overhead; 2 GB free must refuse, not attempt the load."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        _install_engine(monkeypatch, FakeFaceEngine(), gpu_free_gb=2.0)

        res = client.post(
            "/api/skin-enhance",
            json={"image_path": "portrait.png", "mode": "creative"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.INSUFFICIENT_VRAM.value
        assert body["model_id"] == "diffbir"
        assert body["vram_available_gb"] == 2.0
        assert body["vram_required_gb"] > 8.0

    def test_engine_failure_returns_degraded_load_failed(
        self, client, monkeypatch, stub_storage, db_session
    ):
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        _install_engine(
            monkeypatch, FakeFaceEngine(raises=RuntimeError("CUDA driver internal error"))
        )
        before = db_session.query(MediaAsset).count()

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "CUDA driver internal error" in body["message"]
        assert db_session.query(MediaAsset).count() == before

    def test_load_failure_returns_degraded_load_failed(self, client, monkeypatch, stub_storage):
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        monkeypatch.setattr(vram_guard, "get_gpu_info", lambda device=0: _gpu(24.0))

        def failing_loader(mid, **kwargs):
            raise RuntimeError("gfpgan weights not downloaded")

        monkeypatch.setattr(model_registry, "load_model", failing_loader)

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value

    def test_upload_failure_degrades_and_persists_nothing(
        self, client, monkeypatch, stub_storage, db_session
    ):
        """Same rule the #100 review gate applied to /api/generate/image: a storage
        failure must never report COMPLETED and must never leave an orphan asset."""
        import app.ml.skin_enhancer as skin_mod

        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        _install_engine(monkeypatch, FakeFaceEngine())
        monkeypatch.setattr(skin_mod, "upload_object", lambda *a, **kw: False)
        before = db_session.query(MediaAsset).count()

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") != "COMPLETED"
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert db_session.query(MediaAsset).count() == before

    def test_catalog_write_failure_degrades_and_withholds_the_filename(
        self, client, monkeypatch, stub_storage, db_session
    ):
        """The object is already in storage by the time the MediaAsset insert runs, so
        a failed commit must not be reported as COMPLETED: the caller would be handed a
        filename and a URL for an object with no catalog row, and the `source_path`
        lineage #111 decision 7 requires would be silently absent. Degraded envelope,
        no filename."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        _install_engine(monkeypatch, FakeFaceEngine())

        def boom():
            raise RuntimeError("catalog write failed")

        monkeypatch.setattr(db_session, "commit", boom)
        before = db_session.query(MediaAsset).count()

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body.get("status") != "COMPLETED"
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "catalog write failed" in body["message"]
        assert "filename" not in body
        assert "url" not in body
        assert db_session.query(MediaAsset).count() == before

    def test_storage_io_runs_outside_the_inference_lock(
        self, client, monkeypatch, stub_storage
    ):
        """INFERENCE_LOCK exists so registry eviction cannot run mid-inference
        (app/ml/guard.py depends on that). It does not need to cover MinIO round
        trips: a synchronous Creative run is budgeted at up to 60s, and holding the
        lock across download/encode/upload blocks every other image and audio
        inference request for the whole of it. Inference itself must stay inside the
        lock - this test asserts both halves, so the probe cannot pass vacuously."""
        import threading

        import app.ml.skin_enhancer as skin_mod
        from app.ml.registry import INFERENCE_LOCK

        observed = {}

        def locked_by_the_request():
            """True when a *different* thread cannot take the lock, i.e. the request
            thread holds it. A plain acquire() on the same thread would re-enter an
            RLock and answer yes either way."""
            outcome = {}

            def probe():
                acquired = INFERENCE_LOCK.acquire(blocking=False)
                outcome["held"] = not acquired
                if acquired:
                    INFERENCE_LOCK.release()

            thread = threading.Thread(target=probe)
            thread.start()
            thread.join(timeout=10)
            return outcome.get("held")

        class ProbingEngine(FakeFaceEngine):
            def restore_face(self, crop, **params):
                observed["during_inference"] = locked_by_the_request()
                return super().restore_face(crop, **params)

        real_upload = skin_mod.upload_object

        def probing_upload(data, object_name, content_type="application/octet-stream"):
            observed["during_upload"] = locked_by_the_request()
            return real_upload(data, object_name, content_type=content_type)

        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        _install_engine(monkeypatch, ProbingEngine())
        monkeypatch.setattr(skin_mod, "upload_object", probing_upload)

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        assert res.json()["status"] == "COMPLETED"
        assert observed["during_inference"] is True, (
            "inference must stay inside INFERENCE_LOCK; eviction may not run here"
        )
        assert observed["during_upload"] is False, (
            "the storage upload must not run while INFERENCE_LOCK is held"
        )

    def test_new_modules_carry_no_forbidden_mock_strings(self):
        """#111 decision 8: the runtime validator in app/ml/contracts.py raises on any
        message matching r"mock\\b.*\\bbytes\\b", and the grep guards in
        test_localml_audio.py / test_localml_video.py scan backend/app/**/*.py. The two
        modules this ticket adds must be clean. (Scoped to the new modules on purpose:
        two pre-existing docstrings in generate.py and contracts.py already match the
        regex as English prose, and the validator only ever runs on response bodies.)"""
        from app.ml.contracts import _MOCK_BYTES_RE

        offenders = []
        for name in ("app/ml/skin_enhancer.py", "app/routers/skin_enhance.py"):
            path = REPO_ROOT / "backend" / name
            assert path.exists(), f"{name} is missing"
            for line in path.read_text(encoding="utf-8").splitlines():
                if _MOCK_BYTES_RE.search(line):
                    offenders.append(f"{name}: {line.strip()}")
        assert not offenders, f"forbidden mock byte strings: {offenders}"


class TestDerivativeOutput:
    def test_output_stem_is_sanitised(self):
        """The output stem comes from the caller's key, so it is untrusted: a source of
        `..` would otherwise mint the key `skin_enhanced/.._<token>.png`. Anything
        outside `[A-Za-z0-9._-]` becomes `_`, leading/trailing dots and underscores are
        stripped, and an all-punctuation stem falls back to `portrait` so the key is
        never a bare `skin_enhanced/_<token>.png`."""
        from app.ml.skin_enhancer import build_skin_filename

        cases = {
            "..": "portrait",
            "../..": "portrait",
            ".": "portrait",
            "...": "portrait",
            "._.": "portrait",
            "upscaled/photo_2x_abc.png": "photo_2x_abc",
            "upscaled/my portrait.png": "my_portrait",
            # Stripping is on both ends, so the leading/trailing underscores the
            # substitution introduces are dropped too: `$pecial!` -> `pecial`.
            "portraits/$pecial!.png": "pecial",
            ".hidden.png": "hidden",

        }
        for source, expected_stem in cases.items():
            name = build_skin_filename(source)
            assert re.fullmatch(
                rf"skin_enhanced/{re.escape(expected_stem)}_[0-9a-f]{{12}}\.png", name
            ), f"{source!r} produced {name!r}"

    def test_output_key_shape_and_lineage(self, client, monkeypatch, stub_storage, db_session):
        """#111 decision 7: output goes to skin_enhanced/<stem>_<token>.png with
        source_path set to the source asset's file_path, so BeforeAfterModal pairs
        before/after with no new UI. The stem is the *sanitised* source stem: a
        filename with a space keeps its lineage in `source_path` but lands under an
        underscore in the key."""
        stub_storage["uploaded"]["my portrait.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        _install_engine(monkeypatch, FakeFaceEngine())

        res = client.post("/api/skin-enhance", json={"image_path": "my portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"

        filename = body["filename"]
        assert re.fullmatch(r"skin_enhanced/my_portrait_[0-9a-f]{12}\.png", filename), filename
        assert body["source_path"] == "my portrait.png"
        assert body["url"].endswith(filename)
        assert body["faces_enhanced"] == 1
        assert body["engine"] == "gfpgan"

        assert filename in stub_storage["uploaded"]
        assert stub_storage["uploaded"][filename]["content_type"] == "image/png"

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == filename)
            .first()
        )
        assert asset is not None
        assert asset.source_path == "my portrait.png"
        assert asset.content_type == "image/png"
        assert asset.file_size > 0
        # Lineage has to point at a row the catalog can actually resolve.
        assert asset.source_path in stub_storage["uploaded"]

    def test_token_is_unique_per_job_on_one_source(self, client, monkeypatch, stub_storage):
        """#96 regression: without a unique suffix, two jobs on one source overwrite
        each other's output in storage and cross-link their status lookups."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        _install_engine(monkeypatch, FakeFaceEngine())

        names = set()
        for _ in range(3):
            res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
            assert res.status_code == 200
            names.add(res.json()["filename"])
        assert len(names) == 3
        assert len(stub_storage["uploaded"]) == 4, "source + 3 distinct derivatives"

    def test_background_outside_faces_is_untouched(self, client, monkeypatch, stub_storage):
        """#111 decision 4: face-crop only, background untouched. Every pixel outside
        every detected box must be bit-identical to the source, including when the
        default skin_detail=80 texture-retention filter is active - that filter is a
        *skin* control, so it must not spill onto the background either."""
        raw = gradient_png(96, 96)
        stub_storage["uploaded"]["portrait.png"] = {"data": raw, "content_type": "image/png"}
        boxes = [(8, 8, 40, 40), (48, 48, 80, 80)]
        _install_engine(monkeypatch, FakeFaceEngine(faces=boxes))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body["faces_enhanced"] == 2
        assert body["parameters"]["texture_retention"] == pytest.approx(0.8)

        out = np.array(
            Image.open(io.BytesIO(stub_storage["uploaded"][body["filename"]]["data"])).convert("RGB")
        )
        src = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        assert out.shape == src.shape

        mask = np.ones(src.shape[:2], dtype=bool)
        for x0, y0, x1, y1 in boxes:
            mask[y0:y1, x0:x1] = False
        assert np.array_equal(out[mask], src[mask]), "background pixels changed"
        assert not np.array_equal(out[10:20, 10:20], src[10:20, 10:20]), "face was not restored"

    def test_global_sharp_and_grain_do_apply_where_magnific_says_they_do(
        self, client, monkeypatch, stub_storage
    ):
        """sharpen and smart_grain are whole-image controls in every mode, so unlike
        the Faithful texture filter they must reach the background too."""
        raw = gradient_png(96, 96)
        stub_storage["uploaded"]["portrait.png"] = {"data": raw, "content_type": "image/png"}
        _install_engine(monkeypatch, FakeFaceEngine(faces=[(8, 8, 40, 40)]))

        res = client.post(
            "/api/skin-enhance",
            json={
                "image_path": "portrait.png",
                "sharpen": 100,
                "smart_grain": 100,
                "skin_detail": 0,
            },
        )
        assert res.status_code == 200
        body = res.json()
        out = np.array(
            Image.open(io.BytesIO(stub_storage["uploaded"][body["filename"]]["data"])).convert("RGB")
        )
        src = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        corner = (slice(80, 96), slice(80, 96))
        assert not np.array_equal(out[corner], src[corner]), (
            "smart_grain=100 must reach the background; it is a whole-image control"
        )

    def test_faithful_mode_never_forwards_diffusion_parameters(
        self, client, monkeypatch, stub_storage
    ):
        """GFPGAN has no semantic control, so Faithful must reach the engine with
        post-filter parameters only. A prompt or guidance here would mean a silent
        mode switch."""
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        engine = _install_engine(monkeypatch, FakeFaceEngine())

        res = client.post(
            "/api/skin-enhance",
            json={
                "image_path": "portrait.png",
                "mode": "faithful",
                "sharpen": 30,
                "smart_grain": 20,
                "skin_detail": 60,
            },
        )
        assert res.status_code == 200
        assert engine.restore_calls == [{}], engine.restore_calls
        body = res.json()
        assert body["engine"] == "gfpgan"
        assert "prompt" not in body["parameters"]
        assert body["parameters"]["texture_retention"] == pytest.approx(0.6)

    def test_creative_mode_maps_skin_detail_to_guidance(self, client, monkeypatch, stub_storage):
        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        engine = _install_engine(monkeypatch, FakeFaceEngine())

        res = client.post(
            "/api/skin-enhance",
            json={"image_path": "portrait.png", "mode": "creative", "skin_detail": 40},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["engine"] == "diffbir"
        call = engine.restore_calls[0]
        assert call["guidance_scale"] < 5.0
        assert body["parameters"]["guidance_scale"] == pytest.approx(call["guidance_scale"])
        assert call["condition_noise"] > 0.0
        assert call["prompt"]

    def test_flexible_mode_forwards_preset_prompt_and_noise(
        self, client, monkeypatch, stub_storage
    ):
        """#111 decision 3: the preset is a hardcoded (prompt, guidance, noise) tuple
        and it must reach the engine verbatim."""
        from app.ml.skin_enhancer import FLEXIBLE_PRESETS

        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        engine = _install_engine(monkeypatch, FakeFaceEngine())

        res = client.post(
            "/api/skin-enhance",
            json={
                "image_path": "portrait.png",
                "mode": "flexible",
                "preset": "transform_to_real",
            },
        )
        assert res.status_code == 200
        body = res.json()
        preset = FLEXIBLE_PRESETS["transform_to_real"]
        call = engine.restore_calls[0]
        assert call["prompt"] == preset["prompt"]
        assert call["condition_noise"] == pytest.approx(preset["condition_noise"])
        assert call["guidance_scale"] == pytest.approx(preset["guidance_scale"])
        assert body["preset"] == "transform_to_real"

    def test_flexible_default_preset_is_enhance_skin(self, client, monkeypatch, stub_storage):
        from app.ml.skin_enhancer import FLEXIBLE_PRESETS

        stub_storage["uploaded"]["portrait.png"] = {"data": png_bytes(), "content_type": "image/png"}
        engine = _install_engine(monkeypatch, FakeFaceEngine())

        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "flexible"}
        )
        assert res.status_code == 200
        assert engine.restore_calls[0]["prompt"] == FLEXIBLE_PRESETS["enhance_skin"]["prompt"]
        assert res.json()["preset"] == "enhance_skin"

    def test_oversized_input_is_capped_at_8192(self, client, monkeypatch, stub_storage):
        """#111 decision 4: max input dimension is capped at 8192, the same ceiling the
        upscaler uses. A 9000px phone panorama is legitimate input, so it is rescaled
        rather than refused."""
        buf = io.BytesIO()
        Image.new("RGB", (9000, 64), (30, 60, 90)).save(buf, format="PNG")
        stub_storage["uploaded"]["wide.png"] = {
            "data": buf.getvalue(),
            "content_type": "image/png",
        }
        _install_engine(monkeypatch, FakeFaceEngine(faces=[(10, 10, 60, 50)]))

        res = client.post("/api/skin-enhance", json={"image_path": "wide.png"})
        assert res.status_code == 200
        body = res.json()
        out = Image.open(io.BytesIO(stub_storage["uploaded"][body["filename"]]["data"]))
        assert max(out.size) == 8192
        assert out.size == (8192, 58)

    def test_faces_are_restored_sequentially_in_detected_order(
        self, client, monkeypatch, stub_storage
    ):
        """#111 decision 7: group shots run faces sequentially to keep the VRAM floor,
        so the order must be deterministic and reported back for the UI."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": gradient_png(128, 128),
            "content_type": "image/png",
        }
        boxes = [(4, 4, 40, 40), (44, 44, 80, 80), (84, 84, 120, 120)]
        engine = _install_engine(monkeypatch, FakeFaceEngine(faces=boxes))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200
        body = res.json()
        assert body["faces_enhanced"] == 3
        assert body["face_boxes"] == [list(b) for b in boxes]
        assert len(engine.restore_calls) == 3


class TestBatchRestoreDispatch:
    """One restore call per request when the engine can take one, and the per-face
    loop kept intact for the engines that cannot.

    The seam is `restore_faces`. DiffBIR needs it: its CLI takes a folder and every
    invocation reloads five models, so a per-face loop on an N-face group shot pays the
    model load N times against #111's 60s Creative/Flexible budget. GFPGAN does not
    have it - `model_registry` caches the loaded instance, so its second face is a
    forward pass on a resident model, not a reload - and it must keep working exactly
    as before.

    What must not change because of the dispatch: the reported counts and boxes, the
    background-untouched guarantee, and the degraded envelope on failure.
    """

    def test_engine_with_restore_faces_is_asked_once_for_the_whole_request(
        self, client, monkeypatch, stub_storage
    ):
        """Three faces, one call. The assertion is on the call count *and* on the
        crops handed over, because an executor that batched the crops but then looped
        over the results would satisfy the first and not the second."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": gradient_png(128, 128),
            "content_type": "image/png",
        }
        boxes = [(4, 4, 40, 40), (44, 44, 80, 80), (84, 84, 120, 120)]
        engine = _install_engine(monkeypatch, FakeBatchFaceEngine(faces=boxes))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200, res.text
        assert len(engine.batch_calls) == 1, (
            f"one restore call per face means {len(engine.restore_calls)} model loads"
        )
        assert engine.restore_calls == [], "the per-face entry point must not be used"
        assert engine.batch_calls[0]["sizes"] == [(36, 36)] * 3

    def test_a_group_shot_reports_every_face_through_the_batch_path(
        self, client, monkeypatch, stub_storage
    ):
        """`faces_enhanced` / `face_boxes` / `faces_skipped` are computed from the
        detected boxes, not from how many engine calls it took - so a batched run must
        report the same numbers a per-face run would, in detected order."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": gradient_png(128, 128),
            "content_type": "image/png",
        }
        boxes = [(4, 4, 40, 40), (44, 44, 80, 80), (200, 200, 240, 240)]
        engine = _install_engine(monkeypatch, FakeBatchFaceEngine(faces=boxes))

        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "creative"}
        )
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["faces_enhanced"] == 2
        assert body["face_boxes"] == [[4, 4, 40, 40], [44, 44, 80, 80]]
        assert body["faces_skipped"] == 1, "the off-canvas box is still counted as skipped"
        assert len(engine.batch_calls) == 1
        assert engine.batch_calls[0]["params"]["prompt"], "creative params must still be forwarded"

    def test_engine_without_restore_faces_keeps_the_per_face_loop(
        self, client, monkeypatch, stub_storage
    ):
        """`FakeFaceEngine` is the GFPGAN shape: `restore_face` and nothing else. It
        must be called once per face, in order, and the response must be identical."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": gradient_png(128, 128),
            "content_type": "image/png",
        }
        boxes = [(4, 4, 40, 40), (44, 44, 80, 80), (84, 84, 120, 120)]
        engine = _install_engine(monkeypatch, FakeFaceEngine(faces=boxes))

        res = client.post("/api/skin-enhance", json={"image_path": "portrait.png"})
        assert res.status_code == 200, res.text
        body = res.json()
        assert len(engine.restore_calls) == 3
        assert engine.crop_sizes == [(36, 36)] * 3
        assert body["faces_enhanced"] == 3
        assert body["face_boxes"] == [list(b) for b in boxes]
        assert body["faces_skipped"] == 0

    def test_the_real_gfpgan_adapter_has_no_batch_entry_point(self):
        """The dispatch keys off `restore_faces`, so it matters that the one engine
        that must stay on the per-face loop genuinely lacks it - and that it lacks it on
        purpose: `GFPGANer.enhance` re-detects faces *inside* the image it is given, so
        N crops stacked into one image is a different operation, not a batched one."""
        from app.ml.skin_enhancer import DiffBIRFaceEngine, GFPGANFaceEngine

        assert not hasattr(GFPGANFaceEngine, "restore_faces")
        assert hasattr(DiffBIRFaceEngine, "restore_faces")

    def test_a_failed_batch_degrades_the_whole_request_and_writes_nothing(
        self, client, monkeypatch, stub_storage, db_session
    ):
        """One subprocess owns every crop, so a failure is every face's failure. The
        answer is still the labelled LOAD_FAILED envelope at HTTP 200 with the engine's
        own message, and nothing is written to storage or the catalog."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        _install_engine(
            monkeypatch,
            FakeBatchFaceEngine(faces=[(8, 8, 40, 40), (48, 48, 80, 80)], raises=RuntimeError("DiffBIR exited 1: no lpips")),
        )
        before_assets = db_session.query(MediaAsset).count()

        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "flexible"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "no lpips" in body["message"]
        assert "filename" not in body and "url" not in body
        assert len(stub_storage["uploaded"]) == 1, "only the source may exist"
        assert db_session.query(MediaAsset).count() == before_assets

    def test_a_batch_that_returns_fewer_images_than_crops_is_refused(
        self, client, monkeypatch, stub_storage
    ):
        """Shortening the list would shift every later face's result onto the wrong
        face box. The engine refuses this itself; the executor refuses it anyway,
        because the seam is duck-typed and a future engine need not be careful."""
        stub_storage["uploaded"]["portrait.png"] = {
            "data": png_bytes(),
            "content_type": "image/png",
        }
        _install_engine(
            monkeypatch,
            FakeBatchFaceEngine(
                faces=[(8, 8, 40, 40), (48, 48, 80, 80)], drop_results=1
            ),
        )

        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "creative"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["degraded"] is True
        assert body["reason"] == DegradedReason.LOAD_FAILED.value
        assert "filename" not in body

    def test_the_batch_path_leaves_the_background_untouched(
        self, client, monkeypatch, stub_storage
    ):
        """#111 decision 4 under the batched executor: batching changes how the crops
        travel, never which pixels they cover. Every pixel outside every box is
        bit-identical to the source, and every box is visibly restored."""
        raw = gradient_png(96, 96)
        stub_storage["uploaded"]["portrait.png"] = {"data": raw, "content_type": "image/png"}
        boxes = [(8, 8, 40, 40), (48, 48, 80, 80)]
        _install_engine(monkeypatch, FakeBatchFaceEngine(faces=boxes))

        res = client.post(
            "/api/skin-enhance", json={"image_path": "portrait.png", "mode": "creative"}
        )
        assert res.status_code == 200
        body = res.json()
        assert body["faces_enhanced"] == 2

        out = np.array(
            Image.open(io.BytesIO(stub_storage["uploaded"][body["filename"]]["data"])).convert("RGB")
        )
        src = np.array(Image.open(io.BytesIO(raw)).convert("RGB"))
        mask = np.ones(src.shape[:2], dtype=bool)
        for x0, y0, x1, y1 in boxes:
            mask[y0:y1, x0:x1] = False
        assert np.array_equal(out[mask], src[mask]), "background pixels changed"
        assert not np.array_equal(out[10:20, 10:20], src[10:20, 10:20]), "face was not restored"
        assert not np.array_equal(out[50:60, 50:60], src[50:60, 50:60]), (
            "the second face was not restored; results were shifted onto the wrong box"
        )


def _fake_torch(cuda_available: bool) -> types.ModuleType:
    """A stand-in for `torch` with only what the loaders touch.

    Real torch is not installable in CI here, and the loaders need exactly three
    things from it: `cuda.is_available()`, `device(...)` and nothing else. Note what
    is *absent*: no `float16`, no `autocast`, no `nn` - because nothing in the
    loaders uses them any more. The first cut referenced `torch.float16` and
    `torch.float32` for a `DiffBIRPipeline` that does not exist.
    """

    class _Device:
        def __init__(self, spec):
            self.type = spec

        def __eq__(self, other):
            return isinstance(other, _Device) and other.type == self.type

        def __repr__(self):
            return f"device(type={self.type!r})"

    module = types.ModuleType("torch")
    module.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)
    module.device = _Device
    module.__version__ = "0.0.0-fake"
    return module


def _fake_repo(tmp_path) -> Path:
    """A directory shaped like a DiffBIR checkout: `inference.py` at the root plus
    the `configs/inference/` tree its CWD-relative `OmegaConf.load(...)` calls need."""
    root = Path(tmp_path) / "DiffBIR"
    (root / "configs" / "inference").mkdir(parents=True, exist_ok=True)
    (root / "inference.py").write_text("# not executed in tests\n", encoding="utf-8")
    return root


def _install_gfpgan(monkeypatch, restorer_cls, cuda_available: bool = True) -> list:
    """Install fake `gfpgan` + `torch` and return the list of restorers built."""
    built: list = []

    class _Recording(restorer_cls):  # type: ignore[misc, valid-type]
        def __init__(self, *args, **kwargs):
            self.init_args = args
            self.init_kwargs = dict(kwargs)
            super().__init__(*args, **kwargs)
            built.append(self)

    fake_gfpgan = types.ModuleType("gfpgan")
    # gfpgan 1.3.8 exports exactly this class from its top level and nothing else
    # engine-related - in particular no GFPGAN_VERSION_* constants.
    fake_gfpgan.GFPGANer = _Recording
    fake_gfpgan.__version__ = "1.3.8-fake"
    monkeypatch.setitem(sys.modules, "gfpgan", fake_gfpgan)
    monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available))
    return built


class TestLoaderFactories:
    """The loaders, exercised through contract mirrors of the real API.

    Every fake in this class is a *contract mirror* of the installed package -
    `ContractMirrorGFPGANer` and `ContractMirrorFaceRestoreHelper` in
    tests/test_skin_engine_contracts.py, whose signatures are asserted against
    gfpgan 1.3.8 and facexlib 0.3.0 there. They are not definitions of what the
    production code is allowed to call, which is precisely the mistake that let
    #112 ship five invented symbols behind a green suite.
    """

    def test_gfpgan_loader_uses_the_real_constructor_signature(self, monkeypatch):
        """`GFPGANer(model_path, upscale, arch, channel_multiplier, bg_upsampler,
        device)`. The device is a *constructor argument*: `GFPGANer` is a plain
        class, so there is nothing to `.to()` and no `enhance_model()` to call."""
        from app.ml.skin_enhancer import (
            GFPGAN_ARCH,
            GFPGAN_ARCH_CHANNEL_MULTIPLIER,
            GFPGAN_MODEL_URL,
            GFPGAN_UPSCALE,
            make_gfpgan_loader,
        )

        from .test_skin_engine_contracts import ContractMirrorGFPGANer

        built = _install_gfpgan(monkeypatch, ContractMirrorGFPGANer, cuda_available=True)
        make_gfpgan_loader("gfpgan")()

        assert len(built) == 1
        kwargs = built[0].init_kwargs
        assert kwargs["model_path"] == GFPGAN_MODEL_URL
        assert kwargs["upscale"] == GFPGAN_UPSCALE == 1
        assert kwargs["arch"] == GFPGAN_ARCH == "clean"
        assert kwargs["channel_multiplier"] == GFPGAN_ARCH_CHANNEL_MULTIPLIER == 2
        assert kwargs["bg_upsampler"] is None, (
            "bg_upsampler=None plus upscale=1 is what keeps the background "
            "untouched (#111 decision 4)"
        )
        assert kwargs["device"].type == "cuda"
        # The device reached the model, and no offload API was faked into existence.
        assert built[0].device.type == "cuda"

    def test_gfpgan_adapter_detects_and_restores_through_the_real_sequence(
        self, monkeypatch
    ):
        """detect_faces -> read_image(BGR) -> get_face_landmarks_5 -> det_faces;
        restore_face -> enhance(paste_back=True) -> third element of the 3-tuple.

        Both methods are *called*, not merely constructed, because a loader test
        that only checks the constructor received its arguments is what shipped
        `DiffBIRFaceEngine(pipe, None)` green.
        """
        from app.ml.skin_enhancer import make_gfpgan_loader

        from .test_skin_engine_contracts import ContractMirrorGFPGANer

        _install_gfpgan(monkeypatch, ContractMirrorGFPGANer, cuda_available=True)
        engine = make_gfpgan_loader("gfpgan")()

        image = Image.new("RGB", (64, 64), (40, 80, 120))
        assert engine.detect_faces(image) == [(0, 0, 32, 32)]

        # A BGR ndarray reached the helper, not a PIL image: the mirror's
        # `read_image` raises TypeError on a PIL image precisely so this cannot
        # regress silently.
        helper = engine.face_helper
        assert isinstance(helper.input_img, np.ndarray)
        assert helper.input_img.shape == (64, 64, 3)

        crop = image.crop((0, 0, 32, 32))
        restored = engine.restore_face(crop)
        assert isinstance(restored, Image.Image)
        assert restored.size == crop.size
        # The mirror adds 32 levels to every channel, so a real change is visible.
        assert restored.getpixel((5, 5)) != crop.getpixel((5, 5))

    def test_gfpgan_restore_refuses_prompt_parameters(self, monkeypatch):
        """Faithful has no semantic control. A prompt reaching GFPGAN would mean the
        mode had silently stopped being Faithful."""
        from app.ml.skin_enhancer import make_gfpgan_loader

        from .test_skin_engine_contracts import ContractMirrorGFPGANer

        _install_gfpgan(monkeypatch, ContractMirrorGFPGANer, cuda_available=True)
        engine = make_gfpgan_loader("gfpgan")()

        with pytest.raises(ValueError) as exc:
            engine.restore_face(Image.new("RGB", (32, 32)), prompt="a prompt")
        assert "prompt" in str(exc.value)

    def test_gfpgan_loader_falls_back_to_cpu_device_without_cuda(self, monkeypatch):
        """A CPU-only host never reaches inference (the VRAM guard refuses first),
        so the loader only has to be constructible - but it must be constructible
        *without* a `.to()` call, because there is no such method."""
        from app.ml.skin_enhancer import make_gfpgan_loader

        from .test_skin_engine_contracts import ContractMirrorGFPGANer

        built = _install_gfpgan(monkeypatch, ContractMirrorGFPGANer, cuda_available=False)
        make_gfpgan_loader("gfpgan")()
        assert built[0].init_kwargs["device"].type == "cpu"
        assert built[0].init_kwargs["upscale"] == 1

    def test_diffbir_loader_does_not_import_a_pipeline_that_does_not_exist(
        self, monkeypatch, tmp_path
    ):
        """`from diffusers import DiffBIRPipeline` cannot work - DiffBIR is a repo,
        not a package. The loader must not even try, and must resolve the
        operator's checkout instead."""
        import builtins

        import app.ml.skin_enhancer as skin_mod
        from app.ml.skin_enhancer import DiffBIRFaceEngine, make_diffbir_loader

        real_import = builtins.__import__

        def guard(name, *args, **kwargs):
            if name.split(".")[0] in {"diffusers", "gfpgan"}:
                raise AssertionError(f"the DiffBIR loader must not import {name!r}")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr(builtins, "__import__", guard)
        monkeypatch.setitem(sys.modules, "diffusers", None)
        monkeypatch.setitem(sys.modules, "gfpgan", None)
        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_REPO_PATH", str(_fake_repo(tmp_path)))

        engine = make_diffbir_loader("diffbir")()
        assert isinstance(engine, DiffBIRFaceEngine)
        assert engine.repo_root == _fake_repo(tmp_path)
        # No `pipeline` attribute any more: there is nothing to wrap.
        assert not hasattr(engine, "pipeline")

    def test_diffbir_loader_uses_the_configured_interpreter_and_timeout(
        self, monkeypatch, tmp_path
    ):
        """DiffBIR pins torch 2.2.2+cu118 and xformers 0.0.25.post1+cu118, which does
        not coexist with this app's torch in practice, so the interpreter is the
        operator's to choose."""
        import app.ml.skin_enhancer as skin_mod

        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_REPO_PATH", str(_fake_repo(tmp_path)))
        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_PYTHON", "/opt/diffbir-venv/bin/python")
        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_TIMEOUT_SECONDS", 42.0)

        engine = skin_mod.make_diffbir_loader("diffbir")()
        assert engine.python_executable == "/opt/diffbir-venv/bin/python"
        assert engine.timeout_seconds == 42.0

    def test_diffbir_loader_falls_back_to_this_interpreter_when_none_is_configured(
        self, monkeypatch, tmp_path
    ):
        import app.ml.skin_enhancer as skin_mod

        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_REPO_PATH", str(_fake_repo(tmp_path)))
        monkeypatch.setattr(skin_mod.settings, "DIFFBIR_PYTHON", "")
        engine = skin_mod.make_diffbir_loader("diffbir")()
        assert engine.python_executable == sys.executable

    def test_diffbir_detector_uses_a_detector_facexlib_implements(self, monkeypatch, tmp_path):
        """The adapter builds its own `FaceRestoreHelper` because the route needs
        boxes before it can decide whether to refuse with `no_face_detected`. Its
        detector must be one facexlib 0.3.0 actually implements: only
        `retinaface_resnet50` and `retinaface_mobile0.25` exist, and `s3fd` raises
        NotImplementedError."""
        import app.ml.skin_enhancer as skin_mod
        from app.ml.skin_enhancer import DETECT_MODEL

        from .test_skin_engine_contracts import ContractMirrorFaceRestoreHelper

        captured: dict = {}

        class _Recording(ContractMirrorFaceRestoreHelper):
            def __init__(self, *args, **kwargs):
                captured["args"] = args
                captured["kwargs"] = dict(kwargs)
                super().__init__(*args, **kwargs)

        fake_module = types.ModuleType("facexlib.utils.face_restoration_helper")
        fake_module.FaceRestoreHelper = _Recording
        fake_facexlib = types.ModuleType("facexlib")
        fake_facexlib.utils = types.ModuleType("facexlib.utils")
        fake_facexlib.utils.face_restoration_helper = fake_module

        monkeypatch.setitem(sys.modules, "torch", _fake_torch(cuda_available=True))
        monkeypatch.setitem(sys.modules, "facexlib", fake_facexlib)
        monkeypatch.setitem(sys.modules, "facexlib.utils", fake_facexlib.utils)
        monkeypatch.setitem(
            sys.modules, "facexlib.utils.face_restoration_helper", fake_module
        )
        monkeypatch.setattr(
            skin_mod.settings, "DIFFBIR_REPO_PATH", str(_fake_repo(tmp_path=tmp_path))
        )

        engine = skin_mod.make_diffbir_loader("diffbir")()
        assert engine.detect_faces(Image.new("RGB", (64, 64), (5, 5, 5))) == [(0, 0, 32, 32)]
        assert captured["kwargs"]["det_model"] == DETECT_MODEL == "retinaface_resnet50"
        assert captured["args"][0] == 1, "upscale_factor=1: paste back at native size"
        assert "detection_model" not in captured["kwargs"], (
            "facexlib 0.3.0's FaceRestoreHelper has no `detection_model` argument; "
            "the argument is `det_model`"
        )

    def test_unknown_engine_has_no_loader(self):
        """CodeFormer / SUPIR / StableSR / GPEN are excluded on license grounds (#111);
        there is deliberately no loader for them, flag or otherwise."""
        from app.ml.skin_enhancer import make_diffbir_loader, make_gfpgan_loader

        for bad in ("codeformer", "supir", "stablesr", "gpen"):
            # The factories return a closure (mirroring make_diffusers_loader), so the
            # refusal happens when the loader is invoked.
            with pytest.raises(ValueError):
                make_gfpgan_loader(bad)()
            with pytest.raises(ValueError):
                make_diffbir_loader(bad)()


class TestSurfaceDescription:
    def test_presets_endpoint_publishes_the_whole_input_surface(self, client):
        """Ticket #137's panel must render from the same source of truth the endpoint
        validates against, so /presets has to carry modes, engines, presets, slider
        ranges, the input ceiling and the two semantic surprises (mode-aware
        skin_detail, faces-only)."""
        res = client.get("/api/skin-enhance/presets")
        assert res.status_code == 200
        body = res.json()

        assert body["modes"] == ["faithful", "creative", "flexible"]
        assert body["engines"] == {
            "faithful": "gfpgan",
            "creative": "diffbir",
            "flexible": "diffbir",
        }
        assert body["default_preset"] == "enhance_skin"
        assert set(body["presets"]) == {
            "enhance_skin",
            "improve_lighting",
            "enhance_everything",
            "transform_to_real",
            "no_make_up",
        }
        for name, preset in body["presets"].items():
            assert preset["description"].strip(), f"{name} needs a UI description"

        assert body["sliders"]["sharpen"] == {"min": 0, "max": 100, "default": 0}
        assert body["sliders"]["smart_grain"] == {"min": 0, "max": 100, "default": 0}
        assert body["sliders"]["skin_detail"]["default"] == 80

        assert body["max_input_dimension"] == 8192
        assert body["video_supported"] is False
        assert body["faces_only"] is True
        # Decision 2's accepted consequence: the panel must know the slider means
        # different physical things per mode, or the label lies.
        assert body["skin_detail_semantics"]["faithful"] != (
            body["skin_detail_semantics"]["flexible"]
        )
        assert "guidance" in body["skin_detail_semantics"]["creative"]
        assert "texture" in body["skin_detail_semantics"]["faithful"]


class TestRoster:
    def test_engines_are_registered_apache_2_and_image_family(self):
        """#111 decision 1: GFPGAN and DiffBIR are the only two engines, and both are
        Apache-2.0, which is the whole point of the engine choice."""
        from app.ml.skin_enhancer import MODE_ENGINES

        assert MODE_ENGINES == {
            "faithful": "gfpgan",
            "creative": "diffbir",
            "flexible": "diffbir",
        }
        for engine_id in ("gfpgan", "diffbir"):
            meta = model_registry.get(engine_id)
            assert meta.license == "Apache-2.0"
            assert meta.family == "image"
            assert meta.approx_vram_gb > 0

    def test_roster_excludes_non_commercial_engines(self):
        """#111 decision 1: CodeFormer, SUPIR, StableSR and GPEN must not appear in the
        pinned roster at all - not even behind a flag."""
        from app.ml.registry import PINNED_ROSTER

        ids = {m.model_id for m in PINNED_ROSTER}
        for banned in ("codeformer", "supir", "stablesr", "gpen", "realesrgan"):
            assert banned not in ids, f"{banned} is excluded on license grounds"

    def test_diffbir_vram_figure_is_eight_gb(self):
        """DiffBIR v2.1 release notes: 8 GB *for tiled inference*. The engine always
        passes `--cleaner_tiled` and `--cldm_tiled`, so the registry number and the
        runtime configuration agree on that much.

        What the number does not cover: the app runs DiffBIR per face crop at
        `--upscale 1`, which should be no worse than the whole-image case the figure
        describes. That is an inference, not a measurement, and it has not been checked
        against a real GPU - so the figure stays at the published whole-image value
        rather than being lowered on the strength of a hunch.
        """
        assert model_registry.get("diffbir").approx_vram_gb == 8.0
