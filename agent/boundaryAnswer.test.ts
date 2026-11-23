// get_boundary_answer on the real data files (app/public/data/pa_places.json, tract_towns.json, zip_towns.json):
// the answer for a picked county, tract or ZIP code is the one Test Site's Details panel shows (tool/tractRules.ts).
import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { makeExecutors } from '../app/src/agent/executors';
import { parsePlaces } from '../app/src/tool/places';
import { countySummary, tractSummary } from '../app/src/tool/tractRules';
import { nodeProvider } from './nodeProvider';
import type { AreaRef } from '../app/src/agent/boundaryTool';

type J = Record<string, unknown>;
const DATA = resolve(import.meta.dirname, '../app/public/data');
const read = (f: string) => JSON.parse(readFileSync(resolve(DATA, f), 'utf8'));
const places = parsePlaces(read('pa_places.json'));
const pct = (v: number) => `${Math.round(v * 100)}%`;
const run = (input: J, area: AreaRef | null = null) => makeExecutors(nodeProvider({ area })).get_boundary_answer(input) as Promise<J>;

describe('get_boundary_answer', () => {
  it('a ZIP code picked on the map: the panel answer, its share and its towns', async () => {
    const r = await run({}, { kind: 'zip', geoid: '19034', name: 'ZIP code 19034' });
    const s = tractSummary('19034', read('zip_towns.json'), places, 'homes')!;
    expect(r.area).toBe('ZIP code 19034');
    expect(r.answer).toBe(s.title);
    expect(r.share_of_homes_in_towns_that_allow_an_adu_today).toBe(pct(s.allowed));
    expect((r.towns as J[])[0].town).toBe(s.towns[0].name);
    expect(String(r.zip_note)).toMatch(/not the same as postal ZIP areas/);
    expect(String(r.notice)).toMatch(/each town/);
  });

  it('a county by name or by FIPS: weighted by people', async () => {
    const byName = await run({ name: 'Montgomery County' });
    const byFips = await run({ kind: 'county', geoid: '42091' });
    const s = countySummary('42091', places)!;
    expect(byName.area).toBe('Montgomery County');
    expect(byFips.answer).toBe(byName.answer);
    expect(byName.answer).toBe(s.title);
    expect(byName.share_of_people_in_towns_that_allow_an_adu_today).toBe(pct(s.allowed));
    expect(String(byName.more_towns)).toMatch(/^And \d+ more towns/);
  });

  it('a tract by GEOID', async () => {
    const r = await run({ kind: 'tract', geoid: '42003141300' });
    expect(r.kind).toBe('tract');
    expect((r.towns as J[]).map((t) => t.town)).toContain('Pittsburgh city');
  });

  it('a municipality is answered by get_place_answer, and unknown or missing areas ask', async () => {
    const town = await run({}, { kind: 'town', geoid: '4209179008', name: 'Upper Dublin township' });
    expect(town.answered_by).toMatch(/^get_place_answer/);
    expect(String(town.say_place)).toContain('Upper Dublin township');
    expect(town.town_offices).toMatchObject({ zoning: { phone: '(215) 643-1600 ext. 3213' } });
    expect((await run({ kind: 'zip', geoid: '99999' })).found).toBe(false);
    expect((await run({ name: 'Atlantis' })).found).toBe(false);
    expect((await run({})).needs).toBe('area');
    expect((await run({ kind: 'zip' })).needs).toBe('geoid');
  });
});
