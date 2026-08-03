import { test, expect } from '@playwright/test';
import { ALL_PAGE_PATHS, gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

async function expectBlockedExecutionContract(page: import('@playwright/test').Page): Promise<void> {
  const liveBanner = page.getByTestId('live-block-banner');
  const adminHealthStrip = page.getByTestId('admin-health-strip');
  const liveBannerCount = await liveBanner.count();
  const adminHealthStripCount = await adminHealthStrip.count();

  if (liveBannerCount > 0) {
    await expect(liveBanner).toContainText('EXECUTION BLOCKED');
    await expect(liveBanner).toContainText('blocked_human_only');
  } else {
    await expect(page.locator('body')).not.toContainText(/LIVE TRADING:\s*(ENABLED|ACTIVE)|REAL ORDER|REAL ORDERS|LIVE MODE/i);
  }

  if (adminHealthStripCount > 0) {
    await expect(adminHealthStrip).toContainText('EXECUTION BLOCKED');
  }
}

test.describe('live_block_banner', () => {
  for (const path of ALL_PAGE_PATHS) {
    test(`blocked execution banner contract on ${path}`, async ({ page }) => {
      const routePath = String(path);
      const isAdminPath = routePath.startsWith('/admin/') || routePath === '/admin';
      const role = isAdminPath ? 'superadmin' : 'admin';
      await mockAuth(page, role);
      await gotoAs(page, path, role);
      await expectBlockedExecutionContract(page);
    });
  }
});
