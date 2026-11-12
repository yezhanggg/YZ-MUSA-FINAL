// Explore areas: the left panel stays short (word budget, every control still there), and the right panel with a
// tract picked leads with one answer, then at most four rows, with everything else folded and closed.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Locator, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300' };
const hasPgh = existsSync(resolve(LOTS, 'pittsburgh', 'detail', `${PGH.tract}.json.gz`));
/** Words a person sees in the left panel (a closed select shows only its chosen option). */
const LEFT_BUDGET = 80;
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
    return count((n as HTMLElement).innerText) - hidden;
  });
}

test.describe('explore areas', () => {
  test('the left panel shows at most 80 words and keeps every control', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=project');
    await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled();
    for (const level of ['Tracts', 'Towns', 'Counties']) {
      await left(page).getByRole('radio', { name: level }).click();
      const words = await visibleWords(left(page));
      console.log(`left panel, ${level}: ${words} words`);
      expect(words).toBeLessThanOrEqual(LEFT_BUDGET);
    }
    await left(page).getByRole('radio', { name: 'Tracts' }).click();
    // Every control is still on the panel (some inside a closed fold).
    for (const name of ['Bedrooms', 'Stories', 'Rules', 'Map by', 'Build cost per sq ft']) await expect(left(page).getByRole('radiogroup', { name })).toBeVisible();
    await expect(left(page).getByRole('combobox', { name: 'Map colour' })).toBeVisible();
    await expect(left(page).locator('#adu-size')).toBeVisible();
    await expect(left(page).locator('#pay-rate')).toBeVisible();
    const fold = left(page).getByRole('button', { name: /^ADUs by 2031/ });
    await expect(fold).toHaveAttribute('aria-expanded', 'false');
    await fold.click();
    await expect(left(page).getByRole('radiogroup', { name: 'ADUs by 2031 scenario' })).toBeVisible();
    // A bill is marked "not law" where it is picked.
    await left(page).getByRole('radiogroup', { name: 'Rules' }).getByRole('radio', { name: 'State Bill' }).click();
    await expect(left(page).getByText('not law').first()).toBeVisible();
  });

  test('a picked tract: one answer, four rows, the rest closed', async ({ page }) => {
    test.skip(!hasPgh, `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PGH.lot}&tract=${PGH.tract}`);
    await expect(page.locator('section[aria-label="Verdict"]').first()).toBeVisible();
    await page.getByRole('combobox', { name: 'Mode' }).selectOption({ label: 'Explore' });
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
