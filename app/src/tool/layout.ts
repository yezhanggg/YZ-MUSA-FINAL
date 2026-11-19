// One grid for every panel. Breakpoints and sizes match the CSS variables in index.css (.bh-shell).
//   desktop >= 1440: left 300, right 630, side by side
//   laptop 1024-1439: left 300 fixed, the right panel opens as a wide drawer over the map (closable)
//   tablet 768-1023 and phone < 768: controls in a drawer from the left, one bottom sheet with tabs
//   (This lot / Report / Ask). Tablets cap the sheet width.
// On desktop and laptop the right panel can be dragged wider or narrower (RightPanel's handle). The width the user
// wants is kept in localStorage; the width shown is that, kept between RIGHT_MIN and what leaves MAP_MIN of map.
import { useEffect, useState } from 'react';
import { create } from 'zustand';

export type Mode = 'desktop' | 'laptop' | 'tablet' | 'phone';

export const GUTTER = 12;
/** Top of the map's open area, under the top bar (and of the drawers on tablet and phone). */
export const TOP = 64;
/** Desktop and laptop: the side panels start at the top, one gutter down like the sides; the top bar sits between them. */
export const PANEL_TOP = 12;
/** Height of the bottom sheet when it only peeks (tablet, phone). */
export const SHEET_PEEK = 136;
/** Tablet sheet width cap. */
export const SHEET_MAX = 720;
/** Width of the map control row (2D/3D, Aerial, zoom, compass) on desktop and laptop. */
export const CONTROLS_W = 340;
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

// ------------------------------------------------------------------ right panel width (desktop, laptop)
export const RIGHT_DEFAULT = 630;
export const RIGHT_MIN = 360;
/** Open map the right panel always leaves between the two panels. */
export const MAP_MIN = 320;
/** Arrow keys on the handle move it this far. */
export const RIGHT_STEP = 16;
const WIDTH_KEY = 'bh.rightPanelWidth';

function savedWidth(): number {
  try {
    const v = Number(window.localStorage.getItem(WIDTH_KEY));
    return Number.isFinite(v) && v > 0 ? v : RIGHT_DEFAULT;
  } catch {
    return RIGHT_DEFAULT;
  }
}

/** Remember the width. The page works the same when storage is off. */
export function saveRightWidth(w: number) {
  try {
    window.localStorage.setItem(WIDTH_KEY, String(Math.round(w)));
  } catch {
    /* storage blocked: the width lasts for this visit only */
  }
}

/** Widest the right panel may be: the viewport less the left panel, the gutters and MAP_MIN of map. */
export const rightMax = (vw: number) => Math.max(RIGHT_MIN, vw - WIDTHS.desktop.lw - GUTTER * 4 - MAP_MIN);
export const clampRight = (w: number, vw: number) => Math.round(Math.min(rightMax(vw), Math.max(RIGHT_MIN, w)));

/** Desktop and laptop: the card under the left panel where a map legend goes (TestableLegend portals into it). */
export const useLegendSlot = create<{ el: HTMLElement | null; setEl: (el: HTMLElement | null) => void }>((set) => ({ el: null, setEl: (el) => set({ el }) }));

/** Desktop and laptop: the chat box under the results is open, or minimised into the "Chat" button of the map controls
 *  row. It starts minimised on every visit; the "Chat" button opens it. */
const CHAT_KEY = 'bh.chatOpen';
export const useChatOpen = create<{ open: boolean; setOpen: (o: boolean) => void }>((set) => ({
  open: false,
  setOpen: (open) => {
    try {
      window.localStorage.setItem(CHAT_KEY, open ? '1' : '0');
    } catch {
      /* storage blocked: the state lasts for this visit only */
    }
    set({ open });
  },
}));

/** ParcelIQ and Details both open: they stack in the right column, and this is ParcelIQ's share of its height (the
 *  drag bar between them). Remembered in localStorage. Double-click on the bar goes back to half and half. */
const SPLIT_KEY = 'bh.chatStack';
const savedSplit = () => {
  try {
    const v = Number(window.localStorage.getItem(SPLIT_KEY));
    return v > 0.1 && v < 0.9 ? v : 0.5;
  } catch {
    return 0.5;
  }
};
export const useChatSplit = create<{ ratio: number; setRatio: (r: number) => void }>((set) => ({
  ratio: typeof window === 'undefined' ? 0.5 : savedSplit(),
  setRatio: (ratio) => {
    try {
      window.localStorage.setItem(SPLIT_KEY, String(Math.round(ratio * 1000) / 1000));
    } catch {
      /* storage blocked: the split lasts for this visit only */
    }
    set({ ratio });
  },
}));
/** ParcelIQ on its own (Details hidden): the width the user dragged it to, remembered in localStorage. */
const CHAT_W_KEY = 'bh.chatWidth';
export const CHAT_W_DEFAULT = 420;
export const CHAT_W_MIN = 340;
const savedChatW = () => {
  try {
    const v = Number(window.localStorage.getItem(CHAT_W_KEY));
    return v >= CHAT_W_MIN ? v : CHAT_W_DEFAULT;
  } catch {
    return CHAT_W_DEFAULT;
  }
};
export const useChatWidth = create<{ want: number; setWant: (w: number, save?: boolean) => void }>((set) => ({
  want: typeof window === 'undefined' ? CHAT_W_DEFAULT : savedChatW(),
  setWant: (want, save = true) => {
    if (save) {
      try {
        window.localStorage.setItem(CHAT_W_KEY, String(Math.round(want)));
      } catch {
        /* storage blocked: the width lasts for this visit only */
      }
    }
    set({ want });
  },
}));
/** The shortest either box of the stack may get, in px. */
export const SPLIT_MIN = 200;
/** Details (top) and ParcelIQ (bottom) heights for a column of `total` px with ParcelIQ's share `ratio` (a gap of
 *  one gutter between them). */
export const splitHeights = (total: number, ratio: number) => {
  const room = Math.max(0, total - GUTTER);
  const bottom = Math.round(Math.min(room - SPLIT_MIN, Math.max(SPLIT_MIN, room * ratio)));
  return { top: room - bottom, bottom };
};

/** Desktop and laptop: the left panel, and on desktop the right column, can be hidden (a hide button in each header,
 *  a show button at that edge). The left panel is remembered in localStorage. The right column starts hidden on every
 *  visit and opens when a lot is picked. The laptop results drawer keeps its own open state (store resultsOpen),
 *  shown and hidden the same way. */
const SIDES_KEY = 'bh.sides';
const savedSides = (): { left: boolean; right: boolean } => {
  try {
    const v = JSON.parse(window.localStorage.getItem(SIDES_KEY) ?? '{}') as { left?: boolean };
    return { left: v.left !== false, right: false };
  } catch {
    return { left: true, right: false };
  }
};
export const useSides = create<{ left: boolean; right: boolean; setSide: (side: 'left' | 'right', open: boolean) => void }>((set, get) => ({
  ...(typeof window === 'undefined' ? { left: true, right: true } : savedSides()),
  setSide: (side, open) => {
    set({ [side]: open } as { left: boolean } | { right: boolean });
    try {
      window.localStorage.setItem(SIDES_KEY, JSON.stringify({ left: get().left, right: get().right }));
    } catch {
      /* storage blocked: the state lasts for this visit only */
    }
  },
}));

/** The width the user asked for (before it is fitted to the viewport). */
export const usePanelWidth = create<{ want: number; setWant: (w: number) => void }>((set) => ({
  want: typeof window === 'undefined' ? RIGHT_DEFAULT : savedWidth(),
  setWant: (w) => set({ want: w }),
}));

/** The right panel's width now, desktop and laptop. */
export const rightWidth = (vw: number = typeof window === 'undefined' ? 1440 : window.innerWidth) => clampRight(usePanelWidth.getState().want, vw);

/** The same, as a hook that follows the handle and the window. */
export function useRightWidth(vw: number) {
  return usePanelWidth((s) => clampRight(s.want, vw));
}

/** The viewport width, kept up to date. */
export function useViewportWidth() {
  const [vw, setVw] = useState(() => (typeof window === 'undefined' ? 1440 : window.innerWidth));
  useEffect(() => {
    const on = () => setVw(window.innerWidth);
    window.addEventListener('resize', on);
    return () => window.removeEventListener('resize', on);
  }, []);
  return vw;
}
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
  const { lw } = WIDTHS[m];
  if (narrow(m)) return { left: 20, right: 20, top: TOP + 20, bottom: report ? sheetOpenHeight(h) + 20 : SHEET_PEEK + 20 };
  const sides = useSides.getState();
  const right = rightDrawer(m) ? (report ? rightWidth(w) : 0) : sides.right ? rightWidth(w) : 0;
  const left = sides.left ? lw + GUTTER * 2 : GUTTER;
  return { left: left + 20, right: right + GUTTER * 2 + 20, top: TOP + 20, bottom: 40 };
}

/** Explore's statewide view: the panel room (mapPadding) plus a legend that sits on the map (tablet and phone).
 * `open`: the results side is open (laptop drawer) or the sheet is open (tablet, phone). */
export function statePadding(open = false) {
  const p = mapPadding(open);
  const legend = typeof document === 'undefined' ? null : document.querySelector('[data-map-legend]');
  const r = legend?.getBoundingClientRect();
  if (r && r.height) p.top = Math.max(p.top, Math.round(r.bottom) + 12);
  return p;
}
