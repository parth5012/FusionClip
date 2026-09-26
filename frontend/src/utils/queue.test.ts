import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  categorizeTaskStatus,
  applyTaskUpdate,
  adjustTaskCounts,
  calculateTaskCounts,
  parseTaskLogs,
  formatEventLabel,
  getEventBadgeStyle,
  hasTraceback,
  TaskUpdatePayload,
  TaskItem,
  TaskCounts,
  TaskLogEvent,
} from './queue';

describe('Task Queue: status categorization (#107)', () => {
  it('categorizes running statuses correctly', () => {
    assert.equal(categorizeTaskStatus('PROCESSING'), 'running');
    assert.equal(categorizeTaskStatus('PROGRESS'), 'running');
    assert.equal(categorizeTaskStatus('RUNNING'), 'running');
    assert.equal(categorizeTaskStatus('RETRYING'), 'running');
    assert.equal(categorizeTaskStatus('processing'), 'running');
  });

  it('categorizes pending statuses correctly', () => {
    assert.equal(categorizeTaskStatus('PENDING'), 'pending');
    assert.equal(categorizeTaskStatus('PENDING_RETRY'), 'pending');
    assert.equal(categorizeTaskStatus('QUEUED'), 'pending');
    assert.equal(categorizeTaskStatus('WAITING'), 'pending');
    assert.equal(categorizeTaskStatus('pending'), 'pending');
  });

  it('categorizes failed statuses correctly', () => {
    assert.equal(categorizeTaskStatus('FAILED'), 'failed');
    assert.equal(categorizeTaskStatus('FAILURE'), 'failed');
    assert.equal(categorizeTaskStatus('failed'), 'failed');
  });

  it('categorizes completed statuses correctly', () => {
    assert.equal(categorizeTaskStatus('COMPLETED'), 'completed');
    assert.equal(categorizeTaskStatus('SUCCESS'), 'completed');
    assert.equal(categorizeTaskStatus('completed'), 'completed');
  });

  it('handles unknown, empty, or undefined statuses gracefully without throwing', () => {
    assert.equal(categorizeTaskStatus('SOME_UNKNOWN_STATE'), 'unknown');
    assert.equal(categorizeTaskStatus('CANCELLED'), 'unknown');
    assert.equal(categorizeTaskStatus(''), 'unknown');
    assert.equal(categorizeTaskStatus(null as any), 'unknown');
    assert.equal(categorizeTaskStatus(undefined as any), 'unknown');
  });
});

describe('Task Queue: live WebSocket task updates (#107)', () => {
  const baseTask: TaskItem = {
    id: 1,
    task_id: 'task-123',
    name: 'transcode',
    status: 'PENDING',
    progress: 0,
    error: null,
    retry_count: 0,
    max_retries: 3,
    created_at: '2026-09-26T10:00:00Z',
    updated_at: '2026-09-26T10:00:00Z',
  };

  it('updates an existing task with progress and status from WS frame', () => {
    const tasks: TaskItem[] = [baseTask];
    const update: TaskUpdatePayload = {
      task_id: 'task-123',
      status: 'PROCESSING',
      progress: 60,
      error: null,
    };

    const updated = applyTaskUpdate(tasks, update);
    assert.equal(updated.length, 1);
    assert.equal(updated[0].status, 'PROCESSING');
    assert.equal(updated[0].progress, 60);
    assert.equal(updated[0].name, 'transcode'); // preserved
  });

  it('surfaces error on failure frame for an existing task', () => {
    const tasks: TaskItem[] = [baseTask];
    const update: TaskUpdatePayload = {
      task_id: 'task-123',
      status: 'FAILED',
      progress: 0,
      error: 'CUDA out of memory',
    };

    const updated = applyTaskUpdate(tasks, update);
    assert.equal(updated.length, 1);
    assert.equal(updated[0].status, 'FAILED');
    assert.equal(updated[0].error, 'CUDA out of memory');
  });

  it('prepends a new task if frame arrives for a task not currently in list', () => {
    const tasks: TaskItem[] = [baseTask];
    const newUpdate: TaskUpdatePayload = {
      task_id: 'task-456',
      status: 'PROCESSING',
      progress: 10,
      error: null,
    };

    const updated = applyTaskUpdate(tasks, newUpdate);
    assert.equal(updated.length, 2);
    assert.equal(updated[0].task_id, 'task-456');
    assert.equal(updated[0].status, 'PROCESSING');
    assert.equal(updated[0].progress, 10);
    assert.equal(updated[1].task_id, 'task-123');
  });
});

describe('Task Queue: count adjustments on live frames (#107)', () => {
  const initialCounts: TaskCounts = {
    running: 2,
    pending: 3,
    failed: 1,
    completed: 5,
  };

  it('transitions task between buckets correctly (pending -> running)', () => {
    const updated = adjustTaskCounts(initialCounts, 'PENDING', 'PROCESSING');
    assert.equal(updated.pending, 2);
    assert.equal(updated.running, 3);
    assert.equal(updated.failed, 1);
    assert.equal(updated.completed, 5);
  });

  it('transitions task between buckets correctly (running -> completed)', () => {
    const updated = adjustTaskCounts(initialCounts, 'PROCESSING', 'COMPLETED');
    assert.equal(updated.running, 1);
    assert.equal(updated.completed, 6);
  });

  it('transitions task between buckets correctly (running -> failed)', () => {
    const updated = adjustTaskCounts(initialCounts, 'PROCESSING', 'FAILED');
    assert.equal(updated.running, 1);
    assert.equal(updated.failed, 2);
  });

  it('handles brand new task arriving in running state', () => {
    const updated = adjustTaskCounts(initialCounts, null, 'PROCESSING');
    assert.equal(updated.running, 3);
    assert.equal(updated.pending, 3);
  });

  it('never decrements counts below zero', () => {
    const emptyCounts: TaskCounts = { running: 0, pending: 0, failed: 0, completed: 0 };
    const updated = adjustTaskCounts(emptyCounts, 'PROCESSING', 'COMPLETED');
    assert.equal(updated.running, 0);
    assert.equal(updated.completed, 1);
  });
});

describe('Task Queue: calculateTaskCounts from task array (#107)', () => {
  it('correctly tallies task buckets from a list of tasks', () => {
    const tasks: TaskItem[] = [
      { id: 1, task_id: '1', name: 'transcode', status: 'PROCESSING', progress: 50 },
      { id: 2, task_id: '2', name: 'transcode', status: 'PENDING', progress: 0 },
      { id: 3, task_id: '3', name: 'transcode', status: 'FAILED', progress: 0, error: 'err' },
      { id: 4, task_id: '4', name: 'transcode', status: 'COMPLETED', progress: 100 },
      { id: 5, task_id: '5', name: 'transcode', status: 'UNKNOWN_STATUS', progress: 0 },
    ];

    const counts = calculateTaskCounts(tasks);
    assert.deepEqual(counts, {
      running: 1,
      pending: 1,
      failed: 1,
      completed: 1,
    });
  });
});

describe('Task Queue: task logs parsing and formatting (#108)', () => {
  it('parses JSON Lines logs into structured events', () => {
    const rawLogs = [
      JSON.stringify({ event: 'started', timestamp: '2026-09-26T10:00:00Z', task_name: 'transcode' }),
      JSON.stringify({
        event: 'failed',
        timestamp: '2026-09-26T10:00:05Z',
        error: 'CUDA out of memory',
        error_type: 'OOM',
        traceback: 'Traceback (most recent call last):\n  File "run.py", line 10\nMemoryError',
      }),
    ].join('\n');

    const events = parseTaskLogs(rawLogs);
    assert.equal(events.length, 2);
    assert.equal(events[0].event, 'started');
    assert.equal(events[0].task_name, 'transcode');
    assert.equal(events[1].event, 'failed');
    assert.equal(events[1].error_type, 'OOM');
    assert.match(events[1].traceback!, /MemoryError/);
  });

  it('parses JSON array format seamlessly', () => {
    const rawArray = JSON.stringify([
      { event: 'started', timestamp: '2026-09-26T10:00:00Z', task_name: 'waveform' },
      { event: 'finished', timestamp: '2026-09-26T10:00:03Z', status: 'COMPLETED', result_summary: 'OK' },
    ]);

    const events = parseTaskLogs(rawArray);
    assert.equal(events.length, 2);
    assert.equal(events[0].event, 'started');
    assert.equal(events[1].event, 'finished');
    assert.equal(events[1].status, 'COMPLETED');
  });

  it('handles null, undefined, empty, or whitespace logs gracefully', () => {
    assert.deepEqual(parseTaskLogs(null), []);
    assert.deepEqual(parseTaskLogs(undefined), []);
    assert.deepEqual(parseTaskLogs(''), []);
    assert.deepEqual(parseTaskLogs('   \n  \t '), []);
  });

  it('handles legacy non-JSON plain text lines without crashing', () => {
    const legacyLogs = 'Step 1/4: initial frame extraction\nStep 2/4: upscaling\nDone in 2.4s';
    const events = parseTaskLogs(legacyLogs);
    assert.equal(events.length, 3);
    assert.equal(events[0].event, 'log');
    assert.equal(events[0].message, 'Step 1/4: initial frame extraction');
    assert.equal(events[1].message, 'Step 2/4: upscaling');
  });

  it('handles mixed valid JSON lines and corrupt lines without dropping valid lines', () => {
    const mixedLogs = [
      JSON.stringify({ event: 'started', timestamp: '2026-09-26T10:00:00Z' }),
      '{INVALID_JSON_CORRUPT_LINE',
      JSON.stringify({ event: 'finished', timestamp: '2026-09-26T10:00:02Z', status: 'COMPLETED' }),
    ].join('\n');

    const events = parseTaskLogs(mixedLogs);
    assert.equal(events.length, 3);
    assert.equal(events[0].event, 'started');
    assert.equal(events[1].event, 'log');
    assert.equal(events[1].message, '{INVALID_JSON_CORRUPT_LINE');
    assert.equal(events[2].event, 'finished');
  });

  it('formats event labels accurately', () => {
    assert.equal(formatEventLabel({ event: 'started' }), 'Task Started');
    assert.equal(formatEventLabel({ event: 'failed' }), 'Task Failed');
    assert.equal(formatEventLabel({ event: 'retry' }), 'Task Retrying');
    assert.equal(formatEventLabel({ event: 'finished' }), 'Task Completed');
    assert.equal(formatEventLabel({ event: 'pruned' }), 'Logs Pruned');
    assert.equal(formatEventLabel({ event: 'log' }), 'Log');
    assert.equal(formatEventLabel({ event: 'custom_hook' }), 'Custom Hook');
  });

  it('returns badge style object for event types', () => {
    const startedStyle = getEventBadgeStyle({ event: 'started' });
    assert.ok(startedStyle.bg.includes('sky') || startedStyle.text.includes('sky'));

    const failedStyle = getEventBadgeStyle({ event: 'failed' });
    assert.ok(failedStyle.bg.includes('rose') || failedStyle.text.includes('rose'));

    const finishedStyle = getEventBadgeStyle({ event: 'finished' });
    assert.ok(finishedStyle.bg.includes('emerald') || finishedStyle.text.includes('emerald'));

    const retryStyle = getEventBadgeStyle({ event: 'retry' });
    assert.ok(retryStyle.bg.includes('amber') || retryStyle.text.includes('amber'));
  });

  it('detects presence of traceback', () => {
    assert.equal(hasTraceback({ event: 'failed', traceback: 'Traceback...' }), true);
    assert.equal(hasTraceback({ event: 'failed', traceback: '' }), false);
    assert.equal(hasTraceback({ event: 'failed', traceback: '   ' }), false);
    assert.equal(hasTraceback({ event: 'failed' }), false);
  });
});
