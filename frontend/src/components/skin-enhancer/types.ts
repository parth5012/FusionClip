import type { SkinFailure, SkinItemStatus } from '../../utils/skin';

/** One portrait the panel can point at: a catalog key plus its display name. */
export interface SkinSource {
  path: string;
  name: string;
  url?: string;
}

/** Per-source run state for the results tray and the canvas. */
export interface SkinItemState {
  status: SkinItemStatus;
  faces?: number;
  resultUrl?: string;
  engine?: string;
  failure?: SkinFailure;
  degraded?: { reason: string; message: string };
}
