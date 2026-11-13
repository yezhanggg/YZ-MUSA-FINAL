import { Marker, type GeoJSONSource } from 'maplibre-gl';
import { findFeature, inGeom, type LngLat, type TownProps, type TractProps } from './geo';
import { cityTractAt, loadAreas } from './areas';
import { openView } from '../lib/router';
import type { ParcelProps } from './parcels';
import { mapRef, syncHash, useTool, type Spot } from './store';
import { placesShown } from './places';
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

const PLACE_NAME: Record<string, string> = { pittsburgh: 'Pittsburgh', philadelphia: 'Philadelphia' };

interface RecordResult {
  record: LotRecord | null;
  recordNote: string | null;
  builtAt: string | null;
  /** The lot file did not load (network, server, bad file): the panel offers to try again. */
  loadFailed?: boolean;
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
async function recordAt(pt: LngLat, tract: TractProps, signal: AbortSignal, label: string, lotId?: string, recordTract?: string): Promise<RecordResult | null> {
  // A clicked parcel tile and a link name the record's own tract, which can differ from the tract under the point.
  const geoid = recordTract ?? tract.GEOID;
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
    return { record: null, recordNote: `${missing}${why} The tract and town numbers below still apply.`, builtAt: null, loadFailed: !missing };
  }
}

/** A new lot keeps the unit size, finds a spot again, and switches to an allowed unit type. */
function fitUnitTo(record: LotRecord) {
  const { scenario, unit } = useTool.getState();
  const type = typeFor(record, scenario, unit.type);
  useTool.getState().set({ unit: type === unit.type ? { ...unit, at: null, angle: null } : startUnit(record, scenario, type, unit) });
}

let pending: AbortController | null = null;

/** County names for the places with lot records, for a tract known only by its GEOID. */
const COUNTY_OF: Record<string, string> = { '42003': 'Allegheny', '42101': 'Philadelphia' };
const CITY_OF: Record<string, string> = { '42003': 'Pittsburgh city', '42101': 'Philadelphia city' };

/** A tract named by a parcel tile or a link, before (or without) the tract file: enough for the lot panel. */
function knownTract(geoid: string): { tract: TractProps; town: TownProps } {
  const t = Number(geoid.slice(5)) / 100;
  return { tract: { GEOID: geoid, NAMELSAD: `Census Tract ${t}`, county: COUNTY_OF[geoid.slice(0, 5)] }, town: { NAMELSAD: CITY_OF[geoid.slice(0, 5)] } };
}

/**
 * Test one spot. Test Project: the lot record that contains the spot (or the one a parcel tile or a link names) and
 * its tract. Explore: the tract and town at the spot, with no lot (that is Test Project's job).
 * The tract files load only when needed: a lot whose tract is known from its tile or link opens without them.
 */
export async function testSpot(pt: LngLat, label: string, parcel?: ParcelProps | null, opts: { lotId?: string; tract?: string; keepUnit?: boolean } = {}) {
  const { set, view3d, view } = useTool.getState();
  const map = mapRef.current;
  if (!map) return;
  const known = view === 'test' ? (opts.tract ?? parcel?.tr) : undefined;
  // Test Project, a searched or clicked spot with no tract yet: the small city tract index first (Pittsburgh and
  // Philadelphia), the 10 MB area files only outside the two cities.
  const indexed = view === 'test' && !known && useTool.getState().areas !== 'ready' ? await cityTractAt(pt) : null;
  if (!known && !indexed && !(await loadAreas())) {
    set({ msg: 'The map data did not load. Refresh the page to try again.' });
    return;
  }
  const { tracts, towns } = useTool.getState();
  const tract = tracts ? findFeature(tracts, pt) : undefined;
  const town = towns ? findFeature(towns, pt) : undefined;
  let area = tract ? { tract: tract.properties, town: town?.properties ?? {} } : (indexed ?? (known ? knownTract(known) : null));
  if (!area) {
    set({ msg: 'That spot is outside Pennsylvania.' });
    return;
  }
  const n = ++counter;
  pending?.abort();
  const ctrl = new AbortController();
  pending = ctrl;
  set({ msg: null, busy: true, selectedLot: view === 'test' ? (parcel?.id ?? opts.lotId ?? null) : null });

  // The selected parcel's glowing outline is the only mark. Outside the parcels, a ripple shows where.
  if (!parcel) ripple(pt);
  // Where to Build answers for a whole municipality: zoom in only to about county level, so its outline shows.
  const legal = placesShown(useTool.getState());
  map.flyTo({ center: pt, zoom: Math.max(map.getZoom(), view === 'test' ? 16.5 : legal ? 10 : 12), pitch: view3d ? PITCH_SPOT : 0, duration: reduced() ? 0 : 1400, padding: mapPadding(true), essential: true });
  // Explore, Where to Build answers for the municipality, so its outline is the one drawn.
  const outline = legal && town ? town : tract;
  (map.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: outline ? [outline as unknown as GeoJSON.Feature] : [] });

  let rec = view === 'test' ? await recordAt(pt, area.tract, ctrl.signal, label, opts.lotId ?? (parcel?.tr ? parcel.id : undefined), opts.tract ?? parcel?.tr) : { record: null, recordNote: null, builtAt: null };
  if (n !== counter || !rec) return; // a newer spot won
  // No lot record from the index tract: the full area files, for the tract report and in case the point sits in the
  // tract next door. The address match still runs in that tract.
  if (indexed && !rec.record && (await loadAreas())) {
    const s = useTool.getState();
    const t = s.tracts ? findFeature(s.tracts, pt) : undefined;
    if (t) {
      area = { tract: t.properties, town: (s.towns ? findFeature(s.towns, pt)?.properties : undefined) ?? area.town };
      if (t.properties.GEOID !== indexed.tract.GEOID) rec = await recordAt(pt, area.tract, ctrl.signal, label);
      if (n !== counter || !rec) return;
    }
  }
  const record = rec.record;
  const spot: Spot = { n, label: record?.lot.address ? titleCase(record.lot.address) : label, pt, tract: area.tract, town: area.town, parcel: parcel ?? null, ...rec };
  if (record && !opts.keepUnit) fitUnitTo(record);
  set({ busy: false, selectedLot: record?.lot.id ?? null, spot });
  syncHash();
}

/** Explore: switch to Test Project at the selected spot (the tool then opens the lot there). */
export function testLotHere() {
  // The view change re-runs testSpot at the selected spot (ToolPage), now looking for the lot record there.
  openView('test');
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
    await testSpot(pt, 'Linked lot', null, { lotId, tract: geoid, keepUnit });
  } catch (e) {
    useTool.getState().set({ msg: isLotLoadError(e) ? e.userMessage : 'That lot could not be opened.' });
  }
}

export function clearSpot() {
  // A lot still loading must neither come back nor leave the panel on its loading skeleton.
  counter++;
  pending?.abort();
  (mapRef.current?.getSource('pick') as GeoJSONSource | undefined)?.setData({ type: 'FeatureCollection', features: [] });
  useTool.getState().set({ spot: null, selectedLot: null, busy: false });
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
