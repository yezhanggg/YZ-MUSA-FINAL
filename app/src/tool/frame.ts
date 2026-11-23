// The camera for a clicked shape: a lot, a census tract or a county is fitted in the open map (between the left
// panel, Details, the top bar and the search dock) with some of its surroundings, never closer than needed.
//   lot:      the lot plus about five lot widths on each side (about the block), at most zoom 18
//   tract:    the whole tract and a margin, never street or lot zoom
//   county:   the whole county and a margin (a town or a ZIP code: like a tract)
// When the map is already near that zoom and the shape fits, the zoom is kept and the map only pans to it.
// The map element shows the shape's box and the open map on screen (data-focus-box, data-open-box) for the tests.
import type { Map as MLMap } from 'maplibre-gl';

interface PaddingOptions {
  top: number;
  right: number;
  bottom: number;
  left: number;
}
import { GUTTER, mapPadding, modeOf, narrow, useSides } from './layout';
import { mapRef, useTool } from './store';

export type BBox = [number, number, number, number];

/** The search dock at the bottom left on desktop and laptop (AskDock's bar is 60 px high). */
const DOCK = 60 + GUTTER;

/** Most zoom for each shape, and the zoom from which the current zoom is kept. */
export const LOT_MAX_ZOOM = 18;
const LOT_MIN_ZOOM = 14;
const LOT_KEEP_FROM = 15.5;
export const TRACT_MAX_ZOOM = 13;
export const COUNTY_MAX_ZOOM = 11;
/** Lot widths of context on each side of a lot. */
const LOT_CONTEXT = 5;
/** Margin around a tract or a county, in pixels. */
const AREA_MARGIN = 40;

/** Bounding box of any GeoJSON geometry (Polygon, MultiPolygon, lines). null when it has no coordinates. */
export function geomBox(g: { type: string; coordinates?: unknown } | null | undefined): BBox | null {
  if (!g || !('coordinates' in g)) return null;
  const b: BBox = [Infinity, Infinity, -Infinity, -Infinity];
  const walk = (c: unknown) => {
    if (!Array.isArray(c)) return;
    if (typeof c[0] === 'number' && typeof c[1] === 'number') {
      b[0] = Math.min(b[0], c[0]);
      b[1] = Math.min(b[1], c[1]);
      b[2] = Math.max(b[2], c[0]);
      b[3] = Math.max(b[3], c[1]);
      return;
    }
    for (const x of c) walk(x);
  };
  walk(g.coordinates);
  return Number.isFinite(b[0]) ? b : null;
}

export const unionBox = (boxes: (BBox | null)[]): BBox | null =>
  boxes.reduce<BBox | null>((a, b) => (!b ? a : !a ? b : [Math.min(a[0], b[0]), Math.min(a[1], b[1]), Math.max(a[2], b[2]), Math.max(a[3], b[3])]), null);

/** A lot's box grown by `k` lot widths on each side (the lot width is its longer side, in metres). */
export function lotContextBox(b: BBox, k = LOT_CONTEXT): BBox {
  const lat = ((b[1] + b[3]) / 2) * (Math.PI / 180);
  const mx = 111_320 * Math.cos(lat);
  const my = 110_540;
  const w = Math.max((b[2] - b[0]) * mx, (b[3] - b[1]) * my, 8);
  return [b[0] - (k * w) / mx, b[1] - (k * w) / my, b[2] + (k * w) / mx, b[3] + (k * w) / my];
}

/** The open map: mapPadding with room for the search dock. `report`: Details is open (or opens now). */
export function openPadding(report: boolean): PaddingOptions {
  const p = mapPadding(report);
  if (!narrow(modeOf(window.innerWidth))) p.bottom = Math.max(p.bottom, DOCK + 20);
  return p;
}

const grow = (p: PaddingOptions, m: number): PaddingOptions => ({ top: p.top + m, right: p.right + m, bottom: p.bottom + m, left: p.left + m });

/** The box on screen, in container pixels: [left, top, right, bottom]. */
function screenBox(map: MLMap, b: BBox): BBox {
  const pts = [map.project([b[0], b[1]]), map.project([b[0], b[3]]), map.project([b[2], b[1]]), map.project([b[2], b[3]])];
  return [Math.min(...pts.map((p) => p.x)), Math.min(...pts.map((p) => p.y)), Math.max(...pts.map((p) => p.x)), Math.max(...pts.map((p) => p.y))];
}

function inside(map: MLMap, b: BBox, p: PaddingOptions): boolean {
  const s = screenBox(map, b);
  const c = map.getCanvas();
  return s[0] >= p.left && s[1] >= p.top && s[2] <= c.clientWidth - p.right && s[3] <= c.clientHeight - p.bottom;
}

/** The shape's box and the open map, on screen, once the camera rests. */
function markFocus(map: MLMap, shape: BBox, p: PaddingOptions) {
  const write = () => {
    if (mapRef.current !== map) return;
    const c = map.getCanvas();
    const el = map.getContainer();
    el.dataset.focusBox = screenBox(map, shape).map((v) => v.toFixed(1)).join(',');
    el.dataset.openBox = [p.left, p.top, c.clientWidth - p.right, c.clientHeight - p.bottom].join(',');
  };
  if (map.isMoving()) map.once('moveend', write);
  else write();
}

interface FrameOpts {
  maxZoom: number;
  minZoom?: number;
  /** Pixels around the box. */
  margin: number;
  /** The current zoom is kept from here up to the fitted zoom. */
  keepFrom: (fit: number) => number;
  /** Details is open for this pick: open it now, so the padding leaves its room. */
  report: boolean;
  pitch?: number;
  duration: number;
}

/** Fit `box` in the open map (see the top of the file). `shape` is the shape's own box, for data-focus-box. */
export function frameBox(box: BBox, shape: BBox, o: FrameOpts) {
  const map = mapRef.current;
  if (!map) return;
  // Details opens now, so the padding leaves its room. ToolPage keeps the map picture still when a side opens (a jump
  // that would cut a flight short): when Details was closed, move after that has run.
  const wasOpen = useSides.getState().right && useTool.getState().resultsOpen;
  if (o.report) {
    useTool.getState().set({ resultsOpen: true });
    useSides.getState().setSide('right', true);
  }
  const go = () => {
    if (mapRef.current !== map) return;
    const pad = openPadding(o.report);
    // The zoom where the box fills the open map less the margin (the box's size on screen doubles per zoom step).
    const z = map.getZoom();
    const s = screenBox(map, box);
    const c = map.getCanvas();
    const room = Math.min((c.clientWidth - pad.left - pad.right - 2 * o.margin) / Math.max(s[2] - s[0], 1), (c.clientHeight - pad.top - pad.bottom - 2 * o.margin) / Math.max(s[3] - s[1], 1));
    const fit = Math.max(o.minZoom ?? 0, Math.min(z + Math.log2(Math.max(room, 1e-3)), o.maxZoom));
    const keep = z <= fit + 1e-6 && z >= o.keepFrom(fit);
    const zoom = keep ? z : fit;
    const pitchSame = o.pitch === undefined || Math.abs(map.getPitch() - o.pitch) < 1;
    if (keep && pitchSame && inside(map, box, grow(pad, o.margin))) return markFocus(map, shape, pad);
    const center: [number, number] = [(box[0] + box[2]) / 2, (box[1] + box[3]) / 2];
    map.flyTo({ center, zoom, padding: pad, ...(o.pitch === undefined ? {} : { pitch: o.pitch }), duration: o.duration, essential: true });
    markFocus(map, shape, pad);
  };
  if (o.report && !wasOpen) window.setTimeout(go, 120);
  else go();
}

/** A lot: the lot and about the block around it, at most zoom 18. */
export function frameLot(lot: BBox, motion: { pitch?: number; duration: number }) {
  frameBox(lotContextBox(lot), lot, { maxZoom: LOT_MAX_ZOOM, minZoom: LOT_MIN_ZOOM, margin: 0, keepFrom: (fit) => Math.min(LOT_KEEP_FROM, fit), report: true, ...motion });
}

/** A county, town, tract or ZIP code: the whole outline and a margin, at most `maxZoom`. Details opens for it. */
export function frameArea(area: BBox, maxZoom: number, duration: number) {
  frameBox(area, area, { maxZoom, margin: AREA_MARGIN, keepFrom: (fit) => fit - 0.75, report: true, duration });
}
