// The unit box on the main map: one press-and-drag moves it, the site view follows on every frame, and the link
// gains at=. Deselecting: the same lot again, or Esc. Testable lots: select, deselect, zoom out, the squares stay.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const LOT = '42003-0086N00208000000';
const TRACT = '42003141300';
const has = existsSync(resolve(LOTS, 'pittsburgh/detail', `${TRACT}.json.gz`));
const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();
const title = (page: Page) => page.locator('aside[aria-label="Ask and report"] h2');
const main = (page: Page) => page.locator('[aria-label^="Map of Pennsylvania"]');

/** Find the unit box on the main map: the point near the open map's centre where the cursor turns to "grab". */
async function findBox(page: Page) {
  const canvas = main(page).locator('canvas').first();
  const l = (await page.locator('aside[aria-label="Search and map controls"]').boundingBox())!;
  const r = (await page.locator('aside[aria-label="Ask and report"]').boundingBox())!;
  const cx = (l.x + l.width + r.x) / 2;
  const cy = 450;
  for (let dy = -60; dy <= 60; dy += 4)
    for (let dx = -60; dx <= 60; dx += 4) {
      await page.mouse.move(cx + dx, cy + dy);
      if ((await canvas.evaluate((n) => (n as HTMLElement).style.cursor)) === 'grab') return { x: cx + dx, y: cy + dy, canvas };
    }
  return null;
}

test.describe('linked views and selection', () => {
  test.skip(!has, `no lot records at ${LOTS}`);

  test('one press-and-drag moves the box on the main map, the site view follows, the link gains at=', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toBeVisible();
    await page.waitForTimeout(3000); // the fly to the lot
    const box = await findBox(page);
    expect(box, 'unit box under the cursor').not.toBeNull();
    await page.mouse.down();
    const seen: (string | null)[] = [];
    for (let i = 1; i <= 5; i++) {
      await page.mouse.move(box!.x - i * 3, box!.y + i * 2);
      await page.waitForTimeout(60);
      seen.push(await main(page).getAttribute('data-unit-at'));
    }
    // During the drag: the main map moved the box several times, and the site view drew the same box.
    expect(new Set(seen.filter(Boolean)).size).toBeGreaterThan(1);
    const site = page.locator('section[aria-label="Aerial and site view"] .maplibregl-map').first();
    expect(await site.getAttribute('data-unit-at')).toBe(seen[seen.length - 1]);
    await page.mouse.up();
    await expect.poll(() => new URL(page.url()).hash).toContain('at=');
    await expect(title(page)).toHaveText('5459 Beacon St'); // the drag did not pick another lot
  });

  test('deselect: Esc, and a second click on the same lot', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(title(page)).toHaveText('Details');
    // A lot picked on the map, then the same lot again: the map centres the picked point in the open map, so the
    // second click goes to that centre.
    await page.locator('[data-place="pittsburgh"]').click();
    await page.waitForTimeout(4000);
    const l = (await page.locator('aside[aria-label="Search and map controls"]').boundingBox())!;
    const r = (await page.locator('aside[aria-label="Ask and report"]').boundingBox())!;
    const xs = [0.5, 0.35, 0.65].map((f) => l.x + l.width + 12 + (r.x - l.x - l.width - 24) * f);
    let opened = false;
    for (const y of [290, 330, 690, 250]) {
      for (const x of xs) {
        await page.mouse.click(x, y);
        opened = await verdict(page).isVisible({ timeout: 6000 }).catch(() => false);
        if (!opened) opened = await verdict(page).waitFor({ timeout: 6000 }).then(() => true, () => false);
        if (opened) break;
      }
      if (opened) break;
    }
    expect(opened, 'a lot opened').toBe(true);
    const picked = await title(page).innerText();
    await page.waitForTimeout(2500); // the fly to the lot ends with the clicked point in the middle
    const r2 = (await page.locator('aside[aria-label="Ask and report"]').boundingBox())!;
    const cx = (l.x + l.width + r2.x) / 2;
    // The unit box may sit at the centre: a press there is a drag, not a pick. Step off it inside the same lot.
    const canvas = main(page).locator('canvas').first();
    const cy = 472; // middle of the padded map (layout.ts mapPadding: top 84, bottom 40 at 900 px)
    let spot: [number, number] = [cx, cy];
    for (const dy of [0, 6, -6, 12, -12, 18, -18]) {
      await page.mouse.move(cx, cy + dy);
      if ((await canvas.evaluate((n) => (n as HTMLElement).style.cursor)) === 'pointer') {
        spot = [cx, cy + dy];
        break;
      }
    }
    expect(picked).not.toBe('Details');
    await page.mouse.click(spot[0], spot[1]);
    await expect(title(page)).toHaveText('Details');
  });

  test('testable lots: select, deselect and zoom out, the squares are still there', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const sw = page.getByRole('switch', { name: 'Testable Lots' });
    await sw.click();
    await expect(main(page)).toHaveAttribute('data-testable', /parcels-pgh-overview/);
    await page.evaluate(([l, t]) => (window.location.hash = `#/?view=test&lot=${l}&tract=${t}`), [LOT, TRACT]);
    await expect(verdict(page)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(title(page)).toHaveText('Details');
    for (let i = 0; i < 4; i++) await page.getByRole('button', { name: 'Zoom out', exact: true }).click();
    await expect(main(page)).toHaveAttribute('data-testable', /parcels-pgh-overview/);
    await expect(page.getByRole('group', { name: 'Testable lots legend' })).toContainText('Squares: most common answer');
  });
});
