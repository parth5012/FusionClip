"""Regression tests for task_type validation and rejecting unverified pipelines (#81)."""

import pytest


class TestTaskTypeValidation:
    def test_unknown_task_type_rejected_with_400(self, client):
        """POST /api/tasks/process must reject unknown/unimplemented task types with 400."""
        # 'upscale'/'video_upscale' are real pipelines now (#96 + upscaler), so
        # only genuinely unknown names must trip the enum guard.
        res = client.post("/api/tasks/process?path=sample.mp4&task_type=unknown_pipeline")
        assert res.status_code == 400
        assert "Invalid task_type 'unknown_pipeline'" in res.json()["detail"]
        assert "Allowed types" in res.json()["detail"]

        # Completely bogus pipeline name
        res_bogus = client.post("/api/tasks/process?path=sample.mp4&task_type=definitely_not_real")
        assert res_bogus.status_code == 400

    def test_implemented_task_types_accepted(self, client, monkeypatch):
        """All supported pipeline types must be accepted."""
        # Mock Celery delay to avoid needing live Redis broker in unit test
        class DummyTask:
            id = "mock-task-123"
            status = "PENDING"

        monkeypatch.setattr(
            "app.routers.tasks.process_multimedia_task.delay",
            lambda path, task_type: DummyTask(),
        )

        for task_type in ["transcode", "thumbnail", "waveform", "audio_extract"]:
            res = client.post(f"/api/tasks/process?path=sample.mp4&task_type={task_type}")
            assert res.status_code == 200
            data = res.json()
            assert data["task_id"] == "mock-task-123"
            assert data["status"] == "PENDING"

    def test_default_task_type_is_transcode(self, client, monkeypatch):
        """When task_type is omitted, defaults to transcode and succeeds."""
        class DummyTask:
            id = "mock-task-def"
            status = "PENDING"

        monkeypatch.setattr(
            "app.routers.tasks.process_multimedia_task.delay",
            lambda path, task_type: DummyTask(),
        )

        res = client.post("/api/tasks/process?path=sample.mp4")
        assert res.status_code == 200
        assert res.json()["task_id"] == "mock-task-def"
