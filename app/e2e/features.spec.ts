// The top bar's Features menu (Test Site and Explore) and the left panel footer: map credits in one line, no
// attribution button on the map, no lot data dates.
import { expect, test } from '@playwright/test';

test.describe('features menu and footer', () => {
  test('Features opens on hover and focus, marks the open view, switches views and closes on Escape', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const button = page.getByRole('button', { name: 'Features' });
    await expect(button).toHaveAttribute('aria-haspopup', 'menu');
    await button.hover();
    const menu = page.getByRole('menu', { name: 'Features' });
    await expect(menu).toBeVisible();
    await expect(menu.getByRole('menuitemradio', { name: /^Test Site/ })).toHaveAttribute('aria-checked', 'true');
    await expect(menu.getByRole('menuitemradio', { name: /^Explore/ })).toHaveAttribute('aria-checked', 'false');
    await page.keyboard.press('Escape');
    await expect(menu).toHaveCount(0);
    await button.focus();
    await expect(menu).toBeVisible();
    await menu.getByRole('menuitemradio', { name: /^Explore/ }).click();
    await expect.poll(() => new URL(page.url()).hash).toContain('view=project');
    await button.click();
    await expect(page.getByRole('menuitemradio', { name: /^Explore/ })).toHaveAttribute('aria-checked', 'true');
    // Old links keep working.
    await page.goto('/#/?view=test');
    await expect(page.getByRole('radiogroup', { name: 'Zoning Regulation' })).toBeVisible();
  });

  test('the map shows one small OpenStreetMap credit, the left panel no credits and no footer link', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const credit = page.locator('[data-osm-credit]');
    await expect(credit).toHaveText('© OpenStreetMap');
    await expect(credit).toHaveAttribute('href', 'https://www.openstreetmap.org/copyright');
    const box = (await credit.boundingBox())!;
    expect(box.x + box.width).toBeGreaterThan(1440 - 40); // bottom right corner of the map
    expect(box.y + box.height).toBeGreaterThan(900 - 20);
    await expect(page.locator('[aria-label^="Map of Pennsylvania"] .maplibregl-ctrl-attrib')).toHaveCount(0);
    const left = page.locator('aside[aria-label="Search and map controls"]');
    await expect(left).not.toContainText('Lot data:');
    await expect(left).not.toContainText('OpenFreeMap');
    await expect(left.getByRole('button', { name: /How it works/ })).toHaveCount(0);
  });

  test('the left panel is as tall as what is open, and the map under it takes clicks', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const left = page.locator('aside[aria-label="Search and map controls"]');
    await expect(left.locator('section[aria-label="Boundaries"]')).toBeVisible();
    const short = (await left.boundingBox())!.height;
    expect(short).toBeLessThan(900 - 100);
    // Opening ADU Design makes it taller (up to the window, then it scrolls inside).
    await page.locator('section[aria-label="ADU Design"]').getByRole('button', { name: 'ADU Design', exact: true }).click();
    await expect.poll(async () => (await left.boundingBox())!.height).toBeGreaterThan(short + 100);
    expect((await left.boundingBox())!.height).toBeLessThanOrEqual(900 - 24 + 1);
    await page.locator('section[aria-label="ADU Design"]').getByRole('button', { name: 'ADU Design', exact: true }).click();
    // Below the short panel: the map, not the panel's column, is under the pointer.
    const b = (await left.boundingBox())!;
    const hit = await page.evaluate(([x, y]) => document.elementFromPoint(x, y)?.tagName, [b.x + b.width / 2, b.y + b.height + 40]);
    expect(hit).toBe('CANVAS');
  });
});
