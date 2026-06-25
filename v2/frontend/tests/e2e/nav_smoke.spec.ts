import { test, expect } from '@playwright/test';
import { ALL_PAGE_PATHS, gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

test.describe('nav_smoke', () => {
  for (const path of ALL_PAGE_PATHS) {
    test(`renders ${path} as admin without crash`, async ({ page }) => {
      const role = path === '/admin/operator-proof-dashboard' ? 'superadmin' : 'admin';
      await mockAuth(page, role);
      await gotoAs(page, path, role);
      await expect(page.getByTestId('live-block-banner')).toHaveCount(0);
      await expect(page.locator('h1').first()).toBeVisible();
    });
  }
});
