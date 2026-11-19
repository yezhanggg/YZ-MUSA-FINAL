import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { BOUNDARY_KEY, DEFAULT_BOUNDARIES, parseBoundaries } from './boundaries';

describe('boundary switches', () => {
  it('start with only the counties on', () => {
    expect(DEFAULT_BOUNDARIES).toEqual({ county: true, tract: false, zip: false });
    expect(parseBoundaries(null)).toEqual(DEFAULT_BOUNDARIES);
  });

  it('read a saved choice and fall back on anything broken', () => {
    expect(parseBoundaries('{"county":false,"zip":true}')).toEqual({ county: false, tract: false, zip: true });
    expect(parseBoundaries('{"tract":"yes","other":true}')).toEqual(DEFAULT_BOUNDARIES);
    expect(parseBoundaries('not json')).toEqual(DEFAULT_BOUNDARIES);
    expect(parseBoundaries('null')).toEqual(DEFAULT_BOUNDARIES);
  });
});

describe('the boundary store', () => {
  let saved: Map<string, string>;
  beforeEach(() => {
    vi.resetModules();
    saved = new Map();
    vi.stubGlobal('window', { localStorage: { getItem: (k: string) => saved.get(k) ?? null, setItem: (k: string, v: string) => void saved.set(k, v) } });
  });
  afterEach(() => vi.unstubAllGlobals());

  it('toggles a switch and remembers the choice', async () => {
    const { useBoundaries } = await import('./boundaries');
    expect(useBoundaries.getState().on).toEqual(DEFAULT_BOUNDARIES);
    useBoundaries.getState().toggle('tract');
    useBoundaries.getState().setOn('county', false);
    expect(useBoundaries.getState().on).toEqual({ county: false, tract: true, zip: false });
    expect(JSON.parse(saved.get(BOUNDARY_KEY)!)).toEqual({ county: false, tract: true, zip: false });
  });

  it('starts from the saved choice on the next visit', async () => {
    saved.set(BOUNDARY_KEY, '{"county":true,"tract":false,"zip":true}');
    const { useBoundaries } = await import('./boundaries');
    expect(useBoundaries.getState().on).toEqual({ county: true, tract: false, zip: true });
  });

  it('works when storage is blocked', async () => {
    vi.stubGlobal('window', { localStorage: { getItem: () => { throw new Error('blocked'); }, setItem: () => { throw new Error('blocked'); } } });
    const { useBoundaries } = await import('./boundaries');
    expect(useBoundaries.getState().on).toEqual(DEFAULT_BOUNDARIES);
    useBoundaries.getState().toggle('zip');
    expect(useBoundaries.getState().on.zip).toBe(true);
  });
});
