// Everything the testing cards show, worked out once per change of lot, scenario, unit or money settings.
import { useMemo } from 'react';
import { compareScenarios, unitVerdict } from '../../lib/lot/verdict';
import { lotMoney } from '../../lib/lot/summary';
import type { LotRecord } from '../../lib/lot/types';
import { buildSteps } from '../../lib/lot/buildSteps';
import { moneyOptions, siteData, typeOptions, unitInput } from '../testState';
import { useTool } from '../store';

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
