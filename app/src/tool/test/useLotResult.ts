// Everything the testing cards show, worked out once per change of lot, scenario, unit or money settings.
import { useMemo } from 'react';
import { compareScenarios, unitVerdict } from '../../lib/lot/verdict';
import { lotMoney, type MoneyOptions } from '../../lib/lot/summary';
import type { LotRecord, RentByBedroom } from '../../lib/lot/types';
import { buildSteps } from '../../lib/lot/buildSteps';
import { siteData, typeOptions, unitInput, type MoneyDraft } from '../testState';
import type { TractProps } from '../geo';
import { useTool } from '../store';

/** Market rents for a record that has none: the tract's ACS rents by bedrooms. */
export function tractRents(t: TractProps | null | undefined): RentByBedroom | null {
  if (!t) return null;
  const r = { b0: t.rent_b0 ?? null, b1: t.rent_b1 ?? null, b2: t.rent_b2 ?? null, b3: t.rent_b3 ?? null };
  return Object.values(r).some((v) => typeof v === 'number') ? r : null;
}

/** Money options for lotMoney from the screen settings. */
export function moneyOptions(lot: LotRecord, m: MoneyDraft, tract: TractProps | null | undefined): MoneyOptions {
  const own = lot.money?.rent_by_bedroom;
  return {
    rent_by_bedroom: own ? null : tractRents(tract),
    rent_source: own ? (lot.money?.rent_source ?? 'hud_safmr') : 'acs_tract',
    financing: { preset: m.preset, rate: m.rate },
    money: { rent: m.rent, hard_psf: m.psf },
    quality: m.finish,
  };
}

export function useLotResult(record: LotRecord) {
  const scenario = useTool((s) => s.scenario);
  const unit = useTool((s) => s.unit);
  const money = useTool((s) => s.money);
  const tract = useTool((s) => s.spot?.tract);
  const input = useMemo(() => unitInput(unit, scenario), [unit, scenario]);
  const verdict = useMemo(() => unitVerdict(record, input), [record, input]);
  const rows = useMemo(() => compareScenarios(record, input), [record, input]);
  const opts = useMemo(() => moneyOptions(record, money, tract), [record, money, tract]);
  const cash = useMemo(() => lotMoney(record, verdict, opts), [record, verdict, opts]);
  const types = useMemo(() => typeOptions(record, scenario), [record, scenario]);
  const build = useMemo(() => buildSteps({ lot: record, scenario, type: unit.type, floor_sqft: verdict.floor_sqft }), [record, scenario, unit.type, verdict.floor_sqft]);
  const site = useMemo(() => siteData(record, unit, verdict), [record, unit, verdict]);
  return { scenario, unit, input, verdict, rows, money: cash, moneyOpts: opts, types, build, site };
}

export type LotResult = ReturnType<typeof useLotResult>;
