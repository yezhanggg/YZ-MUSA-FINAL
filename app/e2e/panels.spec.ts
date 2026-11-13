// The right panel: the Results tab stays short (word budget), the site view zooms, the panel resizes from its
// left edge and keeps that width after a reload, and the content reflows at any width with no sideways scroll.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const PGH = { lot: '42003-0086N00208000000', tract: '42003141300', place: 'pittsburgh' };
const PHL = { lot: '42101-011000034', tract: '42101002702', place: 'philadelphia' };
const has = (l: typeof PGH) => existsSync(resolve(LOTS, l.place, 'detail', `${l.tract}.json.gz`));
const url = (l: typeof PGH) => `/#/?view=test&lot=${l.lot}&tract=${l.tract}`;
const WIDTH_KEY = 'bh.rightPanelWidth';
/** Words a person sees in the Results tab with a lot open and nothing opened. */
const WORD_BUDGET = 90;

const panel = (page: Page) => page.locator('aside[aria-label="Ask and report"]');
const body = (page: Page) => panel(page).locator('> div.scroll-quiet');
const verdict = (page: Page) => page.locator('section[aria-label="Verdict"]').first();
const panelWidth = (page: Page) => panel(page).evaluate((n) => Math.round(n.getBoundingClientRect().width));

async function open(page: Page, l: typeof PGH) {
  await page.goto(url(l));
  await expect(verdict(page)).toBeVisible();
}

test.describe('right panel', () => {
  test.skip(!has(PGH) || !has(PHL), `no lot records at ${LOTS}`);

  test('the Results tab shows at most 90 words on both demo lots', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    for (const l of [PGH, PHL]) {
      await open(page, l);
      await expect(page.locator('section[aria-label="Rule checklist"]')).toBeVisible();
      const text = await body(page).evaluate((n) => (n as HTMLElement).innerText);
      const words = text.split(/\s+/).filter((w) => /[A-Za-z0-9]/.test(w)).length;
      console.log(`${l.place}: ${words} words in the Results tab`);
      expect(words).toBeLessThanOrEqual(WORD_BUDGET);
      // Everything else starts folded.
      for (const b of await body(page).locator('section > button[aria-expanded]').all()) await expect(b).toHaveAttribute('aria-expanded', 'false');
    }
  });

  test('the drag handle changes the width, and the width survives a reload', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.addInitScript((k) => {
      if (!sessionStorage.getItem('bh-test-started')) {
        sessionStorage.setItem('bh-test-started', '1');
        localStorage.removeItem(k);
      }
    }, WIDTH_KEY);
    await open(page, PGH);
    expect(await panelWidth(page)).toBe(630);
    const handle = page.getByRole('separator', { name: 'Resize the results panel' });
    await expect(handle).toHaveAttribute('aria-orientation', 'vertical');
    const box = (await handle.boundingBox())!;
    const y = box.y + box.height / 2;
    await page.mouse.move(box.x + box.width / 2, y);
    await page.mouse.down();
    await page.mouse.move(box.x + box.width / 2 - 100, y, { steps: 6 });
    await page.mouse.up();
    await expect.poll(() => panelWidth(page)).toBe(730);
    // Arrow keys move it by 16 px; left is wider.
    await handle.focus();
    await page.keyboard.press('ArrowRight');
    await expect.poll(() => panelWidth(page)).toBe(714);
    await page.reload();
    await expect(verdict(page)).toBeVisible();
    expect(await panelWidth(page)).toBe(714);
    // Never past the room the map needs, never under 360; a double-click goes back to 630.
    await handle.focus();
    await page.keyboard.press('End');
    await expect.poll(() => panelWidth(page)).toBe(1440 - 300 - 4 * 12 - 320);
    await page.keyboard.press('Home');
    await expect.poll(() => panelWidth(page)).toBe(360);
    await handle.dblclick();
    await expect.poll(() => panelWidth(page)).toBe(630);
  });

  test('the site view zooms (buttons, wheel after a rest), turns with Cmd + drag, and recentre frames the lot again', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, PGH);
    const site = page.locator('section[aria-label="Aerial and site view"]');
    await site.scrollIntoViewIfNeeded();
    await expect(site).toHaveAttribute('data-zoom', /\d/);
    const zoom = async () => Number(await site.getAttribute('data-zoom'));
    const z0 = await zoom();
    await site.getByRole('button', { name: 'Zoom in on the site' }).click();
    await expect.poll(zoom).toBeGreaterThan(z0 + 0.5);
    await site.getByRole('button', { name: 'Zoom out on the site' }).click();
    await site.getByRole('button', { name: 'Zoom out on the site' }).click();
    await expect.poll(zoom).toBeLessThan(z0 - 0.5);
    await site.getByRole('button', { name: 'Recentre on the lot' }).click();
    await expect.poll(zoom).toBeCloseTo(z0, 1);
    // A wheel that only passes over the site map scrolls the panel; once the pointer rests on the map, it zooms.
    const before = await body(page).evaluate((n) => n.scrollTop);
    const box = (await site.locator('canvas').first().boundingBox())!;
    await page.mouse.move(box.x - 40, box.y + box.height / 2);
    await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
    // Scroll toward whichever end has room (the panel may already sit at its bottom).
    await page.mouse.wheel(0, before > 0 ? -300 : 300);
    await expect.poll(() => body(page).evaluate((n) => n.scrollTop)).not.toBe(before);
    await page.waitForTimeout(400);
    expect(await zoom()).toBeCloseTo(z0, 1);
    const box2 = (await site.locator('canvas').first().boundingBox())!;
    await page.mouse.move(box2.x + box2.width / 3, box2.y + box2.height / 2);
    await page.mouse.move(box2.x + box2.width / 3 + 4, box2.y + box2.height / 2 + 2);
    await page.waitForTimeout(700);
    await page.mouse.wheel(0, -200);
    await expect.poll(zoom).toBeGreaterThan(z0 + 0.1);
    // Cmd / Ctrl + drag turns the view (bearing and pitch).
    const b0 = Number(await site.getAttribute('data-bearing'));
    const mod = (await page.evaluate(() => /Mac|iPhone|iPad/.test(navigator.platform))) ? 'Meta' : 'Control';
    await site.scrollIntoViewIfNeeded();
    const box3 = (await site.locator('canvas').first().boundingBox())!;
    const [ox, oy] = [box3.x + box3.width * 0.3, box3.y + box3.height * 0.5];
    await page.keyboard.down(mod);
    await page.mouse.move(ox, oy);
    await page.mouse.down();
    await page.mouse.move(ox + 120, oy - 20, { steps: 6 });
    await page.mouse.up();
    await page.keyboard.up(mod);
    await expect.poll(async () => Number(await site.getAttribute('data-bearing'))).not.toBeCloseTo(b0, 0);
  });

  test('the chat box grows to at most half the column, the results box keeps the rest, and it minimises into the Chat button', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    const long = Array.from({ length: 30 }, (_, i) => `Line ${i + 1} of a long answer about this lot.`).join('\n');
    await page.route('**/api/agent', (r) => r.fulfill({ json: { type: 'final', text: long } }));
    await open(page, PGH);
    const chat = page.locator('section[aria-label="Ask"]');
    const column = panel(page).locator('..'); // the right column: results box, chat box, map controls row
    const input = chat.locator('input[aria-label="Ask about this site"]');
    for (const q of ['Does this unit fit here?', 'What limits it on this lot?']) {
      await input.fill(q);
      await input.press('Enter');
      await expect(chat.getByText('Line 30 of a long answer about this lot.').last()).toBeAttached();
    }
    await page.waitForTimeout(800); // the conversation's open animation
    const [c, col, res] = await Promise.all([chat.boundingBox(), column.boundingBox(), panel(page).boundingBox()]);
    console.log(`chat ${Math.round(c!.height)} px, results ${Math.round(res!.height)} px, column ${Math.round(col!.height)} px`);
    expect(c!.height).toBeLessThanOrEqual(col!.height * 0.5 + 1);
    expect(res!.height).toBeGreaterThanOrEqual(col!.height * 0.45 - 1);
    // The conversation scrolls inside the chat box.
    await expect.poll(() => chat.evaluate((n) => n.scrollHeight > n.clientHeight)).toBe(true);
    // Minimised: the chat box goes into the "Chat" button of the controls row and the results box takes the height.
    await chat.getByRole('button', { name: 'Minimise chat' }).click();
    await expect(chat).toHaveCount(0);
    const chatButton = page.getByRole('button', { name: 'Chat', exact: true });
    await expect(chatButton).toBeVisible();
    await expect.poll(async () => (await panel(page).boundingBox())!.height).toBeGreaterThan(res!.height + 100);
    await page.reload();
    await expect(verdict(page)).toBeVisible();
    await expect(page.getByRole('button', { name: 'Chat', exact: true })).toBeVisible(); // remembered
    await page.getByRole('button', { name: 'Chat', exact: true }).click();
    await expect(page.locator('section[aria-label="Ask"]')).toBeVisible();
  });

  test('each side hides and comes back, and stays as left after a reload', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await open(page, PGH);
    const left = page.locator('aside[aria-label="Search and map controls"]');
    await page.getByRole('button', { name: 'Hide the controls' }).click();
    await expect(left).toHaveCount(0);
    await page.getByRole('button', { name: 'Hide the details' }).click();
    await expect(panel(page)).toHaveCount(0);
    // Full map: the show buttons at the edges, the map controls and a Chat button stay on the map.
    await expect(page.getByRole('button', { name: 'Show the controls' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Show the details' })).toBeVisible();
    await expect(page.getByRole('radiogroup', { name: 'Map view' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Chat', exact: true })).toBeVisible();
    await page.reload();
    await expect(page.getByRole('button', { name: 'Show the controls' })).toBeVisible();
    await page.getByRole('button', { name: 'Show the controls' }).focus();
    await page.keyboard.press('Enter');
    await expect(left).toBeVisible();
    await page.getByRole('button', { name: 'Show the details' }).click();
    await expect(panel(page)).toBeVisible();
  });

  test('a click on a lot in the main map fills the Details box with the answer', async ({ page }) => {
    for (const [w, h] of [[1440, 900], [1280, 720]] as const) {
      await page.setViewportSize({ width: w, height: h });
      await open(page, PGH); // the map flies to the lot and centres it in the open map
      const l = (await page.locator('aside[aria-label="Search and map controls"]').boundingBox())!;
      const r = (await panel(page).boundingBox())!;
      // Click the centre of the open map: the selected lot is drawn there.
      await page.goto('about:blank');
      await page.goto('/#/?view=test');
      await expect(page.getByRole('combobox', { name: 'Search an address in Pennsylvania' })).toBeEnabled();
      await page.locator('[data-place="pittsburgh"]').click();
      await page.waitForTimeout(4000);
      // Lots are dense in the Pittsburgh view: try points across the open map until one opens a lot record
      // (a street or a non-home lot opens none).
      let ok = false;
      const xs = [0.5, 0.35, 0.65, 0.42, 0.58].map((f) => l.x + l.width + 12 + (r.x - l.x - l.width - 24) * f);
      for (const y of [0.5, 0.35, 0.65].map((f) => h * f)) {
        for (const x of xs) {
          await page.mouse.click(x, y);
          try {
            await expect(verdict(page)).toBeVisible({ timeout: 6_000 });
            ok = true;
          } catch {
            /* try the next point */
          }
          if (ok) break;
        }
        if (ok) break;
      }
      expect(ok, `no lot opened at ${w}x${h}`).toBe(true);
      const vh = (await verdict(page).boundingBox())!.height;
      const bh = await body(page).evaluate((n) => n.getBoundingClientRect().height);
      console.log(`${w}x${h}: answer card ${Math.round(vh)} px, Details body ${Math.round(bh)} px`);
      expect(vh).toBeGreaterThan(40);
      expect(bh).toBeGreaterThan(200);
    }
  });

  for (const w of [360, 480, 630, 900]) {
    test(`content reflows with no sideways scroll at ${w} px`, async ({ page }) => {
      await page.setViewportSize({ width: 1728, height: 1000 });
      await page.addInitScript(([k, v]) => localStorage.setItem(k, v), [WIDTH_KEY, String(w)] as const);
      for (const l of [PGH, PHL]) {
        await open(page, l);
        expect(await panelWidth(page)).toBe(w);
        // Open every fold too, so the long content is checked as well (the folds stay open on the next lot).
        const closed = body(page).locator('section > button[aria-expanded="false"]');
        for (let i = 0; i < 8 && (await closed.count()) > 0; i++) await closed.first().click();
        const wide = await panel(page).evaluate((root) => {
          const out: string[] = [];
          const r = root.getBoundingClientRect();
          for (const el of root.querySelectorAll<HTMLElement>('*')) {
            const s = getComputedStyle(el);
            if ((s.overflowX === 'auto' || s.overflowX === 'scroll') && el.scrollWidth > el.clientWidth + 1) out.push(`scrolls: ${el.className}`);
            const b = el.getBoundingClientRect();
            if (b.width > 0 && b.right > r.right + 1 && !el.closest('.maplibregl-map')) out.push(`sticks out: ${el.tagName}.${el.className}`);
          }
          return out.slice(0, 5);
        });
        expect(wide, `${l.place} at ${w}`).toEqual([]);
      }
    });
  }
});
