import { test, expect, type Page } from '@playwright/test';

const TS = Date.now();
const REGEX_NAME = `TestRegex_${TS}`;
const REGEX_PATTERN = String.raw`TESTRX\d+`;

async function dismiss(page: Page) {
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
  await page.keyboard.press('Escape');
  await page.waitForTimeout(300);
}

test('Create regex type → verify list refreshes', async ({ page }) => {
  // Log ALL network requests to /custom-types
  page.on('request', req => {
    if (req.url().includes('custom-types')) {
      console.log(`>> ${req.method()} ${req.url()}`);
    }
  });
  page.on('response', resp => {
    if (resp.url().includes('custom-types')) {
      console.log(`<< ${resp.status()} ${resp.url()} (${resp.request().method()})`);
    }
  });
  page.on('requestfailed', req => {
    if (req.url().includes('custom-types')) {
      console.log(`!! FAILED ${req.method()} ${req.url()} ${req.failure()?.errorText}`);
    }
  });

  // Go to settings
  await page.goto('/settings');
  await page.waitForLoadState('networkidle');
  await dismiss(page);

  // Click regex tab
  const regexTab = page.locator('[data-testid="subtab-regex"]');
  if (await regexTab.isVisible({ timeout: 3000 }).catch(() => false)) {
    await regexTab.click();
    await page.waitForTimeout(300);
  }

  // Count before
  const beforeText = await regexTab.textContent();
  console.log(`Before: ${beforeText}`);

  // Click add
  await page.locator('[data-testid="add-regex-type"]').click();
  await page.waitForTimeout(500);

  // Fill form
  await page.locator('[data-testid="entity-type-name"]').fill(REGEX_NAME);
  await page.locator('[data-testid="entity-type-regex"]').fill(REGEX_PATTERN);

  // Click save and watch network
  console.log('--- Clicking save ---');
  await page.locator('[data-testid="entity-type-save"]').click();

  // Wait for any GET /custom-types after the POST
  await page.waitForTimeout(3000);

  const afterText = await regexTab.textContent();
  console.log(`After: ${afterText}`);

  await page.screenshot({ path: 'e2e-screenshots/debug-after-save.png' });

  // Also check: manually trigger a page reload to see if it appears then
  console.log('--- Manual reload ---');
  await page.reload();
  await page.waitForLoadState('networkidle');
  await dismiss(page);

  // Click regex tab again
  if (await regexTab.isVisible({ timeout: 3000 }).catch(() => false)) {
    await regexTab.click();
    await page.waitForTimeout(500);
  }

  const afterReload = await regexTab.textContent();
  console.log(`After reload: ${afterReload}`);

  // Navigate to last page to find the new type
  let found = false;
  for (let i = 0; i < 10; i++) {
    const text = await page.textContent('body');
    if (text?.includes(REGEX_NAME)) {
      found = true;
      console.log(`Found "${REGEX_NAME}" on page`);
      break;
    }
    const nextBtn = page.locator('button:has-text("Next"), button:has-text("下一页")').first();
    if (await nextBtn.isEnabled().catch(() => false)) {
      await nextBtn.click();
      await page.waitForTimeout(300);
    } else break;
  }

  await page.screenshot({ path: 'e2e-screenshots/debug-final.png' });
  console.log(`Final found: ${found}`);
  expect(found).toBe(true);
});
