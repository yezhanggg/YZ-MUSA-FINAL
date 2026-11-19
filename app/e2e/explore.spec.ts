// Explore areas: the left panel stays short (word budget, every control still there), and the right panel with a
// tract picked leads with one answer, then at most four rows, with everything else folded and closed.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300' };
const hasPgh = existsSync(resolve(LOTS, 'pittsburgh', 'detail', `${PGH.tract}.json.gz`));
/** Words a person sees in the left panel (a closed select shows only its chosen option). The map credits line in the
 *  footer does not count: it is a licence notice, not panel text. */
// 100 since the map layers became a list with a one-line description each (was 80 with one select).
const LEFT_BUDGET = 100;
/** Words in the right panel with a tract picked and nothing opened. */
const RIGHT_BUDGET = 60;

const left = (page: Page) => page.locator('aside[aria-label="Search and map controls"]');
const right = (page: Page) => page.locator('aside[aria-label="Ask and report"]');
const answer = (page: Page) => page.locator('section[aria-label="Area answer"]').first();

async function visibleWords(el: Locator) {
  return el.evaluate((n) => {
    const count = (t: string) => t.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w)).length;
    let hidden = 0;
    for (const o of n.querySelectorAll('select option')) if (!(o as HTMLOptionElement).selected) hidden += count(o.textContent ?? '');
    for (const c of n.querySelectorAll('[data-map-credits]')) hidden += count((c as HTMLElement).innerText);
    return count((n as HTMLElement).innerText) - hidden;
  });
}

test.describe('explore areas', () => {
  test('the left panel shows at most 100 words and keeps every control', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled();
    const layers = left(page).getByRole('radiogroup', { name: 'Map layer' });
    // Explore opens on Where to Build, in the ADU Layers card. The other two cards start folded.
    await expect(layers.getByRole('radio', { name: 'Where to Build' })).toHaveAttribute('aria-checked', 'true');
    const prediction = left(page).getByRole('button', { name: 'Prediction Layers' });
    await expect(prediction).toHaveAttribute('aria-expanded', 'false');
    await expect(left(page).getByRole('button', { name: 'Data Layers' })).toHaveAttribute('aria-expanded', 'false');
    const counts: Record<string, number> = { 'Where to Build': await visibleWords(left(page)) };
    // ADUs by 2031, by towns and by counties: the Prediction card with its scenario.
    await prediction.click();
    await expect(left(page).getByRole('radiogroup', { name: 'ADUs by 2031 scenario' })).toBeVisible();
    await layers.getByRole('radio', { name: 'ADUs by 2031' }).click();
    // Counted with the card folded again (its scenario table is opt-in reading, like the old fold).
    for (const level of ['Towns', 'Counties']) {
      if ((await prediction.getAttribute('aria-expanded')) === 'false') await prediction.click();
      await left(page).getByRole('radiogroup', { name: 'Map by' }).getByRole('radio', { name: level }).click();
      await prediction.click();
      counts[level] = await visibleWords(left(page));
    }
    for (const [k, words] of Object.entries(counts)) {
      console.log(`left panel, ${k}: ${words} words`);
      expect(words).toBeLessThanOrEqual(LEFT_BUDGET);
    }
    // A data layer: open its card, pick it, and the card title shows it.
    await left(page).getByRole('button', { name: 'Data Layers' }).click();
    await layers.getByRole('radio', { name: 'Rent' }).click();
    await expect(layers.getByRole('radio', { name: 'Rent' })).toHaveAttribute('aria-checked', 'true');
    await expect(layers.getByRole('radio', { name: 'Where to Build' })).toHaveAttribute('aria-checked', 'false');
    await expect(left(page).locator('section[aria-label="Data Layers"]')).toContainText('Rent');
    await expect(left(page).getByText('Inside the margin of error')).toBeVisible(); // its legend, under the list
    // Every control is still on the panel (some inside a closed fold).
    for (const name of ['Bedrooms', 'Stories', 'Rules', 'Map layer', 'Build cost per sq ft']) await expect(left(page).getByRole('radiogroup', { name })).toBeVisible();
    await expect(left(page).locator('#adu-size')).toBeVisible();
    await expect(left(page).locator('#pay-rate')).toBeVisible();
    // A bill is marked "not law" where it is picked.
    await left(page).getByRole('radiogroup', { name: 'Rules' }).getByRole('radio', { name: 'State Bill' }).click();
    await expect(left(page).getByText('not law').first()).toBeVisible();
  });

  test('a picked tract: one answer, four rows, the rest closed', async ({ page }) => {
    test.skip(!hasPgh, `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PGH.lot}&tract=${PGH.tract}`);
    await expect(page.locator('section[aria-label="Verdict"]').first()).toBeVisible();
    await page.getByRole('button', { name: 'Features' }).click();
    await page.getByRole('menuitemradio', { name: /^Explore/ }).click();
    // Explore opens on Where to Build (the municipality's answer, places.spec.ts); a tract map colour shows the tract answer.
    await left(page).getByRole('radio', { name: 'Pays Off?' }).click();
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
    // The state bill: the answer says "not law".
    await left(page).getByRole('radiogroup', { name: 'Rules' }).getByRole('radio', { name: 'State Bill' }).click();
    await expect(answer(page)).toContainText('not law');
  });
});
