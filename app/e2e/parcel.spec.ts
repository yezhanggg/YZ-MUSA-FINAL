// The Parcel tab and Be prepared: open a lot by link, read its parcel number, zoning district, property tax,
// documents and offices, then the Next Step tab's list of what to bring and what to ask. Screenshots go to SHOTS_DIR.
import { existsSync, mkdirSync } from 'node:fs';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { lotDataDir, shotsDir } from '../devData';

const LOTS = lotDataDir();
const SHOTS = shotsDir();
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300', parcel: '0086N00208000000' };
const NAR = { lot: '42091-120000004002', tract: '42091205600', parcel: '120000004002' };
const has = (place: string, tract: string) => existsSync(resolve(LOTS, place, 'detail', `${tract}.json.gz`));

const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();

async function shot(page: Page, name: string) {
  mkdirSync(SHOTS, { recursive: true });
  await page.waitForTimeout(800);
  await page.screenshot({ path: resolve(SHOTS, name) });
}

test.describe('parcel tab', () => {
  test('Pittsburgh: parcel, zoning, tax from the money model, documents, then what to bring and ask', async ({ page }) => {
    test.skip(!has('pittsburgh', PGH.tract), `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PGH.lot}&tract=${PGH.tract}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await page.getByRole('tab', { name: 'Parcel' }).first().click();
    const tab = page.locator('[data-parcel-tab]');
    await expect(tab.locator('[data-parcel-number]')).toHaveText(PGH.parcel);
    // Zoning in plain words: the district, the flags, and the path of each unit type today.
    const zoning = tab.locator('[data-parcel-zoning]');
    await expect(zoning).toContainText('R2-L');
    await expect(zoning).toContainText('Backyard cottage');
    await expect(zoning).toContainText('Flood zone: no');
    // The code sections fold open.
    await zoning.getByRole('button', { name: /code sections behind this answer/ }).click();
    await expect(zoning.locator('[data-code-sections] a').first()).toHaveAttribute('href', /ecode360|pittsburgh/);
    // The district's own rules for any building, from the rule file, with sections.
    await zoning.getByRole('button', { name: /district rules for any building/ }).click();
    await expect(zoning.locator('[data-district-rules]')).toContainText('Smallest lot');
    await expect(zoning.locator('[data-district-rules] a').first()).toHaveAttribute('href', /ecode360/);
    // Tax: the three Pittsburgh levies in mills and what the unit adds.
    const tax = tab.locator('[data-parcel-tax]');
    await expect(tax).toContainText('Allegheny County');
    await expect(tax).toContainText('Pittsburgh Public Schools');
    await expect(tax).toContainText('mills');
    await expect(tax.locator('[data-unit-tax]')).toContainText(/a year in property tax/);
    await expect(tax).toContainText("does not show the lot's own assessment");
    // Documents: at least one official link, each opening in a new tab.
    const docs = tab.locator('[data-parcel-docs] a');
    expect(await docs.count()).toBeGreaterThan(2);
    await expect(docs.first()).toHaveAttribute('target', '_blank');
    await shot(page, 'parcel-1440-pittsburgh.png');

    // Next Step: the steps, then Be prepared with the parcel number and the questions.
    await page.getByRole('tab', { name: 'Next Step' }).first().click();
    const prep = page.locator('[data-prepare]');
    await expect(prep).toContainText(`Parcel number ${PGH.parcel}`);
    await expect(prep.locator('[data-questions] li').first()).toContainText(/\?$/);
    await expect(prep.getByRole('button', { name: 'Copy the questions' })).toBeVisible();
    await shot(page, 'parcel-1440-prepare.png');

    // The printed report carries the parcel part too.
    await page.getByRole('button', { name: 'Lot report' }).first().click();
    const report = page.getByRole('dialog', { name: 'Lot report' });
    await expect(report.locator('[data-report-parcel]')).toContainText('Property tax');
    await expect(report).toContainText('Ask the zoning office');
  });

  test('Narberth: the town rates, the school district and the county record link', async ({ page }) => {
    test.skip(!has('montgomery_county', NAR.tract), `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${NAR.lot}&tract=${NAR.tract}`);
    await expect(verdict(page)).toBeVisible();
    await page.getByRole('tab', { name: 'Parcel' }).first().click();
    const tab = page.locator('[data-parcel-tab]');
    await expect(tab.locator('[data-parcel-number]')).toHaveText(NAR.parcel);
    await expect(tab).toContainText('Narberth borough');
    await expect(tab).toContainText('Montgomery County');
    await expect(tab).toContainText('School District of Lower Merion');
    await expect(tab.locator('[data-parcel-tax]')).toContainText('Montgomery County Community College');
    await expect(tab.locator('[data-parcel-docs] a', { hasText: 'Montgomery County' }).first()).toHaveAttribute('href', /pin=120000004002/);
    await expect(tab.locator('[data-parcel-tax]')).toContainText('mills');
    await shot(page, 'parcel-1440-narberth.png');
  });

  test('phone: the sheet has five tabs and the Parcel tab works', async ({ page }) => {
    test.skip(!has('pittsburgh', PGH.tract), `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/#/?view=test&lot=${PGH.lot}&tract=${PGH.tract}`);
    const tabs = page.getByRole('tablist', { name: 'Results' }).first();
    await expect(tabs.getByRole('tab')).toHaveCount(5);
    await tabs.getByRole('tab', { name: 'Parcel' }).click();
    await expect(page.locator('[data-parcel-number]').first()).toHaveText(PGH.parcel);
    // No tab label is cut or wraps: every label fits inside its tab on one line.
    for (const t of await tabs.getByRole('tab').all()) {
      const fits = await t.evaluate((el) => {
        const label = el.querySelector('span.relative') as HTMLElement;
        const r = label.getBoundingClientRect();
        const b = el.getBoundingClientRect();
        return r.left >= b.left - 0.5 && r.right <= b.right + 0.5 && r.height < 22;
      });
      expect(fits).toBe(true);
    }
    await shot(page, 'parcel-390-phone.png');
  });
});
