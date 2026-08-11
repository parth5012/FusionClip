'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  RefreshCw, Loader2, CheckCircle2, AlertCircle, Clock,
  ChevronRight, ChevronLeft, ChevronsLeft, ChevronsRight,
  ListFilter, RotateCcw, Bug, FileText, Search, X
} from 'lucide-react';
import { fetchTasks, retryTask, TaskListItem } from '../utils/api';

type StatusFilter = '' | 'pending' | 'processing' | 'completed' | 'failed';
type ErrorTypeFilter = 'all' | 'oom' | 'timeout' | 'validation' | 'runtime';

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];

const TASK_TYPE_OPTIONS: { value: string; label: string }[] = [
  { value: '', label: 'All Types' },
  { value: 'transcode', label: 'Transcode' },
  { value: 'upscale', label: 'Upscale' },
  { value: 'thumbnail', label: 'Thumbnail' },
  { value: 'waveform', label: 'Waveform' },
  { value: 'audio_extract', label: 'Audio Extract' },
];

const ERROR_TYPE_OPTIONS: { value: ErrorTypeFilter; label: string; color: string }[] = [
  { value: 'all', label: 'All Errors', color: 'text-slate-400' },
  { value: 'oom', label: 'OOM', color: 'text-purple-400' },
  { value: 'timeout', label: 'Timeout', color: 'text-yellow-400' },
  { value: 'validation', label: 'Validation', color: 'text-blue-400' },
  { value: 'runtime', label: 'Runtime', color: 'text-red-400' },
];

function normalizeStatus(status: string): StatusFilter {
  const s = status.toUpperCase();
  if (s === 'PENDING') return 'pending';
  if (s === 'PROCESSING' || s === 'PROGRESS' || s === 'RETRYING') return 'processing';
  if (s === 'COMPLETED' || s === 'SUCCESS') return 'completed';
  if (s === 'FAILED' || s === 'FAILURE') return 'failed';
  return status.toLowerCase() as StatusFilter;
}

function statusColor(status: string): string {
  switch (status) {
    case 'pending':
      return 'bg-slate-800 text-slate-400 border-slate-700';
    case 'processing':
      return 'bg-sky-950 text-sky-400 border-sky-800';
    case 'completed':
      return 'bg-emerald-950 text-emerald-400 border-emerald-800';
    case 'failed':
      return 'bg-rose-950 text-rose-400 border-rose-800';
    default:
      return 'bg-slate-800 text-slate-400 border-slate-700';
  }
}

function progressBarColor(status: string): string {
  switch (status) {
    case 'processing':
      return 'bg-sky-500';
    case 'completed':
      return 'bg-emerald-500';
    case 'failed':
      return 'bg-rose-500';
    default:
      return 'bg-slate-600';
  }
}

function errorTypeColor(type: string | null): string {
  switch (type) {
    case 'oom':
      return 'bg-purple-950 text-purple-400 border-purple-800';
    case 'timeout':
      return 'bg-yellow-950 text-yellow-400 border-yellow-800';
    case 'validation':
      return 'bg-blue-950 text-blue-400 border-blue-800';
    case 'runtime':
    default:
      return 'bg-rose-950 text-rose-400 border-rose-800';
  }
}

function errorTypeIcon(type: string | null) {
  switch (type) {
    case 'oom':
      return '💾';
    case 'timeout':
      return '⏱️';
    case 'validation':
      return '⚠️';
    default:
      return '🐛';
  }
}

function formatDuration(start: string | null, end: string | null): string {
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

function formatTime(iso: string | null): string {
  if (!iso) return '—';
  const d = new Date(iso);
  return d.toLocaleString();
}

export default function QueueDashboard() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('');
  const [typeFilter, setTypeFilter] = useState('');
  const [searchQuery, setSearchQuery] = useState('');
  const [errorTypeFilter, setErrorTypeFilter] = useState<ErrorTypeFilter>('all');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retryingIds, setRetryingIds] = useState<Set<string>>(new Set());
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

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
        searchQuery || undefined,
        errorTypeFilter !== 'all' ? errorTypeFilter : undefined
      );
      setTasks(data.tasks);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, typeFilter, searchQuery, errorTypeFilter]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  const handleRetry = async (taskId: string) => {
    setRetryingIds((prev) => new Set(prev).add(taskId));
    try {
      await retryTask(taskId);
      await loadTasks();
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

  // WebSocket real-time updates
  useEffect(() => {
    const wsUrl = `${process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'}/api/ws/tasks`.replace(/^http/, 'ws');

    const connect = () => {
      const ws = new WebSocket(wsUrl);
      wsRef.current = ws;

      ws.onmessage = (event) => {
        try {
          const update = JSON.parse(event.data);
          setTasks((prev) =>
            prev.map((t) =>
              t.task_id === update.task_id
                ? {
                    ...t,
                    status: update.status || t.status,
                    progress: update.progress !== undefined ? update.progress : t.progress,
                    error: update.error !== undefined ? update.error : t.error,
                    traceback: update.traceback !== undefined ? update.traceback : t.traceback,
                    error_type: update.error_type !== undefined ? update.error_type : t.error_type,
                    retry_count: update.retry_count !== undefined ? update.retry_count : t.retry_count,
                    max_retries: update.max_retries !== undefined ? update.max_retries : t.max_retries,
                  }
                : t
            )
          );
        } catch {
          // ignore malformed messages
        }
      };

      ws.onclose = () => {
        reconnectTimeoutRef.current = setTimeout(connect, 3000);
      };

      ws.onerror = () => {
        ws.close();
      };
    };

    connect();

    return () => {
      if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
      wsRef.current?.close();
    };
  }, []);

  const totalPages = Math.max(1, Math.ceil(total / pageSize));
  const normalizedTasks = tasks.map((t) => ({ ...t, status: normalizeStatus(t.status) }));

  const expandedTaskData = expandedTask ? normalizedTasks.find((t) => t.task_id === expandedTask) : null;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-100">Queue Dashboard</h2>
        <p className="text-xs text-slate-400">
          Monitor all background Celery tasks in real-time with progress and history.
        </p>
      </div>

      {/* Filters */}
      <div className="flex flex-col sm:flex-row gap-4 items-start sm:items-center bg-slate-900 border border-slate-800 p-4 rounded-lg">
        <div className="flex items-center gap-2 text-slate-300">
          <ListFilter className="w-4 h-4 text-sky-400" />
          <span className="text-sm font-medium">Filters</span>
        </div>

        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value as StatusFilter); setPage(1); }}
          className="bg-slate-950 border border-slate-700 px-3 py-1.5 rounded text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
        >
          {STATUS_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <select
          value={typeFilter}
          onChange={(e) => { setTypeFilter(e.target.value); setPage(1); }}
          className="bg-slate-950 border border-slate-700 px-3 py-1.5 rounded text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
        >
          {TASK_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <select
          value={errorTypeFilter}
          onChange={(e) => { setErrorTypeFilter(e.target.value as ErrorTypeFilter); setPage(1); }}
          className="bg-slate-950 border border-slate-700 px-3 py-1.5 rounded text-sm text-slate-100 focus:outline-none focus:ring-1 focus:ring-sky-500"
        >
          {ERROR_TYPE_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>{opt.label}</option>
          ))}
        </select>

        <div className="relative flex-1 w-full sm:w-auto">
          <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search errors..."
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-slate-950 border border-slate-700 pl-9 pr-3 py-1.5 rounded text-sm text-slate-100 placeholder-slate-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </div>

        <div className="ml-auto flex items-center gap-2">
          <button
            onClick={loadTasks}
            disabled={loading}
            className="p-2 border border-slate-700 rounded text-slate-400 hover:bg-slate-800 hover:text-slate-200 transition disabled:opacity-50"
            title="Refresh"
          >
            <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
          </button>
        </div>
      </div>

      {/* Stats bar */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
        {(['pending', 'processing', 'completed', 'failed'] as const).map((status) => {
          const count = normalizedTasks.filter((t) => t.status === status).length;
          return (
            <div key={status} className="bg-slate-900 border border-slate-800 rounded-lg p-3">
              <div className="text-xs text-slate-500 uppercase tracking-wide">{status}</div>
              <div className={`text-2xl font-bold ${status === 'completed' ? 'text-emerald-400' : status === 'failed' ? 'text-rose-400' : status === 'processing' ? 'text-sky-400' : 'text-slate-400'}`}>
                {count}
              </div>
            </div>
          );
        })}
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
              {loading && normalizedTasks.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center">
                    <Loader2 className="w-6 h-6 animate-spin text-sky-500 mx-auto" />
                    <p className="text-slate-400 text-xs mt-2">Loading tasks...</p>
                  </td>
                </tr>
              ) : normalizedTasks.length === 0 ? (
                <tr>
                  <td colSpan={8} className="px-4 py-12 text-center text-slate-500 text-sm">
                    No tasks found.
                  </td>
                </tr>
              ) : (
                normalizedTasks.map((task) => (
                  <React.Fragment key={task.task_id}>
                    <tr className={`hover:bg-slate-850/40 transition ${expandedTask === task.task_id ? 'bg-slate-800/50' : ''}`}>
                      <td className="px-4 py-3">
                        <span className="font-mono text-xs text-slate-300 truncate block max-w-[200px]" title={task.task_id}>
                          {task.task_id.substring(0, 12)}...
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-slate-300 capitalize">{task.name}</span>
                      </td>
                      <td className="px-4 py-3">
                        <span className={`inline-flex items-center gap-1.5 text-xs px-2 py-0.5 rounded border font-mono ${statusColor(task.status)}`}>
                          {task.status === 'processing' && <Loader2 className="w-3 h-3 animate-spin" />}
                          {task.status === 'completed' && <CheckCircle2 className="w-3 h-3" />}
                          {task.status === 'failed' && <AlertCircle className="w-3 h-3" />}
                          {task.status}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 bg-slate-800 rounded-full h-1.5 overflow-hidden min-w-[60px]">
                            <div
                              className={`h-full transition-all duration-300 ${progressBarColor(task.status)}`}
                              style={{ width: `${task.progress || 0}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-400 w-8 text-right">{task.progress || 0}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span className="text-xs text-slate-400">
                          {task.retry_count}/{task.max_retries}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">
                        {formatDuration(task.created_at, task.updated_at)}
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">
                        {formatTime(task.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1">
                          {task.status === 'failed' && (
                            <>
                              <button
                                onClick={() => setExpandedTask(expandedTask === task.task_id ? null : task.task_id)}
                                className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-sky-400 transition"
                                title="View details"
                              >
                                {expandedTask === task.task_id ? <ChevronRight className="w-3 h-3 rotate-90" /> : <ChevronRight className="w-3 h-3" />}
                              </button>
                              <button
                                onClick={() => handleRetry(task.task_id)}
                                disabled={retryingIds.has(task.task_id)}
                                className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-sky-400 disabled:opacity-40 disabled:cursor-not-allowed transition"
                                title="Retry task"
                              >
                                {retryingIds.has(task.task_id) ? <Loader2 className="w-3 h-3 animate-spin" /> : <RotateCcw className="w-3 h-3" />}
                              </button>
                            </>
                          )}
                        </div>
                      </td>
                    </tr>
                    {expandedTask === task.task_id && (
                      <tr key={`${task.task_id}-expanded`}>
                        <td colSpan={8} className="px-4 py-4 bg-slate-950/50 border-t border-slate-800">
                          <div className="space-y-4">
                            {/* Error info */}
                            {task.error && (
                              <div>
                                <div className="flex items-center gap-2 mb-2">
                                  <Bug className="w-4 h-4 text-rose-400" />
                                  <span className="text-sm font-medium text-slate-200">Error</span>
                                  {task.error_type && (
                                    <span className={`text-xs px-2 py-0.5 rounded border ${errorTypeColor(task.error_type)}`}>
                                      {errorTypeIcon(task.error_type)} {task.error_type.toUpperCase()}
                                    </span>
                                  )}
                                </div>
                                <div className="bg-slate-900 border border-slate-800 rounded p-3">
                                  <p className="text-sm text-rose-300 font-mono">{task.error}</p>
                                </div>
                              </div>
                            )}

                            {/* Stack trace */}
                            {task.traceback && (
                              <div>
                                <div className="flex items-center justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    <FileText className="w-4 h-4 text-slate-400" />
                                    <span className="text-sm font-medium text-slate-200">Stack Trace</span>
                                  </div>
                                  <button
                                    onClick={() => {
                                      navigator.clipboard.writeText(task.traceback || '');
                                    }}
                                    className="text-xs text-slate-500 hover:text-slate-300 transition"
                                  >
                                    Copy
                                  </button>
                                </div>
                                <pre className="bg-slate-950 border border-slate-800 rounded p-4 text-xs text-slate-300 font-mono overflow-x-auto max-h-96 overflow-y-auto">
                                  <code>{task.traceback}</code>
                                </pre>
                              </div>
                            )}

                            {/* Logs */}
                            {task.logs && (
                              <div>
                                <div className="flex items-center gap-2 mb-2">
                                  <FileText className="w-4 h-4 text-slate-400" />
                                  <span className="text-sm font-medium text-slate-200">Logs</span>
                                </div>
                                <pre className="bg-slate-950 border border-slate-800 rounded p-4 text-xs text-slate-300 font-mono overflow-x-auto max-h-48 overflow-y-auto">
                                  <code>{task.logs}</code>
                                </pre>
                              </div>
                            )}

                            {/* Retry info */}
                            <div className="flex flex-wrap gap-4 text-xs text-slate-400">
                              <span>Retry Count: {task.retry_count}/{task.max_retries}</span>
                              {task.last_retry_at && (
                                <span>Last Retry: {formatTime(task.last_retry_at)}</span>
                              )}
                              <span>Created: {formatTime(task.created_at)}</span>
                              <span>Updated: {formatTime(task.updated_at)}</span>
                            </div>
                          </div>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>

      {/* Pagination */}
      <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-4 py-3 border-t border-slate-800 bg-slate-950/40">
        <div className="flex items-center gap-2 text-xs text-slate-400">
          <span>Rows per page:</span>
          <select
            value={pageSize}
            onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
            className="bg-slate-900 border border-slate-700 px-2 py-1 rounded text-slate-200 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {[10, 25, 50, 100].map((n) => (
              <option key={n} value={n}>{n}</option>
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
