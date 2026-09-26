"""Tests for task queue counts endpoint and WebSocket frame contract (#107)."""

import json
import pytest
from app.models import Task


class TestTaskCountsEndpoint:
    """Test GET /api/tasks/counts bucket aggregation and Redis LLEN integration."""

    def test_counts_empty_returns_zeroes(self, client):
        """When no tasks exist in DB or Redis, all counts must be 0."""
        res = client.get("/api/tasks/counts")
        assert res.status_code == 200
        data = res.json()
        assert data == {
            "running": 0,
            "pending": 0,
            "failed": 0,
            "completed": 0,
        }

    def test_counts_buckets_from_database(self, client, db_session):
        """Tasks in DB must be mapped to running, pending, failed, completed buckets."""
        tasks = [
            Task(task_id="t-run-1", name="transcode", status="PROCESSING", progress=40),
            Task(task_id="t-run-2", name="upscale", status="PROGRESS", progress=75),
            Task(task_id="t-run-3", name="waveform", status="RUNNING", progress=10),
            Task(task_id="t-run-4", name="transcode", status="RETRYING", progress=0),
            Task(task_id="t-pend-1", name="thumbnail", status="PENDING", progress=0),
            Task(task_id="t-pend-2", name="waveform", status="PENDING_RETRY", progress=0),
            Task(task_id="t-pend-3", name="upscale", status="QUEUED", progress=0),
            Task(task_id="t-fail-1", name="transcode", status="FAILED", progress=0, error="OOM"),
            Task(task_id="t-fail-2", name="upscale", status="FAILURE", progress=0, error="Timeout"),
            Task(task_id="t-comp-1", name="transcode", status="COMPLETED", progress=100),
            Task(task_id="t-comp-2", name="thumbnail", status="SUCCESS", progress=100),
        ]
        for t in tasks:
            db_session.add(t)
        db_session.commit()

        res = client.get("/api/tasks/counts")
        assert res.status_code == 200
        data = res.json()
        assert data["running"] == 4
        assert data["pending"] == 3
        assert data["failed"] == 2
        assert data["completed"] == 2

    def test_counts_redis_llen_added_to_pending(self, client, db_session, stub_redis):
        """Redis queue lengths (Celery broker queues) must be added to pending count."""
        # 1 task in DB as pending
        db_session.add(Task(task_id="t-pend-db", name="transcode", status="PENDING", progress=0))
        db_session.commit()

        # Add items to Redis Celery queues
        stub_redis.rpush("celery", "msg-1", "msg-2")
        stub_redis.rpush("media.fast", "msg-3")
        stub_redis.rpush("media.heavy", "msg-4", "msg-5")

        res = client.get("/api/tasks/counts")
        assert res.status_code == 200
        data = res.json()
        # 1 from DB + 2 from celery + 1 from media.fast + 2 from media.heavy = 6
        assert data["pending"] == 6

    def test_counts_unknown_status_excluded(self, client, db_session):
        """Statuses outside the known set are excluded from count cards without crashing."""
        tasks = [
            Task(task_id="t-proc-1", name="transcode", status="PROCESSING", progress=50),
            Task(task_id="t-comp-1", name="transcode", status="COMPLETED", progress=100),
            Task(task_id="t-fail-1", name="transcode", status="FAILED", progress=0, error="err"),
            Task(task_id="t-unknown-1", name="transcode", status="UNKNOWN_STATE", progress=0),
            Task(task_id="t-unknown-2", name="transcode", status="CANCELLED", progress=0),
        ]
        for t in tasks:
            db_session.add(t)
        db_session.commit()

        res = client.get("/api/tasks/counts")
        assert res.status_code == 200
        data = res.json()
        assert data["running"] == 1
        assert data["completed"] == 1
        assert data["failed"] == 1
        assert data["pending"] == 0

    def test_counts_redis_error_returns_db_counts(self, client, db_session, monkeypatch):
        """If Redis raises an error, endpoint must return DB counts without failing."""
        db_session.add(Task(task_id="t-db-1", name="transcode", status="PROCESSING", progress=50))
        db_session.commit()

        def fail_llen(name):
            raise ConnectionError("Redis connection lost")

        monkeypatch.setattr("app.routers.tasks.redis_client.llen", fail_llen)

        res = client.get("/api/tasks/counts")
        assert res.status_code == 200
        data = res.json()
        assert data["running"] == 1
        assert data["pending"] == 0


class TestTaskWebSocketContract:
    """Test /api/ws/tasks frame delivery from Redis pub/sub."""

    def test_ws_tasks_receives_frame(self, client, stub_redis):
        """Connecting to /api/ws/tasks and publishing a frame must deliver the frame."""
        frame = {
            "task_id": "test-ws-task-1",
            "status": "PROCESSING",
            "progress": 45,
            "error": None,
        }

        with client.websocket_connect("/api/ws/tasks") as ws:
            stub_redis.publish("task_updates", json.dumps(frame))
            received = ws.receive_json()
            assert received["task_id"] == "test-ws-task-1"
            assert received["status"] == "PROCESSING"
            assert received["progress"] == 45
            assert received["error"] is None

    def test_ws_tasks_drops_malformed_json_without_disconnect(self, client, stub_redis):
        """Malformed JSON frame must be dropped with a warning, keeping the client connected."""
        valid_frame = {
            "task_id": "test-ws-task-valid",
            "status": "COMPLETED",
            "progress": 100,
            "error": None,
        }

        with client.websocket_connect("/api/ws/tasks") as ws:
            # Publish corrupt JSON first
            stub_redis.publish("task_updates", "NOT_VALID_JSON{")
            # Then publish a valid frame
            stub_redis.publish("task_updates", json.dumps(valid_frame))

            # The socket should still be alive and yield the valid frame
            received = ws.receive_json()
            assert received["task_id"] == "test-ws-task-valid"
            assert received["status"] == "COMPLETED"

    def test_ws_tasks_subscribe_failure_closes_with_1011(self, client, monkeypatch):
        """If pubsub.subscribe fails, server must log error and close with code 1011."""
        from fastapi import WebSocketDisconnect

        class FailingPubSub:
            def subscribe(self, *args, **kwargs):
                raise RuntimeError("Redis connection broken during subscribe")

            def unsubscribe(self, *args, **kwargs):
                pass

            def close(self):
                pass

        monkeypatch.setattr("app.routers.tasks.redis_client.pubsub", lambda: FailingPubSub())

        with pytest.raises(WebSocketDisconnect) as excinfo:
            with client.websocket_connect("/api/ws/tasks") as ws:
                ws.receive_text()
        assert excinfo.value.code == 1011
