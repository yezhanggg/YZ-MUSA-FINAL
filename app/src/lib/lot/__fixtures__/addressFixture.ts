// The small address index the Python builder makes for tests/test_address_index.py FIXTURE, served as if published.
import { existsSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { addressIndexSource } from '../addressIndex';
import type { Fetcher } from '../load';

const FIX = resolve(import.meta.dirname, 'addresses');
export const FIXTURE_BASE = 'https://lots.test/';

/** Serves the fixture index (plain JSON) for the .json.gz URLs the reader asks for, and logs each URL. */
export function addressFixtureFetch(log: string[] = []): Fetcher {
  return async (url) => {
    const path = resolve(FIX, url.slice(FIXTURE_BASE.length).replace('/addresses/', '/').replace(/\.gz$/, ''));
    log.push(url);
    return path.startsWith(FIX) && existsSync(path) ? new Response(readFileSync(path)) : new Response('missing', { status: 404 });
  };
}

/** An address index source on the fixture (pittsburgh and chester_county; the other places answer 404). */
export const fixtureAddressIndex = (log?: string[]) => addressIndexSource({ baseUrl: FIXTURE_BASE, fetch: addressFixtureFetch(log) });
