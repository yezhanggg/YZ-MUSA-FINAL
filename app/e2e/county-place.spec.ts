// County places with several towns (Chester County: West Chester, Phoenixville, West Vincent, Malvern, East
// Brandywine). A West Chester lot opened by link gets West Chester's answer, names its town and cites the West Chester
// rule file; a Phoenixville lot in the same county names Phoenixville and links its code. Uses the lot records on the
// external drive (LOT_DATA_DIR, default ~/musa-drive/lots) and skips when they are not there.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const WCH = { lot: '42029-1-4-50', tract: '42029302400' }; // 307 W Marshall St, West Chester, NC-1
const PHX = { lot: '42029-15-7-4', tract: '42029300502' }; // 192 Pennsylvania Av, Phoenixville
const has = [WCH, PHX].every((x) => existsSync(resolve(LOTS, 'chester_county/detail', `${x.tract}.json.gz`)));

const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();
const right = (page: Page) => page.locator('aside[aria-label="Ask and report"]');

test.describe('a county place with several towns', () => {
  test.skip(!has, `no Chester County lot records at ${LOTS}`);

  test("a West Chester lot: West Chester's answer, its town, and the West Chester rule file", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${WCH.lot}&tract=${WCH.tract}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await expect(verdict(page)).toHaveAttribute('data-answer', 'yes');
    await expect(right(page).locator('h2')).toHaveText('307 W Marshall St');
    // The header names the town (not only the county) and links the town's own code.
    await expect(right(page)).toContainText('West Chester borough');
    await expect(right(page).locator('[data-code-link="Zoning code"]')).toHaveAttribute('href', 'https://ecode360.com/6471979');
    const checklist = page.locator('section[aria-label="Rule checklist"]').first();
    await expect(checklist.locator('[data-rule-row="approval"]')).toContainText(/by right/i);
    // Why: the citations name the West Chester rule file, and no other town's.
    const why = page.locator('section[aria-label="Why"]').first();
    await why.getByRole('button', { name: 'Why' }).click();
    await expect(why).toContainText('West Chester Zoning Code (Ch. 112)');
    await expect(why).not.toContainText(/Phoenixville|Malvern|West Vincent|East Brandywine/);
    // City numbers: the town's own share (stats.json by_town), not the county's.
    const numbers = page.locator('section[aria-label="City numbers"]').first();
    await numbers.getByRole('button', { name: 'City numbers' }).click();
    await expect(numbers).toContainText(/West Chester, all \d{1,3}(,\d{3})* lots/);
  });

  test('a Phoenixville lot in the same county names Phoenixville and links its code', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PHX.lot}&tract=${PHX.tract}`);
    await expect(verdict(page)).toBeVisible();
    await expect(right(page)).toContainText('Phoenixville borough');
    await expect(right(page)).not.toContainText('West Chester');
    await expect(right(page).locator('[data-code-link="Zoning code"]')).toHaveAttribute('href', 'https://ecode360.com/47638080');
  });

  test('Testable Lots lists the county by name with its lot count', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const row = page.locator('[data-place="chester_county"]');
    await expect(row).toContainText('Chester County');
    await expect(row).toHaveText(/\d{1,3}(,\d{3})* Lots$/);
    await expect(page.locator('[data-place="centre_county"]')).toContainText('Centre County');
  });
});

// Montgomery County: three towns (Lower Merion, Narberth, Upper Dublin). Its records name their town themselves.
const NAR = { lot: '42091-120000004002', tract: '42091205600' }; // 203 Barrie Rd, Narberth, 3B
const hasMont = existsSync(resolve(LOTS, 'montgomery_county/detail', `${NAR.tract}.json.gz`));

test.describe('Montgomery County, a second county place', () => {
  test.skip(!hasMont, `no Montgomery County lot records at ${LOTS}`);

  test("a Narberth lot: Narberth's answer, its town, the Narberth rule file and its numbers", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${NAR.lot}&tract=${NAR.tract}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await expect(verdict(page)).toHaveAttribute('data-answer', 'yes');
    await expect(right(page).locator('h2')).toHaveText('203 Barrie Rd');
    await expect(right(page)).toContainText('Narberth borough');
    await expect(right(page).locator('[data-code-link="Zoning code"]')).toHaveAttribute('href', 'https://ecode360.com/34400015');
    const why = page.locator('section[aria-label="Why"]').first();
    await why.getByRole('button', { name: 'Why' }).click();
    await expect(why).toContainText('Narberth Zoning Code (Ch. 500)');
    await expect(why).not.toContainText(/Lower Merion|Upper Dublin/);
    const numbers = page.locator('section[aria-label="City numbers"]').first();
    await numbers.getByRole('button', { name: 'City numbers' }).click();
    await expect(numbers).toContainText(/Narberth, all \d{1,3}(,\d{3})* lots/);
  });

  test('Testable Lots lists Montgomery County with its lot count', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const row = page.locator('[data-place="montgomery_county"]');
    await expect(row).toContainText('Montgomery County');
    await expect(row).toHaveText(/\d{1,3}(,\d{3})* Lots$/);
  });
});
