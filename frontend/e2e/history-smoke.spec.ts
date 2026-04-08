import { test, expect } from '@playwright/test';

test('history: navigate to history page and verify page loads', async ({ page }) => {
  await page.goto('/history');

  // Dismiss onboarding dialog if present
  const dismissButton = page.getByRole('button', { name: /dismiss|skip|close|got it|start|begin|ok/i });
  if (await dismissButton.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await dismissButton.click();
  }

  // Verify the history page content is visible
  await expect(
    page.getByText(/history|历史|record|记录/i).first(),
  ).toBeVisible({ timeout: 10_000 });
});
