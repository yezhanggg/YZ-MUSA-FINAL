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

  test('the map credits are a line in the left panel, with no button on the map', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const credits = page.locator('aside[aria-label="Search and map controls"] [data-map-credits]');
    await expect(credits).toContainText('OpenStreetMap');
    await expect(credits.getByRole('link', { name: /OpenStreetMap/ })).toHaveAttribute('href', /openstreetmap\.org/);
    await expect(page.locator('[aria-label^="Map of Pennsylvania"] .maplibregl-ctrl-attrib')).toHaveCount(0);
    await expect(page.locator('aside[aria-label="Search and map controls"]')).not.toContainText('Lot data:');
    await expect(page.getByRole('button', { name: 'How it works →' })).toBeVisible();
  });
});
