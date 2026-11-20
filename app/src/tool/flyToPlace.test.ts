import { describe, expect, it } from 'vitest';
import { isState, lotPlaceOf } from './flyToPlace';

describe('ParcelIQ moves the map to a place', () => {
  it('knows the lot places by their everyday names', () => {
    expect(lotPlaceOf('Philly')).toBe('philadelphia');
    expect(lotPlaceOf('Philadelphia, PA')).toBe('philadelphia');
    expect(lotPlaceOf('Pitts')).toBe('pittsburgh');
    expect(lotPlaceOf('Pittsburgh')).toBe('pittsburgh');
    expect(lotPlaceOf('Chester County')).toBe('chester_county');
    expect(lotPlaceOf('Narberth')).toBe('montgomery_county');
    expect(lotPlaceOf('State College')).toBe('centre_county');
    expect(lotPlaceOf('Erie')).toBeNull();
  });
  it('the whole state', () => {
    expect(isState('Pennsylvania')).toBe(true);
    expect(isState('PA')).toBe(true);
    expect(isState('Pittsburgh')).toBe(false);
  });
});
