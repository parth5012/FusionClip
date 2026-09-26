"""Tests for task logs recording, stack trace capture, and Celery boundaries (#108)."""

import json
import threading
import pytest
from app.models import Task
from app.task_logging import (
    append_task_event,
    parse_log_events,
    MAX_TRACEBACK_LEN,
    TRUNCATION_MARKER,
)
from app.celery_app import celery


class TestTaskLogsBackend:
    """Test backend Celery task lifecycle events and Task.logs persistence."""

    def test_task_success_produces_started_and_finished_events(self, db_session):
        """A successful task run writes 'started' and 'finished' events to Task.logs."""
        task_id = "test-success-task-1"
        db_task = Task(task_id=task_id, name="app.tasks.sample_success", status="PENDING")
        db_session.add(db_task)
        db_session.commit()

        @celery.task(bind=True, name="app.tasks.sample_success")
        def sample_success(self):
            return {"status": "COMPLETED", "items_processed": 5}

        # Run via Celery apply so signal handlers (task_prerun, task_postrun) fire
        res = sample_success.apply(task_id=task_id)
        assert res.state == "SUCCESS"

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.logs is not None
        events = parse_log_events(db_task.logs)
        assert len(events) >= 2

        event_names = [e.get("event") for e in events]
        assert "started" in event_names
        assert "finished" in event_names

        finished_ev = [e for e in events if e.get("event") == "finished"][0]
        assert finished_ev.get("status") == "COMPLETED"
        assert "items_processed" in str(finished_ev.get("result_summary"))

    def test_task_failure_produces_started_and_failed_events_with_traceback(self, db_session):
        """A failed task run writes 'started' and 'failed' with real traceback to Task.logs, and populates Task.traceback."""
        task_id = "test-fail-task-1"
        db_task = Task(task_id=task_id, name="app.tasks.sample_failure", status="PENDING")
        db_session.add(db_task)
        db_session.commit()

        @celery.task(bind=True, name="app.tasks.sample_failure")
        def sample_failure(self):
            raise RuntimeError("Synthetic worker runtime crash for #108")

        res = sample_failure.apply(task_id=task_id)
        assert res.state == "FAILURE"

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        assert db_task.status == "FAILED"
        assert db_task.traceback is not None
        assert "Synthetic worker runtime crash for #108" in db_task.traceback

        events = parse_log_events(db_task.logs)
        event_names = [e.get("event") for e in events]
        assert "started" in event_names
        assert "failed" in event_names

        failed_ev = [e for e in events if e.get("event") == "failed"][0]
        assert failed_ev.get("error") == "Synthetic worker runtime crash for #108"
        assert "Traceback" in failed_ev.get("traceback", "")
        assert "sample_failure" in failed_ev.get("traceback", "")

    def test_oversized_traceback_truncated_with_marker(self, db_session):
        """Oversized traceback in Task.logs must be truncated with explicit marker, while Task.traceback remains full."""
        task_id = "test-oversized-tb-1"
        db_task = Task(task_id=task_id, name="app.tasks.oversized", status="PENDING")
        db_session.add(db_task)
        db_session.commit()

        # Huge traceback string exceeding MAX_TRACEBACK_LEN
        huge_traceback = "Traceback (most recent call last):\n" + ("  File 'deep.py', line 1, in recurse\n" * 500) + "MemoryError: CUDA OOM"
        assert len(huge_traceback) > MAX_TRACEBACK_LEN

        append_task_event(
            task_id=task_id,
            event_type="failed",
            error="CUDA OOM",
            error_type="OOM",
            traceback=huge_traceback,
            db=db_session,
        )

        db_session.refresh(db_task)
        # Full traceback preserved in column
        assert db_task.traceback == huge_traceback
        # Logs event traceback is bounded with explicit marker
        events = parse_log_events(db_task.logs)
        assert len(events) == 1
        failed_ev = events[0]
        assert TRUNCATION_MARKER in failed_ev["traceback"]
        assert len(failed_ev["traceback"]) <= MAX_TRACEBACK_LEN + len(TRUNCATION_MARKER) + 50

    def test_concurrent_appends_do_not_clobber_events(self, db_session):
        """Concurrent appends to Task.logs preserve all events without clobbering."""
        task_id = "test-concurrent-task-1"
        db_task = Task(task_id=task_id, name="transcode", status="PROCESSING")
        db_session.add(db_task)
        db_session.commit()

        num_threads = 8
        events_per_thread = 5

        def worker(thread_idx):
            for i in range(events_per_thread):
                append_task_event(
                    task_id=task_id,
                    event_type="log",
                    message=f"thread-{thread_idx}-event-{i}",
                    db=db_session,
                )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(num_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        db_session.refresh(db_task)
        events = parse_log_events(db_task.logs)
        total_expected = num_threads * events_per_thread
        assert len(events) == total_expected
        messages = {e.get("message") for e in events}
        for thread_idx in range(num_threads):
            for i in range(events_per_thread):
                assert f"thread-{thread_idx}-event-{i}" in messages

    def test_logs_exposed_on_list_endpoint(self, client, db_session):
        """GET /api/tasks/list must include the logs field for tasks."""
        task_id = "test-list-logs-task"
        raw_logs = json.dumps({"event": "started", "timestamp": "2026-09-26T12:00:00Z"}) + "\n"
        db_task = Task(
            task_id=task_id,
            name="transcode",
            status="PROCESSING",
            progress=50,
            logs=raw_logs,
        )
        db_session.add(db_task)
        db_session.commit()

        res = client.get("/api/tasks/list")
        assert res.status_code == 200
        data = res.json()
        matching = [t for t in data["tasks"] if t["task_id"] == task_id]
        assert len(matching) == 1
        assert matching[0]["logs"] == raw_logs

    def test_edge_cases_in_log_handling(self, db_session):
        """Non-string/None/Unicode messages and pre-existing legacy text must not throw."""
        task_id = "test-edge-task"
        # Pre-populate with legacy non-JSON plain text
        db_task = Task(
            task_id=task_id,
            name="legacy",
            status="FAILED",
            logs="Legacy plain text log\nAnother legacy line",
        )
        db_session.add(db_task)
        db_session.commit()

        # Append with None error, unicode characters, empty traceback
        append_task_event(
            task_id=task_id,
            event_type="failed",
            error="Non-ascii error 💥 🚀 \ud83d\ude00",
            error_type="runtime",
            traceback=None,
            db=db_session,
        )

        db_session.refresh(db_task)
        events = parse_log_events(db_task.logs)
        assert len(events) >= 3  # 2 legacy lines wrapped + 1 new failed event
        failed_ev = [e for e in events if e.get("event") == "failed"][0]
        assert "💥" in failed_ev["error"]
