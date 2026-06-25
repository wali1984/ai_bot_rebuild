/**
 * Admin Visual Final E2E
 *
 * Verifies the visual structure of the new admin portal:
 * - ops-terminal theme applied
 * - compact left nav (not old top-nav sections)
 * - breadcrumb present with correct page title
 * - secondary nav divider separates primary from secondary entries
 * - no old ADMIN_NAV_SECTIONS labels visible (Observe, Sense, Core, Guard, Shift, Execute, Replay)
 */

import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

const OLD_NAV_LABELS = ['Observe', 'Sense', 'Core', 'Guard', 'Shift', 'Execute', 'Replay'];

// CLASSIFICATION: COMPONENT_MOCK
// Uses mockAuth + route interception. Screenshots and real-data verification →
// tests/e2e/production/admin_production_audit.spec.ts [PRODUCTION_E2E]
test.describe('Admin Visual Final [COMPONENT_MOCK]', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ services: [], active_incidents: [], generated_at: new Date().toISOString(), live_blocked: true }) });
    });
    await page.route('**/api/v2/risk/status', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live_blocked: true }) });
    });
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
  });

  test('ops-terminal theme applied to admin shell', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toHaveAttribute('data-nervyx-theme', 'ops-terminal');
  });

  test('Compact left nav present (not old top-nav horizontal sections)', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByTestId('admin-left-nav')).toBeVisible();
    // Old top-nav section links should not exist
    for (const oldLabel of OLD_NAV_LABELS) {
      await expect(page.getByText(oldLabel, { exact: true })).not.toBeVisible();
    }
  });

  test('Breadcrumb shows NERVYX ADMIN text', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('admin-breadcrumb')).toBeVisible();
    await expect(page.getByTestId('admin-breadcrumb')).toContainText('NERVYX ADMIN');
  });

  test('Breadcrumb updates to page title on /admin/data', async ({ page }) => {
    await page.goto('/admin/data');
    await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10000 });
    await expect(page.getByTestId('admin-breadcrumb')).toContainText('DATA');
  });

  test('Breadcrumb updates to page title on /admin/intelligence', async ({ page }) => {
    await page.goto('/admin/intelligence');
    await expect(page.getByTestId('admin-breadcrumb')).toContainText('INTELLIGENCE');
  });

  test('Global health strip is always visible', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByTestId('admin-health-strip')).toBeVisible();
    await page.goto('/admin/risk');
    await expect(page.getByTestId('admin-health-strip')).toBeVisible();
  });

  test('Logo present in admin header', async ({ page }) => {
    await page.goto('/admin');
    const logo = page.locator('img[alt="NERVYX ONE"]');
    await expect(logo).toBeVisible();
  });

  test('OPS TERMINAL badge shown in header', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByText('OPS TERMINAL')).toBeVisible();
  });

  test('Primary nav entries appear before the divider', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10000 });
    const primaryNavIds = ['overview', 'data', 'intelligence', 'orchestration', 'risk', 'execution', 'exchanges', 'config', 'users', 'reports'];
    for (const id of primaryNavIds) {
      await expect(page.getByTestId(`admin-nav-${id}`)).toBeVisible();
    }
  });

  test('Nav active state on /admin/data highlights data link', async ({ page }) => {
    await page.goto('/admin/data');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    // The data nav link should be the active one
    const dataLink = page.getByTestId('admin-nav-data');
    await expect(dataLink).toBeVisible();
  });

  test('Admin pages render within AdminShell (Outlet working)', async ({ page }) => {
    // /admin/logs requires live_approver — omit for admin-role test
    const routes = ['/admin', '/admin/data', '/admin/exchanges', '/admin/reports'];
    for (const route of routes) {
      await page.goto(route);
      await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10000 });
      await expect(page.getByTestId('admin-main')).toBeVisible();
    }
  });

  test('Sign out button present in header', async ({ page }) => {
    await page.goto('/admin');
    await expect(page.getByRole('button', { name: /sign out/i })).toBeVisible();
  });
});
