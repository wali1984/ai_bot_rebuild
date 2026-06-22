import { test, expect } from '@playwright/test';
import { ALL_PAGE_PATHS, gotoAs } from './_shared';

test.describe('live_block_banner', () => {
  for (const path of ALL_PAGE_PATHS) {
    test(`legacy live-block banner is absent on ${path}`, async ({ page }) => {
      await gotoAs(page, path, 'admin');
      const banner = page.getByTestId('live-block-banner');
      await expect(banner).toHaveCount(0);
      await expect(page.locator('body')).not.toContainText(/LIVE TRADING: BLOCKED/i);
    });
  }
});
