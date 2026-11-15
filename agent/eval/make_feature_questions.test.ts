// The pure parts of make_feature_questions.ts: the typo it makes, and the patterns its questions forbid.
import { describe, expect, it } from 'vitest';
import { NAMES_A_LOT, SLOPE_AS_BAR, misspell, streetWords } from './make_feature_questions';

describe('misspell', () => {
  it('drops one letter of the first doubled pair in the street name, never the house number', () => {
    expect(misspell('903 WOODS RUN AVE')).toBe('903 Wods Run Ave');
    expect(misspell('1100 Spruce St')).toBeNull();
    expect(misspell('5704 POCUSSET ST')).toBe('5704 Pocuset St');
  });
  it('streetWords drops the street type', () => {
    expect(streetWords('woods run ave')).toBe('woods run');
    expect(streetWords('pocusset st')).toBe('pocusset');
  });
});

describe('forbidden patterns', () => {
  const bar = (s: string) => new RegExp(SLOPE_AS_BAR.pattern, 'i').test(s);
  it('a slope line said as a bar is caught', () => {
    expect(bar('The steep slope rules it out.')).toBe(true);
    expect(bar('The landslide overlay prohibits new buildings here.')).toBe(true);
    expect(bar("You can't build here because of the slope.")).toBe(true);
  });
  it('the same lines said as questions for the city pass', () => {
    expect(bar('The steep slope does not rule it out, but ask the Zoning Administrator whether the spot is in the Steep Slope Overlay (906.08).')).toBe(false);
    expect(bar('The landslide overlay never bars the unit: it asks for a field investigation (906.04.B).')).toBe(false);
    expect(bar('City grading rules apply (915.02): cut or filled slopes may not be steeper than 25%.')).toBe(false);
  });
  it('a linked lot is caught, a street name is not', () => {
    const re = new RegExp(NAMES_A_LOT.pattern, 'i');
    expect(re.test('See [lot 42003-0076B00075000000](lot:42003-0076B00075000000).')).toBe(true);
    expect(re.test('Did you mean Woods Run Ave in Pittsburgh?')).toBe(false);
  });
});
