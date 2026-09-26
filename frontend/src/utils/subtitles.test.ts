import { describe, it } from 'node:test';
import assert from 'node:assert/strict';
import {
  validateSubtitleFile,
  isValidVTTContent,
  convertSrtToVtt,
  parseSubtitleCues,
  resolveActiveTrackId,
  normalizeTrackLabel,
} from './subtitles';

const SAMPLE_VTT = `WEBVTT

1
00:00:01.000 --> 00:00:04.000
Hello world, this is a test caption.

2
00:00:05.500 --> 00:00:08.200
Second subtitle line here.
`;

const SAMPLE_SRT = `1
00:00:01,000 --> 00:00:04,000
Hello world, this is a test caption.

2
00:00:05,500 --> 00:00:08,200
Second subtitle line here.
`;

describe('validateSubtitleFile', () => {
  it('accepts .vtt file within size cap', () => {
    const res = validateSubtitleFile('captions.vtt', 1024);
    assert.equal(res.valid, true);
    assert.equal(res.error, undefined);
  });

  it('accepts .srt file within size cap', () => {
    const res = validateSubtitleFile('captions.srt', 2048);
    assert.equal(res.valid, true);
  });

  it('rejects unsupported file extensions', () => {
    const res = validateSubtitleFile('notes.txt', 500);
    assert.equal(res.valid, false);
    assert.match(res.error!, /Only \.vtt and \.srt files/i);
  });

  it('rejects files exceeding size cap (2MB)', () => {
    const res = validateSubtitleFile('huge.vtt', 3 * 1024 * 1024);
    assert.equal(res.valid, false);
    assert.match(res.error!, /exceeds maximum allowed size/i);
  });
});

describe('isValidVTTContent', () => {
  it('identifies valid WEBVTT content', () => {
    assert.equal(isValidVTTContent(SAMPLE_VTT), true);
    assert.equal(isValidVTTContent('WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi'), true);
    assert.equal(isValidVTTContent('\uFEFFWEBVTT - with header comment'), true);
  });

  it('rejects content without WEBVTT header', () => {
    assert.equal(isValidVTTContent('Not a vtt file'), false);
    assert.equal(isValidVTTContent(SAMPLE_SRT), false);
  });
});

describe('convertSrtToVtt', () => {
  it('converts SRT to valid WebVTT format', () => {
    const vtt = convertSrtToVtt(SAMPLE_SRT);
    assert.ok(vtt.startsWith('WEBVTT'));
    assert.ok(vtt.includes('00:00:01.000 --> 00:00:04.000'));
    assert.ok(vtt.includes('00:00:05.500 --> 00:00:08.200'));
    assert.ok(vtt.includes('Hello world, this is a test caption.'));
  });
});

describe('parseSubtitleCues', () => {
  it('extracts cues from VTT text with millisecond timestamps', () => {
    const cues = parseSubtitleCues(SAMPLE_VTT);
    assert.equal(cues.length, 2);
    assert.equal(cues[0].start, 1);
    assert.equal(cues[0].end, 4);
    assert.equal(cues[0].text, 'Hello world, this is a test caption.');
    assert.equal(cues[1].start, 5.5);
    assert.equal(cues[1].end, 8.2);
  });

  it('extracts cues from SRT text', () => {
    const cues = parseSubtitleCues(SAMPLE_SRT);
    assert.equal(cues.length, 2);
    assert.equal(cues[0].start, 1);
    assert.equal(cues[0].end, 4);
  });

  it('returns empty array for empty or unparseable text', () => {
    assert.deepEqual(parseSubtitleCues(''), []);
    assert.deepEqual(parseSubtitleCues('no timecodes here'), []);
  });
});

describe('resolveActiveTrackId', () => {
  const tracks = [
    { id: 'track-1', label: 'English' },
    { id: 'track-2', label: 'Spanish' },
  ];

  it('resolves matching track id', () => {
    assert.equal(resolveActiveTrackId(tracks, 'track-1'), 'track-1');
    assert.equal(resolveActiveTrackId(tracks, 'track-2'), 'track-2');
  });

  it('returns null when id is empty or "off"', () => {
    assert.equal(resolveActiveTrackId(tracks, ''), null);
    assert.equal(resolveActiveTrackId(tracks, null), null);
    assert.equal(resolveActiveTrackId(tracks, 'off'), null);
  });

  it('returns null when track is not found in list', () => {
    assert.equal(resolveActiveTrackId(tracks, 'non-existent'), null);
  });
});

describe('normalizeTrackLabel', () => {
  it('formats clean label from filename without extension', () => {
    assert.equal(normalizeTrackLabel('english_commentary.vtt'), 'english_commentary');
    assert.equal(normalizeTrackLabel('spanish.srt', 'es'), 'spanish (es)');
  });

  it('preserves existing label', () => {
    assert.equal(normalizeTrackLabel('English CC'), 'English CC');
  });
});

describe('resolveSubtitleContentUrl', () => {
  const { resolveSubtitleContentUrl } = require('./api');

  it('prefixes relative API content URL with API_BASE_URL', () => {
    const resolved = resolveSubtitleContentUrl('/api/media/1/subtitles/2/content');
    assert.ok(resolved.endsWith('/api/media/1/subtitles/2/content'));
    assert.ok(resolved.startsWith('http'));
  });

  it('preserves absolute and blob URLs unchanged', () => {
    assert.equal(
      resolveSubtitleContentUrl('https://cdn.example.com/subs.vtt'),
      'https://cdn.example.com/subs.vtt'
    );
    assert.equal(
      resolveSubtitleContentUrl('blob:http://localhost:3000/12345'),
      'blob:http://localhost:3000/12345'
    );
  });
});
