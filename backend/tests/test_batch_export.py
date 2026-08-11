"""Tests for the batch export/download endpoint (Wayfinder ticket #48)."""


class _FakeAsyncResult:
    id = "batch-task-1"
    status = "PENDING"


class TestBatchExport:
    def test_download_batch_dispatches_task_with_paths_and_format(
        self, client, monkeypatch
    ):
        recorded = {}

        def _fake_delay(paths, export_format):
            recorded["args"] = (paths, export_format)
            return _FakeAsyncResult()

        monkeypatch.setattr(
            "app.routers.storage.export_batch_zip.delay",
            _fake_delay,
            raising=True,
        )

        res = client.post(
            "/api/storage/download-batch",
            json={"paths": ["clip.mp4", "audio.mp3"], "format": "original"},
        )
        assert res.status_code == 200
        assert res.json() == {
            "message": "Batch export initiated successfully",
            "task_id": "batch-task-1",
            "status": "PENDING",
        }
        assert recorded["args"] == (
            ["clip.mp4", "audio.mp3"],
            "original",
        )

    def test_download_batch_defaults_format_to_original(self, client, monkeypatch):
        recorded = {}

        def _fake_delay(paths, export_format):
            recorded["args"] = (paths, export_format)
            return _FakeAsyncResult()

        monkeypatch.setattr(
            "app.routers.storage.export_batch_zip.delay",
            _fake_delay,
            raising=True,
        )

        res = client.post(
            "/api/storage/download-batch",
            json={"paths": ["photo.png"]},
        )
        assert res.status_code == 200
        assert recorded["args"] == (["photo.png"], "original")

    def test_download_batch_rejects_empty_paths(self, client):
        res = client.post(
            "/api/storage/download-batch",
            json={"paths": []},
        )
        assert res.status_code == 422

    def test_download_batch_route_is_registered(self):
        from app.main import app
        from fastapi.routing import APIRoute

        def _walk_routes(routes):
            for route in routes:
                included = getattr(route, "original_router", None)
                nested = getattr(included, "routes", None) or getattr(route, "routes", None)
                if nested:
                    yield from _walk_routes(nested)
                else:
                    yield route

        paths = {
            route.path
            for route in _walk_routes(app.routes)
            if isinstance(route, APIRoute)
        }
        assert "/api/storage/download-batch" in paths
