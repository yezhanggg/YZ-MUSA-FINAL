// Left panel cards fold (Testable Lots and ADU Design start folded). Open one before using what is inside.
import type { Page } from '@playwright/test';

export async function openCard(page: Page, title: 'Testable Lots' | 'ADU Design' | 'Boundaries') {
  const fold = page.locator(`section[aria-label="${title}"]`).getByRole('button', { name: title, exact: true });
  await fold.waitFor();
  if ((await fold.getAttribute('aria-expanded')) === 'false') await fold.click();
}

/** ADU Design's parts fold too (all closed at first): open the card, then the part. */
export async function openPart(page: Page, title: 'ADU Type' | 'Size' | 'Cost and Rent') {
  await openCard(page, 'ADU Design');
  const fold = page.locator(`[data-subfold="${title}"] > button`);
  await fold.waitFor();
  if ((await fold.getAttribute('aria-expanded')) === 'false') await fold.click();
}
