// Map colour for each metric: [break, colour] pairs, lowest first. Jobs and Shift read tract properties.
// Room and Pays off follow the ADU controls, so they read feature-state that MapCanvas recomputes live.
import type { ExpressionSpecification } from 'maplibre-gl';

export type MetricId = 'jobs_after' | 'jobs_shift' | 'room' | 'pays';

export const NO_DATA = '#e7e5e4';

export const METRICS: Record<MetricId, { short: string; label: string; steps: [number, string][]; names: string[] }> = {
  jobs_after: {
    short: 'Jobs',
    label: 'Job change, 2019 to 2024',
    steps: [[-Infinity, '#be123c'], [-5, '#fda4af'], [0, '#a7f3d0'], [5, '#059669']],
    names: ['Lost over 5%', 'Lost 0 to 5%', 'Grew 0 to 5%', 'Grew over 5%'],
  },
  jobs_shift: {
    short: 'Shift',
    label: 'Job growth after 2019 minus before (pts per year)',
    steps: [[-Infinity, '#be123c'], [-1, '#fda4af'], [0, '#a7f3d0'], [1, '#059669']],
    names: ['Slowed a lot', 'Slowed a little', 'Sped up a little', 'Sped up a lot'],
  },
  room: {
    short: 'Room',
    label: 'Lots with room for your ADU (MUSA 6950)',
    steps: [[-Infinity, '#f5f3ff'], [50, '#c4b5fd'], [200, '#8b5cf6'], [500, '#5b21b6']],
    names: ['Under 50', '50 to 200', '200 to 500', 'Over 500'],
  },
  pays: {
    short: 'Pays',
    label: 'Does your ADU pay off? (MUSA 5500)',
    steps: [[0, '#fda4af'], [1, '#fcd34d'], [2, '#10b981']],
    names: ['No', 'Close', 'Yes'],
  },
};

/** Pays off as a number for the map: no 0, maybe 1, yes 2. */
export const PAYS_CODE = { no: 0, maybe: 1, yes: 2 } as const;

export function colorExpr(metric: MetricId): ExpressionSpecification {
  const m = METRICS[metric];
  // live metrics: feature-state, -1 when there is no answer for this ADU
  const live = metric === 'room' || metric === 'pays';
  const value = live ? ['coalesce', ['feature-state', metric], -1] : ['to-number', ['get', metric], -9999];
  const expr: unknown[] = ['step', value, live ? NO_DATA : m.steps[0][1]];
  if (live) expr.push(0, m.steps[0][1]);
  m.steps.slice(1).forEach(([brk, col]) => expr.push(brk, col));
  return (live ? expr : ['case', ['==', ['get', metric], null], NO_DATA, expr]) as unknown as ExpressionSpecification;
}
