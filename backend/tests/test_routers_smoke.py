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


class TestColabEndpoints:
    def test_colab_websocket_authentication(self, client):
        # Without token
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/colab") as websocket:
                pass

        # With invalid token
        with pytest.raises(Exception):
            with client.websocket_connect("/api/ws/colab?token=bad-token") as websocket:
                pass

    def test_colab_websocket_connect(self, client, stub_redis, db_session):
        from app.config import settings
        from app.models import Configuration
        # With valid token
        token = settings.FUSIONCLIP_SECRET_KEY
        with client.websocket_connect(f"/api/ws/colab?token={token}") as websocket:
            # Check DB updated status
            status_row = db_session.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
            assert status_row is not None
            assert status_row.value == "running"
            # Check Redis state
            assert stub_redis.get("colab:connected") == b"true"
        
        # After disconnect, status should be disconnected
        db_session.expire_all()
        status_row = db_session.query(Configuration).filter(Configuration.key == "colab_tunnel_status").first()
        assert status_row.value == "disconnected"
        assert stub_redis.get("colab:connected") == b"false"

    def test_colab_http_endpoints_auth(self, client):
        # 1. pending tasks
        res = client.get("/api/colab/tasks/pending")
        assert res.status_code == 401
        
        res = client.get("/api/colab/tasks/pending?token=invalid")
        assert res.status_code == 401

        # 2. update task
        res = client.post("/api/colab/tasks/update", json={"task_id": "t1", "status": "COMPLETED", "progress": 100})
        assert res.status_code == 401

        # 3. metrics
        res = client.post("/api/colab/metrics", json={
            "vram_used": 1.0, "vram_total": 8.0, "ram_used": 2.0, "ram_total": 16.0, "cpu_load": 10.0
        })
        assert res.status_code == 401

    def test_colab_http_pending_tasks(self, client, stub_redis):
        from app.config import settings
        token = settings.FUSIONCLIP_SECRET_KEY
        
        # Pull when empty
        res = client.get(f"/api/colab/tasks/pending?token={token}")
        assert res.status_code == 200
        assert res.json() == {"task": None}
        
        # Push mock task to Redis list
        import json
        task_payload = {"task_id": "test_id_123", "task_type": "transcode"}
        stub_redis.rpush("colab_pending_tasks_http", json.dumps(task_payload))
        
        # Pull again
        res = client.get(f"/api/colab/tasks/pending?token={token}")
        assert res.status_code == 200
        assert res.json() == task_payload

    def test_colab_http_update_task(self, client, stub_redis, db_session):
        from app.config import settings
        from app.models import Task
        import json
        token = settings.FUSIONCLIP_SECRET_KEY
        
        # Seed Task in DB
        task_id = "test_task_http_update"
        db_task = Task(task_id=task_id, name="transcode", status="PROCESSING", progress=50)
        db_session.add(db_task)
        db_session.commit()
        
        # Update via HTTP
        payload = {
            "task_id": task_id,
            "status": "COMPLETED",
            "progress": 100,
            "output": {"url": "http://test-output.mp4"}
        }
        res = client.post(f"/api/colab/tasks/update?token={token}", json=payload)
        assert res.status_code == 200
        
        # Verify DB updated
        db_session.expire_all()
        updated_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert updated_task.status == "COMPLETED"
        assert updated_task.progress == 100
        
        # Verify Redis state
        task_res = stub_redis.get(f"colab_task_result:{task_id}")
        assert task_res is not None
        assert json.loads(task_res)["status"] == "SUCCESS"

    def test_colab_http_metrics(self, client, stub_redis, db_session):
        from app.config import settings
        from app.models import Configuration
        import json
        token = settings.FUSIONCLIP_SECRET_KEY
        
        # Get metrics initially empty
        res = client.get("/api/colab/metrics")
        assert res.status_code == 200
        assert res.json()["status"] == "disconnected"
        
        # Post metrics
        metrics_payload = {
            "vram_used": 4.0,
            "vram_total": 8.0,
            "ram_used": 8.0,
            "ram_total": 16.0,
            "cpu_load": 45.5,
            "active_task": "upscale"
        }
        res = client.post(f"/api/colab/metrics?token={token}", json=metrics_payload)
        assert res.status_code == 200
        
        # Get updated metrics
        res = client.get("/api/colab/metrics")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "connected"
        assert body["metrics"]["vram_used"] == 4.0
        assert body["metrics"]["vram_percent"] == 50.0
        assert body["metrics"]["ram_percent"] == 50.0
        assert body["metrics"]["cpu_load"] == 45.5
        assert body["metrics"]["active_task"] == "upscale"

    def test_colab_image_generation_routing(self, client, stub_redis, db_session):
        # Set Colab as connected
        stub_redis.set("colab:connected", "true")
        
        # We need a background thread/task to pretend to be Colab and complete the task.
        # Since this runs synchronously in pytest-fastapi-testclient, we can just pre-populate
        # the redis result key beforehand, or run a mock to write it once published.
        # Let's write a thread to monitor dispatches and write back a completion response!
        import json
        import threading
        import time
        
        def mock_colab_worker():
            # Wait for dispatch log
            pubsub = stub_redis.pubsub()
            pubsub.subscribe("colab_dispatches")
            # Let's wait for message
            start = time.time()
            while time.time() - start < 5:
                msg = pubsub.get_message(ignore_subscribe_messages=True)
                if msg:
                    data = json.loads(msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"])
                    task_id = data["task_id"]
                    # Write completion response
                    stub_redis.set(f"colab_task_result:{task_id}", json.dumps({
                        "status": "SUCCESS",
                        "output": {
                            "url": "http://test-colab-output/image.png",
                            "filename": "colab_output.png"
                        }
                    }))
                    break
                time.sleep(0.05)
            pubsub.close()
            
        t = threading.Thread(target=mock_colab_worker)
        t.start()
        
        # Trigger generation: it will dispatch to Colab and wait for result
        res = client.post("/api/generate/image?prompt=scenic+view")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "COMPLETED"
        assert body["url"] == "http://test-colab-output/image.png"
        assert body["colab"] is True
        
        t.join()

    def test_colab_generation_timeout(self, client, stub_redis):
        # Set Colab as connected
        stub_redis.set("colab:connected", "true")
        
        # Trigger generation: it will dispatch to Colab, wait, and timeout (we change timeout locally or mock it)
        # To avoid waiting 60s in tests, let's mock dispatch_gen_to_colab timeout parameter to 0.5s!
        import app.routers.generate as gen_router
        orig_dispatch = gen_router.dispatch_gen_to_colab
        
        def mock_dispatch(task_type, parameters, db, timeout=60, file_extension="png", content_type="image/png"):
            return orig_dispatch(task_type, parameters, db, timeout=0.1, file_extension=file_extension, content_type=content_type)
            
        gen_router.dispatch_gen_to_colab = mock_dispatch
        try:
            res = client.post("/api/generate/image?prompt=scenic+view")
            assert res.status_code == 504
        finally:
            gen_router.dispatch_gen_to_colab = orig_dispatch

    def test_colab_celery_task_routing(self, stub_redis, db_session):
        from app.tasks import process_media_heavy
        from app.models import Task
        
        # Set Colab as connected
        stub_redis.set("colab:connected", "true")
        
        # We need a mock worker thread to respond to the Celery task dispatch
        import json
        import threading
        import time
        
        task_id = "test-celery-colab-task"
        
        # Seed Task in DB
        db_task = Task(task_id=task_id, name="transcode", status="PROCESSING", progress=0)
        db_session.add(db_task)
        db_session.commit()
        
        def mock_colab_worker():
            # Wait for dispatch log
            pubsub = stub_redis.pubsub()
            pubsub.subscribe("colab_dispatches")
            start = time.time()
            while time.time() - start < 5:
                msg = pubsub.get_message(ignore_subscribe_messages=True)
                if msg:
                    data = json.loads(msg["data"].decode() if isinstance(msg["data"], bytes) else msg["data"])
                    task_id_extracted = data["task_id"]
                    # Write completion response
                    stub_redis.set(f"colab_task_result:{task_id_extracted}", json.dumps({
                        "status": "SUCCESS",
                        "output": {
                            "url": "http://test-colab-heavy-output/processed.mp4",
                            "filename": "processed.mp4"
                        }
                    }))
                    break
                time.sleep(0.05)
            pubsub.close()
            
        t = threading.Thread(target=mock_colab_worker)
        t.start()
        
        # Run Celery task on main thread (mocking self.request.id class/task reference)
        process_media_heavy.request.id = task_id
        result = process_media_heavy.run("raw_video.mp4", "transcode")
        
        assert result["status"] == "COMPLETED"
        assert result["processed_url"] == "http://test-colab-heavy-output/processed.mp4"
        
        t.join()