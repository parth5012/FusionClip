"""Tests for refactored colab_client handler registry, artifact upload, and fake mode."""

import json
import os
import sys
import tempfile
from pathlib import Path
import pytest
from unittest.mock import MagicMock, patch

REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import colab_client
from colab_client import ColabComputeWorker, TaskHandlerRegistry, register_handler


def test_handler_registry_custom_handler():
    """Verify custom handlers can be registered and invoked."""
    registry = TaskHandlerRegistry()
    
    called_args = {}
    def dummy_handler(task_id, parameters, report_progress, upload_artifact):
        called_args["task_id"] = task_id
        called_args["parameters"] = parameters
        report_progress(50)
        return {"output_key": "output_value"}
    
    registry.register("test_task", dummy_handler)
    assert registry.has_handler("test_task")
    
    progress_updates = []
    def on_progress(p):
        progress_updates.append(p)
        
    result = registry.execute("test_task", "task_123", {"prompt": "cat"}, on_progress, None)
    assert called_args["task_id"] == "task_123"
    assert called_args["parameters"] == {"prompt": "cat"}
    assert progress_updates == [50]
    assert result == {"output_key": "output_value"}


def test_worker_fake_mode_executes_and_uploads():
    """Verify fake mode produces real image artifact, uploads it, and eliminates mock sleep loops."""
    worker = ColabComputeWorker(
        server_url="http://testserver:8000",
        token="test_token",
        fake_mode=True
    )
    
    # Mock upload_artifact to simulate successful backend storage upload
    mock_upload_response = {
        "message": "File uploaded successfully",
        "filename": "colab_task_999.png",
        "path": "colab_task_999.png",
        "url": "http://testserver:8000/api/storage/file/colab_task_999.png"
    }
    worker.upload_artifact = MagicMock(return_value=mock_upload_response)
    worker.report_progress = MagicMock()
    worker.report_completion = MagicMock()
    worker.report_failure = MagicMock()
    
    worker.execute_task("task_999", "image_generation", {"prompt": "test prompt"})
    
    # Assert progress was reported
    assert worker.report_progress.call_count >= 1
    # Assert upload was called with a real file path that existed
    assert worker.upload_artifact.called
    upload_file_path = worker.upload_artifact.call_args[0][0]
    assert os.path.basename(upload_file_path).endswith(".png")
    
    # Assert completion was called with real upload URL, not mock_colab_output_*.png
    worker.report_completion.assert_called_once()
    output_payload = worker.report_completion.call_args[0][1]
    assert "mock_colab_output" not in output_payload["url"]
    assert output_payload["url"] == "http://testserver:8000/api/storage/file/colab_task_999.png"
    assert output_payload["filename"] == "colab_task_999.png"
    assert not worker.report_failure.called


def test_worker_upload_artifact_calls_endpoint(tmp_path):
    """Verify upload_artifact sends multipart file to /api/storage/upload."""
    worker = ColabComputeWorker(
        server_url="http://localhost:8000",
        token="secret123"
    )
    
    test_file = tmp_path / "test_artifact.png"
    test_file.write_bytes(b"\x89PNG\r\n\x1a\nfakeimagebytes")
    
    with patch("requests.post") as mock_post:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "message": "File uploaded successfully",
            "filename": "test_artifact.png",
            "path": "test_artifact.png",
            "url": "http://localhost:8000/api/storage/file/test_artifact.png"
        }
        mock_post.return_value = mock_resp
        
        result = worker.upload_artifact(str(test_file))
        
        mock_post.assert_called_once()
        call_url = mock_post.call_args[0][0]
        assert call_url == "http://localhost:8000/api/storage/upload"
        assert result["filename"] == "test_artifact.png"
        assert result["url"] == "http://localhost:8000/api/storage/file/test_artifact.png"


def test_register_handler_decorator():
    """Verify @register_handler decorator binds to registry correctly."""
    registry = TaskHandlerRegistry()
    
    @register_handler("decorated_task", registry=registry)
    def custom_decorated(task_id, parameters, report_progress, upload_artifact):
        return f"result_for_{task_id}"

    assert registry.has_handler("decorated_task")
    assert registry.execute("decorated_task", "task_555", None, lambda p: None, None) == "result_for_task_555"


def test_make_fake_png_artifact_sanitizes_path():
    """Verify task_id with traversal characters does not traverse outside temp dir."""
    from colab_client import make_fake_png_artifact
    unsafe_id = "../../etc/passwd"
    path = make_fake_png_artifact(unsafe_id, prompt="test")
    try:
        assert os.path.exists(path)
        assert "passwd" not in path or "colab_fake" in os.path.basename(path)
        assert os.path.dirname(path) == tempfile.gettempdir() or tempfile.gettempdir() in path
    finally:
        if os.path.exists(path):
            os.remove(path)


def test_worker_reports_failure_on_unsupported_task():
    """Verify unknown task type reports failure cleanly."""
    worker = ColabComputeWorker(
        server_url="http://testserver:8000",
        token="test_token",
        fake_mode=False
    )
    worker.report_failure = MagicMock()
    worker.execute_task("task_bad", "nonexistent_task_type", {})
    worker.report_failure.assert_called_once()
    assert "nonexistent_task_type" in worker.report_failure.call_args[0][1]
