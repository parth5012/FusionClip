/**
 * Task Queue utilities: status categorization, live WebSocket updates, and count tracking (#107).
 */

export type TaskBucket = 'running' | 'pending' | 'failed' | 'completed' | 'unknown';

export interface TaskCounts {
  running: number;
  pending: number;
  failed: number;
  completed: number;
}

export interface TaskItem {
  id?: number;
  task_id: string;
  name: string;
  status: string;
  progress: number;
  error?: string | null;
  error_type?: string | null;
  traceback?: string | null;
  logs?: string | null;
  retry_count?: number;
  max_retries?: number;
  last_retry_at?: string | null;
  created_at?: string | null;
  updated_at?: string | null;
}

export interface TaskUpdatePayload {
  task_id: string;
  status: string;
  progress?: number;
  error?: string | null;
  error_type?: string | null;
  traceback?: string | null;
  retry_count?: number;
  max_retries?: number;
  name?: string;
}

const RUNNING_STATUSES = new Set(['PROCESSING', 'PROGRESS', 'RUNNING', 'RETRYING']);
const PENDING_STATUSES = new Set(['PENDING', 'PENDING_RETRY', 'QUEUED', 'WAITING']);
const FAILED_STATUSES = new Set(['FAILED', 'FAILURE']);
const COMPLETED_STATUSES = new Set(['COMPLETED', 'SUCCESS']);

/**
 * Categorize a task status string into one of the four dashboard buckets,
 * or 'unknown' for unmatched/edge statuses.
 */
export function categorizeTaskStatus(status?: string | null): TaskBucket {
  if (!status || typeof status !== 'string') return 'unknown';
  const upper = status.trim().toUpperCase();
  if (RUNNING_STATUSES.has(upper)) return 'running';
  if (PENDING_STATUSES.has(upper)) return 'pending';
  if (FAILED_STATUSES.has(upper)) return 'failed';
  if (COMPLETED_STATUSES.has(upper)) return 'completed';
  return 'unknown';
}

/**
 * Apply a WebSocket frame update to an existing list of tasks.
 * If the task is present, update its fields; if absent, prepend it.
 */
export function applyTaskUpdate(tasks: TaskItem[], update: TaskUpdatePayload): TaskItem[] {
  if (!update || !update.task_id) return tasks;

  const existingIndex = tasks.findIndex((t) => t.task_id === update.task_id);
  if (existingIndex >= 0) {
    const existing = tasks[existingIndex];
    const updatedTask: TaskItem = {
      ...existing,
      status: update.status || existing.status,
      progress: update.progress !== undefined ? update.progress : existing.progress,
      error: update.error !== undefined ? update.error : existing.error,
      error_type: update.error_type !== undefined ? update.error_type : existing.error_type,
      traceback: update.traceback !== undefined ? update.traceback : existing.traceback,
      retry_count: update.retry_count !== undefined ? update.retry_count : existing.retry_count,
      max_retries: update.max_retries !== undefined ? update.max_retries : existing.max_retries,
      updated_at: new Date().toISOString(),
    };
    const nextTasks = [...tasks];
    nextTasks[existingIndex] = updatedTask;
    return nextTasks;
  }

  // Task not in current list (e.g. freshly dispatched or beyond current page)
  const newTask: TaskItem = {
    task_id: update.task_id,
    name: update.name || 'task',
    status: update.status || 'PENDING',
    progress: update.progress ?? 0,
    error: update.error ?? null,
    error_type: update.error_type ?? null,
    traceback: update.traceback ?? null,
    retry_count: update.retry_count ?? 0,
    max_retries: update.max_retries ?? 3,
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
  };
  return [newTask, ...tasks];
}

/**
 * Adjust running/pending/failed/completed counts when a task transitions from oldStatus to newStatus.
 */
export function adjustTaskCounts(
  prevCounts: TaskCounts,
  oldStatus: string | null | undefined,
  newStatus: string
): TaskCounts {
  const oldBucket = categorizeTaskStatus(oldStatus);
  const newBucket = categorizeTaskStatus(newStatus);

  if (oldBucket === newBucket) return prevCounts;

  const next = { ...prevCounts };

  if (oldBucket !== 'unknown') {
    next[oldBucket] = Math.max(0, next[oldBucket] - 1);
  }

  if (newBucket !== 'unknown') {
    next[newBucket] = next[newBucket] + 1;
  }

  return next;
}

/**
 * Tally running/pending/failed/completed counts from an array of tasks.
 */
export function calculateTaskCounts(tasks: TaskItem[]): TaskCounts {
  const counts: TaskCounts = { running: 0, pending: 0, failed: 0, completed: 0 };
  for (const t of tasks) {
    const bucket = categorizeTaskStatus(t.status);
    if (bucket !== 'unknown') {
      counts[bucket]++;
    }
  }
  return counts;
}
