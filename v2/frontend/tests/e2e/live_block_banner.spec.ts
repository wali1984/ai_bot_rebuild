import { test, expect } from '@playwright/test';
import { ALL_PAGE_PATHS, gotoAs } from './_shared';

test.describe('live_block_banner', () => {
  for (const path of ALL_PAGE_PATHS) {
    test(`banner renders BLOCKED on ${path} and cannot be dismissed`, async ({ page }) => {
      await gotoAs(page, path, 'admin');
      const banner = page.getByTestId('live-block-banner');
      await expect(banner).toBeVisible();
      await expect(banner).toHaveAttribute('data-live-state', 'blocked');
      await expect(banner).toContainText('LIVE TRADING: BLOCKED');
      // No dismiss button exists.
      await expect(banner.getByRole('button', { name: /dismiss|close/i })).toHaveCount(0);
    });
  }
});
