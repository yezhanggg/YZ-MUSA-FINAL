// One grid for every panel. Breakpoints and sizes match the CSS variables in index.css (.bh-shell).
//   desktop >= 1440: left 300, right 630, side by side
//   laptop 1024-1439: left 300 fixed, the right panel opens as a wide drawer over the map (closable)
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
/** Desktop starts here. Below it the right panel is a drawer. */
export const DESKTOP_MIN = 1440;

/** Open height of the bottom sheet for a viewport height. */
export const sheetOpenHeight = (vh: number) => Math.min(Math.round(vh * 0.62), 640);

/** Narrow layouts use the drawer and the bottom sheet. */
export const narrow = (m: Mode) => m === 'tablet' || m === 'phone';
/** The right panel is a drawer over the map, not a fixed column. */
export const rightDrawer = (m: Mode) => m === 'laptop';
const WIDTHS: Record<Mode, { lw: number; rw: number }> = {
  desktop: { lw: 300, rw: 630 },
  laptop: { lw: 300, rw: 630 },
  tablet: { lw: 340, rw: 360 },
  phone: { lw: 0, rw: 0 },
};

export function modeOf(w: number): Mode {
  return w >= DESKTOP_MIN ? 'desktop' : w >= 1024 ? 'laptop' : w >= 768 ? 'tablet' : 'phone';
}

export const widths = (m: Mode) => WIDTHS[m];

/** Width of the right drawer on a laptop screen: wide, but never over the left panel. */
export const drawerWidth = (vw: number) => Math.min(WIDTHS.laptop.rw, vw - WIDTHS.laptop.lw - GUTTER * 3);

export function useMode(): Mode {
  const [m, setM] = useState<Mode>(() => (typeof window === 'undefined' ? 'desktop' : modeOf(window.innerWidth)));
  useEffect(() => {
    const on = () => setM(modeOf(window.innerWidth));
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return m;
}

/** Room the panels take, so the map centres a spot in the open part. `report`: the results are open. */
export function mapPadding(report = true) {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const m = modeOf(w);
  const { lw, rw } = WIDTHS[m];
  if (narrow(m)) return { left: 20, right: 20, top: TOP + 20, bottom: report ? sheetOpenHeight(h) + 20 : SHEET_PEEK + 20 };
  const right = rightDrawer(m) ? (report ? drawerWidth(w) : 0) : rw;
  return { left: lw + GUTTER * 2 + 20, right: right + GUTTER * 2 + 20, top: TOP + 20, bottom: 40 };
}
