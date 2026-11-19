// Left panel cards fold (Testable Lots and ADU Design start folded). Open one before using what is inside.
import type { Page } from '@playwright/test';

export async function openCard(page: Page, title: 'Testable Lots' | 'ADU Design' | 'Boundaries') {
  const fold = page.locator(`section[aria-label="${title}"]`).getByRole('button', { name: title, exact: true });
  await fold.waitFor();
  if ((await fold.getAttribute('aria-expanded')) === 'false') await fold.click();
}
