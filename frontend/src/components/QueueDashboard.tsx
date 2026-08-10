'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import {
  RefreshCw, Loader2, CheckCircle2, AlertCircle, Clock,
  ChevronRight, ChevronLeft, ChevronsLeft, ChevronsRight,
  ListFilter
} from 'lucide-react';
import { fetchTasks, TaskListItem } from '../utils/api';

type StatusFilter = '' | 'pending' | 'processing' | 'completed' | 'failed';

const STATUS_OPTIONS: { value: StatusFilter; label: string }[] = [
  { value: '', label: 'All Statuses' },
  { value: 'pending', label: 'Pending' },
  { value: 'processing', label: 'Processing' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
];

const TASK_TYPE_OPTIONS = [
  { value: '', label: 'All Types' },
  { value: 'transcode', label: 'Transcode' },
  { value: 'upscale', label: 'Upscale' },
  { value: 'thumbnail', label: 'Thumbnail' },
  { value: 'waveform', label: 'Waveform' },
  { value: 'audio_extract', label: 'Audio Extract' },
];

function normalizeStatus(status: string): string {
  const s = status.toUpperCase();
  if (s === 'PENDING') return 'pending';
  if (s === 'PROCESSING' || s === 'PROGRESS') return 'processing';
  if (s === 'COMPLETED' || s === 'SUCCESS') return 'completed';
  if (s === 'FAILED' || s === 'FAILURE') return 'failed';
  return s.toLowerCase();
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

function formatDuration(start: string | null, end: string | null): string {
  if (!start) return '—';
  const s = new Date(start).getTime();
  const e = end ? new Date(end).getTime() : Date.now();
  const diff = Math.max(0, e - s);
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
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const statusUpper = statusFilter ? statusFilter.toUpperCase() : undefined;
      const data = await fetchTasks(page, pageSize, statusUpper, typeFilter || undefined);
      setTasks(data.tasks);
      setTotal(data.total);
    } catch (err: any) {
      setError(err.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, typeFilter]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  // WebSocket for real-time updates
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

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h2 className="text-xl font-bold text-slate-100">Queue Dashboard</h2>
        <p className="text-xs text-slate-400">
          Monitor all background Celery tasks with real-time progress and history.
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
        {(['pending', 'processing', 'completed', 'failed'] as const).map((s) => {
          const count = normalizedTasks.filter((t) => t.status === s).length;
          return (
            <div key={s} className={`rounded-lg border p-3 ${statusColor(s)}`}>
              <div className="text-lg font-bold">{count}</div>
              <div className="text-xs capitalize opacity-80">{s}</div>
            </div>
          );
        })}
      </div>

      {/* Error state */}
      {error && (
        <div className="bg-rose-950/20 border border-rose-800/80 rounded-lg p-4 text-rose-300 text-sm">
          {error}
        </div>
      )}

      {/* Task table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-slate-950 text-xs font-semibold text-slate-400 uppercase tracking-wider">
                <th className="px-4 py-3 text-left">Name</th>
                <th className="px-4 py-3 text-left">Type</th>
                <th className="px-4 py-3 text-left">Status</th>
                <th className="px-4 py-3 text-left min-w-[140px]">Progress</th>
                <th className="px-4 py-3 text-left">Duration</th>
                <th className="px-4 py-3 text-left">Created</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {loading && normalizedTasks.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center">
                    <Loader2 className="w-6 h-6 animate-spin text-sky-500 mx-auto" />
                    <p className="text-slate-400 text-xs mt-2">Loading tasks...</p>
                  </td>
                </tr>
              ) : normalizedTasks.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-12 text-center text-slate-500 text-sm">
                    No tasks found.
                  </td>
                </tr>
              ) : (
                normalizedTasks.map((task) => (
                  <tr key={task.task_id} className="hover:bg-slate-850/40 transition">
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
                        {task.status === 'pending' && <Clock className="w-3 h-3" />}
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
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {formatDuration(task.created_at, task.updated_at)}
                    </td>
                    <td className="px-4 py-3 text-slate-400 text-xs">
                      {formatTime(task.created_at)}
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex flex-col sm:flex-row items-center justify-between gap-3 px-4 py-3 border-t border-slate-800 bg-slate-950/40">
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
              disabled={page <= 1}
              className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronsLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage(totalPages)}
              disabled={page >= totalPages}
              className="p-1.5 rounded border border-slate-700 text-slate-400 hover:bg-slate-800 hover:text-slate-200 disabled:opacity-40 disabled:cursor-not-allowed transition"
            >
              <ChevronsRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
