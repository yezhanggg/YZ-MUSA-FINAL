// The Node provider on the lot records on disk: address search, lot by id, tract facts for a selected record.
// Skipped when the Philadelphia smoke build is not on this machine.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { describe, expect, it } from 'vitest';
import { makeExecutors } from '../app/src/agent/executors';
import { nodeProvider, nodeTractLots, tractsOnDisk } from './nodeProvider';

const SMOKE = resolve(homedir(), 'musa-drive/smoke/lots/philadelphia');
type J = Record<string, unknown>;

describe.skipIf(!existsSync(SMOKE))('node provider on lot records', () => {
  process.env.LOT_DATA_DIR_PHILADELPHIA ??= SMOKE;
  const first = async () => (await nodeTractLots(tractsOnDisk('philadelphia')[0])).lots.find((l) => l.lot.address)!;

  it('find_lot finds a record by its address, written another way', async () => {
    const rec = await first();
    const ex = makeExecutors(nodeProvider());
    const spoken = rec.lot.address!.toLowerCase().replace(/\bst$/, 'Street');
    const r = (await ex.find_lot({ address: spoken })) as { candidates: J[] };
    expect(r.candidates.map((c) => c.lot_id)).toContain(rec.lot.id);
    expect(r.candidates[0].tract).toBe(rec.lot.tract);
  }, 60_000);

  it('get_lot_facts finds a lot by id that is not selected', async () => {
    const rec = await first();
    const r = (await makeExecutors(nodeProvider()).get_lot_facts({ lot_id: rec.lot.id })) as J;
    expect(r.lot_id).toBe(rec.lot.id);
  });

  it('a selected record gives get_site its tract and town, and get_area_stats its tract and county', async () => {
    const rec = await first();
    const ex = makeExecutors(nodeProvider({ lot: { id: rec.lot.id } }));
    const site = (await ex.get_site({})) as { tract: J | null; town: J | null };
    expect(site.tract?.geoid).toBe(rec.lot.tract);
    expect(site.town?.name).toBe('Philadelphia city');
    expect(((await ex.get_area_stats({ level: 'tract' })) as J).geoid).toBe(rec.lot.tract);
    expect(((await ex.get_area_stats({ level: 'county' })) as J).geoid).toBe('42101');
  });

  it('get_rules uses the selected town, and errors when there is none', async () => {
    const town = (await makeExecutors(nodeProvider({ townGeoid: '4210160000' })).get_rules({})) as J;
    expect(town.town).toBe('Philadelphia city');
    expect((town.adus_by_2031 as J).hb2186).toBeTruthy();
    expect(((await makeExecutors(nodeProvider()).get_rules({})) as J).error).toMatch(/No town found/);
  });
});
