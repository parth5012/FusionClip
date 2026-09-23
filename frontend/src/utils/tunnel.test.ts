import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  normalizeSettingsStatus,
  resolveTunnelStatus,
  TUNNEL_POLL_INTERVAL_MS,
  TUNNEL_STALE_AFTER_MS,
} from './tunnel';

describe('tunnel status resolution', () => {
  it('normalizes settings status strictly', () => {
    assert.equal(normalizeSettingsStatus('running'), 'running');
    assert.equal(normalizeSettingsStatus('disconnected'), 'disconnected');
    assert.equal(normalizeSettingsStatus('RUNNING'), 'disconnected');
    assert.equal(normalizeSettingsStatus(null), 'disconnected');
    assert.equal(normalizeSettingsStatus(undefined), 'disconnected');
    assert.equal(normalizeSettingsStatus({}), 'disconnected');
  });

  it('resolves effective status to running only when intent is running and metrics connected', () => {
    assert.equal(resolveTunnelStatus('running', 'connected'), 'running');
    assert.equal(resolveTunnelStatus('running', 'disconnected'), 'disconnected');
    assert.equal(resolveTunnelStatus('disconnected', 'connected'), 'disconnected');
    assert.equal(resolveTunnelStatus('disconnected', 'disconnected'), 'disconnected');
  });

  it('has expected poll and stale timing constants', () => {
    assert.equal(TUNNEL_POLL_INTERVAL_MS, 5000);
    assert.equal(TUNNEL_STALE_AFTER_MS, 10000);
  });
});
