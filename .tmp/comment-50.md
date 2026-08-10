## Resolution

Implemented the dedicated queue dashboard UI with the following changes:

### New Files
- **frontend/src/components/QueueDashboard.tsx** — Full dashboard component with:
  - Sortable/filterable task table (Name, Type, Status, Progress, Duration, Created)
  - Status filter (pending/processing/completed/failed) and task type filter
  - Real-time progress bars with color-coded status indicators
  - Stats bar showing counts per status
  - Pagination with configurable page size (10/25/50/100)
  - WebSocket connection to `/api/ws/tasks` for live updates with auto-reconnect
  - Refresh button, loading states, and error handling

### Modified Files
- **backend/app/routers/tasks.py** — Added `GET /api/tasks/list` endpoint with pagination, status filtering, and task type filtering
- **frontend/src/utils/api.ts** — Added `TaskListItem`, `TaskListResponse` interfaces and `fetchTasks()` function
- **frontend/src/store/useStore.ts** — Added `'queue'` to `TabType`
- **frontend/src/components/Sidebar.tsx** — Added "Queue Dashboard" menu item with `ListOrdered` icon
- **frontend/src/app/page.tsx** — Added `'queue'` case to render switch

All changes follow existing project conventions (Tailwind CSS, dark theme with slate colors, Zustand store patterns).
