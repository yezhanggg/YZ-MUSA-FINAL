// County places with several towns (Chester County: West Chester, Phoenixville, West Vincent, Malvern, East
// Brandywine). A West Chester lot opened by link gets West Chester's answer, names its town and cites the West Chester
// rule file; a Phoenixville lot in the same county names Phoenixville and links its code. Uses the lot records on the
// external drive (LOT_DATA_DIR, default ~/musa-drive/lots) and skips when they are not there.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { openCard } from './cards';

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
    await openCard(page, 'Testable Lots');
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
    await openCard(page, 'Testable Lots');
    const row = page.locator('[data-place="montgomery_county"]');
    await expect(row).toContainText('Montgomery County');
    await expect(row).toHaveText(/\d{1,3}(,\d{3})* Lots$/);
  });
});

// The smoke test of Nov 16: answers that must carry their condition, and an address the lot index finds.
const PHX_SOUTH = { lot: '42029-15-2-1.1', tract: '42029300600' }; // 510 South St, Phoenixville, RI: no living area on file
const NAR_5B = { lot: '42091-120002536017', tract: '42091205600' }; // 603 Haverford Rd, Narberth 5b: by right, in doubt
const NAR_5A = { lot: '42091-120001072005', tract: '42091205600' }; // 119 N Essex Ave, Narberth 5a: not allowed
const hasSmoke = has && hasMont && existsSync(resolve(LOTS, 'chester_county/detail', `${PHX_SOUTH.tract}.json.gz`));

test.describe('answers that depend on something the record does not hold', () => {
  test.skip(!hasSmoke, `no Chester and Montgomery lot records at ${LOTS}`);

  test('Phoenixville, no district on file: depends on the district, not "No"', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PHX.lot}&tract=${PHX.tract}`);
    await expect(verdict(page)).toHaveAttribute('data-answer', 'unknown');
    await expect(verdict(page)).toContainText('Depends on the zoning district, not on file');
    const checklist = page.locator('section[aria-label="Rule checklist"]').first();
    // The yard row is never a green pass on a lot whose district is not on file. Since the Nov 16 rebuild the record
    // carries the town's ADU setbacks, so the row may also say the unit does not fit the room left.
    await expect(checklist.locator('[data-rule-row="yard"] [role="img"]').first()).not.toHaveAttribute('aria-label', 'Passes');
  });

  test('Phoenixville 510 South St: a 40 x 60 ft cottage depends on the house size', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PHX_SOUTH.lot}&tract=${PHX_SOUTH.tract}`);
    await expect(verdict(page)).toBeVisible();
    await openCard(page, 'ADU Design');
    await page.locator('#u-width').fill('40');
    await page.locator('#u-depth').fill('60');
    await expect(verdict(page)).toHaveAttribute('data-status', 'check_needed');
    await expect(verdict(page)).toContainText('Depends on the house size, not checked');
  });

  test('Narberth 5b: "Yes, if confirmed" with the condition, never a plain yes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${NAR_5B.lot}&tract=${NAR_5B.tract}`);
    await expect(verdict(page)).toHaveAttribute('data-answer', 'approval');
    await expect(verdict(page)).toContainText('Yes, if confirmed');
    await expect(verdict(page)).toContainText('Only if the ADU rule reaches 5b, which is in doubt. Ask the zoning officer.');
    const checklist = page.locator('section[aria-label="Rule checklist"]').first();
    await expect(checklist.locator('[data-rule-row="approval"]')).toContainText('By right, if confirmed');
    // The local bill is the same as today here: the chip says so, not "not law".
    const scenarios = page.getByRole('group', { name: 'Scenarios' }).first();
    await expect(scenarios.getByRole('button', { name: /Local Bill/ })).toContainText('same as today');
  });

  test('Narberth 5a, not allowed: the height reads "not checked", never "no limit"', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${NAR_5A.lot}&tract=${NAR_5A.tract}`);
    await expect(verdict(page)).toHaveAttribute('data-answer', 'no');
    const checklist = page.locator('section[aria-label="Rule checklist"]').first();
    await expect(checklist.locator('[data-rule-row="height"]')).toContainText('15 ft · not checked');
    await expect(checklist).not.toContainText('no limit');
  });

  test('a lot address opens its lot from the lot index, not the geocoder\'s nearest house', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    // The geocoder answers with the wrong house, as Photon did in the smoke test.
    await page.route('https://photon.komoot.io/**', (route) =>
      route.fulfill({ json: { features: [{ geometry: { coordinates: [-75.5149, 40.1322] }, properties: { state: 'Pennsylvania', housenumber: '145', street: 'South Main Street', city: 'Phoenixville', county: 'Chester' } }] } }),
    );
    await page.goto('/#/?view=test');
    const box = page.getByRole('combobox', { name: 'Search an address in Pennsylvania' });
    await expect(box).toBeEnabled();
    await box.fill('510 South St, Phoenixville');
    await expect(page.getByRole('option').first()).toContainText('510 South St');
    await page.getByRole('option').first().click();
    await expect(right(page).locator('h2')).toHaveText('510 South St');
    await expect(verdict(page)).toBeVisible();
    // The list stays closed after the pick.
    await page.waitForTimeout(1000);
    await expect(page.getByRole('listbox')).toHaveCount(0);
  });
});
