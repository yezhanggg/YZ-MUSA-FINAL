// Where to Build (Explore's default map colour): every municipality coloured by whether an ADU is allowed today,
// the legend card with the share of Pennsylvanians, and Details for one municipality. Then the plain why-not
// sentences on the two demo lots and the ground slope row on a steep lot (Test Project).
import { existsSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const PLACES = resolve(import.meta.dirname, '../public/data/pa_places.json');
const hasPlaces = existsSync(PLACES);
const rows: { geoid: string; name: string; status: string; tier: string }[] = hasPlaces ? JSON.parse(readFileSync(PLACES, 'utf8')) : [];
const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const has = (place: string, tract: string) => existsSync(resolve(LOTS, place, 'detail', `${tract}.json.gz`));

const right = (page: Page) => page.locator('aside[aria-label="Ask and report"]');
const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();

/** Expected answer titles per status (today). Limited depends on the approval, so any of its titles. */
const TITLE: Record<string, RegExp> = {
  by_right: /^Allowed by right$/,
  limited: /^(Allowed with a hearing|Allowed with limits|Allowed with sign-off|Only with a variance)$/,
  not_addressed: /^Not addressed$/,
  prohibited: /^Not allowed today$/,
  no_zoning: /^No zoning here$/,
  unknown: /^Not checked yet$/,
};

/** Click the map at a point (the map's own projection). */
async function clickAt(page: Page, lng: number, lat: number, zoom: number) {
  const xy = await page.evaluate(
    async ([lng, lat, zoom]) => {
      // The dev server serves the app's own modules: the live map is in the store.
      const path = '/src/tool/store.ts';
      const { mapRef } = (await import(path)) as { mapRef: { current: import('maplibre-gl').Map } };
      const m = mapRef.current;
      m.jumpTo({ center: [lng, lat], zoom });
      await new Promise((r) => setTimeout(r, 1500));
      const p = m.project([lng, lat]);
      const r = m.getContainer().getBoundingClientRect();
      return [p.x + r.left, p.y + r.top];
    },
    [lng, lat, zoom],
  );
  await page.mouse.click(xy[0], xy[1]);
}

test.describe('where to build', () => {
  test.skip(!hasPlaces, 'no pa_places.json');

  test('Explore opens on Where to Build: legend card, six answers with shares, then one municipality', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    await expect(page.getByRole('combobox', { name: 'Map colour' })).toHaveValue('legal');
    await expect(page.locator('.bh-map [data-places="ready:current"]')).toHaveCount(1, { timeout: 60_000 });
    const legend = page.getByRole('group', { name: 'Where to build legend' });
    await expect(legend.locator('[data-place-legend]')).toHaveCount(6);
    await expect(legend).toContainText('Hatched');
    await expect(legend).toContainText(/Share of Pennsylvanians, data of/);
    const shares = await legend.locator('[data-place-legend] .tnum').allInnerTexts();
    expect(shares).toHaveLength(6);

    // Allentown: the answer matches its row in the file, at most four rows, no lot test outside the two cities.
    const allentown = rows.find((r) => r.name === 'Allentown city')!;
    await clickAt(page, -75.478, 40.602, 10);
    const answer = right(page).locator('section[aria-label="Place answer"]');
    await expect(answer).toHaveAttribute('data-place-status', allentown.status);
    await expect(answer.locator('h3')).toHaveText(TITLE[allentown.status]);
    expect(await right(page).locator('[data-place-row]').count()).toBeLessThanOrEqual(4);
    await expect(right(page).getByRole('heading', { name: 'Allentown city' })).toBeVisible();
    await expect(right(page).getByRole('button', { name: 'Test a lot here' })).toHaveCount(0);
    await expect(right(page).getByRole('button', { name: 'Payoff and room' })).toHaveAttribute('aria-expanded', 'false');

    // The state bill: a zoned town becomes by right, marked not law.
    await page.getByRole('radiogroup', { name: 'Rules' }).getByRole('radio', { name: 'State Bill' }).click();
    await expect(page.locator('.bh-map [data-places="ready:hb2186"]')).toHaveCount(1);
    await expect(answer.locator('h3')).toHaveText('Allowed by right');
    await expect(answer).toContainText('not law');
    await expect(legend).toContainText('not law');
  });

  test('Pittsburgh keeps Test a lot here', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    await expect(page.locator('.bh-map [data-places="ready:current"]')).toHaveCount(1, { timeout: 60_000 });
    await clickAt(page, -79.9959, 40.4406, 10);
    await expect(right(page).getByRole('heading', { name: 'Pittsburgh city' })).toBeVisible();
    await expect(right(page).getByRole('button', { name: 'Test a lot here' })).toBeVisible();
  });
});

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
    await expect(verdict(page)).toContainText('zoning allows no extra unit on this lot.');
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
