"""End-to-End integration harness testing Colab worker dispatch, real progress, and artifact landing."""

import json
import os
import sys
import threading
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.main import app
from app.config import settings
from app.deps import get_db
from app.models import MediaAsset, Task
from colab_client import ColabComputeWorker


def test_colab_http_fallback_e2e_harness(client, db_session):
    """E2E Test: Exercises full flow without physical Colab.
    
    1. Dispatch task to Colab via HTTP/Redis queue.
    2. ColabComputeWorker (fake mode) polls /api/colab/tasks/pending.
    3. Worker executes handler, reports per-step progress to /api/colab/tasks/update.
    4. Worker uploads generated PNG artifact to /api/storage/upload.
    5. Worker posts completion with uploaded artifact URL.
    6. Verifies Task completes with progress=100 and MediaAsset is recorded.
    """
    db = db_session
    
    # 1. Setup a Task in database
    task_id = "test_colab_e2e_001"
    task = Task(task_id=task_id, name="image_generation", status="PROCESSING", progress=0)
    db.add(task)
    db.commit()
    
    # Push dispatch payload into colab_pending_tasks_http
    from app.routers.settings import redis_client
    dispatch_payload = {
        "type": "task_dispatch",
        "task_id": task_id,
        "task_type": "image_generation",
        "parameters": {"prompt": "A scenic sunset over mountain peaks"}
    }
    redis_client.rpush("colab_pending_tasks_http", json.dumps(dispatch_payload))
    
    # 2. Instantiate ColabComputeWorker in fake mode pointing to TestClient adapter
    worker = ColabComputeWorker(
        server_url="http://testserver",
        token=settings.FUSIONCLIP_SECRET_KEY,
        fake_mode=True
    )
    
    # Bridge requests.post and requests.get to fastapi TestClient
    def mock_requests_post(url, *args, **kwargs):
        endpoint = url.replace("http://testserver", "")
        # Handle files
        if "files" in kwargs:
            files = kwargs["files"]
            params = kwargs.get("params", {})
            # Read bytes for testclient
            file_tuple = files["file"]
            filename, file_obj, content_type = file_tuple
            file_bytes = file_obj.read() if hasattr(file_obj, "read") else file_obj
            res = client.post(
                endpoint,
                files={"file": (filename, file_bytes, content_type)},
                params=params
            )
        else:
            json_data = kwargs.get("json")
            res = client.post(endpoint, json=json_data)
        
        mock_resp = MagicMock()
        mock_resp.status_code = res.status_code
        mock_resp.json = res.json
        mock_resp.text = res.text
        return mock_resp

    def mock_requests_get(url, *args, **kwargs):
        endpoint = url.replace("http://testserver", "")
        res = client.get(endpoint)
        mock_resp = MagicMock()
        mock_resp.status_code = res.status_code
        mock_resp.json = res.json
        mock_resp.text = res.text
        return mock_resp

    with patch("requests.post", side_effect=mock_requests_post), \
         patch("requests.get", side_effect=mock_requests_get):
    
        # 3. Simulate one round of HTTP polling
        res = mock_requests_get(f"http://testserver/api/colab/tasks/pending?token={settings.FUSIONCLIP_SECRET_KEY}")
        assert res.status_code == 200
        data = res.json()
        pending_task = data.get("task") or data
        assert pending_task.get("task_id") == task_id
        
        # 4. Worker executes task
        worker.execute_task(
            pending_task["task_id"],
            pending_task["task_type"],
            pending_task.get("parameters", {})
        )
        
        # 5. Check task status in database
        db.refresh(task)
        assert task.status == "COMPLETED"
        assert task.progress == 100
        
        # Check result in Redis
        result_key = f"colab_task_result:{task_id}"
        res_data = redis_client.get(result_key)
        assert res_data is not None
        res_json = json.loads(res_data)
        assert res_json["status"] == "SUCCESS"
        assert "url" in res_json["output"]
        assert "colab_fake_" in res_json["output"]["filename"]
        
        # Check MediaAsset was landed in storage and DB
        uploaded_filename = res_json["output"]["filename"]
        asset = db.query(MediaAsset).filter(MediaAsset.file_path == uploaded_filename).first()
        assert asset is not None
        assert asset.file_size > 0


def _wait_for(db, task, predicate, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        db.refresh(task)
        if predicate(task):
            return
        time.sleep(0.05)
    db.refresh(task)


def test_colab_websocket_e2e_harness(client, db_session):
    """E2E Test: Exercises dispatch, per-step progress, and completion over WebSocket bridge."""
    db = db_session
    from app.routers.settings import redis_client

    task_id = "test_colab_ws_002"
    task = Task(task_id=task_id, name="image_generation", status="PROCESSING", progress=0)
    db.add(task)
    db.commit()

    with client.websocket_connect(f"/api/ws/colab?token={settings.FUSIONCLIP_SECRET_KEY}") as ws:
        # 1. Send per-step progress update
        ws.send_json({
            "type": "task_progress",
            "task_id": task_id,
            "percent": 45
        })
        _wait_for(db, task, lambda t: t.progress == 45)

        assert task.status == "PROCESSING"
        assert task.progress == 45

        # 2. Upload artifact through storage
        upload_resp = client.post(
            "/api/storage/upload",
            files={"file": ("colab_ws_test.png", b"\x89PNG\r\n\x1a\nrealbytes", "image/png")}
        )
        assert upload_resp.status_code == 200
        upload_data = upload_resp.json()

        # 3. Send task_complete with artifact output
        ws.send_json({
            "type": "task_complete",
            "task_id": task_id,
            "output": {
                "url": upload_data["url"],
                "filename": upload_data["filename"],
                "path": upload_data["path"]
            }
        })
        _wait_for(db, task, lambda t: t.status == "COMPLETED")

        assert task.status == "COMPLETED"
        assert task.progress == 100

        # Check Redis result key
        res_data = redis_client.get(f"colab_task_result:{task_id}")
        assert res_data is not None
        res_json = json.loads(res_data)
        assert res_json["status"] == "SUCCESS"
        assert res_json["output"]["filename"] == "colab_ws_test.png"


def test_colab_failure_lifecycle_http(client, db_session):
    """Verify failed tasks report progress 0 and status FAILED over HTTP."""
    db = db_session
    task_id = "test_colab_fail_003"
    task = Task(task_id=task_id, name="image_generation", status="PROCESSING", progress=30)
    db.add(task)
    db.commit()

    # Update task with failure via HTTP
    res = client.post(
        "/api/colab/tasks/update",
        headers={"Authorization": f"Bearer {settings.FUSIONCLIP_SECRET_KEY}"},
        json={
            "task_id": task_id,
            "status": "FAILED",
            "progress": 30, # Should be forced to 0
            "error": "CUDA out of memory"
        }
    )
    assert res.status_code == 200

    db.refresh(task)
    assert task.status == "FAILED"
    assert task.progress == 0
    assert task.error == "CUDA out of memory"


def test_colab_auth_rejection(client):
    """Verify unauthorized requests are rejected cleanly, including non-ASCII tokens."""
    res = client.get("/api/colab/tasks/pending?token=wrong-secret")
    assert res.status_code == 401

    # Non-ASCII token should return 401, not crash with 500
    res = client.get("/api/colab/tasks/pending?token=é_invalid")
    assert res.status_code == 401

    res = client.post(
        "/api/colab/tasks/update",
        headers={"Authorization": "Bearer bad-token"},
        json={"task_id": "none", "status": "FAILED", "progress": 0}
    )
    assert res.status_code == 401

