import { test, expect } from '@playwright/test';
import { isBackendUp, REAL_TEST_FILES, dismissOnboarding } from './helpers';
import fs from 'fs';

function hasRealTestData(): boolean {
  return Object.values(REAL_TEST_FILES).every((p) => fs.existsSync(p));
}

test.describe('批量脱敏全链路 + 历史眼睛查看', () => {
  test.setTimeout(600_000);

  test('3文件 → 确认脱敏 → 历史每个文件点眼睛看对比', async ({ page, request }) => {
    test.skip(!(await isBackendUp(request)), '后端未启动');
    test.skip(!hasRealTestData(), 'D:\\ceshi 测试数据不存在');

    let jobId: string | null = null;
    try {
      // ═══ Step 1~3: 创建 → 上传 → 识别（复用 fullchain 逻辑）═══
      await page.goto('/batch');
      await dismissOnboarding(page);
      await page.getByRole('button', { name: /新建|批量/ }).first().click();
      await expect(page).toHaveURL(/step=1/, { timeout: 15_000 });
      jobId = new URL(page.url()).searchParams.get('jobId');

      await expect(page.getByText(/任务与配置/).first()).toBeVisible({ timeout: 10_000 });
      const cb = page.locator('input[type="checkbox"]').first();
      if (await cb.isVisible().catch(() => false)) {
        if (!(await cb.isChecked())) await cb.check();
      }
      await expect(page.getByRole('button', { name: '下一步：上传' })).toBeEnabled({ timeout: 60_000 });
      await page.getByRole('button', { name: '下一步：上传' }).click();
      await expect(page).toHaveURL(/step=2/, { timeout: 10_000 });

      await page.locator('input[type="file"]').setInputFiles([
        REAL_TEST_FILES.image, REAL_TEST_FILES.docx1, REAL_TEST_FILES.docx2,
      ]);
      await page.waitForTimeout(5_000);
      await page.getByRole('button', { name: /下一步.*识别|批量识别/ }).first().click();
      await expect(page).toHaveURL(/step=3/, { timeout: 10_000 });

      await page.getByRole('button', { name: '提交后台队列' }).click();
      const nextStep = page.getByRole('button', { name: /下一步：进入核对/ });
      await expect(nextStep).toBeEnabled({ timeout: 300_000 });
      await nextStep.click();
      await expect(page).toHaveURL(/step=4/, { timeout: 10_000 });

      // ═══ Step 4: 逐份确认脱敏 ═══
      for (let i = 0; i < 3; i++) {
        const btn = page.getByRole('button', { name: /确认脱敏/ }).first();
        const ready = await expect(btn).toBeEnabled({ timeout: 30_000 }).then(() => true).catch(() => false);
        if (!ready) break;
        const txt = await btn.textContent();
        if (txt?.includes('已完成')) break;

        await btn.click();
        console.log(`[Step4] 第 ${i+1} 份已确认`);
        await page.waitForTimeout(5_000);

        const exp = page.getByRole('button', { name: /进入导出/ }).first();
        if (await exp.isEnabled().catch(() => false)) break;
        await page.waitForTimeout(5_000);
      }

      // ═══ Step 5: 导出 ═══
      const expBtn = page.getByRole('button', { name: /进入导出/ }).first();
      await expect(expBtn).toBeEnabled({ timeout: 30_000 });
      await expBtn.click();
      await expect(page).toHaveURL(/step=5/, { timeout: 10_000 });
      console.log('[Step5] OK');

      // ═══ 历史记录：每个文件点眼睛验证 ═══
      await page.goto('/history');
      await dismissOnboarding(page);
      await page.waitForTimeout(3_000);

      // 找到所有"查看对比"按钮
      const viewBtns = page.locator('button[title*="查看"], button:has-text("查看对比"), a[title*="查看"]');
      const count = await viewBtns.count();
      console.log(`[History] 找到 ${count} 个查看按钮`);

      for (let i = 0; i < Math.min(count, 3); i++) {
        await viewBtns.nth(i).click();
        await page.waitForTimeout(3_000);
        await page.screenshot({ path: `test-results/history-eye-${i}.png` });

        // 检查没有报错弹窗
        const errToast = page.locator('.bg-red-50, [role="alert"]').first();
        const hasErr = await errToast.isVisible({ timeout: 1_000 }).catch(() => false);
        if (hasErr) {
          const errMsg = await errToast.textContent();
          console.error(`[History] 第 ${i+1} 个文件报错: ${errMsg}`);
        }
        expect(hasErr).toBeFalsy();

        // 检查有内容（图片或文本）
        const hasContent = await page.locator('img[alt*="脱敏"], img[alt*="redact"], .whitespace-pre-wrap').first()
          .isVisible({ timeout: 5_000 }).catch(() => false);
        console.log(`[History] 第 ${i+1} 个文件查看: ${hasContent ? 'OK' : 'WARN no content'}`);

        // 关闭对比弹窗
        const closeBtn = page.getByRole('button', { name: /关闭|close/i }).first();
        if (await closeBtn.isVisible().catch(() => false)) {
          await closeBtn.click();
          await page.waitForTimeout(500);
        }
      }

    } finally {
      if (jobId) {
        await request.post(`http://127.0.0.1:8000/api/v1/jobs/${jobId}/cancel`).catch(() => {});
        await request.delete(`http://127.0.0.1:8000/api/v1/jobs/${jobId}`).catch(() => {});
      }
    }
  });
});
