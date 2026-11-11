// Real lot records for the tests: eight Pittsburgh lots from the full build and one Philadelphia lot
// from the smoke run. Picked by ~/musa-drive/ops/scratch/vitest-lot/pick_fixtures.py. No owner data.
import type { LotRecord } from '../types';
import alleyRear from './alley_rear.json';
import easyFit from './easy_fit.json';
import garage from './garage.json';
import lowConfidence from './low_confidence.json';
import noFit from './no_fit.json';
import philadelphiaInternal from './philadelphia_internal.json';
import steepSlope from './steep_slope.json';
import twinSplit from './twin_split.json';
import twoUnits from './two_units.json';

const RAW = {
  easy_fit: easyFit,
  no_fit: noFit,
  alley_rear: alleyRear,
  twin_split: twinSplit,
  two_units: twoUnits,
  steep_slope: steepSlope,
  garage,
  low_confidence: lowConfidence,
  philadelphia_internal: philadelphiaInternal,
};

export type FixtureName = keyof typeof RAW;

/** A fresh deep copy each call, so a test can change a record without touching the others. */
export function fixture(name: FixtureName): LotRecord {
  return structuredClone(RAW[name]) as unknown as LotRecord;
}

export const FIXTURE_NAMES = Object.keys(RAW) as FixtureName[];
