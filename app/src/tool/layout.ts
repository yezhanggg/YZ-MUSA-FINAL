// One grid for every panel. Breakpoints and sizes match the CSS variables in index.css (.bh-shell).
//   desktop >= 1280: left 360, right 420, side by side
//   laptop 1024-1279: left 320, right 360, low-priority report cards fold
//   tablet 768-1023 and phone < 768: controls in a drawer from the left, one bottom sheet with tabs
//   (This lot / Report / Ask). Tablets cap the sheet width.
import { useEffect, useState } from 'react';

export type Mode = 'desktop' | 'laptop' | 'tablet' | 'phone';

export const GUTTER = 12;
/** Top of the panels: under the top bar. */
export const TOP = 64;
/** Height of the bottom sheet when it only peeks (tablet, phone). */
export const SHEET_PEEK = 136;
/** Tablet sheet width cap. */
export const SHEET_MAX = 720;
/** Width of the map control column (2D/3D, zoom, compass). */
export const CONTROLS_W = 96;

/** Open height of the bottom sheet for a viewport height. */
export const sheetOpenHeight = (vh: number) => Math.min(Math.round(vh * 0.62), 640);

/** Narrow layouts use the drawer and the bottom sheet. */
export const narrow = (m: Mode) => m === 'tablet' || m === 'phone';
const WIDTHS: Record<Mode, { lw: number; rw: number }> = {
  desktop: { lw: 360, rw: 420 },
  laptop: { lw: 320, rw: 360 },
  tablet: { lw: 340, rw: 360 },
  phone: { lw: 0, rw: 0 },
};

export function modeOf(w: number): Mode {
  return w >= 1280 ? 'desktop' : w >= 1024 ? 'laptop' : w >= 768 ? 'tablet' : 'phone';
}

export const widths = (m: Mode) => WIDTHS[m];

export function useMode(): Mode {
  const [m, setM] = useState<Mode>(() => (typeof window === 'undefined' ? 'desktop' : modeOf(window.innerWidth)));
  useEffect(() => {
    const on = () => setM(modeOf(window.innerWidth));
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return m;
}

/** Room the panels take, so the map centres a spot in the open part. */
export function mapPadding(report = true) {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const m = modeOf(w);
  const { lw, rw } = WIDTHS[m];
  if (narrow(m)) return { left: 20, right: 20, top: TOP + 20, bottom: report ? sheetOpenHeight(h) + 20 : SHEET_PEEK + 20 };
  return { left: lw + GUTTER * 2 + 20, right: rw + GUTTER * 2 + 20, top: TOP + 20, bottom: 40 };
}
