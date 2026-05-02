import { test, expect } from '@playwright/test';
import { ALL_PAGE_PATHS, gotoAs } from './_shared';

test.describe('nav_smoke', () => {
  for (const path of ALL_PAGE_PATHS) {
    test(`renders ${path} as admin without crash`, async ({ page }) => {
      await gotoAs(page, path, 'admin');
      await expect(page.getByTestId('live-block-banner')).toBeVisible();
      await expect(page.locator('h1').first()).toBeVisible();
    });
  }
});
