'use client';

import React, { useCallback, useEffect, useRef, useState } from 'react';
import { useStore, ColabMetrics } from '../store/useStore';
import { fetchColabMetrics } from '../utils/api';
import {
  Cpu,
  HardDrive,
  MemoryStick,
  Activity,
  Wifi,
  WifiOff,
  Zap,
  Clock,
  TrendingUp,
} from 'lucide-react';

function formatGB(bytes: number): string {
  return (bytes / 1024).toFixed(1);
}

function formatPercent(value: number): string {
  return `${value.toFixed(1)}%`;
}

function formatTime(ts: number): string {
  if (!ts) return '—';
  const d = new Date(ts * 1000);
  return d.toLocaleTimeString();
}

function GaugeBar({ percent, color, label }: { percent: number; color: string; label: string }) {
  const clamped = Math.min(100, Math.max(0, percent));
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-xs">
        <span className="text-slate-400 font-medium">{label}</span>
        <span className="text-slate-200 font-mono">{formatPercent(clamped)}</span>
      </div>
      <div className="h-3 bg-slate-800 rounded-full overflow-hidden border border-slate-700">
        <div
          className={`h-full rounded-full transition-all duration-500 ease-out ${color}`}
          style={{ width: `${clamped}%` }}
        />
      </div>
    </div>
  );
}

function MiniSparkline({ data, color, height = 60 }: { data: number[]; color: string; height?: number }) {
  if (data.length < 2) {
    return (
      <div
        className="flex items-center justify-center text-xs text-slate-500 border border-slate-800 rounded-md bg-slate-900/50"
        style={{ height }}
      >
        Waiting for data…
      </div>
    );
  }

  const max = Math.max(...data, 100);
  const width = 100;
  const points = data.map((v, i) => {
    const x = (i / (data.length - 1)) * width;
    const y = height - (v / max) * (height - 8) - 4;
    return `${x},${y}`;
  });

  return (
    <svg viewBox={`0 0 ${width} ${height}`} className="w-full" style={{ height }} preserveAspectRatio="none">
      <polyline
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        strokeLinejoin="round"
        strokeLinecap="round"
        points={points.join(' ')}
      />
    </svg>
  );
}

export default function MonitorPanel() {
  const { colabMetrics, colabMetricsHistory, setColabMetrics, pushMetricsHistory, clearMetricsHistory } =
    useStore();

  const [isConnected, setIsConnected] = useState(false);
  const [lastUpdated, setLastUpdated] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  const intervalRef = useRef<NodeJS.Timeout | null>(null);

  const pollMetrics = useCallback(async () => {
    try {
      const res = await fetchColabMetrics();
      if (res.status === 'connected' && res.metrics) {
        setColabMetrics(res.metrics);
        setIsConnected(true);
        setLastUpdated(Date.now());
        setError(null);
        pushMetricsHistory({
          timestamp: res.metrics.updated_at,
          vram_percent: res.metrics.vram_percent,
          ram_percent: res.metrics.ram_percent,
          cpu_load: res.metrics.cpu_load,
        });
      } else {
        setColabMetrics(null);
        setIsConnected(false);
      }
    } catch {
      setError('Failed to reach backend metrics endpoint');
      setIsConnected(false);
    }
  }, [setColabMetrics, pushMetricsHistory]);

  useEffect(() => {
    pollMetrics();
    intervalRef.current = setInterval(pollMetrics, 2000);
    return () => {
      if (intervalRef.current) clearInterval(intervalRef.current);
    };
  }, [pollMetrics]);

  const vramHistory = colabMetricsHistory.map((p) => p.vram_percent);
  const ramHistory = colabMetricsHistory.map((p) => p.ram_percent);
  const cpuHistory = colabMetricsHistory.map((p) => p.cpu_load);

  return (
    <div className="space-y-6 animate-fadeIn max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-xl font-bold text-white flex items-center gap-2">
            <Activity className="w-5 h-5 text-emerald-400" /> Colab Compute Monitor
          </h2>
          <p className="text-xs text-slate-400 mt-1">
            Real-time GPU/CPU utilization from the connected Google Colab notebook
          </p>
        </div>
        <div className="flex items-center gap-3">
          {isConnected ? (
            <span className="flex items-center gap-2 text-xs font-semibold text-emerald-400 bg-emerald-950/40 border border-emerald-800 px-3 py-1.5 rounded-md">
              <Wifi className="w-3.5 h-3.5" /> Connected
            </span>
          ) : (
            <span className="flex items-center gap-2 text-xs font-semibold text-rose-400 bg-rose-950/40 border border-rose-800 px-3 py-1.5 rounded-md">
              <WifiOff className="w-3.5 h-3.5" /> Disconnected
            </span>
          )}
          {lastUpdated && (
            <span className="text-[10px] text-slate-500 flex items-center gap-1">
              <Clock className="w-3 h-3" />
              {formatTime(lastUpdated / 1000)}
            </span>
          )}
        </div>
      </div>

      {error && (
        <p className="text-xs text-rose-400 bg-rose-950/30 border border-rose-900/50 rounded-md px-3 py-2">
          {error}
        </p>
      )}

      {/* Live Gauges */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {/* VRAM Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
          <div className="flex items-center gap-2">
            <HardDrive className="w-4 h-4 text-violet-400" />
            <h3 className="text-sm font-bold text-white">VRAM</h3>
          </div>
          <GaugeBar
            percent={colabMetrics?.vram_percent ?? 0}
            color="bg-gradient-to-r from-violet-500 to-fuchsia-500"
            label="GPU Memory"
          />
          <div className="text-xs text-slate-400 font-mono">
            {colabMetrics ? `${formatGB(colabMetrics.vram_used)} / ${formatGB(colabMetrics.vram_total)} GB` : '—'}
          </div>
        </div>

        {/* RAM Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
          <div className="flex items-center gap-2">
            <MemoryStick className="w-4 h-4 text-sky-400" />
            <h3 className="text-sm font-bold text-white">RAM</h3>
          </div>
          <GaugeBar
            percent={colabMetrics?.ram_percent ?? 0}
            color="bg-gradient-to-r from-sky-500 to-cyan-500"
            label="System Memory"
          />
          <div className="text-xs text-slate-400 font-mono">
            {colabMetrics ? `${formatGB(colabMetrics.ram_used)} / ${formatGB(colabMetrics.ram_total)} GB` : '—'}
          </div>
        </div>

        {/* CPU Card */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
          <div className="flex items-center gap-2">
            <Cpu className="w-4 h-4 text-amber-400" />
            <h3 className="text-sm font-bold text-white">CPU</h3>
          </div>
          <GaugeBar
            percent={colabMetrics?.cpu_load ?? 0}
            color="bg-gradient-to-r from-amber-500 to-orange-500"
            label="Processor Load"
          />
          <div className="text-xs text-slate-400 font-mono">
            {colabMetrics ? formatPercent(colabMetrics.cpu_load) : '—'}
          </div>
        </div>
      </div>

      {/* Active Task */}
      {colabMetrics?.active_task && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 flex items-center gap-3">
          <Zap className="w-4 h-4 text-yellow-400 animate-pulse" />
          <div>
            <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active Task</span>
            <p className="text-sm font-mono text-yellow-300">{colabMetrics.active_task}</p>
          </div>
        </div>
      )}

      {/* Historical Charts */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5 space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-sm font-bold text-white flex items-center gap-2">
            <TrendingUp className="w-4 h-4 text-emerald-400" /> Utilization History
          </h3>
          {colabMetricsHistory.length > 0 && (
            <button
              onClick={clearMetricsHistory}
              className="text-[10px] text-slate-500 hover:text-slate-300 border border-slate-700 px-2 py-1 rounded transition"
            >
              Clear
            </button>
          )}
        </div>

        <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
          <div>
            <span className="text-[10px] text-violet-400 font-semibold uppercase tracking-wider">VRAM %</span>
            <MiniSparkline data={vramHistory} color="#a78bfa" height={80} />
          </div>
          <div>
            <span className="text-[10px] text-sky-400 font-semibold uppercase tracking-wider">RAM %</span>
            <MiniSparkline data={ramHistory} color="#38bdf8" height={80} />
          </div>
          <div>
            <span className="text-[10px] text-amber-400 font-semibold uppercase tracking-wider">CPU %</span>
            <MiniSparkline data={cpuHistory} color="#fbbf24" height={80} />
          </div>
        </div>

        {colabMetricsHistory.length > 0 && (
          <p className="text-[10px] text-slate-500 text-right">
            {colabMetricsHistory.length} samples · 2s interval
          </p>
        )}
      </div>

      {/* Connection Info */}
      <div className="bg-slate-950/40 border border-slate-800 rounded-md p-4 text-xs text-slate-400 space-y-1">
        <p>
          Metrics are reported by the Colab notebook via WebSocket and cached in Redis. The dashboard polls
          <span className="text-slate-300 font-mono"> GET /api/colab/metrics</span> every 2 seconds.
        </p>
        <p className="text-slate-500">
          Data is retained for the last 120 samples (~4 minutes) during the browser session.
        </p>
      </div>
    </div>
  );
}
