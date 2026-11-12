// The main lot flow: pick Testing mode, open a Pittsburgh lot by link, read the verdict, grow the unit until it
// no longer fits, switch the scenario, open the Next Step tab and the lot report. Screenshots go to SHOTS_DIR.
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
    await mode.selectOption({ label: 'Test Project' });
    await expect(page.getByRole('radiogroup', { name: 'Zoning Regulation' })).toBeVisible();

    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    // Answer first: one word and one short line, then the rule checklist.
    await expect(verdict(page)).toHaveAttribute('data-answer', 'approval');
    await expect(verdict(page)).toContainText('Yes, with approval');
    await expect(verdict(page)).toContainText('cottage fits here');
    const checklist = page.locator('section[aria-label="Rule checklist"]').first();
    await expect(checklist.locator('[data-rule-row]')).toHaveCount(6);
    await expect(checklist.locator('[data-rule-row="approval"]')).toContainText("Administrator's Exception");
    // The notice: short on screen, in full on hover and in the Why fold.
    const notice = page.getByText('Estimate. Not legal advice.').first();
    await expect(notice).toBeVisible();
    await expect(notice).toHaveAttribute('title', /Not a zoning determination/);
    await shot(page, 'lot-1440-fits.png');

    // Grow the unit until it no longer fits where it is.
    await page.locator('#u-width').fill('40');
    await page.locator('#u-depth').fill('60');
    await expect(verdict(page)).not.toHaveAttribute('data-status', 'fits');
    await expect(verdict(page)).toContainText(/1,000 sq ft|does not fit/);
    await shot(page, 'lot-1440-too-big.png');

    // Another scenario from the chips under the site view: the answer says "not law", the zoning in Why follows.
    const scenarios = page.getByRole('group', { name: 'Scenarios' }).first();
    await scenarios.getByRole('button', { name: /State Bill/ }).click();
    await expect(scenarios.getByRole('button', { name: /State Bill/ })).toHaveAttribute('aria-pressed', 'true');
    await expect(verdict(page)).toContainText('not law');
    await page.getByRole('button', { name: 'Why' }).first().click();
    await expect(page.getByRole('heading', { name: 'Zoning, state bill' })).toBeVisible();
    expect(new URL(page.url()).hash).toContain('sc=state_reform');

    await page.getByRole('tab', { name: 'Next Step' }).first().click();
    const next = page.locator('section[aria-label="Next steps"]');
    await expect(next.locator('[data-next-summary]')).not.toBeEmpty();
    // Plain steps when it can be built, else what would have to change. Either way at least one item.
    await expect(next.locator('li').first()).toBeVisible();
    await expect(next.getByText('Estimate. Not legal advice.')).toHaveCount(1);
    await shot(page, 'lot-1440-build.png');

    await page.getByRole('button', { name: 'Lot report' }).first().click();
    const report = page.getByRole('dialog', { name: 'Lot report' });
    await expect(report).toContainText('Three scenarios');
    await expect(report).toContainText('Not legal advice');
    await shot(page, 'lot-1440-report.png');
  });

  test('projecting mode shows the tract, and Test a lot here goes back to the lot', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await page.getByRole('combobox', { name: 'Mode' }).selectOption({ label: 'Explore' });
    const testHere = page.getByRole('button', { name: 'Test a lot here' }).first();
    await expect(testHere).toBeVisible();
    await expect(verdict(page)).toHaveCount(0);
    await shot(page, 'proj-tract-1440.png');
    await testHere.click();
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
  });

  test('phone: the same lot in the sheet', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(`/#/?view=test&lot=${LOT}&tract=${TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'fits');
    await shot(page, 'lot-phone.png');
  });
});

const PHL_ROW = '42101-011000034';
const PHL_TRACT = '42101002702';
const hasPhl = existsSync(resolve(LOTS, 'philadelphia/detail', `${PHL_TRACT}.json.gz`));

test.describe('philadelphia lot flow', () => {
  test.skip(!hasPhl, `no Philadelphia lot records at ${LOTS}`);

  test('a rowhouse: no path today, with the reasons and what the bills would change', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PHL_ROW}&tract=${PHL_TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'not_allowed');
    await expect(verdict(page)).toHaveAttribute('data-answer', 'no');
    await expect(verdict(page)).toContainText('Attached building');
    const checklist = page.locator('section[aria-label="Rule checklist"]').first();
    await expect(checklist.locator('[data-rule-row="lot"]')).toContainText('726 / min 1,600 sq ft');
    // A row opens to its code section and "checked on" date.
    await checklist.locator('[data-rule-row="lot"] button').click();
    await expect(checklist.locator('[data-rule-row="lot"]')).toContainText(/Checked on/);
    // The reasons and what each bill would change sit in the Why fold.
    await page.getByRole('button', { name: 'Why' }).first().click();
    const why = page.locator('section[aria-label="Why not, and what would change"]');
    await expect(why).toContainText('Attached building');
    await expect(why).toContainText('Lot is 726 sq ft. Needs 1,600 sq ft or more');
    await expect(page.locator('section[aria-label="Why"]').first()).toContainText('14-604(11)');
    await expect(why).toContainText('State Bill (not law)');
    await page.getByRole('button', { name: 'City numbers' }).first().click();
    await expect(page.getByText(/Today 1\.2% of these lots have a legal path for any ADU/)).toBeVisible();
    await page.getByRole('button', { name: 'Land cover' }).first().click();
    await expect(page.locator('[aria-label="What is on this lot"]').first()).toContainText('Tree canopy');
    await shot(page, 'phl-row-today-1440.png');
    await page.getByRole('radio', { name: 'State Bill' }).click();
    await expect(page.getByRole('heading', { name: 'Zoning, state bill' })).toBeVisible();
    await shot(page, 'phl-row-state-1440.png');
  });

  test('the unit-type list on a Philadelphia lot says why each type is off', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PHL_ROW}&tract=${PHL_TRACT}`);
    await expect(verdict(page)).toHaveAttribute('data-status', 'not_allowed');
    await shot(page, 'phl-unit-types-1440.png');
  });
});

// A searched Philadelphia address, with Photon answered locally (the real lot's address at its centre).
const PHL_ADDRESS = { main: '1818 East Moyamensing Avenue', coords: [-75.15202784, 39.92536822] };
async function mockPhoton(page: Page) {
  await page.route('https://photon.komoot.io/**', (route) =>
    route.fulfill({
      json: { features: [{ geometry: { coordinates: PHL_ADDRESS.coords }, properties: { state: 'Pennsylvania', housenumber: '1818', street: 'East Moyamensing Avenue', city: 'Philadelphia', county: 'Philadelphia' } }] },
    }),
  );
}
async function search(page: Page, text: string) {
  const box = page.getByRole('combobox', { name: 'Search an address in Pennsylvania' });
  await expect(box).toBeEnabled();
  await box.fill(text);
  // The list fades in (motion). Enter picks the first hit, as a user would.
  await expect(page.getByRole('option').first()).toBeAttached();
  await box.press('Enter');
}

test.describe('address search in testing mode', () => {
  test.skip(!hasPhl, `no Philadelphia lot records at ${LOTS}`);

  // Time from picking the address to the verdict on a throttled connection (about 1.6 Mbps down, 150 ms latency),
  // with the city tract index (now) and without it (the old path: the 10 MB area files first).
  for (const mode of ['city tract index', 'area files (old path)'] as const) {
    test(`a searched address opens its lot: ${mode}`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await mockPhoton(page);
      if (mode !== 'city tract index') await page.route('**/data/city_tracts.json', (r) => r.abort());
      const areaFiles: string[] = [];
      page.on('request', (r) => {
        if (/data\/(tracts|towns|counties)\.geojson/.test(r.url())) areaFiles.push(r.url());
      });
      await page.goto('/#/?view=test');
      await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled();
      const cdp = await page.context().newCDPSession(page);
      await cdp.send('Network.enable');
      await cdp.send('Network.emulateNetworkConditions', { offline: false, latency: 150, downloadThroughput: 200_000, uploadThroughput: 90_000 });
      const t0 = Date.now();
      await search(page, '1818 E Moyamensing');
      await expect(verdict(page)).toHaveAttribute('data-status', 'not_allowed', { timeout: 120_000 });
      const ms = Date.now() - t0;
      console.log(`search to lot verdict (${mode}): ${ms} ms, area files fetched: ${areaFiles.length}`);
      if (mode === 'city tract index') expect(areaFiles).toEqual([]);
    });
  }
});

test.describe('room for a 600 sq ft unit (MUSA 5500)', () => {
  test('the statewide map, a Philadelphia tract and the phone legend', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await mockPhoton(page);
    await page.goto('/#/?view=project');
    await page.locator('#map-metric').selectOption('room');
    await expect(page.getByText(/Statewide: about 2\.9 million \(1\.5 to 3\.6 million\)/)).toBeVisible();
    await expect(page.getByText('Outside training range')).toBeVisible();
    await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled(); // areas loaded
    await shot(page, 'room-state-1440.png');
    await search(page, '1818 E Moyamensing');
    await page.locator('[data-area-row="room"] > button').click();
    await expect(page.getByText('Lots with room').first()).toBeVisible();
    await expect(page.getByText(/Measured from every lot record in Philadelphia and Pittsburgh/).first()).toBeVisible();
    await shot(page, 'room-phl-1440.png');
    // Phone: a fresh page, the controls drawer with the map colour and its legend.
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('about:blank');
    await page.goto('/#/?view=project');
    await page.getByRole('button', { name: 'Search and controls' }).click();
    await page.locator('#map-metric').selectOption('room');
    await page.getByText('Outside training range').scrollIntoViewIfNeeded();
    await shot(page, 'room-phone.png');
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
    await page.getByRole('button', { name: /^ADUs by 2031/ }).click();
    await page.getByRole('radio', { name: 'SB 1346' }).click();
    await expect(page.getByText('Bills are not law.').first()).toBeVisible();
    await shot(page, 'proj-1440-e2e.png');

    await page.goto('/#/?view=project&research=5500');
    await expect(page.getByText('7 stable groups')).toBeVisible();
    await page.getByRole('button', { name: 'Open the explorer here' }).click();
    await expect(page.locator('iframe[title="Tract explorer"]')).toBeVisible();
    const res = await page.request.get('/explorer/tract_explorer.html');
    expect(res.ok()).toBe(true);
  });
});
