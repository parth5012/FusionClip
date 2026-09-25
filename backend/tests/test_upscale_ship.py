"""Ship-flow tests for the Magnific upscaler (#96).

Covers the two contract gaps found while rewiring the UI:
  1. Every upscale job must get a UNIQUE output object key — the original
     ``task_id[:6]`` slicing collapsed to the shared ``"upscale"`` prefix for
     every task, so two runs on the same source overwrote each other.
  2. ``GET /api/upscale/status/{task_id}`` must return the result that
     belongs to THAT task, not the first asset whose title happened to
     contain the shared prefix.
"""

import io

from PIL import Image

import app.storage as storage
from app.models import MediaAsset
from app.services.upscaler import execute_upscale_job


def _png_bytes(color=(10, 90, 160), size=(48, 48)) -> bytes:
    img = Image.new("RGB", size, color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _patch_job_env(monkeypatch, db_session):
    """Run background jobs against the test DB with a deterministic embedding."""
    monkeypatch.setattr(
        "app.services.upscaler.SessionLocal", lambda: db_session, raising=False
    )
    monkeypatch.setattr(
        "app.services.upscaler.get_embedding",
        lambda text: [0.0] * 384,
        raising=False,
    )


class TestUniqueOutputPaths:
    def test_two_jobs_same_source_get_distinct_output_paths(
        self, client, db_session, monkeypatch
    ):
        _patch_job_env(monkeypatch, db_session)
        storage.upload_object(_png_bytes(), "ship_unique.png", "image/png")

        r1 = client.post(
            "/api/upscale", json={"image_path": "ship_unique.png", "scale": 2}
        )
        r2 = client.post(
            "/api/upscale", json={"image_path": "ship_unique.png", "scale": 2}
        )
        assert r1.status_code == 200
        assert r2.status_code == 200

        body1, body2 = r1.json(), r2.json()
        assert body1["task_id"] != body2["task_id"]
        assert body1["output_path"] != body2["output_path"]

        # Each output key embeds its own unique token, not the shared
        # "upscale" prefix that task_id[:6] used to produce.
        token1 = body1["task_id"].split("_", 1)[1]
        token2 = body2["task_id"].split("_", 1)[1]
        assert token1 in body1["output_path"]
        assert token2 in body2["output_path"]
        assert body1["output_path"].endswith(".png")
        assert body1["output_path"].startswith("upscaled/")


class TestStatusResultLinkage:
    def test_status_returns_own_result_and_not_another_tasks(
        self, client, db_session, monkeypatch
    ):
        _patch_job_env(monkeypatch, db_session)
        storage.upload_object(_png_bytes(), "ship_link_a.png", "image/png")
        storage.upload_object(_png_bytes(color=(200, 40, 40)), "ship_link_b.png", "image/png")

        # Job A
        ra = client.post(
            "/api/upscale",
            json={"image_path": "ship_link_a.png", "scale": 2, "preset": "subtle"},
        )
        assert ra.status_code == 200
        a = ra.json()

        # Job B (different source, dispatched after A so A's asset exists first
        # if the TestClient drained background tasks synchronously)
        rb = client.post(
            "/api/upscale",
            json={"image_path": "ship_link_b.png", "scale": 2, "preset": "wild"},
        )
        assert rb.status_code == 200
        b = rb.json()

        # Ensure both jobs have executed end-to-end against the test DB.
        for body in (a, b):
            status = client.get(f"/api/upscale/status/{body['task_id']}").json()
            if status["status"] != "COMPLETED":
                execute_upscale_job(
                    task_id=body["task_id"],
                    image_path="ship_link_a.png" if body is a else "ship_link_b.png",
                    scale=body["scale"],
                    creativity=body["parameters"]["creativity"],
                    resemblance=body["parameters"]["resemblance"],
                    fractality=body["parameters"]["fractality"],
                    hdr=body["parameters"]["hdr"],
                    category=body["category"],
                    prompt=None,
                    output_path=body["output_path"],
                )

        sa = client.get(f"/api/upscale/status/{a['task_id']}").json()
        sb = client.get(f"/api/upscale/status/{b['task_id']}").json()

        assert sa["status"] == "COMPLETED"
        assert sb["status"] == "COMPLETED"
        assert sa["output_path"] == a["output_path"]
        assert sb["output_path"] == b["output_path"]
        assert sa["output_path"] != sb["output_path"]
        assert sa["result_url"]
        assert sb["result_url"]
        assert sa["result_url"] != sb["result_url"]

        # Both outputs are independently indexed in the media catalog.
        asset_a = (
            db_session.query(MediaAsset).filter(MediaAsset.file_path == a["output_path"]).first()
        )
        asset_b = (
            db_session.query(MediaAsset).filter(MediaAsset.file_path == b["output_path"]).first()
        )
        assert asset_a is not None
        assert asset_b is not None

    def test_status_ignores_non_upscale_tasks_and_near_miss_assets(
        self, client, db_session
    ):
        """Result resolution only applies to upscale_ tasks and exact suffixes.

        A completed non-upscale task whose id token appears in an unrelated
        asset, or an upscale task whose token only appears in a non-output
        file, must never resolve a result_url (review hardening).
        """
        from app.models import Task

        db_session.add(
            Task(
                task_id="export_deadbeef01",
                name="export something",
                status="COMPLETED",
                progress=100,
            )
        )
        db_session.add(
            MediaAsset(
                title="leak",
                file_path="processed/export_deadbeef01_leak.png",
                file_size=1,
                content_type="image/png",
            )
        )
        db_session.commit()

        s = client.get("/api/upscale/status/export_deadbeef01").json()
        assert s["status"] == "COMPLETED"
        assert s["output_path"] is None
        assert s["result_url"] is None

        token = "feedfacecafe12"
        db_session.add(
            Task(
                task_id=f"upscale_{token}",
                name="upscale: x (2x)",
                status="COMPLETED",
                progress=100,
            )
        )
        db_session.add(
            MediaAsset(
                title="near",
                file_path=f"notes_{token}.txt",
                file_size=1,
                content_type="text/plain",
            )
        )
        db_session.commit()

        s2 = client.get(f"/api/upscale/status/upscale_{token}").json()
        assert s2["status"] == "COMPLETED"
        assert s2["output_path"] is None
        assert s2["result_url"] is None


class TestPresetsAndCategoriesEndpoints:
    def test_presets_endpoint_returns_engine_registry(self, client):
        res = client.get("/api/upscale/presets")
        assert res.status_code == 200
        presets = res.json()["presets"]
        for name in ("subtle", "vivid", "wild", "custom"):
            assert name in presets
        assert presets["subtle"]["creativity"] == -4

    def test_categories_endpoint_returns_engine_registry(self, client):
        res = client.get("/api/upscale/categories")
        assert res.status_code == 200
        cats = res.json()["categories"]
        assert set(cats.keys()) == {
            "universal",
            "portraits",
            "landscapes",
            "anime",
            "architecture",
            "product",
        }
        assert "prompt_keywords" in cats["portraits"]
