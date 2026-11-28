// The agent's data in the browser: the loaded tracts, towns and lot files, and the live map.
import type { ExpressionSpecification } from 'maplibre-gl';
import { findFeature, hasLots, loadLots, lotsLoaded, type LngLat, type Lot, type TownProps } from '../tool/geo';
import { mapRef, useTool } from '../tool/store';
import { openLot, testSpot } from '../tool/actions';
import type { DataProvider, SetMapInput, SiteRecord } from './executors';
import { findLoadedLot, loadedLots, lotByIdAnywhere } from '../lib/lot/load';
import type { LotAgentProvider } from '../lib/lot/agentTools';
import type { LotRecord } from '../lib/lot/types';
import { moneyOptions, tractRents, unitFromInput } from '../tool/testState';
import { SET_UNIT_NO_LOT, aduFromInput, aduText, ruleText, unitText } from './mapText';
import { zoningTextSource } from './zoningText';
import { placesSource } from './placeAnswer';
import { tractTownsSource } from './tractTowns';
import { lotPlacesText } from './lotPlaces';
import { lotTownOf } from '../lib/lot/towns';
import { flyToPlace } from '../tool/flyToPlace';
import { addressIndexSource } from '../lib/lot/addressIndex';
import { ruleFileByKey } from './ruleText';
import { bundledDocs } from './docsSearch';

/** { town } of a lot record for find_lot, when its town is known. */
const townOf = (r: LotRecord) => {
  const t = lotTownOf(r);
  return t ? { town: t.name } : {};
};

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
  // get_parcel_info's district table: the town rule file, one lazy chunk per town (the Parcel tab loads the same one).
  ruleFile: (key) => ruleFileByKey(key) as Promise<Record<string, unknown> | null>,
};

export const browserProvider: DataProvider = {
  lots: lotProvider,
  // Public zoning text (tier B), one file per town, loaded when the assistant searches it.
  zoningText: zoningTextSource(),
  // search_tool_docs: the project documents index, a lazy chunk loaded on the first search.
  docs: bundledDocs,
  // The statewide place table for get_place_answer, from the app's own data folder.
  places: placesSource(),
  tractTowns: tractTownsSource(),
  // get_boundary_answer on a ZIP code: the same shape as tract_towns.json.
  zipTowns: tractTownsSource({ url: 'data/zip_towns.json' }),
  // The area picked on a boundary in Test Site (ruleLayers.ts), only while no lot is open.
  area() {
    const s = useTool.getState();
    const p = s.areaPick;
    return p && !s.spot?.record ? { kind: p.kind, geoid: p.geoid, name: p.name } : null;
  },
  // find_lot: the address index of every lot place (published next to the tract files), fetched per street.
  addressIndex: addressIndexSource(),
  async lotById(id) {
    const lot = await lotById(id);
    return lot ? siteOfLot(lot) : null;
  },
  async selected() {
    const spot = useTool.getState().spot;
    // The tool's spot has no pilot lot: one lot is a lot record (the lot tools read it).
    return spot ? { lot: null, tract: spot.tract, town: spot.town } : null;
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
    return { lots, center, scope: ids.length ? `${ids.length} tract(s) on screen or around the selected site` : `no tracts with older pilot lots on screen. For one lot in ${lotPlacesText('or')} use find_lot and the lot record tools` };
  },
  async addressBook() {
    const recs = loadedLots();
    const entries = recs.filter((r) => r.lot.address).map((r) => ({ lot_id: r.lot.id, tract: r.lot.tract ?? '', place: r.lot.place ?? '', ...townOf(r), address: r.lot.address! }));
    return { entries, scope: `lot records loaded on the map (${new Set(entries.map((e) => e.tract)).size} tracts). Search the address on the map to load more` };
  },
  async areas() {
    const { tracts, towns, counties } = useTool.getState();
    return { tracts, towns, counties };
  },
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
      case 'fly_to_place':
        return input.place ? flyToPlace(input.place) : 'No place was given.';
      case 'highlight':
        highlight(input.lot_ids ?? []);
        return `Highlighted ${(input.lot_ids ?? []).length} lots`;
      case 'set_adu': {
        const adu = aduFromInput(st.adu, input);
        st.setAdu(adu);
        return aduText(adu);
      }
      case 'set_rule':
        st.set({ rule: input.rule === 'hb2186' ? 'hb2186' : 'current' });
        return ruleText(input.rule);
      case 'set_unit': {
        if (st.view !== 'test') return SET_UNIT_NO_LOT;
        const next = unitFromInput(st.unit, input);
        st.setUnit(next);
        return unitText({ ...st.unit, ...next });
      }
    }
  },
};

/** Go to a pilot lot from a link in an answer or from set_map: the map shows its tract (pilot lots are not lot records). */
export async function selectLot(lot: Lot) {
  await testSpot([lot.lon, lot.lat], 'Selected spot');
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

