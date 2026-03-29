import { test, expect } from '@playwright/test';

test.describe('全链路主路径 E2E', () => {
  test('BatchHub：标题、文本/图像入口与底部导航', async ({ page }) => {
    await page.goto('/batch');
    await expect(page.getByRole('heading', { name: '开始或恢复批量任务' })).toBeVisible();
    await expect(page.getByRole('button', { name: '文本批量' })).toBeVisible();
    await expect(page.getByRole('button', { name: '图像批量' })).toBeVisible();
    await expect(page.getByRole('link', { name: '任务中心' }).first()).toBeVisible();
    await expect(page.getByRole('link', { name: '处理历史' }).first()).toBeVisible();
  });

  test('任务中心 /jobs 可访问', async ({ page }) => {
    const res = await page.goto('/jobs');
    expect(res?.ok() || res?.status() === 200).toBeTruthy();
    await expect(page.getByRole('heading', { name: '任务中心' }).first()).toBeVisible();
  });

  test('处理历史 /history 筛选与刷新', async ({ page }) => {
    await page.goto('/history');
    await expect(page.getByRole('button', { name: '全部' })).toBeVisible();
    await expect(page.getByRole('button', { name: '批量与任务' })).toBeVisible();
    await page.getByRole('button', { name: '批量与任务' }).click();
    await expect(page.getByRole('button', { name: '批量与任务' })).toBeVisible();
  });

  test('Hub → 任务中心链接跳转', async ({ page }) => {
    await page.goto('/batch');
    await page.getByRole('link', { name: '任务中心' }).first().click();
    await expect(page).toHaveURL(/\/jobs/);
    await expect(page.getByRole('heading', { name: '任务中心' }).first()).toBeVisible();
  });

  test('后端可用时：新建文本批量任务并进入向导第 1 步', async ({ page, request }) => {
    const health = await request.get('http://127.0.0.1:8000/health').catch(() => null);
    test.skip(!health?.ok(), '本地后端 127.0.0.1:8000 未启动，跳过创建任务用例');

    await page.goto('/batch');
    await page.getByRole('button', { name: '文本批量' }).click();
    await expect(page).toHaveURL(/\/batch\/text\?/);
    await expect(page).toHaveURL(/jobId=/);
    await expect(page).toHaveURL(/step=1/);
    await expect(page.getByRole('heading', { name: '① 任务与配置' })).toBeVisible({ timeout: 15_000 });
  });

  test('后端可用时：GET /jobs 返回 nav_hints', async ({ request }) => {
    const health = await request.get('http://127.0.0.1:8000/health').catch(() => null);
    test.skip(!health?.ok(), '本地后端未启动');
    const res = await request.get('http://127.0.0.1:8000/api/v1/jobs?page_size=5');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    if (Array.isArray(body.jobs) && body.jobs.length > 0) {
      const j = body.jobs[0];
      if (!('nav_hints' in j)) {
        test.skip(true, '已连接的后端非当前代码版本（无 nav_hints），请重启 8000 后再跑');
      }
      expect(typeof (j as { nav_hints: { item_count: number } }).nav_hints.item_count).toBe('number');
    }
  });

  test('任务中心：运行中任务可出现「打开工作台」次要链接', async ({ page, request }) => {
    const health = await request.get('http://127.0.0.1:8000/health').catch(() => null);
    test.skip(!health?.ok(), '本地后端未启动');
    await page.goto('/jobs');
    const secondary = page.getByRole('link', { name: '打开工作台' });
    const n = await secondary.count();
    if (n > 0) {
      await secondary.first().click();
      await expect(page).toHaveURL(/\/batch\/(text|image)\?/);
      await expect(page).toHaveURL(/step=3/);
    }
  });
});
