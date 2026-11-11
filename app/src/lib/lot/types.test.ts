import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { FIXTURE_NAMES, fixture } from './__fixtures__';
import { LOT_KEYS, SCHEMA_VERSION, type LotBlock } from './types';

interface SchemaNode {
  properties?: Record<string, SchemaNode>;
  $ref?: string;
  const?: unknown;
}
interface Schema extends SchemaNode {
  $defs: Record<string, SchemaNode>;
}

const schema = JSON.parse(readFileSync(new URL('../../../../pipeline/lot_schema.json', import.meta.url), 'utf8')) as Schema;
const defs = schema.$defs;
const props = (node: SchemaNode | undefined) => Object.keys(node?.properties ?? {});

/** Where each LOT_KEYS block lives in the JSON Schema. */
const SCHEMA_BLOCKS: Record<LotBlock, string[]> = {
  record: props(schema),
  citation: props(defs.citation),
  edge: props(defs.edge),
  lot: props(defs.lot),
  building: props(defs.building),
  share: props(defs.share),
  cover: props(defs.cover),
  object: props(defs.object),
  zoning: props(defs.zoning),
  zoning_flags: props(defs.zoning.properties?.flags),
  rules: props(defs.rules),
  buildable: props(defs.buildable),
  check: props(defs.check),
  fit_result: props(defs.fit_result),
  fit_checks: props(defs.fit_result.properties?.checks),
  facts: props(defs.facts),
  money: props(defs.money),
  rent_by_bedroom: props(defs.money.properties?.rent_by_bedroom),
  quality: props(defs.quality),
};

describe('types match pipeline/lot_schema.json', () => {
  it('has the schema version the types are written for', () => {
    expect(schema.properties?.schema_version.const).toBe(SCHEMA_VERSION);
  });

  for (const block of Object.keys(SCHEMA_BLOCKS) as LotBlock[]) {
    it(`block ${block}: every schema property is in LOT_KEYS`, () => {
      const ours = new Set<string>(LOT_KEYS[block]);
      expect(SCHEMA_BLOCKS[block].length).toBeGreaterThan(0);
      expect(SCHEMA_BLOCKS[block].filter((k) => !ours.has(k))).toEqual([]);
    });
    it(`block ${block}: LOT_KEYS has no key the schema lacks`, () => {
      const theirs = new Set(SCHEMA_BLOCKS[block]);
      expect(LOT_KEYS[block].filter((k) => !theirs.has(k))).toEqual([]);
    });
  }
});

describe('fixtures use only known keys', () => {
  const unknown = (obj: object | null | undefined, block: LotBlock) => {
    const known = new Set<string>(LOT_KEYS[block]);
    return Object.keys(obj ?? {}).filter((k) => !known.has(k));
  };
  for (const name of FIXTURE_NAMES) {
    it(name, () => {
      const r = fixture(name);
      expect(r.schema_version).toBe(SCHEMA_VERSION);
      const extra = [
        ...unknown(r, 'record'),
        ...unknown(r.lot, 'lot'),
        ...r.buildings.flatMap((b) => unknown(b, 'building')),
        ...unknown(r.zoning, 'zoning'),
        ...unknown(r.zoning.flags, 'zoning_flags'),
        ...Object.values(r.rules).flatMap((x) => unknown(x, 'rules')),
        ...Object.values(r.buildable).flatMap((x) => unknown(x, 'buildable')),
        ...Object.values(r.fit).flatMap((types) => Object.values(types ?? {}).flatMap((f) => unknown(f, 'fit_result'))),
        ...unknown(r.facts, 'facts'),
        ...unknown(r.quality, 'quality'),
      ];
      expect(extra).toEqual([]);
    });
  }
});
