// Loading: while a lot's data loads, the results open at once on a "Loading" message with a spinning circle, and the
// answer replaces it. A failed load shows its message there instead. The lot file is held back on purpose here.
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { lotDataDir } from '../devData';
import { expect, test, type Page } from '@playwright/test';

const LOTS = lotDataDir();
const LOT = '42003-0086N00208000000';
const TRACT = '42003141300';
const has = existsSync(resolve(LOTS, 'pittsburgh/detail', `${TRACT}.json.gz`));
const results = (page: Page) => page.locator('aside[aria-label="Ask and report"]');
const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();

test.describe('loading a lot', () => {
  test.skip(!has, `no lot records at ${LOTS}`);

  test('a link opens the results on Loading, then the answer', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    let release!: () => void;
    const held = new Promise<void>((r) => (release = r));
    await page.route(`**/pittsburgh/detail/${TRACT}.json.gz`, async (route) => {
      await held;
      await route.continue();
    });
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    const loading = results(page).locator('[data-loading]');
    await expect(loading).toBeVisible();
    await expect(loading).toContainText('Loading');
    await expect(verdict(page)).toHaveCount(0);
    release();
    await expect(verdict(page)).toBeVisible();
    await expect(loading).toHaveCount(0);
  });

  test('a failed load shows its message, not a spinner', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route(`**/pittsburgh/detail/${TRACT}.json.gz`, (route) => route.abort('failed'));
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(results(page).locator('[data-load-error], [role="status"]').filter({ hasNotText: 'Loading' }).first()).toBeVisible();
    await expect(results(page).locator('[data-loading]')).toHaveCount(0);
  });

  test('with reduced motion the circle stands still', async ({ page }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route(`**/pittsburgh/detail/${TRACT}.json.gz`, () => undefined); // never answers
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    const circle = results(page).locator('[data-loading] svg');
    await expect(circle).toBeVisible();
    expect(await circle.evaluate((el) => getComputedStyle(el).animationName)).toBe('none');
  });
});
