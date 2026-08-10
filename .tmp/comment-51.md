## Resolution

Auto-retry logic was already fully implemented in the codebase. Verified all requirements are satisfied:

### Backend
- **Task model** (`models.py`): `retry_count`, `max_retries`, `last_retry_at` fields added
- **Migration**: `a1b2c3d4e5f6_add_retry_fields.py` — adds columns with defaults
- **Celery retry logic** (`tasks.py`):
  - `_handle_task_failure()` — handles transient vs permanent errors
  - `exponential_backoff(retry_count)` — countdown = 2^retry_count * 60s
  - `is_transient_error()` — matches OOM, TimeoutError, ConnectionError, etc.
  - `PERMANENT_ERRORS` — invalid file, bad parameters, validation errors, 404, 403
  - `TRANSIENT_ERRORS` — OOM, timeout, connection errors, 429/503
  - Both `process_media_fast` and `process_media_heavy` use retry logic
- **Manual retry API**: `POST /api/tasks/{task_id}/retry` endpoint in `routers/tasks.py`

### Frontend
- **`retryTask()`** in `api.ts` — calls manual retry endpoint
- **QueueDashboard.tsx** — shows retry count column (`{retry_count}/{max_retries}`), retry button on failed tasks with spinner while retrying

All requirements met: exponential backoff, transient vs permanent error classification, retry count tracking, manual retry from dashboard.
