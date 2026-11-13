import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import raw from './__fixtures__/pa_places_small.json';
import { LOT_CITY_CODE, codeLink, publisher, LEGEND_ORDER, STATUS_COLOR, hasLotTesting, hatched, loadPlaces, paintGroups, parsePlaces, peopleShares, placeAnswer, placeRows, shareText, shownStatus, usePlaces } from './places';

const P = parsePlaces(raw, { built_on: '2026-11-12' });
const row = (name: string) => P.rows.find((r) => r.name === name)!;
const words = (s: string) => s.split(/\s+/).filter(Boolean).length;

describe('places file', () => {
  it('keeps good rows, drops a row with no GEOID, and reads a status at the wrong tier as not checked', () => {
    expect(P.rows).toHaveLength(10);
    expect(P.byGeoid.has('bad')).toBe(false);
    expect(row('Odd row').status).toBe('unknown');
    expect(P.date).toBe('2026-11-12');
  });

  it('a missing or broken file gives no rows, and the loader reports it as missing', async () => {
    expect(parsePlaces(null).rows).toHaveLength(0);
    expect(parsePlaces({ not: 'an array' }).rows).toHaveLength(0);
    usePlaces.setState({ state: 'idle', places: null });
    await loadPlaces(async () => new Response('nope', { status: 404 }));
    expect(usePlaces.getState().state).toBe('missing');
    usePlaces.setState({ state: 'idle', places: null });
    await loadPlaces(async (u) => new Response(JSON.stringify(u.endsWith('meta.json') ? { built_on: '2026-11-12' } : raw)));
    expect(usePlaces.getState().state).toBe('ready');
    expect(usePlaces.getState().places?.date).toBe('2026-11-12');
  });

  it('six colours, all different, grey for not checked', () => {
    expect(LEGEND_ORDER).toHaveLength(6);
    expect(new Set(LEGEND_ORDER.map((s) => STATUS_COLOR[s])).size).toBe(6);
  });

  it('hatches first readings and lists by others, not checked rows and verified rows stay plain', () => {
    expect(hatched(row('Abington township'), 'current')).toBe(true);
    expect(hatched(row('Atwood borough'), 'current')).toBe(true);
    expect(hatched(row('Allentown city'), 'current')).toBe(false);
    expect(hatched(row('Highland township'), 'current')).toBe(false);
    const g = paintGroups(P, 'current');
    expect(g.hatch.sort()).toEqual(['4200503480', '4209100156']);
    expect(g.byStatus.unknown).toContain('4200134424');
  });

  it('the state bill: zoned places become by right, no zoning stays, unknown zoning stays not checked', () => {
    expect(shownStatus(row('Reading city'), 'hb2186')).toBe('by_right');
    expect(shownStatus(row('Abbottstown borough'), 'hb2186')).toBe('by_right');
    expect(shownStatus(row('Atwood borough'), 'hb2186')).toBe('no_zoning');
    expect(shownStatus(row('Mystery township'), 'hb2186')).toBe('unknown');
    const a = placeAnswer(row('Reading city'), 'hb2186');
    expect(a).toMatchObject({ answer: 'yes', title: 'Allowed by right', notLaw: true });
    expect(a.sub).toBe('Under the state bill. Today: not allowed.');
    expect(placeAnswer(row('Atwood borough'), 'hb2186').sub).toContain('would not change');
  });

  it('one plain answer per status', () => {
    expect(placeAnswer(row('Pittsburgh city'), 'current').title).toBe('Allowed by right');
    expect(placeAnswer(row('Abington township'), 'current').title).toBe('Allowed with a hearing');
    expect(placeAnswer(row('Allentown city'), 'current')).toMatchObject({ title: 'Allowed with limits', sub: 'Zoning permit, owner must live on the lot.' });
    expect(placeAnswer(row('Reading city'), 'current')).toMatchObject({ answer: 'no', title: 'Not allowed today' });
    expect(placeAnswer(row('Lancaster city'), 'current')).toMatchObject({ answer: 'no', title: 'Not addressed' });
    expect(placeAnswer(row('Atwood borough'), 'current').title).toBe('No zoning here');
    expect(placeAnswer(row('Atwood borough'), 'current').sub).toMatch(/^Not restricted by zoning/);
    expect(placeAnswer(row('Abbottstown borough'), 'current').title).toBe('Not checked yet');
    expect(placeAnswer(undefined, 'current').title).toBe('Not checked yet');
    for (const r of P.rows) for (const m of ['current', 'hb2186'] as const) expect(words(placeAnswer(r, m).sub), r.name).toBeLessThanOrEqual(18);
  });

  it('at most four rows, with how sure in the words of the tier', () => {
    for (const r of P.rows) for (const m of ['current', 'hb2186'] as const) expect(placeRows(r, m).length).toBeLessThanOrEqual(4);
    const sure = (n: string) => placeRows(row(n), 'current').find((x) => x.id === 'sure')!.value;
    expect(sure('Allentown city')).toBe('Checked against the code on Nov 11, 2026');
    expect(sure('Abington township')).toBe('First reading');
    expect(sure('Atwood borough')).toBe('Listed by PA DCED, 2026');
    expect(sure('Highland township')).toBe('Not checked yet');
    const ask = placeRows(row('Allentown city'), 'current').find((x) => x.id === 'ask')!;
    expect(ask).toMatchObject({ value: 'City office', phone: '(610) 437-7558 x 2140' });
    expect(ask.link?.href).toBe('http://allentownpa.gov');
    expect(placeRows(row('Reading city'), 'current').find((x) => x.id === 'ask')!.link?.href).toBe('https://readingpa.gov');
    expect(placeRows(row('Abbottstown borough'), 'current').map((x) => x.id)).toEqual(['sure']);
  });

  it('shares of people add up to one, and the bill moves people to by right', () => {
    const today = peopleShares(P, 'current')!;
    const bill = peopleShares(P, 'hb2186')!;
    const sum = (o: Record<string, number>) => Object.values(o).reduce((a, b) => a + b, 0);
    expect(sum(today)).toBeCloseTo(1, 6);
    expect(sum(bill)).toBeCloseTo(1, 6);
    expect(bill.by_right).toBeGreaterThan(today.by_right);
    expect(peopleShares(parsePlaces([]), 'current')).toBeNull();
    expect(shareText(0.001)).toBe('<1%');
    expect(shareText(0)).toBe('0%');
  });

  it('a list by others names its publisher from the status source, not from who zones', () => {
    const base = { ...row('Atwood borough'), zoning_source: 'dced', status: 'limited' as const };
    const named = (name: string) => publisher({ ...base, source: { name, url: null, date: '2019' } });
    expect(named('Delaware Valley Regional Planning Commission: Municipal Implementation Toolbox')).toBe('DVRPC');
    expect(named('Chester County Planning Commission: Planning for Attractive Homes')).toBe('Chester County Planning Commission');
    expect(named('Centre County (County Planning Office), PA: Needs Assessment')).toBe('Centre County');
    expect(named('Othering & Belonging Institute, UC Berkeley: Zoning Reform Tracker (database)')).toBe('Othering & Belonging Institute');
    expect(named('PA DCED Municipal Statistics, municipal zoning filing')).toBe('PA DCED');
    const plum = { ...base, status_detail: 'relatives, caretakers, farm workers or on-site employees only; for-profit apartments prohibited in single-family districts (inventory dated 2019)' };
    expect(placeAnswer(plum, 'current').sub).toBe('Relatives, caretakers, farm workers or on-site employees only.');
    expect(placeAnswer({ ...base, status_detail: 'Accessory Mobile Home (min. lot 2 acres) special exception (A)' }, 'current').sub).toBe('Accessory Mobile Home.');
  });

  it('lot testing only in the three lot cities', () => {
    expect(hasLotTesting('4200361000')).toBe(true);
    expect(hasLotTesting('4210160000')).toBe(true);
    expect(hasLotTesting('4207702000')).toBe(true);
    expect(hasLotTesting('4209100156')).toBe(false);
  });
});

describe('zoning code link', () => {
  it('the code when the row has one, else the town website, else nothing; the lot cities without the file', () => {
    expect(codeLink(row('Allentown city'), '4207702000')).toEqual({ href: 'https://ecode360.com/49783893', label: 'Zoning code' });
    expect(codeLink(row('Abington township'), '4209100156')).toEqual({ href: 'http://WWW.ABINGTONPA.GOV', label: 'Town website' });
    expect(codeLink(row('Atwood borough'), '4200503480')).toBeNull();
    expect(codeLink(undefined, '4210160000')?.label).toBe('Zoning code');
    expect(codeLink(undefined, '4207702000')?.href).toBe('https://ecode360.com/49783893');
    expect(codeLink(undefined, '4209100156')).toBeNull();
  });

  it('the lot cities link the code the index and their rule files name', () => {
    const rules = resolve(__dirname, '../../../shared/rules');
    const idx = JSON.parse(readFileSync(resolve(rules, 'towns_index.json'), 'utf8')) as { towns: { geoid: string; file: string; code_url: string | null }[] };
    for (const [geoid, url] of Object.entries(LOT_CITY_CODE)) {
      const e = idx.towns.find((t) => t.geoid === geoid)!;
      expect(e.code_url).toBe(url);
      expect(readFileSync(resolve(rules, `${e.file}.json`), 'utf8')).toContain(url);
    }
  });
});
