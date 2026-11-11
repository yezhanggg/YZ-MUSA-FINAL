// Every parcel in the two pilot counties, from vector tiles (public/data/parcels.pmtiles, layer `parcels`, z14-15).
// Properties: id (lot_id), s (1 = single-family lot checked by MUSA 6950), t (detached / row / twin / other),
// f, k (fits, fits keeping trees at 600 sq ft, 0/1), mf, mk (largest footprint in sq ft, after the model rerun),
// r (Philadelphia rule: c = conversion only, v = variance).
import type { ExpressionSpecification } from 'maplibre-gl';
import { footprint, isBaseFootprint } from '../lib/adu';
import type { Adu } from '../lib/numbers';
import type { LotRule } from '../lib/rules';

export const PARCEL_LAYER = 'parcels';
export const PARCEL_URL = '/data/parcels.pmtiles';

export type LotStatus = 'yes' | 'trees' | 'no' | 'unknown' | 'unchecked';
export const LOT_COLORS: Record<LotStatus, string> = { yes: '#16a34a', trees: '#f59e0b', no: '#e11d48', unknown: '#94a3b8', unchecked: '#cbd5e1' };
export const LOT_LABEL: Record<LotStatus, string> = { yes: 'Fits', trees: 'Fits if trees cut', no: 'No room', unknown: 'Not ready for this size', unchecked: 'Not checked' };

export interface ParcelProps {
  id: string;
  s?: number;
  t?: 'detached' | 'row' | 'twin' | 'other' | string;
  f?: number;
  k?: number;
  mf?: number;
  mk?: number;
  r?: 'c' | 'v' | string;
}

const TYPE_LABEL: Record<string, string> = { row: 'Rowhouse', twin: 'Twin', detached: 'Detached house', other: 'Other parcel' };
export const parcelType = (p: ParcelProps) => TYPE_LABEL[p.t ?? 'other'] ?? 'Other parcel';

/** Result of one parcel for the ADU being tested (same rule as lotFit in lib/adu.ts). */
export function parcelStatus(p: ParcelProps, a: Adu): LotStatus {
  if (p.s !== 1) return 'unchecked';
  const fp = footprint(a);
  if (typeof p.mf === 'number') return p.mf >= fp ? ((p.mk ?? 0) >= fp ? 'yes' : 'trees') : 'no';
  if (!isBaseFootprint(a)) return 'unknown';
  return p.f === 1 ? (p.k === 1 ? 'yes' : 'trees') : 'no';
}

/** Hover text: the result, or what kind of parcel was not checked. */
export const parcelTip = (p: ParcelProps, a: Adu) => {
  const st = parcelStatus(p, a);
  return st === 'unchecked' ? `${parcelType(p)} · not checked` : LOT_LABEL[st];
};

/** The Philadelphia rule carried on the tile, for parcels without a lot record. */
export const parcelRule = (p: ParcelProps): LotRule | null => (p.r === 'v' ? { rule_lot: 'variance' } : p.r === 'c' ? { rule_lot: 'conversion_only' } : null);

/** The status as a MapLibre expression, rebuilt when the footprint changes. */
export function statusExpr(a: Adu): ExpressionSpecification {
  const fp = footprint(a);
  const base = isBaseFootprint(a) ? ['case', ['==', ['get', 'f'], 1], ['case', ['==', ['get', 'k'], 1], 'yes', 'trees'], 'no'] : 'unknown';
  return ['case', ['!=', ['get', 's'], 1], 'unchecked', ['has', 'mf'], ['case', ['>=', ['get', 'mf'], fp], ['case', ['>=', ['coalesce', ['get', 'mk'], 0], fp], 'yes', 'trees'], 'no'], base] as unknown as ExpressionSpecification;
}

const byStatus = (a: Adu, v: Record<LotStatus, unknown>) => ['match', statusExpr(a), 'yes', v.yes, 'trees', v.trees, 'no', v.no, 'unchecked', v.unchecked, v.unknown] as unknown as ExpressionSpecification;
const hovered = (on: unknown, off: unknown) => ['case', ['boolean', ['feature-state', 'hover'], false], on, off];

export const parcelFillColor = (a: Adu) => byStatus(a, { ...LOT_COLORS, unchecked: '#f1f5f9' });
export const parcelFillOpacity = (a: Adu) => byStatus(a, { yes: hovered(0.6, 0.38), trees: hovered(0.6, 0.38), no: hovered(0.6, 0.38), unknown: hovered(0.5, 0.3), unchecked: hovered(0.55, 0.35) });
export const parcelLineColor = (a: Adu) => byStatus(a, { ...LOT_COLORS, unchecked: '#94a3b8' });

/** Layer filter for the "Show" toggles. Filters only, no data reload. */
export function parcelFilter(a: Adu, sfOnly: boolean, hideNoRoom: boolean): ExpressionSpecification | null {
  const parts: unknown[] = [];
  if (sfOnly) parts.push(['==', ['get', 's'], 1]);
  if (hideNoRoom) parts.push(['!=', statusExpr(a), 'no']);
  return parts.length ? (['all', ...parts] as unknown as ExpressionSpecification) : null;
}

/** Sample neighbourhoods for the "jump to" chips (dense single-family lots). */
export const PILOTS = [
  { name: 'Philadelphia', center: [-75.0126, 40.0618] as [number, number] },
  { name: 'Cumberland County', center: [-76.9311, 40.2442] as [number, number] },
];
