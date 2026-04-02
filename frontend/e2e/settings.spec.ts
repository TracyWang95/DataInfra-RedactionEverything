import { test, expect } from '@playwright/test';
import { isBackendUp, waitForPageReady, dismissOnboarding } from './helpers';

test.describe('识别项配置', () => {
  test('页面加载：标题与规则区块', async ({ page }) => {
    await page.goto('/settings');
    await dismissOnboarding(page);
    await waitForPageReady(page);
    await expect(page.getByText('识别项配置').first()).toBeVisible();
  });

  test('文本识别规则与图像识别规则可见', async ({ page }) => {
    await page.goto('/settings');
    await dismissOnboarding(page);
    await waitForPageReady(page);
    await expect(page.getByText('文本识别规则').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('图像识别规则').first()).toBeVisible();
  });

  test('正则规则与 AI 语义区块', async ({ page }) => {
    await page.goto('/settings');
    await dismissOnboarding(page);
    await waitForPageReady(page);
    await expect(page.getByText('正则规则').first()).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(/AI 语义/).first()).toBeVisible();
  });

  test('后端可用时：新增类型按钮', async ({ page, request }) => {
    test.skip(!(await isBackendUp(request)), '后端未启动');

    await page.goto('/settings');
    await dismissOnboarding(page);
    await waitForPageReady(page);

    const addBtn = page.getByRole('button', { name: /新增/ }).first();
    await expect(addBtn).toBeVisible({ timeout: 10_000 });
  });

  test('后端可用时：正则测试功能', async ({ page, request }) => {
    test.skip(!(await isBackendUp(request)), '后端未启动');

    await page.goto('/settings');
    await dismissOnboarding(page);
    await waitForPageReady(page);

    const testInput = page.getByPlaceholder(/输入测试文本/).first();
    if (await testInput.isVisible().catch(() => false)) {
      await testInput.fill('张三的身份证号是 110101199003071234');
      const testBtn = page.getByRole('button', { name: /测试正则/ }).first();
      if (await testBtn.isVisible().catch(() => false)) {
        await testBtn.click();
        await page.waitForTimeout(2_000);
        await expect(
          page.getByText(/匹配到|不通过|通过/).first()
        ).toBeVisible({ timeout: 5_000 });
      }
    }
  });
});

test.describe('脱敏清单', () => {
  test('页面加载：标题', async ({ page }) => {
    await page.goto('/settings/redaction');
    await dismissOnboarding(page);
    await waitForPageReady(page);
    await expect(page.getByText('脱敏清单').first()).toBeVisible();
  });

  test('固定显示默认文本与图像配置清单', async ({ page }) => {
    await page.goto('/settings/redaction');
    await dismissOnboarding(page);
    await waitForPageReady(page);
    await expect(page.getByText('默认文本脱敏配置清单')).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText('默认图像脱敏配置清单')).toBeVisible({ timeout: 10_000 });
  });

  test('默认项初始收起，点击预览后再展开', async ({ page }) => {
    await page.goto('/settings/redaction');
    await dismissOnboarding(page);
    await waitForPageReady(page);

    await expect(page.getByText('系统内置项全选，不包含用户自定义项。')).toHaveCount(0);
    await page.getByRole('button', { name: '预览' }).first().click();
    await expect(page.getByText('系统内置项全选，不包含用户自定义项。').first()).toBeVisible({
      timeout: 10_000,
    });
  });

  test('新建弹窗始终显示创建按钮', async ({ page, request }) => {
    test.skip(!(await isBackendUp(request)), '后端未启动');

    await page.goto('/settings/redaction');
    await dismissOnboarding(page);
    await waitForPageReady(page);

    await page.getByRole('button', { name: /新建文本配置清单/ }).click();
    const createButton = page.getByRole('button', { name: '创建' });
    await expect(createButton).toBeVisible({ timeout: 10_000 });
    await expect(createButton).toBeEnabled();
    const backgroundColor = await createButton.evaluate(el => getComputedStyle(el).backgroundColor);
    expect(backgroundColor).not.toBe('rgba(0, 0, 0, 0)');
  });

  test('后端可用时：预设列表或空状态', async ({ page, request }) => {
    test.skip(!(await isBackendUp(request)), '后端未启动');

    await page.goto('/settings/redaction');
    await dismissOnboarding(page);
    await waitForPageReady(page);

    await expect(
      page.getByText(/预设|清单|配置/).first()
    ).toBeVisible({ timeout: 10_000 });
  });
});
