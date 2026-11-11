// The main lot flow: pick Testing mode, open a Pittsburgh lot by link, read the verdict, grow the unit until it
// no longer fits, switch the scenario, open the Build tab and the lot report. Screenshots go to SHOTS_DIR.
import { existsSync, mkdirSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const LOT = '42003-0086N00208000000';
const TRACT = '42003141300';
const SHOTS = resolve(process.env.SHOTS_DIR ?? resolve(homedir(), 'musa-drive/ops/scratch/app-shots'));
const hasLots = existsSync(resolve(LOTS, 'pittsburgh/detail', `${TRACT}.json.gz`));

const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(1500); // tiles and the site view settle
  await page.screenshot({ path: resolve(SHOTS, name) });
}

test.describe('lot flow', () => {
  test.skip(!hasLots, `no lot records at ${LOTS}`);

  test('desktop 1440: verdict, size, scenario, build, report', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    const mode = page.getByRole('combobox', { name: 'Mode' });
    await expect(mode).toHaveValue('project');
    await mode.selectOption({ label: 'ADU Testing (MUSA 6950)' });
    await expect(page.getByRole('heading', { name: 'Test a lot' }).first()).toBeVisible();

    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await expect(verdict(page)).toContainText('backyard cottage fits here');
    await expect(page.getByText('Not legal advice. Not a zoning determination. Parcel lines are not a survey.').first()).toBeVisible();
    await shot(page, 'lot-1440-fits.png');

    // Grow the unit until it no longer fits where it is.
    await page.locator('#u-width').fill('40');
    await page.locator('#u-depth').fill('60');
    await expect(verdict(page)).not.toHaveAttribute('data-status', 'fits');
    await expect(verdict(page)).toContainText(/1,000 sq ft|does not fit/);
    await shot(page, 'lot-1440-too-big.png');

    // Another scenario: the zoning card follows.
    await page.getByRole('radio', { name: 'State reform' }).click();
    await expect(page.getByRole('heading', { name: 'Zoning, state reform' })).toBeVisible();
    expect(new URL(page.url()).hash).toContain('sc=state_reform');

    await page.getByRole('tab', { name: 'Build' }).first().click();
    await expect(page.locator('section[aria-label="Build steps"] li').first()).toBeVisible();
    expect(await page.locator('section[aria-label="Build steps"] li').count()).toBeGreaterThan(3);
    await shot(page, 'lot-1440-build.png');

    await page.getByRole('button', { name: 'Lot report' }).first().click();
    const report = page.getByRole('dialog', { name: 'Lot report' });
    await expect(report).toContainText('Three scenarios');
    await expect(report).toContainText('Not legal advice');
    await shot(page, 'lot-1440-report.png');
  });

  test('phone: the same lot in the sheet', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await shot(page, 'lot-phone.png');
  });
});

test.describe('projecting mode', () => {
  test('payoff controls, counties and the research explorer', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    const share = page.locator('p[aria-live="polite"]', { hasText: 'pays off in' }).first();
    await expect(share).toContainText('10%');
    await page.getByRole('radio', { name: '$300' }).click();
    await expect(share).toContainText('4%');
    await page.getByRole('radio', { name: 'Counties' }).click();
    await expect(page.getByRole('heading', { name: /Counties/ })).toBeVisible();
    await page.getByRole('radio', { name: 'SB 1346' }).click();
    await expect(page.getByText('Both bills die on Nov 30, 2026 if not enacted.').first()).toBeVisible();
    await shot(page, 'proj-1440-e2e.png');

    await page.goto('/#/?view=project&research=5500');
    await expect(page.getByText('7 stable groups')).toBeVisible();
    await page.getByRole('button', { name: 'Open the explorer here' }).click();
    await expect(page.locator('iframe[title="Tract explorer"]')).toBeVisible();
    const res = await page.request.get('/explorer/tract_explorer.html');
    expect(res.ok()).toBe(true);
  });
});
