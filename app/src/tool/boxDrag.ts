// Dragging the unit box, on the small site view and on the main map alike. One drag, one box: on every animation
// frame the box is drawn into every linked map (same ring, same green / red fit), and letting go writes the spot to
// the store, which both maps then draw from (the lot test gives the full answer). The lot and its latest result come
// from setBoxContext (Test Project results, test/LotResults).
import type { Map as MLMap, MapLayerMouseEvent, MapLayerTouchEvent } from 'maplibre-gl';
import type { Pt } from '../lib/fitBox';
import type { LotRecord } from '../lib/lot/types';
import { setUnitBox } from './siteLayers';
import { useTool } from './store';
import { boxRing, fitsAt } from './testState';
import type { LotResult } from './test/useLotResult';

let ctx: { record: LotRecord; r: LotResult } | null = null;
/** The lot and result the box belongs to; null when no lot record is open. */
export const setBoxContext = (c: typeof ctx) => void (ctx = c);

const linked = new Set<MLMap>();
let drag: { offset: Pt; center: Pt; angle: number } | null = null;
let frame = 0;
/** The map last pressed on the box; its click handler skips that click (no lot change, no deselect). */
let pressed: MLMap | null = null;
export const consumeBoxPress = (map: MLMap) => {
  const p = pressed === map;
  pressed = null;
  return p;
};

function current(): { center: Pt; angle: number } {
  const res = ctx!.r;
  const p = res.verdict.placed;
  const center: Pt = res.unit.at ? [res.unit.at.lon, res.unit.at.lat] : (p?.center ?? res.site.unit?.ring[0] ?? [0, 0]);
  return { center, angle: res.unit.angle ?? p?.angle_deg ?? 0 };
}

function draw() {
  frame = 0;
  if (!drag || !ctx) return;
  const { record: lot, r: res } = ctx;
  const { width, depth } = res.unit;
  const box = { ring: boxRing(lot, drag.center, drag.angle, width, depth), fits: fitsAt(lot, res.scenario, drag.center, drag.angle, width, depth), heightFt: res.verdict.height_ft ?? 15, stories: res.unit.stories };
  const at = `${drag.center[0].toFixed(7)},${drag.center[1].toFixed(7)}`;
  for (const m of linked) {
    if (!m.getSource('site-unit')) continue;
    setUnitBox(m, box);
    m.getContainer().dataset.unitAt = at;
  }
}

/**
 * Make the box on this map draggable (layers: the box's fill and 3D layers that exist on it). A plain drag off the
 * box still pans. Returns the clean-up.
 */
export function attachBoxDrag(map: MLMap, layers: string[]): () => void {
  linked.add(map);
  const onMove = (e: { lngLat: { lng: number; lat: number } }) => {
    if (!drag) return;
    drag.center = [e.lngLat.lng - drag.offset[0], e.lngLat.lat - drag.offset[1]];
    if (!frame) frame = requestAnimationFrame(draw);
  };
  const end = () => {
    if (!drag) return;
    const d = drag;
    drag = null;
    cancelAnimationFrame(frame);
    frame = 0;
    map.off('mousemove', onMove);
    map.off('touchmove', onMove);
    map.dragPan.enable();
    map.getCanvas().style.cursor = '';
    glow(false);
    // The click of this press (if MapLibre sends one) comes right after mouseup; after that the flag must not linger.
    window.setTimeout(() => pressed === map && (pressed = null), 0);
    useTool.getState().setUnit({ at: { lon: d.center[0], lat: d.center[1] }, angle: d.angle });
  };
  const start = (e: MapLayerMouseEvent | MapLayerTouchEvent) => {
    if (!ctx || ctx.r.unit.type !== 'detached_new') return;
    const oe = e.originalEvent as MouseEvent;
    if (oe.metaKey || oe.ctrlKey || (typeof oe.button === 'number' && oe.button !== 0)) return; // Cmd + drag turns the view
    e.preventDefault();
    pressed = map;
    const c = current();
    drag = { offset: [e.lngLat.lng - c.center[0], e.lngLat.lat - c.center[1]], center: c.center, angle: c.angle };
    map.dragPan.disable();
    map.getCanvas().style.cursor = 'grabbing';
    map.on('mousemove', onMove);
    map.on('touchmove', onMove);
    map.once('mouseup', end);
    map.once('touchend', end);
  };
  // Hover: a grab cursor and a light highlight on the box (fill a little stronger), so it reads as something to drag.
  const glow = (on: boolean) => map.getLayer('site-unit-fill') && map.setPaintProperty('site-unit-fill', 'fill-opacity', on ? 0.55 : 0.35);
  const enter = () => {
    if (drag || ctx?.r.unit.type !== 'detached_new') return;
    map.getCanvas().style.cursor = 'grab';
    glow(true);
  };
  const leave = () => {
    if (drag) return;
    map.getCanvas().style.cursor = '';
    glow(false);
  };
  for (const layer of layers) {
    map.on('mousedown', layer, start);
    map.on('touchstart', layer, start);
    map.on('mouseenter', layer, enter);
    map.on('mousemove', layer, enter); // after the lot hover, so the box keeps its grab cursor
    map.on('mouseleave', layer, leave);
  }
  return () => {
    linked.delete(map);
    for (const layer of layers) {
      map.off('mousedown', layer, start);
      map.off('touchstart', layer, start);
      map.off('mouseenter', layer, enter);
      map.off('mousemove', layer, enter);
      map.off('mouseleave', layer, leave);
    }
  };
}
