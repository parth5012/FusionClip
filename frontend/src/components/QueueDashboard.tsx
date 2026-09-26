'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  RefreshCw,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Clock,
  ChevronRight,
  ChevronLeft,
  ChevronsLeft,
  ChevronsRight,
  ListFilter,
  RotateCcw,
  Bug,
  FileText,
  Search,
  Wifi,
  WifiOff,
  ListOrdered,
} from 'lucide-react';
import { fetchTasks, fetchTaskCounts, retryTask, TaskListItem } from '../utils/api';
import {
  categorizeTaskStatus,
  applyTaskUpdate,
  adjustTaskCounts,
  TaskCounts,
  TaskItem,
  TaskBucket,
} from '../utils/queue';

type StatusFilter = '' | 'pending' | 'processing' | 'completed' | 'failed';

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'processing', label: 'Running / Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];

const TASK_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All Types' },
  { value: 'transcode', label: 'Transcode' },
  { value: 'upscale', label: 'Upscale' },
  { value: 'video_upscale', label: 'Video Upscale' },
  { value: 'thumbnail', label: 'Thumbnail' },
  { value: 'waveform', label: 'Waveform' },
  { value: 'audio_extract', label: 'Audio Extract' },
];

function statusColor(bucket: TaskBucket): string {
  switch (bucket) {
    case 'running':
      return 'bg-sky-950 text-sky-400 border-sky-800';
    case 'pending':
      return 'bg-amber-950 text-amber-400 border-amber-800';
    case 'completed':
      return 'bg-emerald-950 text-emerald-400 border-emerald-800';
    case 'failed':
      return 'bg-rose-950 text-rose-400 border-rose-800';
    default:
      return 'bg-slate-800 text-slate-400 border-slate-700';
  }
}

function progressBarColor(bucket: TaskBucket): string {
  switch (bucket) {
    case 'running':
      return 'bg-sky-500';
    case 'completed':
      return 'bg-emerald-500';
    case 'failed':
      return 'bg-rose-500';
    case 'pending':
      return 'bg-amber-500';
    default:
      return 'bg-slate-600';
  }
}

function formatDuration(start: string | null | undefined, end: string | null | undefined): string {
  if (!start) return '—';
  const startTime = new Date(start).getTime();
  const endTime = end ? new Date(end).getTime() : Date.now();
  const diff = Math.max(0, endTime - startTime);
  const seconds = Math.floor(diff / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`;
  const hours = Math.floor(minutes / 60);
  return `${hours}h ${minutes % 60}m`;
}

function formatTime(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString();
}

export default function QueueDashboard() {
  const [tasks, setTasks] = useState<TaskItem[]>([]);
  const [counts, setCounts] = useState<TaskCounts>({
    running: 0,
    pending: 0,
    failed: 0,
    completed: 0,
  });
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');
  const [typeFilter, setTypeFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [wsStatus, setWsStatus] = useState<'connected' | 'reconnecting' | 'disconnected'>('disconnected');

  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Backfill counts from REST endpoint
  const backfillCounts = useCallback(async () => {
    try {
      const countsData = await fetchTaskCounts();
      setCounts({
        running: countsData.running,
        pending: countsData.pending,
        failed: countsData.failed,
        completed: countsData.completed,
      });
    } catch (err: any) {
      console.warn('Failed to backfill task counts:', err);
    }
  }, []);

  // Fetch tasks list
  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const statusUpper = statusFilter ? statusFilter.toUpperCase() : undefined;
      const data = await fetchTasks(
        page,
        pageSize,
        statusUpper,
        typeFilter || undefined,
        searchQuery || undefined
      );
      setTasks(data.tasks);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, typeFilter, searchQuery]);

  // Initial load
  useEffect(() => {
    backfillCounts();
    loadTasks();
  }, [backfillCounts, loadTasks]);

  const handleRetry = async (taskId: string) => {
    setRetryingIds((prev) => new Set(prev).add(taskId));
    try {
      await retryTask(taskId);
      await Promise.all([loadTasks(), backfillCounts()]);
    } catch (err: any) {
      setError(err.message || 'Failed to retry task');
    } finally {
      setRetryingIds((prev) => {
        const next = new Set(prev);
        next.delete(taskId);
        return next;
      });
    }
  };

  // WebSocket connection & live updates
  useEffect(() => {
    const wsUrl = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/ws/tasks`.replace(/^http/, 'ws');

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onopen = () => {
        setWsStatus('connected');
        // Backfill REST state on connect and after reconnect
        backfillCounts();
        loadTasks();
      };

      ws.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data);
          if (!update || !update.task_id) return;

          setTasks((prevTasks) => {
            const existing = prevTasks.find((t) => t.task_id === update.task_id);
            const oldStatus = existing ? existing.status : null;

            // Dynamically adjust count cards
            setCounts((prevCounts) =>
              adjustTaskCounts(prevCounts, oldStatus, update.status || 'PROCESSING')
            );

            return applyTaskUpdate(prevTasks, update);
          });
        } catch {
          // ignore malformed frames
        }
      };

      ws.onclose = () => {
        setWsStatus('reconnecting');
        // Do NOT blank out tasks or counts; keep stale data visible
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        setWsStatus('reconnecting');
        ws.close();
      };
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
    };
  }, [backfillCounts, loadTasks]);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      {/* Header with live WebSocket indicator */}
      <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4">
        <div>
          <h2 className="text-xl font-bold text-slate-100">Task Queue</h2>
          <p className="text-xs text-slate-400">
            Monitor running, pending, failed, and completed background tasks in real time.
          </p>
        </div>

        {/* WebSocket Connection Status */}
        <div className="flex items-center gap-2">
          {wsStatus === 'connected' ? (
            <span
              data-testid="ws-status"
              className="inline-flex items-center gap-1.5 text-xs text-emerald-400 bg-emerald-950/60 border border-emerald-800/80 px-3 py-1 rounded-full font-medium"
            >
              <Wifi className="w-3.5 h-3.5" />
              <span>Live</span>
            </span>
          ) : (
            <span
              data-testid="ws-status"
              className="inline-flex items-center gap-1.5 text-xs text-amber-400 bg-amber-950/60 border border-amber-800/80 px-3 py-1 rounded-full font-medium"
            >
              <WifiOff className="w-3.5 h-3.5 animate-pulse" />
              <span>Reconnecting...</span>
            </span>
          )}
        </div>
      </div>

      {/* Four Count Cards (running / pending / failed / completed) */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4" data-testid="count-cards">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center justify-between shadow-sm">
          <div>
            <div className="text-xs text-sky-400 uppercase tracking-wider font-semibold">Running</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">{counts.running}</div>
          </div>
          <Loader2 className="w-7 h-7 text-sky-500/40 animate-spin" />
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center justify-between shadow-sm">
          <div>
            <div className="text-xs text-amber-400 uppercase tracking-wider font-semibold">Pending</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">{counts.pending}</div>
          </div>
          <Clock className="w-7 h-7 text-amber-500/40" />
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center justify-between shadow-sm">
          <div>
            <div className="text-xs text-rose-400 uppercase tracking-wider font-semibold">Failed</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">{counts.failed}</div>
          </div>
          <AlertCircle className="w-7 h-7 text-rose-500/40" />
        </div>

        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center justify-between shadow-sm">
          <div>
            <div className="text-xs text-emerald-400 uppercase tracking-wider font-semibold">Completed</div>
            <div className="text-2xl font-bold text-slate-100 mt-1">{counts.completed}</div>
          </div>
          <CheckCircle2 className="w-7 h-7 text-emerald-500/40" />
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center bg-slate-900 border border-slate-800 p-4 rounded-lg">
        <div className="flex items-center gap-2 text-slate-300">
          <ListFilter className="w-4 h-4 text-sky-400" />
          <span className="text-sm font-medium">Filters</span>
        </div>

        <select
          value={statusFilter}
          onChange={(e) => {
            setStatusFilter(e.target.value as StatusFilter);
            setPage(1);
          }}
          className="bg-slate-950 border border-slate-700 px-3 py-1.5 rounded text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <select
          value={typeFilter}
          onChange={(e) => {
            setTypeFilter(e.target.value);
            setPage(1);
          }}
          className="bg-slate-950 border border-slate-700 px-3 py-1.5 rounded text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
        >
          {TASK_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>

        <div className="relative flex-1 w-full sm:w-auto">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search tasks by name or error..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 pl-9 pr-3 py-1.5 rounded text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={() => {
              backfillCounts();
              loadTasks();
            }}
            disabled={loading}
            className="p-2 border border-slate-700 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Task table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/50">
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Task ID</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Name</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Status</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Progress</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Retries</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Duration</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Created</th>
                <th className="px-4 py-3 text-left text-xs font-medium text-slate-400">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800/50">
              {loading && tasks.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <Loader2 className="w-6 h-6 animate-spin text-sky-500 mx-auto" />
                    <p className="text-slate-400 text-xs mt-2">Loading task queue...</p>
                  </td>
                </tr>
              ) : tasks.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-slate-500">
                    <div className="flex flex-col items-center justify-center space-y-2">
                      <ListOrdered className="w-8 h-8 text-slate-600" />
                      <p className="text-sm font-medium text-slate-300">No tasks in queue</p>
                      <p className="text-xs text-slate-500">
                        Trigger a background task from the Media Library or Generative AI tab to track progress here.
                      </p>
                    </div>
                  </td>
                </tr>
              ) : (
                tasks.map((task) => {
                  const bucket = categorizeTaskStatus(task.status);
                  const isExpanded = expandedTask === task.task_id;
                  const hasError = !!task.error;

                  return (
                    <React.Fragment key={task.task_id}>
                      <tr
                        className={`hover:bg-slate-850/40 transition ${
                          isExpanded ? 'bg-slate-800/50' : ''
                        } ${bucket === 'failed' ? 'bg-rose-950/10' : ''}`}
                      >
                        <td className="px-4 py-3">
                          <span
                            className="font-mono text-xs text-slate-300 truncate block max-w-[180px]"
                            title={task.task_id}
                          >
                            {task.task_id.length > 16 ? `${task.task_id.substring(0, 16)}...` : task.task_id}
                          </span>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-slate-300 capitalize">{task.name || 'Task'}</span>
                        </td>
                        <td className="px-4 py-3">
                          <span
                            className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded border font-mono ${statusColor(
                              bucket
                            )}`}
                          >
                            {bucket === 'running' && <Loader2 className="w-3 h-3 animate-spin" />}
                            {bucket === 'completed' && <CheckCircle2 className="w-3 h-3" />}
                            {bucket === 'failed' && <AlertCircle className="w-3 h-3" />}
                            {bucket === 'pending' && <Clock className="w-3 h-3" />}
                            {task.status || 'UNKNOWN'}
                          </span>
                        </td>
                        <td className="px-4 py-3 min-w-[160px]">
                          <div className="space-y-1">
                            <div className="flex items-center gap-2">
                              <div className="flex-1 bg-slate-800 rounded-full h-1.5 overflow-hidden">
                                <div
                                  className={`h-full transition-all duration-300 ${progressBarColor(bucket)}`}
                                  style={{ width: `${Math.min(100, Math.max(0, task.progress || 0))}%` }}
                                />
                              </div>
                              <span className="text-xs text-slate-400 w-8 text-right font-mono">
                                {task.progress || 0}%
                              </span>
                            </div>
                            {/* Surface error on failure directly in row */}
                            {hasError && (
                              <p className="text-[11px] text-rose-400 truncate max-w-[220px]" title={task.error || ''}>
                                {task.error}
                              </p>
                            )}
                          </div>
                        </td>
                        <td className="px-4 py-3">
                          <span className="text-xs text-slate-400">
                            {task.retry_count || 0}/{task.max_retries || 3}
                          </span>
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">
                          {formatDuration(task.created_at, task.updated_at)}
                        </td>
                        <td className="px-4 py-3 text-slate-400 text-xs">{formatTime(task.created_at)}</td>
                        <td className="px-4 py-3">
                          <div className="flex items-center gap-1">
                            {/* Toggle expandable details / logs section */}
                            <button
                              onClick={() => setExpandedTask(isExpanded ? null : task.task_id)}
                              className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-sky-400 transition"
                              title={isExpanded ? 'Hide details' : 'View details'}
                              aria-label="Toggle details"
                            >
                              <ChevronRight className={`w-3.5 h-3.5 transition-transform ${isExpanded ? 'rotate-90' : ''}`} />
                            </button>

                            {/* Retry button for failed tasks */}
                            {bucket === 'failed' && (
                              <button
                                onClick={() => handleRetry(task.task_id)}
                                disabled={retryingIds.has(task.task_id)}
                                className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-sky-400 disabled:opacity-40 disabled:cursor-not-allowed transition"
                                title="Retry task"
                              >
                                {retryingIds.has(task.task_id) ? (
                                  <Loader2 className="w-3.5 h-3.5 animate-spin" />
                                ) : (
                                  <RotateCcw className="w-3.5 h-3.5" />
                                )}
                              </button>
                            )}
                          </div>
                        </td>
                      </tr>

                      {/* Expandable details row structured for ticket #108 */}
                      {isExpanded && (
                        <tr key={`${task.task_id}-expanded`}>
                          <td colSpan={8} className="px-4 py-4 bg-slate-950/60 border-t border-slate-800">
                            <div className="space-y-3">
                              {/* Error callout if present */}
                              {task.error && (
                                <div>
                                  <div className="flex items-center gap-2 mb-1.5">
                                    <Bug className="w-4 h-4 text-rose-400" />
                                    <span className="text-xs font-semibold text-rose-300">Failure Diagnostics</span>
                                    {task.error_type && (
                                      <span className="text-[10px] uppercase px-1.5 py-0.5 rounded bg-rose-950 text-rose-300 border border-rose-800">
                                        {task.error_type}
                                      </span>
                                    )}
                                  </div>
                                  <div className="bg-slate-900 border border-rose-900/40 rounded p-3 text-xs text-rose-300 font-mono">
                                    {task.error}
                                  </div>
                                </div>
                              )}

                              {/* Task metadata */}
                              <div className="flex flex-wrap gap-4 text-xs text-slate-400">
                                <span>Task ID: <span className="font-mono text-slate-300">{task.task_id}</span></span>
                                <span>Retries: <span className="text-slate-300">{task.retry_count || 0}/{task.max_retries || 3}</span></span>
                                {task.last_retry_at && <span>Last Retry: {formatTime(task.last_retry_at)}</span>}
                                <span>Created: {formatTime(task.created_at)}</span>
                                <span>Updated: {formatTime(task.updated_at)}</span>
                              </div>

                              {/* Structured seam for Ticket #108: logs / stack-trace viewer */}
                              <div className="border-t border-slate-800/80 pt-2 text-xs text-slate-500">
                                <span className="font-medium text-slate-400">Diagnostics & Logs Seam (#108): </span>
                                <span>Structured row ready for stack-trace viewer.</span>
                              </div>
                            </div>
                          </td>
                        </tr>
                      )}
                    </React.Fragment>
                  );
                })
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-4 py-3 border-t border-slate-800 bg-slate-950/40 rounded-lg">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>Rows per page:</span>
          <select
            value={pageSize}
            onChange={(e) => {
              setPageSize(Number(e.target.value));
              setPage(1);
            }}
            className="bg-slate-900 border border-slate-700 px-2 py-1 rounded text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>
                {n}
              </option>
            ))}
          </select>
          <span className="ml-2">
            Page {page} of {totalPages} ({total} total)
          </span>
        </div>

        <div className="flex items-center gap-1">
          <button
            onClick={() => setPage(1)}
            disabled={page === 1}
            className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
            title="First page"
          >
            <ChevronsLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
            title="Previous page"
          >
            <ChevronLeft className="w-4 h-4" />
          </button>
          <button
            onClick={() => setPage(Math.min(totalPages, page + 1))}
            disabled={page === totalPages}
            className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
            title="Next page"
          >
            <ChevronRight className="w-4 h-4" />
          </button>
          <button
            onClick={() => setPage(totalPages)}
            disabled={page === totalPages}
            className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
            title="Last page"
          >
            <ChevronsRight className="w-4 h-4" />
          </button>
        </div>
      </div>
    </div>
  );
}
