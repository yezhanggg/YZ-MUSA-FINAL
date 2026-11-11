// The agent's data in the browser: the loaded tracts, towns and lot files, and the live map.
import type { ExpressionSpecification } from 'maplibre-gl';
import { findFeature, hasLots, loadLots, lotsLoaded, type LngLat, type Lot, type TownProps } from '../tool/geo';
import { mapRef, useTool } from '../tool/store';
import { openLot, testSpot } from '../tool/actions';
import { BED_SIZE, SIZE_MAX, SIZE_MIN, type Bed, type Stories } from '../lib/numbers';
import type { DataProvider, SetMapInput, SiteRecord } from './executors';
import { findLoadedLot, loadedLots, lotByIdAnywhere } from '../lib/lot/load';
import type { LotAgentProvider } from '../lib/lot/agentTools';
import type { LotRecord } from '../lib/lot/types';
import { moneyOptions, tractRents } from '../tool/testState';

function siteOfLot(lot: Lot): SiteRecord {
  const { tracts, towns } = useTool.getState();
  const pt: LngLat = [lot.lon, lot.lat];
  return { lot, tract: tracts ? (findFeature(tracts, pt)?.properties ?? null) : null, town: towns ? (findFeature(towns, pt)?.properties ?? null) : null };
}

/** Tracts on screen (corners, centre) plus the selected tract. Pilot tracts only. */
function tractsInView(): string[] {
  const map = mapRef.current;
  const { tracts, spot } = useTool.getState();
  const out = new Set<string>();
  if (spot?.tract.GEOID && hasLots(spot.tract.GEOID)) out.add(spot.tract.GEOID);
  if (map && tracts && map.getZoom() >= 12) {
    const c = map.getContainer();
    const w = c.clientWidth;
    const h = c.clientHeight;
    for (let i = 0; i <= 4; i++)
      for (let j = 0; j <= 4; j++) {
        const ll = map.unproject([(w * i) / 4, (h * j) / 4]);
        const t = findFeature(tracts, [ll.lng, ll.lat]);
        if (t && hasLots(t.properties.GEOID)) out.add(t.properties.GEOID);
      }
  }
  return [...out].slice(0, 12);
}

async function lotById(id: string): Promise<Lot | null> {
  for (const lots of lotsLoaded.values()) {
    const hit = lots.find((l) => l.lot_id === id);
    if (hit) return hit;
  }
  // Not loaded yet: try the tracts on screen.
  for (const g of tractsInView()) {
    const hit = (await loadLots(g))?.find((l) => l.lot_id === id);
    if (hit) return hit;
  }
  return null;
}

/** Lots drawn as "suggested" by the agent. */
function highlight(ids: string[]) {
  const map = mapRef.current;
  if (!map?.getSource('parcels')) return;
  const filter = ['in', ['get', 'id'], ['literal', ids]] as unknown as ExpressionSpecification;
  if (!map.getLayer('agent-highlight')) map.addLayer({ id: 'agent-highlight', type: 'line', source: 'parcels', 'source-layer': 'parcels', filter, paint: { 'line-color': '#0ea5e9', 'line-width': 3, 'line-dasharray': [1.5, 1] } });
  else map.setFilter('agent-highlight', filter);
}

/** The tract of a lot record, from the loaded tracts. */
const tractOf = (lot: LotRecord) => useTool.getState().tracts?.features.find((f) => f.properties.GEOID === lot.lot.tract)?.properties ?? null;

/** Lot records for the lot tools: the selected record, the scenario and unit on screen, and the money settings. */
export const lotProvider: LotAgentProvider = {
  async lotById(id) {
    const sel = useTool.getState().spot?.record;
    // In memory first, else through the build's lot_tract index (one request per place, then the tract file).
    return sel?.lot.id === id ? sel : lotByIdAnywhere(id);
  },
  async selectedLot() {
    return useTool.getState().spot?.record ?? null;
  },
  scenario() {
    const st = useTool.getState();
    return st.view === 'test' ? st.scenario : st.rule === 'hb2186' ? 'state_reform' : 'today';
  },
  unit() {
    const { view, unit: u } = useTool.getState();
    return view === 'test' ? { type: u.type, width_ft: u.width, depth_ft: u.depth, stories: u.stories, height_ft: u.height, angle_deg: u.angle, units: u.units, position: u.at ?? 'best' } : null;
  },
  rents: (lot) => tractRents(tractOf(lot)),
  money: (lot) => moneyOptions(lot, useTool.getState().money, tractOf(lot)),
};

export const browserProvider: DataProvider = {
  lots: lotProvider,
  async lotById(id) {
    const lot = await lotById(id);
    return lot ? siteOfLot(lot) : null;
  },
  async selected() {
    const spot = useTool.getState().spot;
    return spot ? { lot: spot.lot, tract: spot.tract, town: spot.town } : null;
  },
  async town(geoid) {
    const { towns, spot } = useTool.getState();
    if (!geoid) return spot?.town ?? null;
    return (towns?.features.find((f) => f.properties.GEOID === geoid)?.properties as TownProps | undefined) ?? null;
  },
  async searchLots() {
    const ids = tractsInView();
    const lots: (SiteRecord & { lot: Lot })[] = [];
    for (const g of ids) for (const l of (await loadLots(g)) ?? []) lots.push(siteOfLot(l) as SiteRecord & { lot: Lot });
    const map = mapRef.current;
    const spot = useTool.getState().spot;
    const center: LngLat | null = spot ? spot.pt : map ? [map.getCenter().lng, map.getCenter().lat] : null;
    return { lots, center, scope: ids.length ? `${ids.length} tract(s) on screen or around the selected site` : 'no pilot tracts on screen (zoom in on Philadelphia or Cumberland County)' };
  },
  async addressBook() {
    const recs = loadedLots();
    const entries = recs.filter((r) => r.lot.address).map((r) => ({ lot_id: r.lot.id, tract: r.lot.tract ?? '', place: r.lot.place ?? '', address: r.lot.address! }));
    return { entries, scope: `lot records loaded on the map (${new Set(entries.map((e) => e.tract)).size} tracts). Search the address on the map to load more` };
  },
  async areas() {
    const { tracts, towns, counties } = useTool.getState();
    return { tracts, towns, counties };
  },
  curves: () => useTool.getState().curves,
  adu: () => useTool.getState().adu,
  rule: () => useTool.getState().rule,
  async setMap(input: SetMapInput) {
    const st = useTool.getState();
    switch (input.action) {
      case 'fly_to_lot': {
        const lot = input.lot_id ? await lotById(input.lot_id) : null;
        if (!lot) return `Lot ${input.lot_id} not found in the loaded data`;
        await selectLot(lot);
        return `Selected lot ${lot.lot_id}`;
      }
      case 'highlight':
        highlight(input.lot_ids ?? []);
        return `Highlighted ${(input.lot_ids ?? []).length} lots`;
      case 'set_adu': {
        const bed = [0, 1, 2, 3].includes(Number(input.bedrooms)) ? (Number(input.bedrooms) as Bed) : st.adu.bed;
        const size = typeof input.size_sqft === 'number' ? Math.min(SIZE_MAX, Math.max(SIZE_MIN, Math.round(input.size_sqft / 50) * 50)) : input.bedrooms !== undefined ? BED_SIZE[bed] : st.adu.size;
        const stories = (Number(input.stories) === 2 ? 2 : input.stories !== undefined ? 1 : st.adu.stories) as Stories;
        st.setAdu({ bed, size, stories });
        return `ADU set to ${bed === 0 ? 'studio' : `${bed} BR`}, ${size} sq ft, ${stories} ${stories === 2 ? 'stories' : 'story'}`;
      }
      case 'set_rule':
        st.set({ rule: input.rule === 'hb2186' ? 'hb2186' : 'current' });
        return `Rules set to ${input.rule === 'hb2186' ? 'HB 2186' : 'today'}`;
    }
  },
};

/** Select a lot from a link in an answer or from set_map. */
export async function selectLot(lot: Lot) {
  await testSpot([lot.lon, lot.lat], 'Selected lot', { id: lot.lot_id, s: 1, f: lot.fits ? 1 : 0, k: lot.fits_keep_trees ? 1 : 0 });
}

export async function selectLotById(id: string) {
  const rec = findLoadedLot(id);
  if (rec?.lot.tract) {
    await openLot(id, rec.lot.tract);
    return true;
  }
  const lot = await lotById(id);
  if (lot) await selectLot(lot);
  return !!lot;
}
