"""Smoke tests asserting the router split preserved every pre-existing contract.

Each test below pins a path, a query-parameter name and the JSON keys that the
Playwright suite in ``frontend/e2e`` already asserts on. If the T-01 refactor
renamed anything, these fail.
"""

import pytest
from fastapi.routing import APIRoute, APIWebSocketRoute

from app.main import app
from app.models import MediaAsset

# Every path that existed in the pre-refactor monolithic main.py.
LEGACY_HTTP_ROUTES = {
    ("/", "GET"),
    ("/api/storage/upload", "POST"),
    ("/api/storage/list", "GET"),
    ("/api/storage/delete", "DELETE"),
    ("/api/storage/create-folder", "POST"),
    ("/api/tasks/process", "POST"),
    ("/api/tasks/status/{task_id}", "GET"),
    ("/api/settings", "GET"),
    ("/api/settings", "POST"),
    ("/api/colab/tunnel", "POST"),
    ("/api/generate/text", "POST"),
    ("/api/generate/audio", "POST"),
    ("/api/generate/image", "POST"),
    ("/api/media", "GET"),
    ("/api/media/search", "GET"),
}


def _walk_routes(routes):
    """Flatten routes, descending into included sub-routers.

    Recent FastAPI versions wrap ``include_router`` results in a container
    route rather than splicing the children into ``app.routes`` directly.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        nested = getattr(included, "routes", None) or getattr(route, "routes", None)
        if nested:
            yield from _walk_routes(nested)
        else:
            yield route


class TestRouteRegistry:
    def test_every_legacy_path_still_registered(self):
        registered = {
            (route.path, method)
            for route in _walk_routes(app.routes)
            if isinstance(route, APIRoute)
            for method in route.methods
            if method not in ("HEAD", "OPTIONS")
        }
        missing = LEGACY_HTTP_ROUTES - registered
        assert not missing, f"Routes lost in the refactor: {sorted(missing)}"

    def test_task_websocket_still_registered(self):
        ws_paths = {
            route.path
            for route in _walk_routes(app.routes)
            if isinstance(route, APIWebSocketRoute)
        }
        assert "/api/ws/tasks" in ws_paths

    def test_app_imports_without_circular_import_helper(self):
        import app.routers.tasks as tasks_router

        assert not hasattr(tasks_router, "celery_app_instance")

    def test_no_router_module_constructs_sessionlocal(self):
        import pkgutil

        import app.routers as routers_pkg

        offenders = []
        for mod in pkgutil.iter_modules(routers_pkg.__path__):
            path = f"{routers_pkg.__path__[0]}/{mod.name}.py"
            with open(path, "r", encoding="utf-8") as handle:
                if "SessionLocal(" in handle.read():
                    offenders.append(mod.name)
        assert not offenders, f"Routers still constructing sessions directly: {offenders}"


class TestRoot:
    def test_root_shape(self, client):
        res = client.get("/")
        assert res.status_code == 200
        assert res.json() == {
            "app": "FusionClip API Portal",
            "status": "Green",
            "database": "pgvector ready",
            "storage": "MinIO S3 integration live",
        }


class TestStorageRouter:
    def test_upload_returns_original_keys(self, client, stub_storage, db_session):
        res = client.post(
            "/api/storage/upload",
            files={"file": ("smoke.txt", b"hello world", "text/plain")},
        )
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"message", "filename", "path", "url"}
        assert body["message"] == "File uploaded successfully"
        assert body["filename"] == "smoke.txt"
        assert body["path"] == "smoke.txt"
        assert "smoke.txt" in stub_storage["uploaded"]

        asset = db_session.query(MediaAsset).filter(MediaAsset.file_path == "smoke.txt").one()
        assert asset.file_size == len(b"hello world")

    def test_upload_honours_folder_query_param(self, client, stub_storage):
        res = client.post(
            "/api/storage/upload?folder=/nested/dir/",
            files={"file": ("clip.mp4", b"bytes", "video/mp4")},
        )
        assert res.json()["path"] == "nested/dir/clip.mp4"
        assert "nested/dir/clip.mp4" in stub_storage["uploaded"]

    def test_list_uses_prefix_query_param(self, client):
        res = client.get("/api/storage/list?prefix=media")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"current_dir", "directories", "files"}
        assert body["current_dir"] == "media/"

    def test_delete_uses_path_query_param(self, client, stub_storage):
        res = client.delete("/api/storage/delete?path=obsolete.bin")
        assert res.status_code == 200
        assert res.json() == {
            "message": "Successfully deleted object matching key: obsolete.bin"
        }
        assert "obsolete.bin" in stub_storage["deleted"]

    def test_create_folder_uses_folder_path_query_param(self, client):
        res = client.post("/api/storage/create-folder?folder_path=/projects/alpha/")
        assert res.status_code == 200
        assert res.json() == {
            "message": "Folder directory structure created successfully",
            "path": "projects/alpha/",
        }

    def test_create_folder_rejects_empty_path(self, client):
        assert client.post("/api/storage/create-folder?folder_path=/").status_code == 400


class TestTasksRouter:
    def test_process_dispatch_shape(self, client, monkeypatch):
        class _FakeAsyncResult:
            id = "smoke-task-id"
            status = "PENDING"

        recorded = {}

        def _fake_delay(path, task_type):
            recorded["args"] = (path, task_type)
            return _FakeAsyncResult()

        monkeypatch.setattr(
            "app.routers.tasks.process_multimedia_task.delay", _fake_delay, raising=True
        )

        res = client.post("/api/tasks/process?path=clip.mp4&task_type=thumbnail")
        assert res.status_code == 200
        assert res.json() == {
            "message": "Processing pipeline initiated successfully",
            "task_id": "smoke-task-id",
            "status": "PENDING",
        }
        assert recorded["args"] == ("clip.mp4", "thumbnail")

    def test_status_shape(self, client, monkeypatch):
        class _Result:
            state = "SUCCESS"
            result = {"processed_url": "http://test-minio/out.mp4"}

        monkeypatch.setattr("app.routers.tasks.AsyncResult", lambda *a, **k: _Result())

        res = client.get("/api/tasks/status/abc-123")
        assert res.status_code == 200
        assert res.json() == {
            "id": "abc-123",
            "state": "SUCCESS",
            "info": {"processed_url": "http://test-minio/out.mp4"},
        }

    @pytest.mark.parametrize(
        "state,raw,expected",
        [
            ("PENDING", None, None),
            ("PROGRESS", {"percent": 40}, {"percent": 40}),
            ("FAILURE", RuntimeError("boom"), "boom"),
        ],
    )
    def test_status_info_per_state(self, client, monkeypatch, state, raw, expected):
        class _Result:
            pass

        _Result.state = state
        _Result.info = raw
        _Result.result = raw

        monkeypatch.setattr("app.routers.tasks.AsyncResult", lambda *a, **k: _Result())
        assert client.get("/api/tasks/status/x").json()["info"] == expected


class TestSettingsRouter:
    def test_settings_roundtrip(self, client):
        payload = {"e2e_test_key": "value-1", "another_key": "another_value"}
        saved = client.post("/api/settings", json=payload)
        assert saved.status_code == 200
        assert saved.json() == {
            "status": "SUCCESS",
            "message": "Settings saved successfully.",
        }

        retrieved = client.get("/api/settings").json()
        assert retrieved["e2e_test_key"] == "value-1"
        assert retrieved["another_key"] == "another_value"

    def test_settings_values_are_stringified(self, client):
        client.post("/api/settings", json={"numeric": 42})
        assert client.get("/api/settings").json()["numeric"] == "42"

    def test_colab_tunnel_shape_and_persistence(self, client):
        url = "https://smoke-tunnel.trycloudflare.com"
        res = client.post(f"/api/colab/tunnel?url={url}&status=running")
        assert res.status_code == 200
        assert res.json() == {
            "status": "SUCCESS",
            "colab_url": url,
            "colab_status": "running",
        }

        settings_body = client.get("/api/settings").json()
        assert settings_body["colab_tunnel_url"] == url
        assert settings_body["colab_tunnel_status"] == "running"

    def test_colab_tunnel_updates_existing_rows(self, client):
        client.post("/api/colab/tunnel?url=https://one.test&status=running")
        client.post("/api/colab/tunnel?url=https://two.test&status=disconnected")
        body = client.get("/api/settings").json()
        assert body["colab_tunnel_url"] == "https://two.test"
        assert body["colab_tunnel_status"] == "disconnected"


class TestGenerateRouter:
    def test_generate_text_shape(self, client):
        prompt = "A cinematic drone shot over a canyon"
        res = client.post(f"/api/generate/text?prompt={prompt.replace(' ', '+')}")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "output"}
        assert body["status"] == "COMPLETED"
        # Relaxed (L-4): pins the mock string today, but T-07 will replace
        # the mock with a real Gemini call and break this assertion.
        # Verify non-empty output + correct status only.
        assert body["output"]

    def test_generate_audio_no_longer_raises_nameerror(self, client, stub_storage, db_session):
        """Regression: `time` was never imported in the old main.py (NameError)."""
        res = client.post("/api/generate/audio?prompt=Smoke+test+voice&type=tts")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "type", "filename", "url"}
        assert body["status"] == "COMPLETED"
        assert body["type"] == "tts"
        assert body["filename"].startswith("gen_audio_")
        assert body["filename"].endswith(".mp3")
        assert body["url"]
        assert body["filename"] in stub_storage["uploaded"]

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "audio/mpeg"

    def test_generate_image_no_longer_raises_nameerror(self, client, stub_storage, db_session):
        res = client.post("/api/generate/image?prompt=Smoke+test+art&steps=10&scale=7.0")
        assert res.status_code == 200
        body = res.json()
        assert set(body) == {"status", "parameters", "filename", "url"}
        assert body["status"] == "COMPLETED"
        assert body["parameters"] == {"steps": 10, "scale": 7.0}
        assert body["filename"].startswith("gen_image_")
        assert body["filename"].endswith(".png")
        assert body["filename"] in stub_storage["uploaded"]

        asset = (
            db_session.query(MediaAsset)
            .filter(MediaAsset.file_path == body["filename"])
            .one()
        )
        assert asset.content_type == "image/png"

    def test_generate_image_defaults(self, client, stub_storage):
        body = client.post("/api/generate/image?prompt=Defaults").json()
        assert body["parameters"] == {"steps": 28, "scale": 7.5}


class TestMediaRouter:
    ASSET_KEYS = {
        "id",
        "title",
        "file_path",
        "file_size",
        "content_type",
        "duration",
        "url",
        "created_at",
    }

    def _seed(self, db_session):
        db_session.add_all(
            [
                MediaAsset(
                    title="Sunset timelapse",
                    file_path="clips/sunset.mp4",
                    file_size=2048,
                    content_type="video/mp4",
                    duration=12.5,
                ),
                MediaAsset(
                    title="Narration take one",
                    file_path="audio/narration.mp3",
                    file_size=512,
                    content_type="audio/mpeg",
                    duration=30.0,
                ),
            ]
        )
        db_session.commit()

    def test_list_media_shape(self, client, db_session, stub_storage):
        self._seed(db_session)
        res = client.get("/api/media")
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 2
        for item in body:
            assert set(item) == self.ASSET_KEYS
            assert item["url"].startswith("http://test-minio/")

    def test_list_media_empty(self, client):
        assert client.get("/api/media").json() == []

    def test_search_uses_query_and_limit_params(self, client, db_session, stub_storage):
        self._seed(db_session)
        res = client.get("/api/media/search?query=sunset&limit=5")
        assert res.status_code == 200
        body = res.json()
        assert len(body) == 1
        assert set(body[0]) == self.ASSET_KEYS
        assert body[0]["title"] == "Sunset timelapse"

    def test_search_falls_back_when_vector_search_unavailable(
        self, client, db_session, stub_storage
    ):
        """Without pgvector the vector branch raises and ILIKE takes over."""
        self._seed(db_session)
        res = client.get("/api/media/search?query=narration")
        assert res.status_code == 200
        assert [item["title"] for item in res.json()] == ["Narration take one"]

    def test_search_no_matches(self, client, db_session, stub_storage):
        self._seed(db_session)
        assert client.get("/api/media/search?query=nonexistent").json() == []


class TestDependencyOverride:
    def test_get_db_is_overridable(self, client, db_session):
        """The fixture itself proves dependency_overrides works end to end."""
        from app.deps import get_db

        assert get_db in app.dependency_overrides
        client.post("/api/settings", json={"override_probe": "yes"})
        from app.models import Configuration

        assert (
            db_session.query(Configuration)
            .filter(Configuration.key == "override_probe")
            .one()
            .value
            == "yes"
        )
