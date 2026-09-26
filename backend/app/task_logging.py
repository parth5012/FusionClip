"""Celery task boundary logging: records started, failed, retry, and finished events to Task.logs (#108)."""

import json
import logging
import threading
from datetime import datetime, timezone
from typing import Optional, List, Dict, Any

from celery.signals import (
    task_prerun,
    task_postrun,
    task_failure,
    task_retry,
)

from app.database import SessionLocal
from app.models import Task

logger = logging.getLogger(__name__)

MAX_TRACEBACK_LEN = 8192
MAX_RESULT_SUMMARY_LEN = 1024
MAX_EVENT_COUNT = 50
MAX_LOGS_BYTES = 65536
TRUNCATION_MARKER = "\n... [TRUNCATED: traceback exceeded limit]"

_lock = threading.Lock()


def categorize_error(error_msg: Optional[str]) -> str:
    """Categorize error message into standard diagnostic categories."""
    if not error_msg:
        return "runtime"
    lower = str(error_msg).lower()
    if "out of memory" in lower or "oom" in lower or "memoryerror" in lower or "cuda out of memory" in lower:
        return "OOM"
    if "timeout" in lower or "timed out" in lower:
        return "timeout"
    if any(v in lower for v in ("invalid", "validation", "bad parameter", "unsupported")):
        return "validation"
    return "runtime"


def sanitize_str(val: Any) -> str:
    """Sanitize arbitrary strings to clean UTF-8, replacing illegal surrogates or bytes."""
    if val is None:
        return ""
    try:
        s = str(val)
        return s.encode("utf-8", errors="replace").decode("utf-8")
    except Exception:
        return repr(val)


def truncate_text(text: Optional[str], max_len: int, marker: str = TRUNCATION_MARKER) -> Optional[str]:
    """Truncate text if it exceeds max_len, appending an explicit marker."""
    if text is None:
        return None
    s = sanitize_str(text)
    if len(s) <= max_len:
        return s
    return s[:max_len] + marker


def parse_log_events(raw_logs: Optional[str]) -> List[Dict[str, Any]]:
    """Parse Task.logs into a list of event dictionaries.

    Supports JSON Lines (NDJSON), JSON array, and legacy non-JSON text.
    Never raises an exception on malformed content.
    """
    if not raw_logs or not isinstance(raw_logs, str) or not raw_logs.strip():
        return []

    trimmed = raw_logs.strip()

    # Try JSON array first
    if trimmed.startswith("[") and trimmed.endswith("]"):
        try:
            parsed = json.loads(trimmed)
            if isinstance(parsed, list):
                return [item if isinstance(item, dict) else {"event": "log", "message": str(item)} for item in parsed]
        except Exception:
            pass

    # Process line-by-line (NDJSON / legacy plain text)
    events: List[Dict[str, Any]] = []
    for line in trimmed.split("\n"):
        line_str = line.strip()
        if not line_str:
            continue
        try:
            obj = json.loads(line_str)
            if isinstance(obj, dict):
                events.append(obj)
            else:
                events.append({"event": "log", "message": str(obj)})
        except Exception:
            # Legacy non-JSON line
            events.append({"event": "log", "message": line_str})

    return events


def append_task_event(
    task_id: str,
    event_type: str,
    db=None,
    **kwargs: Any,
) -> Optional[Task]:
    """Append a structured lifecycle event to Task.logs and update Task record."""
    if not task_id:
        return None

    with _lock:
        session = db if db is not None else SessionLocal()
        close_session = db is None

        try:
            db_task = session.query(Task).filter(Task.task_id == task_id).first()
            if not db_task:
                task_name = kwargs.get("task_name") or "task"
                db_task = Task(
                    task_id=task_id,
                    name=task_name,
                    status="PROCESSING" if event_type == "started" else ("FAILED" if event_type == "failed" else "PENDING"),
                    progress=0,
                )
                session.add(db_task)
                session.flush()

            timestamp = datetime.now(timezone.utc).isoformat()
            event: Dict[str, Any] = {
                "event": event_type,
                "timestamp": timestamp,
                "task_id": task_id,
            }

            if event_type == "started":
                db_task.status = "PROCESSING"
                task_name = sanitize_str(kwargs.get("task_name") or db_task.name)
                event["task_name"] = task_name
                db_task.name = task_name

            elif event_type == "failed":
                db_task.status = "FAILED"
                error_raw = kwargs.get("error")
                error_str = sanitize_str(error_raw) if error_raw is not None else "Unknown error"
                event["error"] = error_str
                db_task.error = error_str

                error_type = sanitize_str(kwargs.get("error_type") or categorize_error(error_str))
                event["error_type"] = error_type
                db_task.error_type = error_type

                raw_tb = kwargs.get("traceback")
                if raw_tb is not None:
                    full_tb = sanitize_str(raw_tb)
                    # Full untruncated traceback in Task.traceback column
                    db_task.traceback = full_tb
                    # Bounded traceback with explicit marker in event logs
                    event["traceback"] = truncate_text(full_tb, MAX_TRACEBACK_LEN, TRUNCATION_MARKER)

            elif event_type == "retry":
                db_task.status = "RETRYING"
                reason = kwargs.get("reason") or kwargs.get("error")
                event["reason"] = sanitize_str(reason) if reason is not None else None
                raw_tb = kwargs.get("traceback")
                if raw_tb is not None:
                    event["traceback"] = truncate_text(sanitize_str(raw_tb), MAX_TRACEBACK_LEN, TRUNCATION_MARKER)
                retry_count = kwargs.get("retry_count")
                if retry_count is not None:
                    event["retry_count"] = retry_count
                    db_task.retry_count = retry_count

            elif event_type == "finished":
                status = sanitize_str(kwargs.get("status") or "COMPLETED")
                db_task.status = status
                db_task.progress = 100
                event["status"] = status
                retval = kwargs.get("result_summary") or kwargs.get("retval")
                if retval is not None:
                    summary_str = sanitize_str(retval)
                    event["result_summary"] = truncate_text(summary_str, MAX_RESULT_SUMMARY_LEN, "\n... [TRUNCATED]")

            else:
                for k, v in kwargs.items():
                    event[k] = sanitize_str(v) if isinstance(v, str) else v

            existing_events = parse_log_events(db_task.logs)

            # Deduplication check for consecutive duplicate events
            if existing_events and existing_events[-1].get("event") == event_type:
                last_ev = existing_events[-1]
                if event_type == "failed" and last_ev.get("error") == event.get("error"):
                    # Avoid duplicate failed entry if already recorded
                    return db_task
                if event_type == "started" and last_ev.get("task_name") == event.get("task_name"):
                    return db_task

            existing_events.append(event)

            # Cap event count to MAX_EVENT_COUNT
            if len(existing_events) > MAX_EVENT_COUNT:
                dropped = len(existing_events) - MAX_EVENT_COUNT
                prune_event = {
                    "event": "pruned",
                    "timestamp": timestamp,
                    "message": f"... [{dropped} earlier event(s) pruned to maintain bounded log size] ...",
                }
                existing_events = [existing_events[0], prune_event] + existing_events[-(MAX_EVENT_COUNT - 2):]

            # Serialize to NDJSON (JSON Lines)
            serialized = "\n".join(json.dumps(ev, ensure_ascii=False) for ev in existing_events) + "\n"

            # Check total byte size
            if len(serialized.encode("utf-8", errors="replace")) > MAX_LOGS_BYTES:
                # Retain only the most recent events that fit
                while len(existing_events) > 3 and len(serialized.encode("utf-8", errors="replace")) > MAX_LOGS_BYTES:
                    existing_events.pop(1)
                    serialized = "\n".join(json.dumps(ev, ensure_ascii=False) for ev in existing_events) + "\n"

            db_task.logs = serialized
            session.commit()
            return db_task

        except Exception as e:
            logger.error(f"Failed to append task event for {task_id}: {e}")
            if session:
                session.rollback()
            return None
        finally:
            if close_session:
                session.close()


# Celery Signal Handlers (boundary hooks)

@task_prerun.connect
def on_task_prerun(task_id=None, task=None, args=None, kwargs=None, **kw):
    """Fired when a task starts execution."""
    if not task_id:
        return
    task_name = getattr(task, "name", "unknown") if task else "unknown"
    append_task_event(task_id, "started", task_name=task_name)


@task_postrun.connect
def on_task_postrun(task_id=None, task=None, args=None, kwargs=None, retval=None, state=None, **kw):
    """Fired after a task has finished executing."""
    if not task_id:
        return
    # Only record finished event on success/completion; failure is recorded by task_failure
    if state in ("SUCCESS", "COMPLETED"):
        append_task_event(task_id, "finished", status="COMPLETED", retval=retval)


@task_failure.connect
def on_task_failure(task_id=None, exception=None, args=None, kwargs=None, traceback=None, einfo=None, **kw):
    """Fired when a task fails with an unhandled exception."""
    if not task_id:
        return

    full_tb = ""
    if einfo and getattr(einfo, "traceback", None):
        full_tb = einfo.traceback
    elif traceback:
        import traceback as tb_module
        full_tb = "".join(tb_module.format_tb(traceback))
    else:
        import traceback as tb_module
        full_tb = tb_module.format_exc()

    error_msg = str(exception) if exception else "Task failed"
    append_task_event(task_id, "failed", error=error_msg, traceback=full_tb)


@task_retry.connect
def on_task_retry(request=None, reason=None, einfo=None, **kw):
    """Fired when a task is scheduled for retry."""
    task_id = getattr(request, "id", None) if request else None
    if not task_id:
        return

    full_tb = einfo.traceback if einfo and getattr(einfo, "traceback", None) else None
    retry_count = getattr(request, "retries", None) if request else None
    append_task_event(task_id, "retry", reason=str(reason) if reason else None, traceback=full_tb, retry_count=retry_count)
