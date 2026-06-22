import { test, expect } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

test.describe('rbac_visibility', () => {
  test('admin sees backend-confirmed admin navigation', async ({ page }) => {
    await mockAuth(page, 'admin');
    await gotoAs(page, '/admin/system');
    const nav = page.getByTestId('admin-nav');
    await expect(nav).toBeVisible();
    await expect(page.getByTestId('nav-item-system-health')).toBeVisible();
    await expect(page.getByTestId('nav-item-risk-control')).toBeVisible();
    await expect(page.getByTestId('nav-item-operator-proof-dashboard')).toHaveCount(0);
  });

  test('superadmin sees protected evidence navigation', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await gotoAs(page, '/admin/evidence');
    const nav = page.getByTestId('admin-nav');
    await expect(nav).toBeVisible();
    await expect(page.getByTestId('nav-item-operator-proof-dashboard')).toBeVisible();
  });

  test('public actor is redirected away from admin surface', async ({ page }) => {
    await mockAuth(page, 'public');
    await gotoAs(page, '/admin/mission-control');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId('admin-nav')).toHaveCount(0);
  });

  test('viewer is redirected away from reviewer-only page', async ({ page }) => {
    await mockAuth(page, 'viewer');
    await gotoAs(page, '/admin/risk-control');
    await expect(page.getByTestId('access-denied')).toBeVisible();
    await expect(page.getByTestId('page-risk-control')).toHaveCount(0);
  });
});
