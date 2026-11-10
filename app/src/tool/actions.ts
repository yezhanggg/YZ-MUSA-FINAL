import { Marker, type GeoJSONSource } from 'maplibre-gl';
import { findFeature, findLot, type LngLat, type Lot } from './geo';
import { ensureShapes } from './lotShapes';
import { mapRef, useTool } from './store';

let marker: Marker | null = null;
let counter = 0;

const isPhone = () => window.matchMedia('(max-width: 639px)').matches;
export const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Pitch used for the 3D view, and the gentler one used when flying to a tested spot. */
export const PITCH_3D = 55;
const PITCH_SPOT = 45;

/** Room the floating panels take, so the map centres the spot in the open part. */
export function mapPadding(report: boolean) {
  if (isPhone()) return { left: 20, right: 20, top: 150, bottom: report ? Math.round(window.innerHeight * 0.5) : 40 };
  const wide = window.innerWidth >= 1100;
  return { left: wide ? 400 : 370, right: report ? (wide ? 470 : 420) : 40, top: 80, bottom: 40 };
}

function pinElement(label: string) {
  const el = document.createElement('div');
  el.className = 'bh-pin';
  el.innerHTML = `<div class="bh-pin-ring"></div><div class="bh-pin-dot"></div><div class="bh-pin-label"></div>`;
  (el.querySelector('.bh-pin-label') as HTMLElement).textContent = label;
  return el;
}

/**
 * Test one spot: find its tract and town, the lot, and open the report. `pickedLot` is a lot the user clicked
 * (its outline), which beats the nearest-centre rule.
 */
export async function testSpot(pt: LngLat, label: string, pickedLot?: Lot | null) {
  const { tracts, towns, set, view3d } = useTool.getState();
  const map = mapRef.current;
  if (!tracts || !towns || !map) return;
  const tract = findFeature(tracts, pt);
  const town = findFeature(towns, pt);
  if (!tract) {
    set({ msg: 'That spot is outside Pennsylvania.' });
    return;
  }
  const n = ++counter;
  set({ msg: null, busy: true, selectedLot: pickedLot?.lot_id ?? null });

  marker?.remove();
  marker = new Marker({ element: pinElement(label) }).setLngLat(pt).addTo(map);
  map.flyTo({ center: pt, zoom: Math.max(map.getZoom(), 16.5), pitch: view3d ? PITCH_SPOT : 0, duration: reduced() ? 0 : 1400, padding: mapPadding(true), essential: true });
  (map.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [tract as unknown as GeoJSON.Feature] });
  void ensureShapes(map, tract.properties.GEOID, tracts);

  const lot = pickedLot ?? (await findLot(tract.properties.GEOID, pt));
  if (n !== counter) return; // a newer spot won
  set({ busy: false, selectedLot: lot?.lot_id ?? null, spot: { n, label, pt, tract: tract.properties, town: town?.properties ?? {}, lot } });
}

export function clearSpot() {
  marker?.remove();
  marker = null;
  (mapRef.current?.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [] });
  useTool.getState().set({ spot: null, selectedLot: null });
}

/** Switch between the flat map and the tilted 3D view. */
export function setView3d(on: boolean) {
  const map = mapRef.current;
  useTool.getState().set({ view3d: on });
  if (!map) return;
  map.easeTo({ pitch: on ? PITCH_3D : 0, bearing: on ? map.getBearing() || -20 : 0, duration: reduced() ? 0 : 1000 });
}
