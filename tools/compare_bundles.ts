// Usage: node_modules/.bin/jiti tools/compare_bundles.ts ~/musa-drive/host ~/musa-drive/host_pack1 [every Nth city tract]
// Equivalence check: every tract of the baseline bundle and of the packed bundle, read through the app loader
// (app/src/lib/lot/load.ts) with a file-system fetch, must give the same records (JSON text, key order included).
import { readFileSync, readdirSync, existsSync } from 'node:fs';
import { createHash } from 'node:crypto';
import { loadTractLots, lotTractOf, TractCache, type Fetcher } from '../app/src/lib/lot/load.ts';

const [A, B, every = '1'] = process.argv.slice(2);
const fsFetch = (root: string): Fetcher => async (url) => {
  const p = root + url.slice('https://x/'.length);
  if (!existsSync(p)) return new Response('missing', { status: 404 });
  return new Response(readFileSync(p), { status: 200 });
};
const step = Number(every);
let tracts = 0, lots = 0, bad = 0, idx = 0;
const t0 = Date.now();
for (const place of readdirSync(`${A}/lots`).sort()) {
  const names = readdirSync(`${A}/lots/${place}/detail`).filter((f) => /^\d{11}\.json\.gz$/.test(f)).sort();
  const ca = new TractCache(), cb = new TractCache();
  let ms = 0;
  for (let i = 0; i < names.length; i += place === 'philadelphia' || place === 'pittsburgh' ? step : 1) {
    const g = names[i].slice(0, 11);
    const a = await loadTractLots(g, { baseUrl: 'https://x/', fetch: fsFetch(`${A}/lots/`), cache: ca });
    const s = performance.now();
    const b = await loadTractLots(g, { baseUrl: 'https://x/', fetch: fsFetch(`${B}/lots/`), cache: cb });
    ms += performance.now() - s;
    const ha = createHash('sha256').update(JSON.stringify(a.lots)).digest('hex');
    const hb = createHash('sha256').update(JSON.stringify(b.lots)).digest('hex');
    tracts++; lots += a.lots.length;
    if (ha !== hb || a.dataVersion !== b.dataVersion) { bad++; console.log(`DIFF ${place} ${g}`); }
    ca.clear?.(); cb.clear?.();
    // lot id -> tract through each bundle's index (plain json vs the gzip copy the manifest names)
    const id = a.lots[idx++ % a.lots.length]?.lot.id;
    if (id) {
      const ta = await lotTractOf(id, { baseUrl: `https://x/`, fetch: fsFetch(`${A}/lots/`), cache: new TractCache() });
      const tb = await lotTractOf(id, { baseUrl: `https://y/`, fetch: async (u) => fsFetch(`${B}/lots/`)(u.replace('https://y/', 'https://x/')), cache: new TractCache() });
      if (ta !== g || tb !== g) { bad++; console.log(`INDEX ${place} ${id} ${ta} ${tb}`); }
    }
  }
  console.log(`${place}: ${tracts} tracts so far, ${lots} lots, packed read ${ms.toFixed(0)} ms total`);
}
console.log(`checked ${tracts} tracts, ${lots} lots, ${bad} differences, ${((Date.now() - t0) / 1000).toFixed(0)} s`);
process.exit(bad ? 1 : 0);
