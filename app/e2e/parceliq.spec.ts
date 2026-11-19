// ParcelIQ: the map button opens the chat over the map area without opening Details, a topic sends a question, the
// answer waits behind the thinking pill for at least 4 s, "Explain more" asks again, and with a lot open the chat and
// Details split the space with a drag bar. Escape closes the chat.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300', place: 'pittsburgh' };
const hasPgh = existsSync(resolve(LOTS, PGH.place, 'detail', `${PGH.tract}.json.gz`));

const chat = (page: Page) => page.getByRole('dialog', { name: 'ParcelIQ' });
const details = (page: Page) => page.locator('aside[aria-label="Ask and report"]');

async function fakeAgent(page: Page, asked: string[]) {
  await page.route('**/api/agent', async (r) => {
    const body = r.request().postDataJSON() as { messages: { role: string; content: unknown }[] };
    const last = body.messages.filter((m) => m.role === 'user' && typeof m.content === 'string').pop();
    asked.push(String(last?.content ?? ''));
    await r.fulfill({ json: { type: 'final', text: asked.length === 1 ? '**Yes**\nThe yard has room.\n**What to do:** Ask the town.' : 'Here are the details.' } });
  });
}

test.describe('ParcelIQ', () => {
  test('opens full width over the map, a topic is answered after the pill, Explain more asks again, Escape closes', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const asked: string[] = [];
    await fakeAgent(page, asked);
    await page.goto('/#/?view=test');
    await page.getByRole('button', { name: 'ParcelIQ', exact: true }).click();
    await expect(chat(page)).toBeVisible();
    await expect(details(page)).toHaveCount(0);
    const box = (await chat(page).boundingBox())!;
    expect(box.width).toBeGreaterThan(800);
    const t0 = Date.now();
    await chat(page).getByRole('button', { name: 'What is an ADU?' }).click();
    await expect(chat(page).getByRole('status')).toBeVisible(); // the thinking pill
    await expect(chat(page).getByText('The yard has room.')).toBeVisible({ timeout: 15000 });
    expect(Date.now() - t0).toBeGreaterThan(3900);
    await expect(chat(page).locator('strong', { hasText: 'Yes' })).toBeVisible();
    await chat(page).getByRole('button', { name: 'Explain more' }).click();
    await expect(chat(page).getByText('Here are the details.')).toBeVisible({ timeout: 15000 });
    expect(asked).toEqual(['What is an ADU?', 'Explain more']);
    await page.keyboard.press('Escape');
    await expect(chat(page)).toHaveCount(0);
    // The conversation is kept.
    await page.getByRole('button', { name: 'ParcelIQ', exact: true }).click();
    await expect(chat(page).getByText('Here are the details.')).toBeVisible();
  });

  test('with a lot open, chat and Details split the space and the bar drags', async ({ page }) => {
    test.skip(!hasPgh, `no lot records at ${LOTS}`);
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript(() => window.localStorage.removeItem('bh.chatSplit'));
    await page.goto(`/#/?view=test&lot=${PGH.lot}&tract=${PGH.tract}`);
    await expect(details(page)).toBeVisible();
    await page.getByRole('button', { name: 'ParcelIQ', exact: true }).click();
    await expect(chat(page)).toBeVisible();
    await expect(chat(page).getByRole('button', { name: 'Can I build an ADU on this lot?' })).toBeVisible();
    const bar = page.getByRole('separator', { name: 'Resize ParcelIQ and Details' });
    await expect(bar).toBeVisible();
    await page.waitForTimeout(400);
    const w0 = (await chat(page).boundingBox())!.width;
    const d0 = (await details(page).boundingBox())!.width;
    expect(Math.abs(w0 - d0)).toBeLessThan(40); // half and half
    const b = (await bar.boundingBox())!;
    await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2);
    await page.mouse.down();
    await page.mouse.move(b.x - 150, b.y + b.height / 2, { steps: 6 });
    await page.mouse.up();
    const w1 = (await chat(page).boundingBox())!.width;
    expect(w1).toBeLessThan(w0 - 100);
    await bar.dblclick();
    await expect.poll(async () => Math.round((await chat(page).boundingBox())!.width)).toBe(Math.round(w0));
    // Closing Details gives the chat the full width.
    await page.getByRole('button', { name: 'Hide the details' }).click();
    await expect(bar).toHaveCount(0);
    await expect.poll(async () => (await chat(page).boundingBox())!.width).toBeGreaterThan(w0 + 200);
  });
});
