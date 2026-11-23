// The plain why-not sentences on the two demo lots and the ground slope row on a steep lot (Test Site).
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { lotDataDir } from '../devData';
import { expect, test, type Page } from '@playwright/test';

const LOTS = lotDataDir();
const has = (place: string, tract: string) => existsSync(resolve(LOTS, place, 'detail', `${tract}.json.gz`));

const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();

test.describe('why not, and ground slope', () => {
  test('the approval lot: it fits, it needs the administrator', async ({ page }) => {
    test.skip(!has('pittsburgh', '42003141300'), 'no Pittsburgh lot records');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test&lot=42003-0086N00208000000&tract=42003141300');
    await expect(verdict(page)).toHaveAttribute('data-answer', 'approval');
    await expect(verdict(page)).toContainText("It fits, but it needs the zoning administrator's sign-off.");
    const zoning = page.locator('[data-rule-row="zoning"]').first();
    await zoning.locator('> button').click();
    await expect(zoning.locator('[data-why-not]')).toContainText(/zoning allows a backyard cottage with the zoning administrator's sign-off\./);
    await expect(zoning.locator('[data-why-not]')).toContainText(/^.*Yours is a 20 x 30 ft backyard cottage/);
  });

  test('the Philadelphia rowhouse lot: No, and what the zoning allows', async ({ page }) => {
    test.skip(!has('philadelphia', '42101002702'), 'no Philadelphia lot records');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test&lot=42101-011000034&tract=42101002702');
    await expect(verdict(page)).toHaveAttribute('data-answer', 'no');
    await expect(verdict(page)).toContainText('zoning allows no extra unit here.');
    const zoning = page.locator('[data-rule-row="zoning"]').first();
    await zoning.locator('> button').click();
    await expect(zoning.locator('[data-why-not] p')).toHaveCount(3);
  });

  test('a steep lot: the ground slope row warns, the answer stays, the line says steep site', async ({ page }) => {
    test.skip(!has('pittsburgh', '42003260700'), 'no Pittsburgh lot records');
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test&lot=42003-0116K00029000000&tract=42003260700');
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    const slope = page.locator('[data-rule-row="slope"]').first();
    await expect(slope).toHaveAttribute('data-slope', 'steep');
    await expect(slope).toContainText(/\d+% in the best spot/);
    await expect(slope.getByRole('img', { name: 'Ground slope: steep' })).toBeVisible();
    await expect(verdict(page)).toContainText('Steep site.');
    await slope.locator('> button').click();
    await expect(slope).toContainText('USGS 3DEP lidar');
    await expect(slope).toContainText('not a zoning rule');
  });
});
