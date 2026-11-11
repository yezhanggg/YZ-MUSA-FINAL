import { Marker, type GeoJSONSource } from 'maplibre-gl';
import { findFeature, findLot, inGeom, loadLots, type LngLat, type Lot, type TractProps } from './geo';
import type { ParcelProps } from './parcels';
import { mapRef, syncHash, useTool, type Spot } from './store';
import { mapPadding } from './layout';
import { isLotLoadError, loadLot, loadTractLots, placeOfGeoid } from '../lib/lot/load';
import { centroid, frameOf } from '../lib/lot/geometry';
import { toFeet } from '../lib/fitBox';
import type { LotRecord } from '../lib/lot/types';
import { lotByAddress, startUnit, typeFor } from './testState';

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

const PLACE_NAME: Record<string, string> = { pittsburgh: 'Pittsburgh', philadelphia: 'Philadelphia' };

interface RecordResult {
  record: LotRecord | null;
  recordNote: string | null;
  builtAt: string | null;
}

/** What is missing when a place has no lot records, said plainly. */
function noRecordsHere(t: TractProps): string {
  return `There are no lot records for ${t.county ? `${t.county} County` : 'this place'} yet. Lot records cover Pittsburgh and Philadelphia. The tract and town numbers below still apply.`;
}

/**
 * The lot record whose lot outline contains the point (no snapping to a nearby lot). `lotId` (a link, or the
 * assistant) wins over the point. A searched address that lands on the street finds its lot by address.
 * Aborts quietly when a newer spot starts.
 */
async function recordAt(pt: LngLat, tract: TractProps, signal: AbortSignal, label: string, lotId?: string): Promise<RecordResult | null> {
  const geoid = tract.GEOID;
  const place = placeOfGeoid(geoid);
  if (!place) return { record: null, recordNote: noRecordsHere(tract), builtAt: null };
  try {
    const t = await loadTractLots(geoid, { signal });
    const record = (lotId ? t.byId.get(lotId) : undefined) ?? t.lots.find((l) => inGeom(pt, l.lot.polygon as Parameters<typeof inGeom>[1])) ?? lotByAddress(label, t.lots);
    const recordNote = record ? null : 'No lot record contains this spot. Lot records cover home lots. Click inside a lot outline.';
    return { record, recordNote, builtAt: t.builtAt };
  } catch (e) {
    if (isLotLoadError(e) && e.kind === 'aborted') return null;
    const why = isLotLoadError(e) ? e.userMessage : 'The lot data could not be loaded.';
    const missing = isLotLoadError(e) && e.kind === 'not_found' ? `There is no lot file for ${PLACE_NAME[place] ?? place} here yet. ` : '';
    return { record: null, recordNote: `${missing}${why} The tract and town numbers below still apply.`, builtAt: null };
  }
}

/** A new lot keeps the unit size, finds a spot again, and switches to an allowed unit type. */
function fitUnitTo(record: LotRecord) {
  const { scenario, unit } = useTool.getState();
  const type = typeFor(record, scenario, unit.type);
  useTool.getState().set({ unit: type === unit.type ? { ...unit, at: null, angle: null } : startUnit(record, scenario, type, unit) });
}

let pending: AbortController | null = null;

/**
 * Test one spot: find its tract and town, the lot, and open the report. A clicked parcel beats the 40 m
 * nearest-lot rule. A parcel that was not checked (s = 0) gets the short report. In testing mode the lot record
 * that contains the spot is loaded too.
 */
export async function testSpot(pt: LngLat, label: string, parcel?: ParcelProps | null, opts: { lotId?: string; keepUnit?: boolean } = {}) {
  const { tracts, towns, set, view3d, view } = useTool.getState();
  const map = mapRef.current;
  if (!tracts || !towns || !map) return;
  const tract = findFeature(tracts, pt);
  const town = findFeature(towns, pt);
  if (!tract) {
    set({ msg: 'That spot is outside Pennsylvania.' });
    return;
  }
  const n = ++counter;
  pending?.abort();
  const ctrl = new AbortController();
  pending = ctrl;
  set({ msg: null, busy: true, selectedLot: parcel?.id ?? opts.lotId ?? null });

  // The selected parcel's glowing outline is the only mark. Outside the parcels, a ripple shows where.
  if (!parcel) ripple(pt);
  map.flyTo({ center: pt, zoom: Math.max(map.getZoom(), 16.5), pitch: view3d ? PITCH_SPOT : 0, duration: reduced() ? 0 : 1400, padding: mapPadding(true), essential: true });
  (map.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [tract as unknown as GeoJSON.Feature] });

  const geoid = tract.properties.GEOID;
  const [lot, rec] = await Promise.all([
    parcel ? (parcel.s === 1 ? lotForParcel(geoid, parcel, pt) : null) : view === 'project' ? findLot(geoid, pt) : null,
    view === 'test' || opts.lotId ? recordAt(pt, tract.properties, ctrl.signal, label, opts.lotId) : { record: null, recordNote: null, builtAt: null },
  ]);
  if (n !== counter || !rec) return; // a newer spot won
  const record = rec.record;
  const spot: Spot = { n, label: record?.lot.address ? titleCase(record.lot.address) : label, pt, tract: tract.properties, town: town?.properties ?? {}, lot, parcel: parcel ?? null, ...rec };
  if (record && !opts.keepUnit) fitUnitTo(record);
  set({ busy: false, selectedLot: record?.lot.id ?? parcel?.id ?? lot?.lot_id ?? null, spot });
  syncHash();
}

/** "5459 BEACON ST" -> "5459 Beacon St" */
export const titleCase = (s: string) => s.toLowerCase().replace(/\b([a-z])/g, (m) => m.toUpperCase());

/** Open a lot from a link: load its record, then test the spot at its center. A link with a unit keeps it. */
export async function openLot(lotId: string, geoid: string) {
  const keepUnit = /[?&]ut=/.test(window.location.hash);
  try {
    const rec = await loadLot(lotId, geoid);
    const f = frameOf(rec);
    // The lot's center. The lot id wins over the point, so an odd-shaped lot still opens.
    const pt = f.toLonLat(centroid(toFeet(rec.lot.polygon, f.origin)));
    await testSpot(pt, 'Linked lot', null, { lotId, keepUnit });
  } catch (e) {
    useTool.getState().set({ msg: isLotLoadError(e) ? e.userMessage : 'That lot could not be opened.' });
  }
}

export function clearSpot() {
  pending?.abort();
  (mapRef.current?.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [] });
  useTool.getState().set({ spot: null, selectedLot: null });
  syncHash();
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
