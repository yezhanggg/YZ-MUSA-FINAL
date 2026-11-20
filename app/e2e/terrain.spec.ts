// Ground terrain in the 3D views (tool/terrain.ts): the site view and the main map stand on the place's terrain
// tiles in 3D, are flat in Top / 2D, the unit box still drags on terrain, and a missing terrain file leaves the
// views working on flat ground. Needs the lot records with terrain.pmtiles (LOT_DATA_DIR, e.g.
// ~/Library/Caches/yz-musa/lots-local); skips when they are not there.
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { lotDataDir } from '../devData';
import { expect, test, type Page } from '@playwright/test';

const LOTS = lotDataDir();
const STEEP = { lot: '42003-0116K00029000000', tract: '42003260700' }; // 405 Venture St, steep site
const BEACON = { lot: '42003-0086N00208000000', tract: '42003141300' }; // 5459 Beacon St, a detached unit fits
const has = existsSync(resolve(LOTS, 'pittsburgh/tiles/terrain.pmtiles')) && existsSync(resolve(LOTS, 'pittsburgh/detail', `${STEEP.tract}.json.gz`));

const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();
const siteSection = (page: Page) => page.locator('section[aria-label="Aerial and site view"]').first();
const siteMap = (page: Page) => siteSection(page).locator('.maplibregl-map').first();
const main = (page: Page) => page.locator('[aria-label^="Map of Pennsylvania"]');

async function open(page: Page, l: { lot: string; tract: string }) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/#/?view=test&ut=detached_new&lot=${l.lot}&tract=${l.tract}`);
  await expect(verdict(page)).toBeVisible();
  await siteSection(page).scrollIntoViewIfNeeded();
}

/** Scan the site view for the point where the cursor turns to "grab" (the unit box). */
async function findBox(page: Page) {
  const canvas = siteMap(page).locator('canvas').first();
  const bb = (await canvas.boundingBox())!;
  for (let y = bb.y + 24; y < bb.y + bb.height - 24; y += 8)
    for (let x = bb.x + 24; x < bb.x + bb.width - 64; x += 8) {
      await page.mouse.move(x, y);
      if ((await canvas.evaluate((n) => (n as HTMLElement).style.cursor)) === 'grab') return { x, y };
    }
  return null;
}

test.describe('ground terrain in 3D', () => {
  test.skip(!has, `no lot records with terrain at ${LOTS}`);

  test('site view: terrain in 3D on a Pittsburgh lot, none in Top; main map: terrain in 3D, none in 2D', async ({ page }) => {
    await open(page, STEEP);
    await expect(siteMap(page)).toHaveAttribute('data-terrain', 'pittsburgh');
    // The steep lot turns to look across its slope, a little lower than the usual 50 degrees.
    await expect.poll(() => siteSection(page).getAttribute('data-pitch'), { timeout: 30_000 }).toBe('60.0');
    await siteSection(page).getByRole('radio', { name: 'Top' }).click();
    await expect(siteMap(page)).not.toHaveAttribute('data-terrain', /./);
    await siteSection(page).getByRole('radio', { name: '3D' }).click();
    await expect(siteMap(page)).toHaveAttribute('data-terrain', 'pittsburgh');

    await expect(main(page)).not.toHaveAttribute('data-terrain', /./);
    const mapView = page.getByRole('radiogroup', { name: 'Map view' });
    await mapView.getByRole('radio', { name: '3D' }).click();
    await expect(main(page)).toHaveAttribute('data-terrain', 'pittsburgh');
    await mapView.getByRole('radio', { name: '2D' }).click();
    await expect(main(page)).not.toHaveAttribute('data-terrain', /./);
  });

  test('the unit box still drags in the 3D site view with terrain on', async ({ page }) => {
    await open(page, BEACON);
    await expect(siteMap(page)).toHaveAttribute('data-terrain', 'pittsburgh');
    await page.waitForTimeout(4000); // ground tiles, and the turn across the slope
    const box = await findBox(page);
    expect(box, 'unit box under the cursor').not.toBeNull();
    await page.mouse.down();
    const seen: (string | null)[] = [];
    for (let i = 1; i <= 6; i++) {
      await page.mouse.move(box!.x - i * 4, box!.y + i * 2);
      await page.waitForTimeout(60);
      seen.push(await siteMap(page).getAttribute('data-unit-at'));
    }
    expect(new Set(seen.filter(Boolean)).size).toBeGreaterThan(2);
    // The main map draws the same box while it is dragged.
    expect(await main(page).getAttribute('data-unit-at')).toBe(seen[seen.length - 1]);
    await page.mouse.up();
    await expect.poll(() => new URL(page.url()).hash).toContain('at=');
    await expect(siteMap(page)).toHaveAttribute('data-terrain', 'pittsburgh');
  });

  test('a missing terrain file (404) leaves flat ground and a working view', async ({ page }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.route('**/terrain.pmtiles', (r) => r.fulfill({ status: 404, body: 'not found' }));
    await open(page, BEACON);
    await expect(siteMap(page).locator('canvas')).toBeVisible();
    await page.waitForTimeout(3000);
    await expect(siteMap(page)).not.toHaveAttribute('data-terrain', /./);
    await page.getByRole('radiogroup', { name: 'Map view' }).getByRole('radio', { name: '3D' }).click();
    await page.waitForTimeout(2000);
    await expect(main(page)).not.toHaveAttribute('data-terrain', /./);
    // The box still drags on flat ground.
    const box = await findBox(page);
    expect(box, 'unit box under the cursor').not.toBeNull();
    await page.mouse.down();
    for (let i = 1; i <= 4; i++) await page.mouse.move(box!.x - i * 4, box!.y + i * 2);
    await page.mouse.up();
    await expect.poll(() => new URL(page.url()).hash).toContain('at=');
    expect(errors).toEqual([]);
  });
});
