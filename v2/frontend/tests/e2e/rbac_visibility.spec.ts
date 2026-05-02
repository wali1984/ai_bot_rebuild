import { test, expect } from '@playwright/test';
import {
  REVIEWER_ONLY_ADMIN_PATHS,
  VIEWER_VISIBLE_ADMIN_PATHS,
  gotoAs,
} from './_shared';

test.describe('rbac_visibility', () => {
  test('viewer sees only viewer-eligible admin nav entries', async ({ page }) => {
    await gotoAs(page, '/admin/mission-control', 'viewer');
    const nav = page.getByTestId('admin-nav');
    await expect(nav).toBeVisible();
    for (const path of VIEWER_VISIBLE_ADMIN_PATHS) {
      const id = path.replace('/admin/', '');
      await expect(page.getByTestId(`nav-item-${id}`)).toBeVisible();
    }
    for (const path of REVIEWER_ONLY_ADMIN_PATHS) {
      const id = path.replace('/admin/', '');
      await expect(page.getByTestId(`nav-item-${id}`)).toHaveCount(0);
    }
  });

  test('reviewer sees viewer + reviewer admin nav entries', async ({ page }) => {
    await gotoAs(page, '/admin/mission-control', 'reviewer');
    const nav = page.getByTestId('admin-nav');
    await expect(nav).toBeVisible();
    for (const path of [...VIEWER_VISIBLE_ADMIN_PATHS, ...REVIEWER_ONLY_ADMIN_PATHS]) {
      const id = path.replace('/admin/', '');
      await expect(page.getByTestId(`nav-item-${id}`)).toBeVisible();
    }
  });

  test('public actor is redirected away from admin surface', async ({ page }) => {
    await gotoAs(page, '/admin/mission-control', 'public');
    await expect(page).toHaveURL(/\/(\?.*)?$/);
    // Public landing renders, no admin nav present.
    await expect(page.getByTestId('admin-nav')).toHaveCount(0);
  });

  test('viewer is redirected away from reviewer-only page', async ({ page }) => {
    await gotoAs(page, '/admin/risk-control', 'viewer');
    await expect(page).toHaveURL(/\/(\?.*)?$/);
    await expect(page.getByTestId('page-risk-control')).toHaveCount(0);
  });
});
