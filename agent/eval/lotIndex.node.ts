// Stand-in for the `virtual:lot-index` module that vite.config.ts makes, for scripts run outside Vite (cli.mjs).
import { existsSync, readdirSync } from 'node:fs';
import { resolve } from 'node:path';

const DATA = resolve(import.meta.dirname, '../../app/public/data');
const list = (dir: string, ext: string) => {
  const d = resolve(DATA, dir);
  return existsSync(d) ? readdirSync(d).filter((f) => f.endsWith(ext)).map((f) => f.slice(0, -ext.length)) : [];
};

export const LOT_TRACTS: string[] = list('lots', '.json');
export const HAS_FIT_CURVES: boolean = existsSync(resolve(DATA, 'fit_curves.json'));
export const HAS_LOT_DETAIL: boolean = existsSync(resolve(DATA, 'lot_detail.pmtiles'));
