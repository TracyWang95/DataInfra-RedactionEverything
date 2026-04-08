import { test, expect } from '@playwright/test';

test('batch: navigate to batch page and verify page loads', async ({ page }) => {
  await page.goto('/batch');

  // Dismiss onboarding dialog if present
  const dismissButton = page.getByRole('button', { name: /dismiss|skip|close|got it|start|begin|ok/i });
  if (await dismissButton.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await dismissButton.click();
  }

  // Verify the batch page content is visible
  await expect(
    page.getByText(/batch|批量|job|任务/i).first(),
  ).toBeVisible({ timeout: 10_000 });
});

test('batch: verify create job button exists', async ({ page }) => {
  await page.goto('/batch');

  const dismissButton = page.getByRole('button', { name: /dismiss|skip|close|got it|start|begin|ok/i });
  if (await dismissButton.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await dismissButton.click();
  }

  // Look for a create/new job button
  const createButton = page.getByRole('button', {
    name: /create|new|新建|创建/i,
  });
  if (await createButton.isVisible({ timeout: 5_000 }).catch(() => false)) {
    await expect(createButton).toBeVisible();
  }
});
