/**
 * Subtitle utility functions (#109)
 *
 * Handles file validation, format conversions (SRT -> WebVTT), cue parsing,
 * track label normalization, and textTrack DOM mode synchronization.
 */

export const MAX_SUBTITLE_BYTES = 2 * 1024 * 1024; // 2MB
export const ALLOWED_SUBTITLE_EXTENSIONS = ['.vtt', '.srt'];

const TIMESTAMP_REGEX = /(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})\s*-->\s*(\d{1,2}):(\d{2}):(\d{2})[,.](\d{1,3})/;

export function validateSubtitleFile(
  filename: string,
  sizeBytes: number
): { valid: boolean; error?: string } {
  const lower = filename.toLowerCase();
  const hasValidExt = ALLOWED_SUBTITLE_EXTENSIONS.some((ext) => lower.endsWith(ext));
  if (!hasValidExt) {
    return {
      valid: false,
      error: 'Invalid subtitle format. Only .vtt and .srt files are supported.',
    };
  }

  if (sizeBytes > MAX_SUBTITLE_BYTES) {
    return {
      valid: false,
      error: `Subtitle file exceeds maximum allowed size (${MAX_SUBTITLE_BYTES / (1024 * 1024)}MB).`,
    };
  }

  return { valid: true };
}

export function isValidVTTContent(text: string): boolean {
  if (!text) return false;
  const cleaned = text.replace(/^\uFEFF/, '').trim();
  return cleaned.startsWith('WEBVTT');
}

export function convertSrtToVtt(srtText: string): string {
  if (!srtText) return 'WEBVTT\n\n';
  const converted = srtText.replace(
    /(\d{1,2}:\d{2}:\d{2}),(\d{3})/g,
    '$1.$2'
  );
  const normalized = converted.replace(/\r?\n/g, '\n').trim();
  return `WEBVTT\n\n${normalized}\n`;
}

function parseTimeToSeconds(h: string, m: string, s: string, ms: string): number {
  return (
    parseInt(h, 10) * 3600 +
    parseInt(m, 10) * 60 +
    parseInt(s, 10) +
    parseInt(ms.padEnd(3, '0').slice(0, 3), 10) / 1000
  );
}

export function parseSubtitleCues(
  text: string
): { start: number; end: number; text: string }[] {
  if (!text) return [];
  const cues: { start: number; end: number; text: string }[] = [];
  const blocks = text.split(/\r?\n\r?\n/);

  for (const block of blocks) {
    const lines = block.split(/\r?\n/);
    const timingLine = lines.find((line) => line.includes('-->'));
    if (!timingLine) continue;

    const match = timingLine.match(TIMESTAMP_REGEX);
    if (!match) continue;

    const start = parseTimeToSeconds(match[1], match[2], match[3], match[4]);
    const end = parseTimeToSeconds(match[5], match[6], match[7], match[8]);
    const textIndex = lines.indexOf(timingLine) + 1;
    const cueText = lines
      .slice(textIndex)
      .filter((line) => line.trim() !== '')
      .join(' ')
      .replace(/<[^>]+>/g, '')
      .trim();

    if (cueText) {
      cues.push({ start, end, text: cueText });
    }
  }

  return cues.sort((a, b) => a.start - b.start);
}

export function resolveActiveTrackId(
  tracks: { id: string }[],
  requestedId: string | null
): string | null {
  if (!requestedId || requestedId.toLowerCase() === 'off') {
    return null;
  }
  const match = tracks.find((t) => t.id === requestedId);
  return match ? match.id : null;
}

export function normalizeTrackLabel(filenameOrLabel: string, lang?: string | null): string {
  let label = filenameOrLabel.replace(/\.(srt|vtt)$/i, '').trim();
  if (!label) label = 'Subtitles';
  if (lang && !label.toLowerCase().includes(lang.toLowerCase())) {
    return `${label} (${lang})`;
  }
  return label;
}

export function syncTextTrackModes(
  video: HTMLVideoElement | null,
  activeTrackId: string | null,
  enabled: boolean
): void {
  if (!video || !video.textTracks) return;

  for (let i = 0; i < video.textTracks.length; i++) {
    const track = video.textTracks[i];
    // Check by track id (e.g. "track-<id>") or by matching label
    const isTarget =
      Boolean(activeTrackId) &&
      (track.id === `track-${activeTrackId}` ||
        track.id === activeTrackId ||
        track.label === activeTrackId);

    if (enabled && isTarget) {
      track.mode = 'showing';
    } else {
      track.mode = 'disabled';
    }
  }
}
