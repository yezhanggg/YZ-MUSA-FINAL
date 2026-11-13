// The assistant's list of cities with lot records comes from the loader's registry, the same one the app shows.
import { describe, expect, it } from 'vitest';
import { PLACES, PLACE_TITLE } from '../tool/test/placeData';
import { LOT_PLACES, lotPlaceOfTown, lotPlaceTitle, lotPlacesText } from './lotPlaces';
import { FIND_LOT_TOOL, findLotResult } from './areaTools';
import { PLACE_ANSWER_TOOL } from './placeAnswer';
import { SYSTEM_PROMPT } from '../../../agent/schema';

describe('places with lot records', () => {
  it('match the app registry (placeData), names included', () => {
    expect([...LOT_PLACES].sort()).toEqual([...PLACES].sort());
    for (const p of LOT_PLACES) expect(lotPlaceTitle(p)).toBe(PLACE_TITLE[p]);
  });
  it('every city is named wherever the assistant says which cities have lot tools', () => {
    const text = [FIND_LOT_TOOL.description, PLACE_ANSWER_TOOL.description, SYSTEM_PROMPT, String(findLotResult('1 Nowhere St', { entries: [], scope: 'x' }).message)].join('\n');
    for (const p of LOT_PLACES) expect(text.split(PLACE_TITLE[p]).length - 1, p).toBeGreaterThanOrEqual(4);
    expect(lotPlacesText()).toMatch(/, .* and /);
  });
  it('a town has lot records only when it is the registry city of its county', () => {
    expect(lotPlaceOfTown('4207702000', 'Allentown city')).toBe('allentown');
    expect(lotPlaceOfTown('4207784528', 'Whitehall township')).toBeNull();
    expect(lotPlaceOfTown('4210160000', 'Philadelphia city')).toBe('philadelphia');
    expect(lotPlaceOfTown('4200361000', 'Pittsburgh city')).toBe('pittsburgh');
    expect(lotPlaceOfTown(null, 'Allentown city')).toBeNull();
  });
});
