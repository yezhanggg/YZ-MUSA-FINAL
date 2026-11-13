// Real lot records for the tests: eight Pittsburgh lots and five Philadelphia lots from the final builds of
// Nov 11, 2026, and one Allentown lot (build of Nov 12, ops/scratch/ui9/pick_abe.py). Picked by ~/musa-drive/ops/scratch/vitest-lot/pick_fixtures2.py. No owner data.
import type { LotRecord } from '../types';
import abeDetached from './abe_detached.json';
import alleyRear from './alley_rear.json';
import easyFit from './easy_fit.json';
import garage from './garage.json';
import lowConfidence from './low_confidence.json';
import noFit from './no_fit.json';
import philadelphiaInternal from './philadelphia_internal.json';
import phlHistoric from './phl_historic.json';
import phlRowToday from './phl_row_today.json';
import phlRsa5Internal from './phl_rsa5_internal.json';
import phlTwinState from './phl_twin_state.json';
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
  phl_row_today: phlRowToday,
  phl_rsa5_internal: phlRsa5Internal,
  phl_historic: phlHistoric,
  phl_twin_state: phlTwinState,
  abe_detached: abeDetached,
};

export type FixtureName = keyof typeof RAW;

/** A fresh deep copy each call, so a test can change a record without touching the others. */
export function fixture(name: FixtureName): LotRecord {
  return structuredClone(RAW[name]) as unknown as LotRecord;
}

export const FIXTURE_NAMES = Object.keys(RAW) as FixtureName[];
