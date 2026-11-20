// Explore, like a simple GIS: the left panel lists Boundaries first, then one Data Layers card with every map layer as
// a row. The layer on the map shows its own settings right under its row, and its legend above the map buttons. A click on an area opens
// Details with "This layer here" (the value, how it compares, a takeaway), then the answer and the folds.
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { lotDataDir } from '../devData';
import { expect, test, type Locator, type Page } from '@playwright/test';

const LOTS = lotDataDir();
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300' };
const hasPgh = existsSync(resolve(LOTS, 'pittsburgh', 'detail', `${PGH.tract}.json.gz`));
/** Words a person sees in the left panel with Where to Build on (its legend and Rules open under the row). */
const LEFT_BUDGET = 120;
/** Words in the right panel with a tract picked and nothing opened (This layer here, the answer, four rows). */
const RIGHT_BUDGET = 130;

const left = (page: Page) => page.locator('aside[aria-label="Search and map controls"]');
const right = (page: Page) => page.locator('aside[aria-label="Ask and report"]');
const answer = (page: Page) => page.locator('section[aria-label="Area answer"]').first();
const layers = (page: Page) => left(page).getByRole('radiogroup', { name: 'Map layer' });
const here = (page: Page) => right(page).locator('section[aria-label="This layer here"]');

async function visibleWords(el: Locator) {
  return el.evaluate((n) => {
    const count = (t: string) => t.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w)).length;
    let hidden = 0;
    for (const o of n.querySelectorAll('select option')) if (!(o as HTMLOptionElement).selected) hidden += count(o.textContent ?? '');
    for (const c of n.querySelectorAll('[data-map-credits]')) hidden += count((c as HTMLElement).innerText);
    return count((n as HTMLElement).innerText) - hidden;
  });
}

/** Click the map at a point (the map's own projection). */
async function clickAt(page: Page, lng: number, lat: number, zoom: number) {
  const xy = await page.evaluate(
    async ([lng, lat, zoom]) => {
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

test.describe('explore areas', () => {
  test('Boundaries first, then Data Layers: the layer on shows its legend and settings under its row', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled();
    const order = await left(page).locator('section[aria-label]').evaluateAll((els) => els.map((e) => e.getAttribute('aria-label')));
    expect(order.filter((l) => ['Boundaries', 'Data Layers'].includes(l ?? ''))).toEqual(['Boundaries', 'Data Layers']);
    for (const t of ['Boundaries', 'Data Layers']) await expect(left(page).locator(`section[aria-label="${t}"]`).getByRole('button', { name: t, exact: true })).toHaveAttribute('aria-expanded', 'true');
    // Every layer is a row, in three groups. Where to Build is on at the start.
    for (const name of ['Where to Build', 'Lots with Room', 'Does It Pay Off', 'Jobs', 'Job Growth Shift', 'People', 'Homes', 'Rent', 'Trend Groups', 'By ACS Window', 'ADUs by 2031'])
      await expect(layers(page).getByRole('radio', { name, exact: true })).toBeVisible();
    await expect(layers(page).getByRole('radio', { name: 'Where to Build' })).toHaveAttribute('aria-checked', 'true');
    // Rules sits under its row, no payoff settings.
    const legal = left(page).locator('[data-layer-detail="legal"]');
    // The legend itself sits above the map buttons at the bottom right (the legend slot), titled with the layer.
    const slot = page.locator('[data-legend-slot]');
    await expect(slot.getByRole('group', { name: 'Where to build legend' })).toBeVisible();
    await expect(slot.locator('[data-layer-legend="legal"]')).toContainText('Where to Build');
    await expect(legal.getByRole('radiogroup', { name: 'Rules' })).toBeVisible();
    await expect(page.getByRole('group', { name: 'Where to build legend' })).toHaveCount(1);
    await expect(left(page).getByRole('radiogroup', { name: 'Bedrooms' })).toHaveCount(0);
    const words = await visibleWords(left(page));
    console.log(`left panel, Where to Build: ${words} words`);
    expect(words).toBeLessThanOrEqual(LEFT_BUDGET);

    // Rent: the legend card shows Rent, Rules goes away.
    await layers(page).getByRole('radio', { name: 'Rent', exact: true }).click();
    await expect(layers(page).getByRole('radio', { name: 'Rent', exact: true })).toHaveAttribute('aria-checked', 'true');
    await expect(layers(page).getByRole('radio', { name: 'Where to Build' })).toHaveAttribute('aria-checked', 'false');
    await expect(page.locator('[data-legend-slot]').getByRole('group', { name: 'Rent legend' })).toContainText('Inside the margin of error');
    await expect(left(page).locator('[data-layer-detail]')).toHaveCount(1);
    await expect(left(page).getByRole('radiogroup', { name: 'Rules' })).toHaveCount(0);

    // Does It Pay Off: your ADU and the payoff settings.
    await layers(page).getByRole('radio', { name: 'Does It Pay Off' }).click();
    const pays = left(page).locator('[data-layer-detail="pays"]');
    for (const name of ['Bedrooms', 'Stories', 'Build cost per sq ft']) await expect(pays.getByRole('radiogroup', { name })).toBeVisible();
    await expect(pays.locator('#adu-size')).toBeVisible();
    await expect(pays.locator('#pay-rate')).toBeVisible();

    // ADUs by 2031: by towns or counties and the scenario; a bill is marked not law.
    await layers(page).getByRole('radio', { name: 'ADUs by 2031' }).click();
    const forecast = left(page).locator('[data-layer-detail="forecast"]');
    await expect(page.locator('[data-legend-slot]').getByRole('group', { name: 'ADUs by 2031 legend' })).toBeVisible();
    await forecast.getByRole('radiogroup', { name: 'Map by' }).getByRole('radio', { name: 'Counties' }).click();
    await forecast.getByRole('radiogroup', { name: 'ADUs by 2031 scenario' }).getByRole('radio', { name: 'SB 1346' }).click();
    await expect(forecast.getByText('not law').first()).toBeVisible();
    await expect(left(page).getByRole('radiogroup', { name: 'Bedrooms' })).toHaveCount(0);

    // By ACS Window: the measure and the window.
    await layers(page).getByRole('radio', { name: 'By ACS Window' }).click();
    for (const name of ['Measure', 'ACS window']) await expect(left(page).locator('[data-layer-detail="window"]').getByRole('radiogroup', { name })).toBeVisible();
  });

  test('a click on an area: This layer here with an insight and a takeaway, following the layer', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled();
    await layers(page).getByRole('radio', { name: 'Rent', exact: true }).click();
    await clickAt(page, -79.9959, 40.4406, 9);
    await expect(here(page)).toHaveAttribute('data-layer-here', 'rent_after');
    await expect(here(page)).toContainText('This layer here');
    await expect(here(page).locator('[data-layer-value]')).toHaveText(/^[+-]?\d+\.\d% a year$|^No data$/);
    await expect(here(page).locator('[data-insight]').first()).toContainText(/Pennsylvania tracts|no figure/);
    await expect(here(page).locator('[data-takeaway]')).toContainText(/Takeaway\. \S+/);
    // The panel follows the layer.
    await layers(page).getByRole('radio', { name: 'Jobs', exact: true }).click();
    await expect(here(page)).toHaveAttribute('data-layer-here', 'jobs_after');
    await expect(here(page).locator('[data-layer-value]')).toHaveText(/since 2019$|^No data$/);
    await layers(page).getByRole('radio', { name: 'Where to Build' }).click();
    await expect(here(page)).toHaveAttribute('data-layer-here', 'legal');
    await expect(here(page).locator('[data-insight]').first()).toContainText('of Pennsylvanians');
    // The map did not fly in past what the area needs.
    const zoom = await page.evaluate(async () => {
      const path = '/src/tool/store.ts';
      const { mapRef } = (await import(path)) as { mapRef: { current: import('maplibre-gl').Map } };
      return mapRef.current.getZoom();
    });
    expect(zoom).toBeLessThanOrEqual(12.01);
  });

  test('a picked tract: this layer, one answer, four rows, the rest closed', async ({ page }) => {
    test.skip(!hasPgh, `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    // A link to the lot in Explore picks its tract (the Features menu starts clean, lot-flow.spec.ts).
    await page.goto(`/#/?view=project&lot=${PGH.lot}&tract=${PGH.tract}`);
    // Explore opens on Where to Build (the municipality's answer, places.spec.ts); a tract layer shows the tract answer.
    await left(page).getByRole('radio', { name: 'Does It Pay Off' }).click();
    await expect(here(page)).toHaveAttribute('data-layer-here', 'pays');
    await expect(here(page)).toContainText('Estimate');
    await expect(answer(page)).toBeVisible();
    await expect(answer(page)).toHaveAttribute('data-answer', /^(yes|approval|no|unknown)$/);
    await expect(answer(page)).toContainText(/Pays off|paying off|No payoff estimate/);
    await expect(answer(page)).toContainText(/Pittsburgh city|not on file/);
    const rows = right(page).locator('[data-area-row]');
    await expect(rows).toHaveCount(4);
    await expect(right(page).getByText('Estimate. Not legal advice.')).toBeVisible();
    for (const b of await right(page).locator('section > button[aria-expanded], li > button[aria-expanded]').all()) await expect(b).toHaveAttribute('aria-expanded', 'false');
    const words = await visibleWords(right(page));
    console.log(`right panel, tract picked: ${words} words`);
    expect(words).toBeLessThanOrEqual(RIGHT_BUDGET);
    // A row opens to its detail.
    await rows.filter({ hasText: 'Room on lots' }).locator('> button').click();
    await expect(right(page).getByText('Lots with room').first()).toBeVisible();
    // The state bill, under Where to Build: marked not law here and in the answer.
    await left(page).getByRole('radio', { name: 'Where to Build' }).click();
    await left(page).getByRole('radiogroup', { name: 'Rules' }).getByRole('radio', { name: 'State Bill' }).click();
    await expect(here(page)).toContainText('not law');
  });
});
