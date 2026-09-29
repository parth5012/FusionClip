"""Tests for the Magnific-equivalent Image Editor core (#121, map #75).

Seams under test (HTTP boundary only — no unit tests against internals):
1. GET /api/editor/presets — the endpoint's own description of its inputs
   (version, slider ranges, rotate range, crop aspects).
2. POST /api/editor/recipe + GET /api/editor/recipes — versioned edit-recipe
   JSON persist with lineage (edit-save-reload fidelity at the HTTP seam).
3. POST /api/editor/render — synchronous PIL authoritative re-render producing
   a derivative PNG with MediaAsset.source_path lineage plus a co-saved recipe
   sidecar, deterministic per recipe (same recipe bytes twice => same bytes).

Validation contract (mirrors #111 decision 4 for skin): out-of-range,
non-integer, non-finite, unknown-key, bad crop/rotate and traversal paths are
HTTP 400 with an actionable message — never a silent clamp, never a 422.
"""

import io

import pytest
from PIL import Image

from app.models import MediaAsset


@pytest.fixture()
def editor_listing(monkeypatch, stub_storage):
    """Drive recipe-version listing from the stub's uploaded keys.

    The router and engine list versions through `list_workspace_files`
    (bound into their own namespaces, hence patched where read). Deriving
    the listing from what the stub actually stored keeps the version-bump
    assertions about the mechanism, not about a hand-built fake.
    """
    import app.ml.image_adjust as image_adjust
    import app.routers.editor as editor_router

    def _fake_list(prefix=""):
        files = [
            {
                "name": key[len(prefix):],
                "path": key,
                "type": "file",
                "url": f"http://test-minio/{key}",
            }
            for key in stub_storage["uploaded"]
            if key.startswith(prefix)
        ]
        return {"current_dir": prefix, "directories": [], "files": files}

    monkeypatch.setattr(
        image_adjust, "list_workspace_files", _fake_list, raising=False
    )
    monkeypatch.setattr(
        editor_router, "list_workspace_files", _fake_list, raising=False
    )


def png_bytes(size=(64, 48), color=(120, 90, 60)) -> bytes:
    """A real, decodable PNG so the render decode step is genuinely exercised."""
    img = Image.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def gradient_png(width=64, height=64) -> bytes:
    """A gradient PNG: tone ops must observably change its pixels."""
    img = Image.new("RGB", (width, height))
    px = img.load()
    for y in range(height):
        for x in range(width):
            px[x, y] = (int(255 * x / width), int(255 * y / height), 128)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def seed_source(stub_storage, path="uploads/e2e-editor.png", raw=None):
    stub_storage["uploaded"][path] = {
        "data": raw or gradient_png(),
        "content_type": "image/png",
    }
    return path


def render(client, source_path, recipe):
    return client.post(
        "/api/editor/render", json={"source_path": source_path, "recipe": recipe}
    )


class TestEditorPresets:
    def test_presets_surface_lists_version_sliders_and_aspects(self, client):
        res = client.get("/api/editor/presets")
        assert res.status_code == 200
        body = res.json()
        assert body["version"] == 1
        for key in (
            "exposure",
            "brightness",
            "contrast",
            "highlights",
            "shadows",
            "tint",
            "grain",
        ):
            assert body["sliders"][key]["min"] is not None
            assert body["sliders"][key]["max"] is not None
            assert body["sliders"][key]["default"] == 0
        assert body["sliders"]["grain"]["min"] == 0
        assert body["rotate"] == {"min": -45, "max": 45, "default": 0}
        assert set(body["crop_aspects"]) == {"free", "1:1", "4:3", "16:9"}
        assert body["default_crop"] == "free"


class TestRecipeValidation:
    def test_out_of_range_slider_is_400(self, client, stub_storage):
        src = seed_source(stub_storage)
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"exposure": 101}},
        )
        assert res.status_code == 400
        assert "exposure" in res.json()["detail"]

    def test_fractional_slider_is_400(self, client, stub_storage):
        src = seed_source(stub_storage)
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"contrast": 12.5}},
        )
        assert res.status_code == 400

    def test_unknown_key_is_400(self, client, stub_storage):
        src = seed_source(stub_storage)
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"vibrance": 10}},
        )
        assert res.status_code == 400

    def test_bad_crop_and_rotate_are_400(self, client, stub_storage):
        src = seed_source(stub_storage)
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"crop_aspect": "3:2"}},
        )
        assert res.status_code == 400
        res = client.post(
            "/api/editor/recipe", json={"source_path": src, "recipe": {"rotate": 90}}
        )
        assert res.status_code == 400

    def test_traversal_path_is_400(self, client):
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": "../secret.png", "recipe": {}},
        )
        assert res.status_code == 400

    def test_missing_source_is_400_source_not_found(self, client):
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": "uploads/does-not-exist.png", "recipe": {}},
        )
        assert res.status_code == 400
        assert "source_not_found" in res.json()["detail"]

    def test_video_source_is_refused(self, client, stub_storage):
        stub_storage["uploaded"]["uploads/clip.mp4"] = {
            "data": b"\x00\x00\x00\x1cftyp",
            "content_type": "video/mp4",
        }
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": "uploads/clip.mp4", "recipe": {}},
        )
        assert res.status_code == 400
        assert "video_input_not_supported" in res.json()["detail"]

    def test_camelcase_crop_aspect_alias_is_accepted(self, client, stub_storage):
        """HIGH-01 (#121 review): the frontend EditorRecipe type is camelCase."""
        src = seed_source(stub_storage)
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"cropAspect": "16:9"}},
        )
        assert res.status_code == 200
        assert res.json()["recipe"]["crop_aspect"] == "16:9"


class TestRecipePersistLineage:
    def test_save_then_list_round_trips_recipe_with_version(
        self, client, stub_storage, editor_listing
    ):
        src = seed_source(stub_storage)
        res = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"exposure": 25, "grain": 10}},
        )
        assert res.status_code == 200
        saved = res.json()
        assert saved["status"] == "SAVED"
        assert saved["version"] == 1
        assert saved["source_path"] == src
        assert saved["recipe"]["exposure"] == 25
        assert saved["recipe"]["grain"] == 10
        assert saved["recipe"]["contrast"] == 0  # missing keys fill defaults
        assert saved["file_path"].startswith("edits/")
        assert saved["url"].startswith("http://test-minio/")

        # GET lists through list_workspace_files — the editor_listing fixture
        # derives it from the stub's uploaded keys, so this exercises the
        # real listing path rather than a hand-built fake.
        res = client.get("/api/editor/recipes", params={"source_path": src})
        assert res.status_code == 200
        body = res.json()
        assert body["source_path"] == src
        assert len(body["versions"]) == 1
        assert body["versions"][0]["recipe"]["exposure"] == 25
        assert body["versions"][0]["file_path"] == saved["file_path"]

    def test_second_save_bumps_version(self, client, stub_storage, editor_listing):
        src = seed_source(stub_storage)
        first = client.post(
            "/api/editor/recipe", json={"source_path": src, "recipe": {}}
        ).json()
        second = client.post(
            "/api/editor/recipe",
            json={"source_path": src, "recipe": {"brightness": 5}},
        ).json()
        assert second["version"] == first["version"] + 1
        assert second["file_path"] != first["file_path"]


class TestEditorRender:
    def test_render_produces_derivative_with_lineage(
        self, client, stub_storage, db_session
    ):
        src = seed_source(stub_storage)
        res = render(client, src, {"exposure": 20, "contrast": 10})
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["source_path"] == src
        assert body["filename"].startswith("edited/")
        assert body["url"].startswith("http://test-minio/")
        assert body["recipe_path"].startswith("edits/")
        assert body["parameters"]["exposure"] == 20

        out = stub_storage["uploaded"][body["filename"]]["data"]
        img = Image.open(io.BytesIO(out))
        assert img.format == "PNG"

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .first()
        )
        assert asset is not None
        assert asset.source_path == src  # lineage for before/after pairing
        assert asset.content_type == "image/png"

    def test_default_recipe_is_near_identity(self, client, stub_storage):
        raw = gradient_png()
        src = seed_source(stub_storage, raw=raw)
        body = render(client, src, {}).json()
        out = stub_storage["uploaded"][body["filename"]]["data"]
        assert out is not None
        a = Image.open(io.BytesIO(raw)).convert("RGB")
        b = Image.open(io.BytesIO(out)).convert("RGB")
        assert a.size == b.size
        pa, pb = list(a.getdata()), list(b.getdata())  # type: ignore[arg-type]
        diffs = [
            abs(ca - cb) + abs(ga - gb) + abs(ba - bb)
            for (ca, ga, ba), (cb, gb, bb) in zip(pa, pb)
        ]
        assert sum(diffs) / len(diffs) < 2.0

    def test_exposure_change_moves_pixels(self, client, stub_storage):
        src = seed_source(stub_storage)
        base = render(client, src, {}).json()
        pushed = render(client, src, {"exposure": 60}).json()
        out_base = stub_storage["uploaded"][base["filename"]]["data"]
        out_pushed = stub_storage["uploaded"][pushed["filename"]]["data"]
        assert out_base != out_pushed

    def test_same_recipe_renders_byte_identical_including_grain(
        self, client, stub_storage
    ):
        src = seed_source(stub_storage)
        recipe = {"grain": 40, "exposure": -10, "tint": 15}
        first = render(client, src, recipe).json()
        second = render(client, src, recipe).json()
        assert (
            stub_storage["uploaded"][first["filename"]]["data"]
            == stub_storage["uploaded"][second["filename"]]["data"]
        )

    def test_render_refuses_video_and_missing_source(self, client, stub_storage):
        stub_storage["uploaded"]["uploads/clip.mp4"] = {
            "data": b"\x00\x00\x00\x1cftyp",
            "content_type": "video/mp4",
        }
        res = render(client, "uploads/clip.mp4", {})
        assert res.status_code == 400
        res = render(client, "uploads/gone.png", {})
        assert res.status_code == 400
