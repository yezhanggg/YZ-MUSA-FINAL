// "Testable Lots": the switch in the Test Project panel puts the lot answer layers and the map legend on, and taking
// it off removes both. Uses the lot tiles on the external drive (LOT_DATA_DIR, default ~/musa-drive/lots) and skips
// when they are not there. The map element lists the testable-lot layers it draws in data-testable.
import { existsSync } from 'node:fs';
import { homedir } from 'node:os';
import { resolve } from 'node:path';
import { expect, test } from '@playwright/test';

const LOTS = resolve(process.env.LOT_DATA_DIR ?? resolve(homedir(), 'musa-drive/lots'));
const hasTiles = ['lots.pmtiles', 'overview.pmtiles'].every((f) => existsSync(resolve(LOTS, 'pittsburgh/tiles', f)));

test.describe('show testable lots', () => {
  test.skip(!hasTiles, `no lot tiles at ${LOTS}`);

  test('the switch adds the layers and the legend, and removes them again', async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 900 });
    await page.goto('/#/?view=test');
    const sw = page.getByRole('switch', { name: 'Testable Lots' });
    const map = page.locator('[aria-label^="Map of Pennsylvania"]'); // the main map (a selected lot adds a second one)
    const legend = page.getByRole('group', { name: 'Testable lots legend' });

    // Off by default: the map is ready and draws nothing extra, and there is no legend.
    await expect(sw).toHaveAttribute('aria-checked', 'false');
    await expect(map).toHaveAttribute('data-testable', '');
    await expect(legend).toHaveCount(0);
    // One button per city, each with its lot count from the place manifest.
    for (const place of ['pittsburgh', 'philadelphia', 'allentown']) await expect(page.locator(`[data-place="${place}"]`)).toHaveText(/\d{1,3}(,\d{3})* Lots$/);
    // The legend is a card under the left panel, not over the map.
    const panel = page.locator('aside[aria-label="Search and map controls"]');

    await sw.click();
    await expect(sw).toHaveAttribute('aria-checked', 'true');
    await expect(legend).toBeVisible();
    const [p, l] = [(await panel.boundingBox())!, (await legend.boundingBox())!];
    expect(l.y).toBeGreaterThanOrEqual(p.y + p.height);
    expect(Math.round(l.x)).toBe(Math.round(p.x));
    expect(Math.round(l.width)).toBe(Math.round(p.width));
    for (const label of ['Allowed and fits', 'Allowed, does not fit', 'Not allowed']) await expect(legend).toContainText(label);
    await expect(legend).toContainText('Squares: most common answer'); // the state map is below lot level
    await expect(map).toHaveAttribute('data-testable', /parcels-pgh-overview/);
    await expect(map).toHaveAttribute('data-testable', /parcels-pgh-fill/);
    // A view setting like the aerial photo: not written into the link.
    expect(new URL(page.url()).hash).not.toMatch(/lots/i);

    await sw.click();
    await expect(sw).toHaveAttribute('aria-checked', 'false');
    await expect(legend).toHaveCount(0);
    await expect(map).toHaveAttribute('data-testable', '');
  });
});
