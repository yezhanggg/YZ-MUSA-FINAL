// One box at the bottom left for an address or a question (AskDock). A question opens ParcelIQ above the box; an
// address lists its matches with "Ask ParcelIQ" last. ParcelIQ answers after the thinking pill (at least 4 s),
// "Explain more" asks again, its right and top edges drag its size, Escape closes it, and Details stays on the right.
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';
import { lotDataDir } from '../devData';
import { expect, test, type Page } from '@playwright/test';

const LOTS = lotDataDir();
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300', place: 'pittsburgh' };
const hasPgh = existsSync(resolve(LOTS, PGH.place, 'detail', `${PGH.tract}.json.gz`));

const chat = (page: Page) => page.getByRole('dialog', { name: 'ParcelIQ' });
const box = (page: Page) => page.getByRole('combobox', { name: /ask ParcelIQ/ });
/** The whole box (the input sits inside it, after the search icon). */
const bar = (page: Page) => page.locator('[data-ask-dock] > div').last();
const details = (page: Page) => page.locator('aside[aria-label="Ask and report"]');

/** The context block of each question sent to the agent (AskBox.tsx useAskContext). */
async function contextOf(page: Page, seen: Record<string, unknown>[]) {
  await page.route('**/api/agent', async (r) => {
    const body = r.request().postDataJSON() as { context?: Record<string, unknown> };
    seen.push(body.context ?? {});
    await r.fulfill({ json: { type: 'final', text: '**Mostly allowed**\nMost homes here are in towns that allow an ADU.' } });
  });
}

async function fakeAgent(page: Page, asked: string[]) {
  await page.route('**/api/agent', async (r) => {
    const body = r.request().postDataJSON() as { messages: { role: string; content: unknown }[] };
    const last = body.messages.filter((m) => m.role === 'user' && typeof m.content === 'string').pop();
    asked.push(String(last?.content ?? ''));
    await r.fulfill({ json: { type: 'final', text: asked.length === 1 ? '**Yes**\nThe yard has room.\n**What to do:** Ask the town.' : 'Here are the details.' } });
  });
}

test.describe('ParcelIQ and the one search box', () => {
  test('a question typed in the box opens ParcelIQ above it, answered after the pill; Explain more; Escape closes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const asked: string[] = [];
    await fakeAgent(page, asked);
    await page.goto('/#/?view=test');
    // The left panel has no search box on desktop: the one box is at the bottom left.
    await expect(page.locator('aside[aria-label="Search and map controls"]').getByRole('combobox')).toHaveCount(0);
    const b = (await bar(page).boundingBox())!;
    expect(b.x).toBeLessThan(30);
    expect(b.y + b.height).toBeGreaterThan(900 - 30);
    // A question: one row, "Ask ParcelIQ", and Enter asks.
    await box(page).fill('Can I build an ADU in Narberth?');
    await expect(page.locator('[data-ask-row]')).toBeVisible();
    const t0 = Date.now();
    await box(page).press('Enter');
    await expect(chat(page)).toBeVisible();
    await expect(box(page)).toHaveValue('');
    await expect(chat(page).getByRole('status')).toBeVisible(); // the thinking pill
    await expect(chat(page).getByText('The yard has room.')).toBeVisible({ timeout: 15000 });
    expect(Date.now() - t0).toBeGreaterThan(3900);
    await expect(chat(page).locator('strong', { hasText: 'Yes' })).toBeVisible();
    // ParcelIQ sits above the box, at the left; Details did not open.
    const c = (await chat(page).boundingBox())!;
    expect(c.x).toBeLessThan(30);
    expect(c.y + c.height).toBeLessThanOrEqual(b.y + 1);
    await expect(details(page)).toHaveCount(0);
    await chat(page).getByRole('button', { name: 'Explain more' }).click();
    await expect(chat(page).getByText('Here are the details.')).toBeVisible({ timeout: 15000 });
    expect(asked).toEqual(['Can I build an ADU in Narberth?', 'Explain more']);
    await page.keyboard.press('Escape');
    await expect(chat(page)).toHaveCount(0);
    // No ParcelIQ button on the map: a click in the box opens it again, with the conversation kept.
    await expect(page.getByRole('button', { name: 'ParcelIQ', exact: true })).toHaveCount(0);
    await box(page).click();
    await expect(chat(page).getByText('Here are the details.')).toBeVisible();
    await chat(page).getByRole('button', { name: /Clear Chat/ }).click();
    await expect(chat(page).getByText('Hi there!')).toBeVisible();
  });

  test('a click in the box opens ParcelIQ; typing an address puts it aside for the address list', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.route('https://photon.komoot.io/**', (r) => r.fulfill({ json: { features: [{ geometry: { coordinates: [-79.93, 40.43] }, properties: { state: 'Pennsylvania', housenumber: '5459', street: 'Beacon Street', city: 'Pittsburgh', county: 'Allegheny' } }] } }));
    await page.goto('/#/?view=test');
    await box(page).click();
    await expect(chat(page)).toBeVisible();
    await box(page).fill('5459 Beacon St');
    await expect(chat(page)).toHaveCount(0);
    await expect(page.getByRole('option').first()).toContainText('5459 Beacon');
    await box(page).fill('');
    await expect(chat(page)).toBeVisible();
    await box(page).fill('What is an ADU?');
    await expect(chat(page)).toBeVisible();
  });

  test('ParcelIQ reaches up to the Controls panel, sits right on the box, and its right edge drags the width', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(() => window.localStorage.removeItem('bh.chatSize'));
    await page.goto('/#/?view=test');
    await box(page).click();
    await expect(chat(page)).toBeVisible();
    await page.waitForTimeout(800);
    const c0 = (await chat(page).boundingBox())!;
    const left = (await page.locator('aside[aria-label="Search and map controls"]').boundingBox())!;
    const b = (await bar(page).boundingBox())!;
    // Its top just under the Controls panel (one gutter), its bottom on the box with no gap.
    expect(Math.abs(c0.y - (left.y + left.height + 12))).toBeLessThan(4);
    expect(Math.abs(c0.y + c0.height - b.y)).toBeLessThan(2);
    // Folding a card makes the panel shorter: ParcelIQ grows up to follow it.
    await page.locator('section[aria-label="Boundaries"]').getByRole('button', { name: 'Boundaries', exact: true }).click({ force: true });
    await expect.poll(async () => (await chat(page).boundingBox())!.height).not.toBe(c0.height);
    const g = (await page.getByRole('separator', { name: 'Resize ParcelIQ width' }).boundingBox())!;
    await page.mouse.move(g.x + g.width / 2, g.y + g.height / 2);
    await page.mouse.down();
    await page.mouse.move(g.x + g.width / 2 + 140, g.y + g.height / 2, { steps: 6 });
    await page.mouse.up();
    await expect.poll(async () => (await chat(page).boundingBox())!.width).toBeGreaterThan(c0.width + 100);
    await expect.poll(async () => Math.abs((await bar(page).boundingBox())!.width - (await chat(page).boundingBox())!.width)).toBeLessThan(3);
    await page.getByRole('separator', { name: 'Resize ParcelIQ width' }).dblclick();
    await expect.poll(async () => Math.abs((await chat(page).boundingBox())!.width - c0.width)).toBeLessThan(4);
  });

  test('"move the map to Philly": ParcelIQ flies there and shows the lots that can be tested', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    let n = 0;
    await page.route('**/api/agent', async (r) => {
      n += 1;
      if (n === 1) await r.fulfill({ json: { type: 'tool_use', content: [{ type: 'tool_use', id: 't1', name: 'set_map', input: { action: 'fly_to_place', place: 'Philly' } }], calls: [{ id: 't1', name: 'set_map', input: { action: 'fly_to_place', place: 'Philly' } }] } });
      else await r.fulfill({ json: { type: 'final', text: 'The map is on Philadelphia. Click a lot to test it.' } });
    });
    await page.goto('/#/?view=test');
    await box(page).fill('move the map to Philly');
    await box(page).press('Enter');
    await expect(chat(page).getByText('The map is on Philadelphia.')).toBeVisible({ timeout: 20000 });
    await expect(page.locator('section[aria-label="Testable Lots"]').getByRole('switch')).toHaveAttribute('aria-checked', 'true');
  });


  test('an area picked on a boundary: ParcelIQ offers a question about it and sends the area with the question', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const seen: Record<string, unknown>[] = [];
    await contextOf(page, seen);
    await page.goto('/#/?view=test');
    // County is on at the start and coloured by its rule. A click in the open map picks the county under it.
    const map = page.locator('[aria-label^="Map of Pennsylvania"]');
    await expect(map).toHaveAttribute('data-rules', 'county:ready');
    await page.mouse.click(880, 430);
    await expect(map).toHaveAttribute('data-area-kind', 'county');
    const geoid = await map.getAttribute('data-area-pick');
    await box(page).click();
    await expect(chat(page)).toBeVisible();
    await chat(page).getByRole('button', { name: 'Can I build an ADU here?' }).click();
    await expect.poll(() => seen.length).toBeGreaterThan(0);
    expect(seen[0].area).toMatchObject({ kind: 'county', geoid });
  });

  test('with a lot open, ParcelIQ stays at the left and Details on the right, with a topic for the lot', async ({ page }) => {
    test.skip(!hasPgh, `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto(`/#/?view=test&lot=${PGH.lot}&tract=${PGH.tract}`);
    await expect(details(page)).toBeVisible();
    await box(page).click();
    await expect(chat(page)).toBeVisible();
    await expect(chat(page).getByRole('button', { name: 'Can I build an ADU on this lot?' })).toBeVisible();
    const c = (await chat(page).boundingBox())!;
    const d = (await details(page).boundingBox())!;
    expect(c.x + c.width).toBeLessThan(d.x);
  });
});
