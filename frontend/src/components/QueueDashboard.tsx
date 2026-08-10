'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { fetchTasks, retryTask, TaskListItem } from '../utils/api';
import { RefreshCw, RotateCcw, Search, ChevronLeft, ChevronRight, AlertTriangle, Clock, CheckCircle2, XCircle, Loader2 } from 'lucide-react';

const STATUS_OPTIONS = ['all', 'PROCESSING', 'COMPLETED', 'FAILED', 'PENDING_RETRY'];
const ERROR_TYPE_OPTIONS = ['all', 'OOM', 'timeout', 'validation', 'runtime'];
const PAGE_SIZE_OPTIONS = [10, 25, 50, 100];

function StatusBadge({ status }: { status: string }) {
  const config: Record<string, { bg: string; text: string; icon: React.ReactNode }> = {
    PROCESSING: { bg: 'bg-sky-900/40 border-sky-700', text: 'text-sky-400', icon: <Loader2 className="w-3 h-3 animate-spin" /> },
    COMPLETED: { bg: 'bg-emerald-900/40 border-emerald-700', text: 'text-emerald-400', icon: <CheckCircle2 className="w-3 h-3" /> },
    FAILED: { bg: 'bg-red-900/40 border-red-700', text: 'text-red-400', icon: <XCircle className="w-3 h-3" /> },
    PENDING_RETRY: { bg: 'bg-amber-900/40 border-amber-700', text: 'text-amber-400', icon: <Clock className="w-3 h-3" /> },
  };
  const c = config[status] || config.FAILED;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${c.bg} ${c.text}`}>
      {c.icon}
      {status}
    </span>
  );
}

function ErrorTypeBadge({ type }: { type: string | null }) {
  if (!type) return null;
  const config: Record<string, string> = {
    OOM: 'bg-red-900/60 text-red-300 border-red-600',
    timeout: 'bg-amber-900/60 text-amber-300 border-amber-600',
    validation: 'bg-orange-900/60 text-orange-300 border-orange-600',
    runtime: 'bg-slate-800 text-slate-300 border-slate-600',
  };
  const cls = config[type] || config.runtime;
  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded text-xs font-medium border ${cls}`}>
      <AlertTriangle className="w-3 h-3" />
      {type}
    </span>
  );
}

export default function QueueDashboard() {
  const [tasks, setTasks] = useState<TaskListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [pageSize, setPageSize] = useState(25);
  const [statusFilter, setStatusFilter] = useState('all');
  const [errorTypeFilter, setErrorTypeFilter] = useState('all');
  const [searchQuery, setSearchQuery] = useState('');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [retrying, setRetrying] = useState<Set<string>>(new Set());
  const [expandedTask, setExpandedTask] = useState<string | null>(null);
  const [stats, setStats] = useState({ pending: 0, processing: 0, completed: 0, failed: 0 });

  const loadTasks = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: Parameters<typeof fetchTasks>[0] = page;
      const params2: Parameters<typeof fetchTasks>[1] = pageSize;
      const statusParam = statusFilter !== 'all' ? statusFilter : undefined;
      const data = await fetchTasks(page, pageSize, statusParam, undefined, searchQuery || undefined);
      setTasks(data.tasks);
      setTotal(data.total);

      const s = { pending: 0, processing: 0, completed: 0, failed: 0 };
      data.tasks.forEach(t => {
        if (t.status === 'PROCESSING') s.processing++;
        else if (t.status === 'COMPLETED') s.completed++;
        else if (t.status === 'FAILED' || t.status === 'PENDING_RETRY') s.failed++;
        else s.pending++;
      });
      setStats(s);
    } catch (e: any) {
      setError(e.message || 'Failed to load tasks');
    } finally {
      setLoading(false);
    }
  }, [page, pageSize, statusFilter, searchQuery]);

  useEffect(() => {
    loadTasks();
  }, [loadTasks]);

  useEffect(() => {
    const interval = setInterval(loadTasks, 3000);
    return () => clearInterval(interval);
  }, [loadTasks]);

  const handleRetry = async (taskId: string) => {
    setRetrying(prev => new Set(prev).add(taskId));
    try {
      await retryTask(taskId);
      await loadTasks();
    } catch (e: any) {
      setError(e.message || 'Failed to retry task');
    } finally {
      setRetrying(prev => {
        const next = new Set(prev);
        next.delete(taskId);
        return next;
      });
    }
  };

  const totalPages = Math.max(1, Math.ceil(total / pageSize));

  return (
    <div className="space-y-6">
      <div>
        <h2 className="text-xl font-bold text-slate-100">Queue Dashboard</h2>
        <p className="text-xs text-slate-400">
          Monitor background Celery tasks, retry failures, inspect error diagnostics.
        </p>
      </div>

      {/* Stats Bar */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Processing</div>
          <div className="text-lg font-bold text-sky-400">{stats.processing}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Completed</div>
          <div className="text-lg font-bold text-emerald-400">{stats.completed}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Failed</div>
          <div className="text-lg font-bold text-red-400">{stats.failed}</div>
        </div>
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-3">
          <div className="text-xs text-slate-500">Total</div>
          <div className="text-lg font-bold text-slate-200">{total}</div>
        </div>
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3 bg-slate-900 border border-slate-800 rounded-lg p-3">
        <div className="flex items-center gap-2 flex-1 min-w-[200px]">
          <Search className="w-4 h-4 text-slate-500" />
          <input
            type="text"
            placeholder="Search tasks..."
            value={searchQuery}
            onChange={(e) => { setSearchQuery(e.target.value); setPage(1); }}
            className="bg-transparent border-none text-sm text-slate-200 placeholder-slate-500 outline-none w-full"
          />
        </div>
        <select
          value={statusFilter}
          onChange={(e) => { setStatusFilter(e.target.value); setPage(1); }}
          className="bg-slate-800 border border-slate-700 text-sm text-slate-200 rounded px-2 py-1"
        >
          {STATUS_OPTIONS.map(s => (
            <option key={s} value={s}>{s === 'all' ? 'All Statuses' : s}</option>
          ))}
        </select>
        <select
          value={errorTypeFilter}
          onChange={(e) => { setErrorTypeFilter(e.target.value); setPage(1); }}
          className="bg-slate-800 border border-slate-700 text-sm text-slate-200 rounded px-2 py-1"
        >
          {ERROR_TYPE_OPTIONS.map(t => (
            <option key={t} value={t}>{t === 'all' ? 'All Error Types' : t}</option>
          ))}
        </select>
        <button
          onClick={loadTasks}
          disabled={loading}
          className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 border border-slate-700 text-slate-400 hover:text-slate-200 transition disabled:opacity-50"
          title="Refresh"
        >
          <RefreshCw className={`w-4 h-4 ${loading ? 'animate-spin' : ''}`} />
        </button>
      </div>

      {/* Error Banner */}
      {error && (
        <div className="bg-red-900/30 border border-red-800 rounded-lg p-3 text-sm text-red-300 flex items-center gap-2">
          <AlertTriangle className="w-4 h-4" />
          {error}
        </div>
      )}

      {/* Task Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <div className="overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-800 bg-slate-950/50">
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Name</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Type</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Status</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Progress</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Retries</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Error</th>
                <th className="text-left px-4 py-3 text-xs font-medium text-slate-500 uppercase">Actions</th>
              </tr>
            </thead>
            <tbody>
              {loading && tasks.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500">
                    <Loader2 className="w-6 h-6 animate-spin mx-auto mb-2" />
                    Loading tasks...
                  </td>
                </tr>
              ) : tasks.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-12 text-slate-500">
                    No tasks found
                  </td>
                </tr>
              ) : (
                tasks.map((task) => (
                  <React.Fragment key={task.task_id}>
                    <tr className="border-b border-slate-800/50 hover:bg-slate-800/30 transition">
                      <td className="px-4 py-3 text-slate-200 font-medium">{task.name}</td>
                      <td className="px-4 py-3 text-slate-400">{task.name}</td>
                      <td className="px-4 py-3"><StatusBadge status={task.status} /></td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <div className="w-20 h-1.5 bg-slate-800 rounded-full overflow-hidden">
                            <div
                              className={`h-full rounded-full transition-all ${
                                task.status === 'COMPLETED' ? 'bg-emerald-500' :
                                task.status === 'FAILED' ? 'bg-red-500' : 'bg-sky-500'
                              }`}
                              style={{ width: `${task.progress}%` }}
                            />
                          </div>
                          <span className="text-xs text-slate-500">{task.progress}%</span>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-slate-400 text-xs">
                        {task.retry_count}/{task.max_retries}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <ErrorTypeBadge type={task.error_type} />
                          {task.error && (
                            <button
                              onClick={() => setExpandedTask(expandedTask === task.task_id ? null : task.task_id)}
                              className="text-xs text-sky-500 hover:text-sky-400"
                            >
                              {expandedTask === task.task_id ? 'Hide' : 'Details'}
                            </button>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        {(task.status === 'FAILED' || task.status === 'PENDING_RETRY') && (
                          <button
                            onClick={() => handleRetry(task.task_id)}
                            disabled={retrying.has(task.task_id)}
                            className="inline-flex items-center gap-1 px-2 py-1 rounded text-xs font-medium bg-sky-900/40 border border-sky-700 text-sky-400 hover:bg-sky-800/60 transition disabled:opacity-50"
                          >
                            {retrying.has(task.task_id) ? (
                              <Loader2 className="w-3 h-3 animate-spin" />
                            ) : (
                              <RotateCcw className="w-3 h-3" />
                            )}
                            Retry
                          </button>
                        )}
                      </td>
                    </tr>
                    {expandedTask === task.task_id && task.traceback && (
                      <tr>
                        <td colSpan={7} className="px-4 py-3 bg-slate-950/60 border-b border-slate-800">
                          <details open>
                            <summary className="text-xs text-slate-400 cursor-pointer mb-2 font-medium">
                              Stack Trace
                            </summary>
                            <pre className="text-xs text-slate-300 bg-slate-900 border border-slate-800 rounded p-3 overflow-x-auto max-h-64 overflow-y-auto font-mono leading-relaxed">
                              {task.traceback}
                            </pre>
                            {task.error && (
                              <div className="mt-2">
                                <span className="text-xs text-slate-500 font-medium">Error: </span>
                                <span className="text-xs text-red-400">{task.error}</span>
                              </div>
                            )}
                          </details>
                        </td>
                      </tr>
                    )}
                  </React.Fragment>
                ))
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination */}
        <div className="flex items-center justify-between px-4 py-3 border-t border-slate-800 bg-slate-950/30">
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">Rows per page:</span>
            <select
              value={pageSize}
              onChange={(e) => { setPageSize(Number(e.target.value)); setPage(1); }}
              className="bg-slate-800 border border-slate-700 text-xs text-slate-200 rounded px-2 py-1"
            >
              {PAGE_SIZE_OPTIONS.map(s => (
                <option key={s} value={s}>{s}</option>
              ))}
            </select>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500">
              Page {page} of {totalPages} ({total} total)
            </span>
            <button
              onClick={() => setPage(p => Math.max(1, p - 1))}
              disabled={page <= 1}
              className="p-1 rounded bg-slate-800 border border-slate-700 text-slate-400 hover:text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronLeft className="w-4 h-4" />
            </button>
            <button
              onClick={() => setPage(p => Math.min(totalPages, p + 1))}
              disabled={page >= totalPages}
              className="p-1 rounded bg-slate-800 border border-slate-700 text-slate-400 hover:text-slate-200 disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <ChevronRight className="w-4 h-4" />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
