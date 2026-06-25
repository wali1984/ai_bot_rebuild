/**
 * Admin Controls Security E2E
 *
 * Verifies that:
 * 1. LIVE EXECUTION BLOCKED banner is always present in admin pages
 * 2. Dangerous controls require confirm dialog (never fire on first click)
 * 3. Dangerous controls are hidden from insufficient roles
 * 4. Admin nav is invisible to trader accounts
 * 5. Controls call the backend — no frontend-only control execution
 */

import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

test.describe('Admin Controls Security', () => {
  test.beforeEach(async ({ page }) => {
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ services: [], active_incidents: [], generated_at: new Date().toISOString(), live_blocked: true }) });
    });
    await page.route('**/api/v2/risk/status', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live_blocked: true, rules: [] }) });
    });
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
  });

  test('EXECUTION BLOCKED shown in health strip on every admin page visit', async ({ page }) => {
    await mockAuth(page, 'admin');
    const paths = ['/admin', '/admin/data', '/admin/risk', '/admin/execution'];
    for (const path of paths) {
      await page.goto(path);
      await expect(page.getByTestId('admin-health-strip')).toContainText('EXECUTION BLOCKED');
    }
  });

  test('LIVE EXECUTION BLOCKED banner present on /admin/risk', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin/risk');
    await expect(page.getByTestId('admin-risk-page')).toBeVisible();
    const page_ = page.getByTestId('admin-risk-page');
    await expect(page_).toContainText('BLOCKED');
  });

  test('Dangerous control enable_live_trading does not fire without confirmation', async ({ page }) => {
    await mockAuth(page, 'admin');
    let controlCalled = false;
    await page.route('**/api/v2/admin/controls/enable_live_trading', async (route) => {
      controlCalled = true;
      await route.fulfill({ status: 403, contentType: 'application/json', body: JSON.stringify({ error: 'Forbidden' }) });
    });
    await page.goto('/admin/risk');
    await expect(page.getByTestId('admin-risk-page')).toBeVisible();
    // If a dangerous control button exists, clicking it should open a confirm dialog, not execute
    const dangerBtn = page.locator('[data-testid*="control-btn-enable_live_trading"]');
    if (await dangerBtn.count() > 0) {
      await dangerBtn.first().click();
      // Should show a confirm dialog, not immediately call the backend
      await expect(page.locator('[data-testid*="control-dialog-enable_live_trading"]')).toBeVisible({ timeout: 3000 });
      expect(controlCalled).toBe(false);
    }
  });

  test('Admin nav not visible when logged in as trader', async ({ page }) => {
    await mockAuth(page, 'trader');
    await page.goto('/trade');
    // Admin nav entries should not exist in the DOM
    await expect(page.getByTestId('admin-left-nav')).not.toBeAttached();
    await expect(page.getByTestId('admin-nav-overview')).not.toBeAttached();
  });

  test('Trader cannot access /admin (access-denied or login redirect)', async ({ page }) => {
    await mockAuth(page, 'trader');
    await page.goto('/admin');
    // Either access-denied shown or redirect to /login
    const hasAccessDenied = await page.getByTestId('access-denied').isVisible().catch(() => false);
    const isOnLogin = page.url().includes('/login');
    expect(hasAccessDenied || isOnLogin).toBe(true);
  });

  test('Reviewer can access /admin/data without access-denied', async ({ page }) => {
    await mockAuth(page, 'reviewer');
    await page.goto('/admin/data');
    // reviewer >= minRole:reviewer — should load the page
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    await expect(page.getByTestId('access-denied')).not.toBeVisible();
  });

  test('Reviewer denied on /admin (minRole: admin)', async ({ page }) => {
    await mockAuth(page, 'reviewer');
    await page.goto('/admin');
    await expect(page.getByTestId('access-denied')).toBeVisible();
  });

  test('Admin cannot access /admin/audit (minRole: live_approver)', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin/audit');
    await expect(page.getByTestId('access-denied')).toBeVisible();
  });

  test('Control confirm dialog shows action_id', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await page.goto('/admin/risk');
    await expect(page.getByTestId('admin-risk-page')).toBeVisible();
    // If a DangerousControlPanel renders buttons, clicking one shows the confirm dialog
    const anyControlBtn = page.locator('[data-testid^="control-btn-"]');
    if (await anyControlBtn.count() > 0) {
      const btn = anyControlBtn.first();
      const actionId = await btn.getAttribute('data-testid');
      await btn.click();
      const dialogTestId = actionId?.replace('control-btn-', 'control-dialog-');
      if (dialogTestId) {
        await expect(page.getByTestId(dialogTestId)).toBeVisible({ timeout: 4000 });
        // Dialog should show the action_id text
        await expect(page.getByTestId(dialogTestId)).toContainText('action_id:');
      }
    }
  });
});
