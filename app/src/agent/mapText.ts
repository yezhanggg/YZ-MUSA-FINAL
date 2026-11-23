// set_map without the map: the new ADU or unit for an input, and the line ParcelIQ gets back. Pure, so the browser
// (browserProvider.ts) and the Node eval (agent/nodeProvider.ts) change the same things and say the same words.
import { BED_SIZE, SIZE_MAX, SIZE_MIN, type Adu, type Bed, type Stories } from '../lib/numbers';
import { TYPE_LABEL } from '../lib/lot/words';
import type { UnitDraft } from '../tool/testState';
import type { SetMapInput } from './executors';

/** set_adu: the ADU after the input (size rounded to 50 sq ft within the slider, bedrooms set the size when no size). */
export function aduFromInput(cur: Adu, input: SetMapInput): Adu {
  const bed = [0, 1, 2, 3].includes(Number(input.bedrooms)) ? (Number(input.bedrooms) as Bed) : cur.bed;
  const size = typeof input.size_sqft === 'number' ? Math.min(SIZE_MAX, Math.max(SIZE_MIN, Math.round(input.size_sqft / 50) * 50)) : input.bedrooms !== undefined ? BED_SIZE[bed] : cur.size;
  const stories = (Number(input.stories) === 2 ? 2 : input.stories !== undefined ? 1 : cur.stories) as Stories;
  return { bed, size, stories };
}

export const aduText = (a: Adu) => `ADU set to ${a.bed === 0 ? 'studio' : `${a.bed} BR`}, ${a.size} sq ft, ${a.stories} ${a.stories === 2 ? 'stories' : 'story'}`;

export const ruleText = (rule: unknown) => `Rules set to ${rule === 'hb2186' ? 'HB 2186' : 'today'}`;

export const SET_UNIT_NO_LOT = 'set_unit works in Test Site, with a lot open. Nothing was changed.';

/** set_unit: the unit now on screen. */
export function unitText(u: UnitDraft): string {
  const floor = Math.round(u.width * u.depth * u.stories);
  return `The unit on screen is now a ${u.stories === 2 ? 'two-story ' : ''}${TYPE_LABEL[u.type]}, ${u.width} x ${u.depth} ft (${floor.toLocaleString('en-US')} sq ft of floor)${u.height !== null ? `, ${u.height} ft tall` : ''}. The tool looks for the best spot for it.`;
}
