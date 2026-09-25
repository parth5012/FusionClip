/* Colab tunnel status resolution (ticket #79).
 *
 * The effective tunnel state shown in the UI is derived from TWO backend
 * sources — never from localStorage:
 *   1. `colab_tunnel_status` in GET /api/settings (user intent: the operator
 *      pressed Connect/Disconnect, or saved an endpoint URL), and
 *   2. GET /api/colab/metrics `status` (liveness: the backend reports
 *      "disconnected" when no notebook metrics arrived within 10s —
 *      see settings.py `colab_get_metrics`).
 *
 * Effective status is 'running' ONLY when both agree; anything else means
 * the badge/Settings panel must show Disconnected.
 */

export type TunnelStatus = 'running' | 'disconnected';
export type MetricsLiveness = 'connected' | 'disconnected';

/** How often the header re-reads tunnel state from the backend. */
export const TUNNEL_POLL_INTERVAL_MS = 5000;

/** Backend marks metrics stale after 10s without a notebook report. */
export const TUNNEL_STALE_AFTER_MS = 10_000;

/** The settings store holds free-form strings; only exact 'running' opts in. */
export function normalizeSettingsStatus(value: unknown): TunnelStatus {
  return value === 'running' ? 'running' : 'disconnected';
}

/** Combine user intent (settings) with liveness (metrics) into one status. */
export function resolveTunnelStatus(
  settingsStatus: TunnelStatus,
  metricsStatus: MetricsLiveness,
): TunnelStatus {
  return settingsStatus === 'running' && metricsStatus === 'connected'
    ? 'running'
    : 'disconnected';
}
