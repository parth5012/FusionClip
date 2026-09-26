import pytest
from unittest.mock import MagicMock, patch
from app.models import Task

@patch("app.routers.tasks.process_upscale_task.apply_async")
def test_upscale_endpoint_dispatches(mock_apply_async, client, db_session):
    response = client.post(
        "/api/upscale?path=test_image.png",
        json={
            "denoising_strength": 0.4,
            "controlnet_weight": 1.2,
            "preset": "Portraits",
            "preview": False
        }
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["message"] == "Upscale task initiated successfully"
    assert "task_id" in data
    assert data["status"] == "PROCESSING"
    
    # Verify task database record exists
    task_id = data["task_id"]
    db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
    assert db_task is not None
    assert db_task.name == "upscale"
    assert db_task.status == "PROCESSING"
    
    # Verify Celery apply_async params
    mock_apply_async.assert_called_once_with(
        args=[task_id, "test_image.png", {
            "denoising_strength": 0.4,
            "controlnet_weight": 1.2,
            "preset": "Portraits",
            "preview": False
        }],
        task_id=task_id
    )
