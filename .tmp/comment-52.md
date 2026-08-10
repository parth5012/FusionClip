## Resolution

Implemented error diagnostics panel with the following changes:

### Backend Changes

1. **Task model** (`models.py`):
   - Added `traceback` field (Text) to store full stack traces separately from error messages

2. **Migration** (`a1b2c3d4e5f7_add_traceback_field.py`):
   - Created migration to add `traceback` column to tasks table

3. **Error handling** (`tasks.py`):
   - Updated `_handle_task_failure()` to capture full traceback using `traceback.format_exc()`
   - Store both `error` (message) and `traceback` (full stack trace) in database
   - Added error type detection function `categorize_error()` that classifies errors as:
     - "OOM" - MemoryError, out of memory
     - "timeout" - TimeoutError, timeout
     - "validation" - validation errors, bad parameters
     - "runtime" - other runtime errors

4. **API endpoint** (`routers/tasks.py`):
   - Updated `GET /api/tasks/list` to include `traceback` field in response
   - Added `GET /api/tasks/errors/types` endpoint to return available error types
   - Added search functionality via `search` query parameter

### Frontend Changes

1. **API client** (`utils/api.ts`):
   - Updated `TaskListItem` interface to include `traceback` field
   - Added `getErrorTypes()` function

2. **QueueDashboard** (`QueueDashboard.tsx`):
   - Added expandable error detail panel for failed tasks
   - Added error type filter dropdown (OOM, timeout, validation, runtime)
   - Added search input for filtering by error messages
   - Added syntax-highlighted stack trace display using pre/code blocks
   - Added error badge with type icon and color coding

All changes follow existing project conventions (Tailwind CSS, dark theme with slate colors).
