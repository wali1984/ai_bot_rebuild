import { test, expect } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

test.describe('rbac_visibility', () => {
  test('admin sees backend-confirmed admin navigation', async ({ page }) => {
    await mockAuth(page, 'admin');
    await gotoAs(page, '/admin/system');
    const nav = page.getByTestId('admin-nav');
    await expect(nav).toBeVisible();
    await expect(page.getByTestId('admin-nav-overview')).toBeVisible();
    await expect(page.getByTestId('admin-nav-risk')).toBeVisible();
    await expect(page.getByTestId('admin-nav-audit')).toHaveCount(0);
    await expect(page.getByTestId('admin-nav-tools')).toHaveCount(0);
  });

  test('superadmin sees protected evidence navigation', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await gotoAs(page, '/admin/evidence');
    const nav = page.getByTestId('admin-nav');
    await expect(nav).toBeVisible();
    await expect(page.getByTestId('admin-nav-audit')).toBeVisible();
    await expect(page.getByTestId('admin-nav-tools')).toBeVisible();
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
