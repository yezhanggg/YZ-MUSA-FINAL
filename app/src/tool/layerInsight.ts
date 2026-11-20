// Explore, Details: "This layer here" for the picked area. The value of the map layer that is on (big, with its
// legend colour), one or two lines on how it compares with the rest of Pennsylvania, and one plain takeaway for a
// homeowner. Pure: the panel (LayerHere.tsx) gathers the numbers from the loaded data, this file only words them.
// Every number comes from the data passed in. No rule is decided here: Where to Build words come from the place's own
// status, and a bill is always marked as not law.
import { AREA_STEPS, FORECAST_LABEL, GROUP_COLORS, METRICS, MOE_GREY, NO_DATA, WINDOW_LABEL, WINDOW_VAR_LABEL, windowLegend, WINDOW_STEPS, type Forecast, type MetricId, type Window, type WindowVar } from './metrics';
import { STATUS_COLOR, STATUS_NAME, shareText, type ShownStatus } from './places';

/** The map layers of Explore: every tract metric, and ADUs by 2031 (towns or counties). */
export type LayerId = MetricId | 'forecast';
export type AreaKind = 'tract' | 'town' | 'county';

export type GrowthId = 'jobs_after' | 'jobs_shift' | 'pop_after' | 'units_after' | 'rent_after';

export type Facts =
  | { layer: 'legal'; status: ShownStatus; title: string; peopleShare: number | null; bill: boolean }
  | { layer: 'group'; group: string | null; count: number; total: number }
  | { layer: 'pays'; pays: 'yes' | 'maybe' | 'no' | null; gap: number | null; yesShare: number | null }
  | { layer: 'room'; mid: number | null; lots: number | null; measured: boolean; outside: boolean; all: number[] }
  | { layer: 'window'; v: WindowVar; w: Window; value: number | null; all: number[] }
  | { layer: 'forecast'; kind: 'town' | 'county'; perK: number | null; adus: number | null; scenario: Forecast; all: number[] }
  | { layer: GrowthId; value: number | null; moe: boolean; all: number[] };

export interface Reading {
  /** The big value: "+2.1% a year", "Allowed with limits". */
  value: string;
  /** What the value is, in plain words. */
  unit: string;
  /** Its colour in the map legend. */
  color: string;
  /** Hatched on the map (outside the room model's range). */
  hatch?: boolean;
  /** One or two short lines: how it compares with Pennsylvania. */
  insight: string[];
  /** One sentence for a homeowner. */
  takeaway: string;
  /** The value is a model estimate. */
  estimate: boolean;
  /** A bill's result: not law. */
  notLaw: boolean;
}

// ------------------------------------------------------------------ numbers
/** Median of the numbers, or null when there are none. */
export function median(values: number[]): number | null {
  const v = values.filter(Number.isFinite).sort((a, b) => a - b);
  if (!v.length) return null;
  const m = Math.floor(v.length / 2);
  return v.length % 2 ? v[m] : (v[m - 1] + v[m]) / 2;
}

/** How many of the values are below and above v. */
export function rankOf(values: number[], v: number): { below: number; above: number; n: number } {
  let below = 0;
  let above = 0;
  let n = 0;
  for (const x of values) {
    if (!Number.isFinite(x)) continue;
    n++;
    if (x < v) below++;
    else if (x > v) above++;
  }
  return { below, above, n };
}

const PLURAL: Record<AreaKind, string> = { tract: 'tracts', town: 'towns', county: 'counties' };

/** "Higher than 72% of Pennsylvania tracts." or "Lower than 64% of Pennsylvania towns." null with too few values. */
export function rankLine(values: number[], v: number, kind: AreaKind): string | null {
  const r = rankOf(values, v);
  if (r.n < 2) return null;
  // Never "100%" while some area is level or on the other side, never "0%" while one is not.
  const share = (k: number) => (k === 0 ? 0 : Math.min(99, Math.max(1, Math.round((100 * k) / r.n))));
  const below = share(r.below);
  const above = share(r.above);
  if (below >= above && below > 0) return `Higher than ${below}% of Pennsylvania ${PLURAL[kind]}.`;
  if (above > 0) return `Lower than ${above}% of Pennsylvania ${PLURAL[kind]}.`;
  return `The same as most Pennsylvania ${PLURAL[kind]}.`;
}

/** Where v sits: the top third, the bottom third or the middle. */
export function band(values: number[], v: number): 'high' | 'mid' | 'low' | null {
  const r = rankOf(values, v);
  if (r.n < 2) return null;
  const at = (r.below + (r.n - r.below - r.above) / 2) / r.n;
  return at >= 2 / 3 ? 'high' : at <= 1 / 3 ? 'low' : 'mid';
}

/** The legend colour of a stepped scale. */
export function stepColor(steps: [number, string][], v: number | null): string {
  if (v === null || !Number.isFinite(v)) return NO_DATA;
  let c = steps[0][1];
  for (const [brk, col] of steps) if (v >= brk) c = col;
  return c;
}

const signed = (v: number, d = 1) => `${v > 0 ? '+' : v < 0 ? '-' : ''}${Math.abs(v).toFixed(d)}`;
const usd = (v: number) => `$${Math.round(v).toLocaleString('en-US')}`;
const count = (v: number) => Math.round(v).toLocaleString('en-US');

// ------------------------------------------------------------------ per layer
const GROWTH: Record<GrowthId, { unit: string; text: (v: number) => string }> = {
  jobs_after: { unit: 'Change in jobs, 2019 to 2024', text: (v) => `${signed(v)}% since 2019` },
  jobs_shift: { unit: 'Job growth after 2019 minus before, points a year', text: (v) => `${signed(v)} points a year` },
  pop_after: { unit: 'Population growth per year, ACS 2015-19 to 2020-24', text: (v) => `${signed(v)}% a year` },
  units_after: { unit: 'Growth in homes per year, ACS 2015-19 to 2020-24', text: (v) => `${signed(v)}% a year` },
  rent_after: { unit: 'Rent growth per year after inflation, ACS 2015-19 to 2020-24', text: (v) => `${signed(v)}% a year` },
};

/** The takeaway for a growth layer, by where the tract sits among Pennsylvania tracts. */
function growthTakeaway(layer: GrowthId, b: 'high' | 'mid' | 'low', v: number): string {
  switch (layer) {
    case 'rent_after':
      if (b === 'high') return 'Rent here is rising faster than in most of the state, so a backyard unit would likely rent well.';
      if (b === 'mid') return "Rent here is rising at about the state's pace, so a unit would likely rent near today's local rents.";
      return v < 0
        ? 'Rent here has fallen after inflation, so check local rents before counting on a unit to pay for itself.'
        : 'Rent here is rising slower than in most of the state, so check local rents before counting on a unit to pay for itself.';
    case 'pop_after':
      if (b === 'high') return 'More people are moving here than to most of the state, which tends to keep renters looking for small homes.';
      if (b === 'mid') return "The population here is growing at about the state's pace, so demand for a small rental is likely steady.";
      return v < 0 ? 'Fewer people live here than before, so a backyard unit may take longer to rent.' : 'The population here is growing slower than in most of the state, so a backyard unit may take longer to rent.';
    case 'units_after':
      if (b === 'high') return 'Homes are being added here faster than in most of the state, a sign of demand, though a new unit would face more competition.';
      if (b === 'mid') return "Homes are being added here at about the state's pace, so a new unit would join a steady market.";
      return 'Few homes are being added here, so a small new unit could help fill a gap if people want to live nearby.';
    case 'jobs_after':
      if (b === 'high') return 'Jobs here grew faster than in most of the state, a good sign for renters looking nearby.';
      if (b === 'mid') return "Jobs here changed at about the state's pace, so rental demand is likely steady.";
      return v < 0 ? 'Jobs here fell after 2019, so rental demand may be softer.' : 'Jobs here grew slower than in most of the state, so rental demand may be softer.';
    case 'jobs_shift':
      if (v <= 0) return 'Job growth here slowed after 2019, so rental demand may be softer than before.';
      return b === 'high' ? 'Job growth here picked up after 2019 more than in most of the state, which could bring more renters.' : 'Job growth here picked up a little after 2019, which could help rental demand.';
  }
}

const LEGAL_TAKEAWAY: Record<ShownStatus, string> = {
  by_right: 'The zoning code here allows a backyard unit with a permit and no hearing, so the main steps are the zoning and building permits.',
  limited: 'A backyard unit is possible here with limits or a hearing, so read the town rule before you plan.',
  not_addressed: 'The zoning code here does not mention ADUs, so ask the zoning office before you plan one. It may need a variance.',
  prohibited: 'The zoning code here bars an ADU today, so building one would need a variance or a change in the rules.',
  no_zoning: 'Zoning does not limit a backyard unit here, but building and sewage permits still apply.',
  unknown: 'The rule here has not been checked yet, so call the zoning office before you plan a unit.',
};

const PAYS_VALUE = { yes: 'Pays off', maybe: 'Close', no: 'Does not pay off' } as const;
const PAYS_COLOR = { yes: METRICS.pays.steps[2][1], maybe: METRICS.pays.steps[1][1], no: METRICS.pays.steps[0][1] } as const;

const NO_FIGURE = (kind: AreaKind, unit: string, estimate = false): Reading => ({
  value: 'No data',
  unit,
  color: NO_DATA,
  insight: [`There is no figure for this ${kind === 'county' ? 'county' : kind === 'town' ? 'town' : 'tract'} on this layer.`],
  takeaway: 'Look at the other layers, or test a lot here for an answer on one lot.',
  estimate,
  notLaw: false,
});

/** The value, how it compares and the takeaway, for one layer in one area. */
export function readLayer(f: Facts): Reading {
  switch (f.layer) {
    case 'legal': {
      const people = f.peopleShare != null ? `${shareText(f.peopleShare)} of Pennsylvanians live where the answer is ${STATUS_NAME[f.status].toLowerCase()}.` : null;
      return {
        value: f.title,
        unit: f.bill ? 'Under the state bill HB 2186' : "Where to build, under today's rules",
        color: STATUS_COLOR[f.status],
        insight: people ? [people] : [],
        takeaway: f.bill
          ? f.status === 'by_right'
            ? 'Under the state bill a backyard unit would be allowed by right here, but the bill is not law, so plan under the town rule today.'
            : `The state bill would not change this answer here. ${LEGAL_TAKEAWAY[f.status]}`
          : LEGAL_TAKEAWAY[f.status],
        estimate: false,
        notLaw: f.bill,
      };
    }
    case 'group': {
      if (!f.group) return NO_FIGURE('tract', 'Trend group');
      const color = GROUP_COLORS.find(([g]) => g === f.group)?.[1] ?? NO_DATA;
      const share = f.total ? Math.round((100 * f.count) / f.total) : null;
      const kind = f.group.split(':')[0].trim().toLowerCase();
      const takeaway =
        kind === 'growing'
          ? 'This tract is growing, so demand for a backyard unit is likely to hold up.'
          : kind === 'shrinking'
            ? 'This tract is shrinking, so a backyard unit may take longer to rent.'
            : kind === 'steady'
              ? 'This tract is steady, so expect demand for a unit close to what it is today.'
              : 'There is not enough data to group this tract, so check the Rent and Jobs layers.';
      return {
        value: f.group,
        unit: 'Trend group, tracts grouped by how they changed',
        color,
        insight: share != null ? [`${count(f.count)} of ${count(f.total)} Pennsylvania tracts (${share}%) are in this group.`] : [],
        takeaway,
        estimate: false,
        notLaw: false,
      };
    }
    case 'pays': {
      if (!f.pays || f.gap === null) return NO_FIGURE('tract', 'Does a backyard unit pay off, at your settings', true);
      const lines = [`Rent less upkeep is ${usd(Math.abs(f.gap))} a month ${f.gap >= 0 ? 'above' : 'below'} the build cost.`];
      if (f.yesShare != null) lines.push(`Pays off in ${Math.round(f.yesShare * 100)}% of Pennsylvania tracts at these settings.`);
      return {
        value: PAYS_VALUE[f.pays],
        unit: 'Does a backyard unit pay off, at your settings',
        color: PAYS_COLOR[f.pays],
        insight: lines,
        takeaway:
          f.pays === 'yes'
            ? 'At these settings, rent from a backyard unit would likely cover its build cost here.'
            : f.pays === 'maybe'
              ? 'Rent would come close to covering the build cost here, so a lower cost or rate could tip it.'
              : 'At these settings, rent would likely not cover the build cost here, so a smaller unit or a lower cost would help.',
        estimate: true,
        notLaw: false,
      };
    }
    case 'room': {
      if (f.mid === null || !f.lots) return NO_FIGURE('tract', 'Lots with room for a 600 sq ft unit', true);
      const share = f.mid / f.lots;
      const rank = rankLine(f.all, f.mid, 'tract');
      return {
        value: `${f.measured ? '' : 'About '}${count(f.mid)} lots`,
        unit: 'Lots with room for a 600 sq ft unit',
        color: stepColor(METRICS.room.steps, f.mid),
        hatch: f.outside,
        insight: [`${Math.round(share * 100)}% of the ${count(f.lots)} home lots here.`, ...(rank ? [rank] : [])],
        takeaway:
          share >= 0.5
            ? 'Most lots here likely have room for a 600 sq ft cottage, so yours may well fit. Check your own lot.'
            : share >= 0.2
              ? 'Some lots here have room for a 600 sq ft cottage, so yours may fit. Check your own lot.'
              : 'Few lots here have room for a 600 sq ft cottage, so a unit inside the house or over a garage may fit better.',
        estimate: !f.measured,
        notLaw: false,
      };
    }
    case 'window': {
      const what = `${WINDOW_VAR_LABEL[f.v]}, ACS ${WINDOW_LABEL[f.w]}${f.v === 'rent' ? ', 2024 dollars' : ''}`;
      if (f.value === null) return NO_FIGURE('tract', what);
      const l = windowLegend(f.v);
      const steps = [[-Infinity, l.colors[0]], ...WINDOW_STEPS[f.v].map((b, i) => [b, l.colors[i + 1]])] as [number, string][];
      const med = median(f.all);
      const b = band(f.all, f.value) ?? 'mid';
      const rank = rankLine(f.all, f.value, 'tract');
      const show = (v: number) => (f.v === 'rent' ? `${usd(v)} a month` : f.v === 'pop' ? `${count(v)} people` : `${count(v)} homes`);
      const takeaway =
        f.v === 'rent'
          ? b === 'high'
            ? 'Rent here is higher than in most of the state, so a backyard unit could bring in more each month.'
            : b === 'low'
              ? 'Rent here is lower than in most of the state, so a unit may take longer to pay off.'
              : "Rent here is near the middle for the state, so a unit's payoff depends mostly on its build cost."
          : b === 'high'
            ? `This tract has more ${f.v === 'pop' ? 'people' : 'homes'} than most, so there are more possible renters nearby.`
            : b === 'low'
              ? `This tract has fewer ${f.v === 'pop' ? 'people' : 'homes'} than most, so a unit may draw fewer renters nearby.`
              : `This tract is about average in ${f.v === 'pop' ? 'people' : 'homes'}, so look at the Rent layer for what a unit could earn.`;
      return {
        value: show(f.value),
        unit: what,
        color: stepColor(steps, f.value),
        insight: [...(rank ? [rank] : []), ...(med != null ? [`The median Pennsylvania tract: ${show(med)}.`] : [])],
        takeaway,
        estimate: false,
        notLaw: false,
      };
    }
    case 'forecast': {
      const bill = f.scenario !== 'current';
      const unit = `ADUs by 2031 per 1,000 people, ${FORECAST_LABEL[f.scenario]}, mid case`;
      if (f.perK === null) return { ...NO_FIGURE(f.kind, unit, true), notLaw: bill };
      const rank = rankLine(f.all, f.perK, f.kind);
      const b = band(f.all, f.perK) ?? 'mid';
      const tail = bill ? ' The bill is not law.' : '';
      return {
        value: `${f.perK.toFixed(f.perK < 10 ? 1 : 0)} per 1,000 people`,
        unit,
        color: stepColor(AREA_STEPS, f.perK),
        insight: [...(f.adus != null ? [`About ${f.adus.toLocaleString('en-US', { maximumFractionDigits: f.adus < 10 ? 1 : 0 })} new ADUs here by 2031.`] : []), ...(rank ? [rank] : [])],
        takeaway:
          (b === 'high'
            ? `More backyard units are expected here than in most of the state under ${bill ? 'the bill' : "today's rules"}, so a unit here would not be unusual.`
            : b === 'low'
              ? `Few backyard units are expected here under ${bill ? 'the bill' : "today's rules"}, so ask the town early about the steps.`
              : `Some backyard units are expected here under ${bill ? 'the bill' : "today's rules"}, about as many as in a typical ${f.kind}.`) + tail,
        estimate: true,
        notLaw: bill,
      };
    }
    default: {
      const g = GROWTH[f.layer];
      if (f.value === null) return NO_FIGURE('tract', g.unit);
      const m = METRICS[f.layer];
      const med = median(f.all);
      const rank = rankLine(f.all, f.value, 'tract');
      const b = band(f.all, f.value) ?? 'mid';
      return {
        value: g.text(f.value),
        unit: g.unit,
        color: f.moe ? MOE_GREY : stepColor(m.steps, f.value),
        hatch: f.moe,
        insight: [...(rank ? [rank] : []), ...(med != null ? [`The median Pennsylvania tract: ${g.text(med)}.`] : [])],
        takeaway: f.moe ? 'This change is inside the margin of error, so treat it as no clear change when you plan a unit.' : growthTakeaway(f.layer, b, f.value),
        estimate: false,
        notLaw: false,
      };
    }
  }
}
