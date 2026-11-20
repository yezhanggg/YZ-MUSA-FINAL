// Where the local preview and the browser tests read the lot records, so they run with or without the data drive.
// First LOT_DATA_DIR if set, then the data drive (~/musa-drive/lots), then the laptop copy of the public data
// repository (git clone https://github.com/yezhanggg/backyard-homes-lots ~/Developer/backyard-homes-lots), which is
// the same files the live site reads. Node only (vite.config.ts, playwright.config.ts, app/e2e).
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';

const home = (p: string) => resolve(p.replace(/^~(?=$|\/)/, homedir()));

export const DRIVE_LOTS = home('~/musa-drive/lots');
export const LAPTOP_LOTS = home('~/Developer/backyard-homes-lots/lots');

/** The lot records folder to use. */
export function lotDataDir(): string {
  if (process.env.LOT_DATA_DIR) return home(process.env.LOT_DATA_DIR);
  if (existsSync(resolve(DRIVE_LOTS, 'pittsburgh'))) return DRIVE_LOTS;
  if (existsSync(resolve(LAPTOP_LOTS, 'pittsburgh'))) return LAPTOP_LOTS;
  return DRIVE_LOTS;
}

/** Where the browser tests save screenshots: SHOTS_DIR, else the drive's scratch folder, else the laptop cache. */
export function shotsDir(): string {
  if (process.env.SHOTS_DIR) return home(process.env.SHOTS_DIR);
  return existsSync(home('~/musa-drive/ops')) ? home('~/musa-drive/ops/scratch/app-shots') : home('~/Library/Caches/yz-musa/app-shots');
}
