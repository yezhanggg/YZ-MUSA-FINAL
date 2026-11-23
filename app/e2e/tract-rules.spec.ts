// Test Site, Boundaries: every boundary level carries the ADU rule. The finest level on is coloured (data-rules on the
// map element, "tract:ready") with one legend, and a click on an area opens its answer in Details without flying in to
// lot level: a county, census tract or ZIP code sums up its towns, a township or city shows its own rule. Every
// boundary click fits the whole outline in the open map (data-focus-box inside data-open-box), and a lot click fits
// the lot with the block around it. Test Site and Explore keep their own switches. The map element says what is
// picked (data-area-pick, data-area-kind).
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { lotDataDir } from '../devData';
import { openCard } from './cards';

const LOTS = lotDataDir();
const hasLots = existsSync(resolve(LOTS, 'pittsburgh/manifest.json'));
const main = (page: Page) => page.locator('[aria-label^="Map of Pennsylvania"]');
const card = (page: Page) => page.locator('section[aria-label="Boundaries"]');
const sw = (page: Page, name: string) => card(page).getByRole('switch', { name });
const answer = (page: Page, label: string) => page.locator(`section[aria-label="${label}"]`).first();
const tractAnswer = (page: Page) => answer(page, 'Census tract answer');
const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();
const legends = (page: Page) => page.locator('[data-rule-legend]');
/** The middle of the open map at 1440 x 900 with Details closed: central Pennsylvania. */
const MID: [number, number] = [880, 430];

const zoom = async (page: Page) => Number(await main(page).getAttribute('data-zoom'));
const box = async (page: Page, attr: string) => ((await main(page).getAttribute(attr)) ?? '').split(',').map(Number);

/** The shape's box on screen sits inside the open map, with at least `margin` pixels to spare on each side. */
async function expectInOpenMap(page: Page, margin = 0) {
  await page.waitForTimeout(2500); // the camera rests
  const f = await box(page, 'data-focus-box');
  const o = await box(page, 'data-open-box');
  expect(f).toHaveLength(4);
  expect(o).toHaveLength(4);
  expect(f[0] - o[0], 'left').toBeGreaterThanOrEqual(margin - 2);
  expect(f[1] - o[1], 'top').toBeGreaterThanOrEqual(margin - 2);
  expect(o[2] - f[2], 'right').toBeGreaterThanOrEqual(margin - 2);
  expect(o[3] - f[3], 'bottom').toBeGreaterThanOrEqual(margin - 2);
  return f;
}

async function start(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/#/?view=test');
  await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-county-line/);
  await expect(main(page)).toHaveAttribute('data-zoom', /\d/);
}

test.describe('boundary rules', () => {
  test('Census Tract colours the tracts, a click opens the tract answer and fits it, close and Esc clear it', async ({ page }) => {
    await start(page);
    const legend = page.getByRole('group', { name: 'Census tract legend' });
    await expect(legend).toHaveCount(0);
    await sw(page, 'Census Tract').click();
    await expect(main(page)).toHaveAttribute('data-rules', 'tract:ready');
    await expect(legend).toBeVisible();
    await expect(legends(page)).toHaveCount(1); // One boundary at a time: Census Tract turned County off
    await expect(sw(page, 'County')).toHaveAttribute('aria-checked', 'false');
    for (const label of ['Allowed by right', 'Allowed with limits', 'Not addressed', 'No zoning', 'Not checked yet']) await expect(legend).toContainText(label);
    await expect(card(page).locator('[data-rule-note="tract"]')).toContainText('Coloured by the ADU rule for most of its homes');
    await expect(card(page).locator('[data-rule-note="county"]')).toHaveCount(0);

    await page.mouse.click(...MID);
    await expect(tractAnswer(page)).toBeVisible();
    await expect(tractAnswer(page)).toContainText(/Mostly allowed|Mostly not allowed|Mixed|Not checked yet/);
    await expect(main(page)).toHaveAttribute('data-area-kind', 'tract');
    const geoid = await main(page).getAttribute('data-area-pick');
    expect(geoid).toMatch(/^42\d{9}$/);
    await expect(tractAnswer(page)).toHaveAttribute('data-area', geoid!);
    expect(await page.locator('[data-tract-town]').count()).toBeGreaterThan(0);
    await expect(page.getByText('Census tract', { exact: true })).toBeVisible();
    await expect(page.getByText(/Rules are set by each town/)).toBeVisible();
    await expect(verdict(page)).toHaveCount(0);
    // The whole tract in the open map, and never at street or lot zoom.
    await expectInOpenMap(page);
    expect(await zoom(page)).toBeLessThanOrEqual(13.01);

    // The Details close button lets go of the tract.
    await page.getByRole('button', { name: 'Hide the details' }).click();
    await expect(main(page)).toHaveAttribute('data-area-pick', '');
    await expect(tractAnswer(page)).toHaveCount(0);
    // Esc too.
    await page.getByRole('button', { name: 'Show the details' }).click();
    await page.mouse.click(...MID);
    await expect(tractAnswer(page)).toBeVisible();
    await page.keyboard.press('Escape');
    await expect(main(page)).toHaveAttribute('data-area-pick', '');
    await expect(tractAnswer(page)).toHaveCount(0);

    // Off: nothing is coloured. County back on: the county colours come back.
    await sw(page, 'Census Tract').click();
    await expect(legend).toHaveCount(0);
    await expect(main(page)).toHaveAttribute('data-rules', '');
    await sw(page, 'County').click();
    await expect(main(page)).toHaveAttribute('data-rules', 'county:ready');
    await expect(card(page).locator('[data-rule-note="tract"]')).toHaveCount(0);
  });

  test('County (on at the start) is coloured, a click opens the county answer and fits it; no boundary on: a dropped pin as before', async ({ page }) => {
    await start(page);
    await expect(sw(page, 'County')).toHaveAttribute('aria-checked', 'true');
    await expect(main(page)).toHaveAttribute('data-rules', 'county:ready');
    await expect(page.getByRole('group', { name: 'County legend' })).toBeVisible();
    await page.mouse.click(...MID);
    const county = answer(page, 'County answer');
    await expect(county).toBeVisible();
    await expect(county).toContainText(/% of people here/);
    await expect(main(page)).toHaveAttribute('data-area-kind', 'county');
    expect(await main(page).getAttribute('data-area-pick')).toMatch(/^42\d{3}$/);
    // The largest towns (at most eight), then a count line for the rest.
    const rows = await page.locator('[data-tract-town]').count();
    expect(rows).toBeGreaterThan(0);
    expect(rows).toBeLessThanOrEqual(8);
    await expect(page.locator('[data-rest-line]')).toContainText(/^And \d+ more towns?: /);
    await expectInOpenMap(page);
    expect(await zoom(page)).toBeLessThanOrEqual(11.01);
    await expect(verdict(page)).toHaveCount(0);

    // Today's click with no boundary on: a dropped pin, tested for a lot record (none here).
    await page.keyboard.press('Escape');
    await sw(page, 'County').click();
    await expect(main(page)).toHaveAttribute('data-rules', '');
    await page.reload();
    await expect(main(page)).toHaveAttribute('data-zoom', /\d/);
    await page.waitForTimeout(1500);
    await page.mouse.click(...MID);
    await expect(page.getByText(/There are no lot records for .* yet/).first()).toBeVisible();
    await expect(main(page)).toHaveAttribute('data-area-pick', '');
  });

  test('Township or City: its own switch and colours, a click opens the town answer; Census Tract replaces it', async ({ page }) => {
    await start(page);
    const order = await card(page).locator('[data-boundary]').evaluateAll((els) => els.map((e) => e.getAttribute('data-boundary')));
    expect(order).toEqual(['county', 'town', 'tract', 'zip']);
    await expect(sw(page, 'Township or City')).toHaveAttribute('aria-checked', 'false');
    await sw(page, 'Township or City').click();
    await expect(main(page)).toHaveAttribute('data-boundaries', /bnd-town-line/);
    await expect(main(page)).toHaveAttribute('data-rules', 'town:ready');
    await expect(page.getByRole('group', { name: 'Township or City legend' })).toBeVisible();
    await expect(legends(page)).toHaveCount(1);
    await expect(card(page).locator('[data-rule-note="town"]')).toBeVisible();

    await page.mouse.click(...MID);
    await expect(answer(page, 'Town answer')).toBeVisible();
    await expect(main(page)).toHaveAttribute('data-area-kind', 'town');
    expect(await main(page).getAttribute('data-area-pick')).toMatch(/^42\d{8}$/);
    await expect(page.locator('section[aria-label="Place checklist"]')).toBeVisible();
    await expectInOpenMap(page);
    expect(await zoom(page)).toBeLessThanOrEqual(13.01);

    // Kept on reload, like the other switches.
    await page.reload();
    await expect(sw(page, 'Township or City')).toHaveAttribute('aria-checked', 'true');
    // One at a time: Census Tract turns Township or City off, and the tract is coloured and picked.
    await sw(page, 'Census Tract').click();
    await expect(sw(page, 'Township or City')).toHaveAttribute('aria-checked', 'false');
    await expect(main(page)).toHaveAttribute('data-rules', 'tract:ready');
    await expect(legends(page)).toHaveCount(1);
    await page.mouse.click(...MID);
    await expect(tractAnswer(page)).toBeVisible();
    await expect(main(page)).toHaveAttribute('data-area-kind', 'tract');
    await sw(page, 'Census Tract').click();
    await expect(main(page)).not.toHaveAttribute('data-boundaries', /bnd-town-line/);
  });

  test('ZIP Code: coloured by the rule for most homes, a click opens the ZIP code answer and fits it', async ({ page }) => {
    await start(page);
    await sw(page, 'ZIP Code').click();
    await expect(main(page)).toHaveAttribute('data-rules', 'zip:ready');
    await expect(page.getByRole('group', { name: 'ZIP code legend' })).toBeVisible();
    await expect(legends(page)).toHaveCount(1);
    await page.mouse.click(...MID);
    const zip = answer(page, 'ZIP code answer');
    await expect(zip).toBeVisible();
    await expect(zip).toContainText(/% of homes here|not checked yet/);
    await expect(main(page)).toHaveAttribute('data-area-kind', 'zip');
    const z = await main(page).getAttribute('data-area-pick');
    expect(z).toMatch(/^\d{5}$/);
    await expect(page.getByRole('heading', { name: `ZIP code ${z}` })).toBeVisible();
    expect(await page.locator('[data-tract-town]').count()).toBeGreaterThan(0);
    await expectInOpenMap(page);
    expect(await zoom(page)).toBeLessThanOrEqual(13.01);
    await sw(page, 'ZIP Code').click();
    await expect(main(page)).toHaveAttribute('data-area-pick', '');
  });

  test('a lot click fits the whole lot with the block around it, at most zoom 18', async ({ page }) => {
    test.skip(!hasLots, `no lot records at ${LOTS}`);
    await start(page);
    await openCard(page, 'Testable Lots');
    await page.locator('[data-place="pittsburgh"]').click();
    await page.waitForTimeout(4000);
    const canvas = main(page).locator('canvas').first();
    let spot: [number, number] | null = null;
    for (let y = 300; y <= 700 && !spot; y += 40)
      for (let x = 420; x <= 1300 && !spot; x += 40) {
        await page.mouse.move(x, y);
        if ((await canvas.evaluate((c) => (c as HTMLElement).style.cursor)) === 'pointer') spot = [x, y];
      }
    expect(spot, 'a lot under the cursor').not.toBeNull();
    await page.mouse.click(spot![0], spot![1]);
    await expect(verdict(page)).toBeVisible({ timeout: 30_000 });
    await page.waitForTimeout(1500);
    const f = await box(page, 'data-focus-box');
    // About the block: the lot plus at least two lot widths on every side inside the open map.
    await expectInOpenMap(page, Math.max(f[2] - f[0], f[3] - f[1]) * 2);
    expect(await zoom(page)).toBeLessThanOrEqual(18.01);
  });
});
