// "Boundaries": county, census tract and ZIP code outlines on the main map. County is on at the start, Tract and ZIP
// Code add and remove their layers, the choice is kept on reload, and a lot can still be clicked with all three on.
// The map element lists the boundary layers it shows in data-boundaries.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { openCard } from './cards';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const hasLots = existsSync(resolve(LOTS, 'pittsburgh/manifest.json'));
const main = (page: Page) => page.locator('[aria-label^="Map of Pennsylvania"]');
const card = (page: Page) => page.locator('section[aria-label="Boundaries"]');
const sw = (page: Page, name: string) => card(page).getByRole('switch', { name });
const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();

test.describe('boundaries', () => {
  test('County is on at the start, Tract and ZIP Code add and remove their layers', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    await expect(card(page)).toBeVisible();
    // First under Zoning Regulation and open; Testable Lots and ADU Design follow, folded.
    const order = await page.locator('aside[aria-label="Search and map controls"] section[aria-label]').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
    expect(order.filter((l) => ['Boundaries', 'Testable Lots', 'ADU Design'].includes(l ?? ''))).toEqual(['Boundaries', 'Testable Lots', 'ADU Design']);
    await expect(card(page).getByRole('button', { name: 'Boundaries' })).toHaveAttribute('aria-expanded', 'true');
    for (const t of ['Testable Lots', 'ADU Design']) await expect(page.locator(`section[aria-label="${t}"]`).getByRole('button', { name: t, exact: true })).toHaveAttribute('aria-expanded', 'false');
    await expect(sw(page, 'County')).toHaveAttribute('aria-checked', 'true');
    await expect(sw(page, 'Census Tract')).toHaveAttribute('aria-checked', 'false');
    await expect(sw(page, 'ZIP Code')).toHaveAttribute('aria-checked', 'false');
    await expect(card(page)).toContainText('ZIP Code Tabulation Areas');
    await expect(main(page)).toHaveAttribute('data-boundaries', 'bnd-county-line bnd-county-label');

    await sw(page, 'Census Tract').click();
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-tract-line/);
    await sw(page, 'ZIP Code').click();
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-zip-line/);
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-county-line/);
    // The ZIP code file is there and holds Pennsylvania's ZCTAs.
    const n = await page.evaluate(async () => ((await (await fetch('data/zcta.geojson')).json()) as { features: unknown[] }).features.length);
    expect(n).toBeGreaterThan(1700);

    // Kept on reload.
    await page.reload();
    await expect(sw(page, 'ZIP Code')).toHaveAttribute('aria-checked', 'true');
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-zip-line/);

    await sw(page, 'Census Tract').click();
    await sw(page, 'ZIP Code').click();
    await sw(page, 'County').click();
    await expect(main(page)).toHaveAttribute('data-boundaries', '');
  });

  test('the card folds, and Explore has the same switches', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    await card(page).getByRole('button', { name: 'Boundaries' }).click();
    await expect(sw(page, 'County')).toHaveCount(0);
    await page.reload();
    await expect(card(page).getByRole('button', { name: 'Boundaries' })).toHaveAttribute('aria-expanded', 'false');
    await card(page).getByRole('button', { name: 'Boundaries' }).click();
    await expect(sw(page, 'County')).toHaveAttribute('aria-checked', 'true');
    await page.goto('/#/?view=project');
    // Explore keeps few words on the panel: the card starts folded there.
    await card(page).getByRole('button', { name: 'Boundaries' }).click();
    await sw(page, 'ZIP Code').click();
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-zip-line/);
  });

  test('with all three on, a lot can still be clicked and opened', async ({ page }) => {
    test.skip(!hasLots, `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    await sw(page, 'Census Tract').click();
    await sw(page, 'ZIP Code').click();
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-county-line.*bnd-tract-line.*bnd-zip-line/);
    await openCard(page, 'Testable Lots');
    await page.locator('[data-place="pittsburgh"]').click();
    await page.waitForTimeout(4000); // the fly to the city
    const canvas = main(page).locator('canvas').first();
    const l = (await page.locator('aside[aria-label="Search and map controls"]').boundingBox())!;
    // A spot where the cursor turns to a pointer is a lot.
    let spot: [number, number] | null = null;
    for (let y = 300; y <= 700 && !spot; y += 40)
      for (let x = l.x + l.width + 80; x <= 1300 && !spot; x += 40) {
        await page.mouse.move(x, y);
        if ((await canvas.evaluate((c) => (c as HTMLElement).style.cursor)) === 'pointer') spot = [x, y];
      }
    expect(spot, 'a lot under the cursor').not.toBeNull();
    await page.mouse.click(spot![0], spot![1]);
    await expect(verdict(page)).toBeVisible({ timeout: 30_000 });
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-tract-line/);
  });
});
