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

    def test_list_endpoint_returns_event_count_summary(self, client, db_session):
        """GET /api/tasks/list must omit logs/traceback from task items and return event_count summary (#108)."""
        task_id = "test-list-logs-task"
        raw_logs = json.dumps({"event": "started", "timestamp": "2026-09-26T12:00:00Z"}) + "\n"
        db_task = Task(
            task_id=task_id,
            name="transcode",
            status="PROCESSING",
            progress=50,
            logs=raw_logs,
            traceback="some traceback",
        )
        db_session.add(db_task)
        db_session.commit()

        res = client.get("/api/tasks/list")
        assert res.status_code == 200
        data = res.json()
        matching = [t for t in data["tasks"] if t["task_id"] == task_id]
        assert len(matching) == 1
        assert matching[0].get("event_count") == 1
        assert "logs" not in matching[0] or matching[0]["logs"] is None
        assert "traceback" not in matching[0] or matching[0]["traceback"] is None

    def test_task_logs_endpoint_returns_stored_events(self, client, db_session):
        """GET /api/tasks/{task_id}/logs returns detailed logs, traceback, and event_count (#108)."""
        task_id = "test-detail-logs-task"
        raw_logs = (
            json.dumps({"event": "started", "timestamp": "2026-09-26T12:00:00Z", "task_name": "transcode"})
            + "\n"
            + json.dumps({"event": "failed", "timestamp": "2026-09-26T12:00:05Z", "error": "Disk full"})
            + "\n"
        )
        tb_str = "Traceback (most recent call last):\n  File 'worker.py', line 5\nOSError: Disk full"
        db_task = Task(
            task_id=task_id,
            name="transcode",
            status="FAILED",
            progress=0,
            error="Disk full",
            logs=raw_logs,
            traceback=tb_str,
        )
        db_session.add(db_task)
        db_session.commit()

        # Valid task ID
        res = client.get(f"/api/tasks/{task_id}/logs")
        assert res.status_code == 200
        data = res.json()
        assert data["task_id"] == task_id
        assert data["logs"] == raw_logs
        assert data["traceback"] == tb_str
        assert data["event_count"] == 2

        # 404 for unknown task ID
        res_404 = client.get("/api/tasks/unknown-nonexistent-id/logs")
        assert res_404.status_code == 404

    def test_retry_path_produces_exactly_one_retry_event(self, db_session):
        """Task retry path produces exactly one retry event without duplicate logging (#108)."""
        task_id = "test-single-retry-task"
        db_task = Task(task_id=task_id, name="app.tasks.sample_retry", status="PROCESSING", retry_count=0, max_retries=3)
        db_session.add(db_task)
        db_session.commit()

        attempt = 0

        @celery.task(bind=True, name="app.tasks.sample_retry", max_retries=3)
        def sample_retry_task(self):
            nonlocal attempt
            attempt += 1
            if attempt == 1:
                # Simulate a transient failure triggering Celery retry on first attempt
                try:
                    raise ConnectionError("Transient network glitch")
                except Exception as exc:
                    raise self.retry(exc=exc, countdown=1)
            return "recovered"

        res = sample_retry_task.apply(task_id=task_id)
        assert res.state == "SUCCESS"
        assert res.result == "recovered"

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        events = parse_log_events(db_task.logs)
        retry_events = [e for e in events if e.get("event") == "retry"]
        assert len(retry_events) == 1
        assert "Transient network glitch" in str(retry_events[0].get("reason"))

    def test_signal_handler_exception_swallowed_and_task_succeeds(self, db_session, monkeypatch):
        """Any exception in Celery signal handlers must be swallowed so tasks are never aborted (#108)."""
        task_id = "test-signal-swallow-task"
        db_task = Task(task_id=task_id, name="app.tasks.sample_unbreakable", status="PENDING")
        db_session.add(db_task)
        db_session.commit()

        @celery.task(bind=True, name="app.tasks.sample_unbreakable")
        def sample_unbreakable_task(self):
            return "all_good"

        # Force append_task_event to fail
        def broken_append(*args, **kwargs):
            raise RuntimeError("Catastrophic database crash in logging handler")

        monkeypatch.setattr("app.task_logging.append_task_event", broken_append)

        # Task execution must succeed despite signal handler failure
        res = sample_unbreakable_task.apply(task_id=task_id)
        assert res.state == "SUCCESS"
        assert res.result == "all_good"

    def test_two_event_row_with_huge_failed_event_within_max_bytes(self, db_session):
        """A 2-event row with huge failed event must stay within MAX_LOGS_BYTES and carry truncation marker (#108)."""
        task_id = "test-huge-fail-task"
        db_task = Task(task_id=task_id, name="transcode", status="PROCESSING")
        db_session.add(db_task)
        db_session.commit()

        # Step 1: started event
        append_task_event(task_id=task_id, event_type="started", task_name="transcode", db=db_session)

        # Step 2: huge failed event with massive traceback and massive error (>80KB total)
        massive_error = "FATAL: " + ("Large error string pattern " * 2000)
        massive_traceback = "Traceback (most recent call last):\n" + ("  File 'core.py', line 10\n" * 3000) + "MemoryError"

        append_task_event(
            task_id=task_id,
            event_type="failed",
            error=massive_error,
            error_type="OOM",
            traceback=massive_traceback,
            db=db_session,
        )

        db_task = db_session.query(Task).filter(Task.task_id == task_id).first()
        from app.task_logging import MAX_LOGS_BYTES

        encoded_len = len(db_task.logs.encode("utf-8", errors="replace"))
        assert encoded_len <= MAX_LOGS_BYTES

        events = parse_log_events(db_task.logs)
        assert len(events) == 2
        assert events[0]["event"] == "started"
        assert events[1]["event"] == "failed"
        assert TRUNCATION_MARKER in events[1]["traceback"]

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
