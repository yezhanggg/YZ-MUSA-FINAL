import { Marker, type GeoJSONSource } from 'maplibre-gl';
import { findFeature, findLot, loadLots, type LngLat, type Lot } from './geo';
import type { ParcelProps } from './parcels';
import { mapRef, useTool } from './store';
import { mapPadding } from './layout';

export { mapPadding };

let counter = 0;

export const reduced = () => window.matchMedia('(prefers-reduced-motion: reduce)').matches;

/** Pitch used for the 3D view, and the gentler one used when flying to a tested spot. */
export const PITCH_3D = 55;
const PITCH_SPOT = 45;

/** A brief ripple where the user clicked or searched. It fades out and leaves nothing behind. */
function ripple(pt: LngLat) {
  const map = mapRef.current;
  if (!map || reduced()) return;
  const el = document.createElement('div');
  el.className = 'bh-ripple';
  const m = new Marker({ element: el }).setLngLat(pt).addTo(map);
  window.setTimeout(() => m.remove(), 900);
}

/** A checked parcel's lot record: from its tract file by id, or (edge lots) from the tile's own fields. */
async function lotForParcel(geoid: string, p: ParcelProps, pt: LngLat): Promise<Lot> {
  const hit = (await loadLots(geoid))?.find((l) => l.lot_id === p.id);
  if (hit) return hit;
  return { lot_id: p.id, lon: pt[0], lat: pt[1], lot_m2: NaN, open_m2: NaN, tree_m2: NaN, fits: p.f === 1, fits_keep_trees: p.k === 1, max_fit_sqft: p.mf ?? null, max_fit_keep_trees_sqft: p.mk ?? null };
}

/**
 * Test one spot: find its tract and town, the lot, and open the report. A clicked parcel beats the 40 m
 * nearest-lot rule. A parcel that was not checked (s = 0) gets the short report.
 */
export async function testSpot(pt: LngLat, label: string, parcel?: ParcelProps | null) {
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
  set({ msg: null, busy: true, selectedLot: parcel?.id ?? null });

  // The selected parcel's glowing outline is the only mark. Outside the parcels, a ripple shows where.
  if (!parcel) ripple(pt);
  map.flyTo({ center: pt, zoom: Math.max(map.getZoom(), 16.5), pitch: view3d ? PITCH_SPOT : 0, duration: reduced() ? 0 : 1400, padding: mapPadding(true), essential: true });
  (map.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [tract as unknown as GeoJSON.Feature] });

  const geoid = tract.properties.GEOID;
  const lot = parcel ? (parcel.s === 1 ? await lotForParcel(geoid, parcel, pt) : null) : await findLot(geoid, pt);
  if (n !== counter) return; // a newer spot won
  set({ busy: false, selectedLot: parcel?.id ?? lot?.lot_id ?? null, spot: { n, label, pt, tract: tract.properties, town: town?.properties ?? {}, lot, parcel: parcel ?? null } });
}

export function clearSpot() {
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

/** Fly to a parcel-level view of a pilot neighbourhood. */
export function flyToPilot(center: LngLat) {
  const map = mapRef.current;
  map?.flyTo({ center, zoom: 16.2, pitch: useTool.getState().view3d ? PITCH_SPOT : 0, duration: reduced() ? 0 : 1800, padding: mapPadding(!!useTool.getState().spot), essential: true });
}
