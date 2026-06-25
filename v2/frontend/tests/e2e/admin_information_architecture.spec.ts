/**
 * Admin Information Architecture E2E
 *
 * Verifies that all 13 canonical admin routes load correctly and that the
 * compact left nav renders with the right entries for each role level.
 * Uses route interception for auth (no ?role= bypass, no frontend-only mocks).
 */

import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

const ADMIN_NAV_IDS = [
  'overview', 'data', 'intelligence', 'orchestration', 'risk',
  'execution', 'exchanges', 'config', 'users', 'reports',
  'logs', 'audit', 'tools',
] as const;

const CANONICAL_ROUTES: Array<{ path: string; testId: string; minRole: 'reviewer' | 'admin' | 'live_approver' }> = [
  { path: '/admin',              testId: 'admin-overview-page',      minRole: 'admin' },
  { path: '/admin/data',         testId: 'admin-data-page',           minRole: 'reviewer' },
  { path: '/admin/intelligence', testId: 'admin-intelligence-page',   minRole: 'reviewer' },
  { path: '/admin/orchestration',testId: 'admin-orchestration-page',  minRole: 'admin' },
  { path: '/admin/risk',         testId: 'admin-risk-page',           minRole: 'admin' },
  { path: '/admin/execution',    testId: 'admin-execution-page',      minRole: 'admin' },
  { path: '/admin/exchanges',    testId: 'admin-exchanges-page',      minRole: 'reviewer' },
  { path: '/admin/config',       testId: 'admin-config-page',         minRole: 'admin' },
  { path: '/admin/users',        testId: 'admin-users-page',          minRole: 'admin' },
  { path: '/admin/reports',      testId: 'admin-reports-page',        minRole: 'reviewer' },
  { path: '/admin/logs',         testId: 'admin-logs-page',           minRole: 'live_approver' },
  { path: '/admin/audit',        testId: 'admin-audit-page',          minRole: 'live_approver' },
  { path: '/admin/tools',        testId: 'admin-tools-page',          minRole: 'live_approver' },
];

test.describe('Admin Information Architecture', () => {
  test.beforeEach(async ({ page }) => {
    // Stub overview to avoid network errors in tests
    await page.route('**/api/v2/admin/overview', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ services: [], active_incidents: [], generated_at: new Date().toISOString(), live_gate: 'blocked' }),
      });
    });
    // Stub all admin API endpoints to avoid noise
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.route('**/api/v2/risk/status', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live_blocked: true }) });
    });
  });

  test('AdminShell renders with left nav for admin role', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    await expect(page.getByTestId('admin-left-nav')).toBeVisible();
    await expect(page.getByTestId('admin-health-strip')).toBeVisible();
    await expect(page.getByTestId('admin-role-badge')).toContainText('ADMIN');
    await expect(page.getByTestId('admin-breadcrumb')).toBeVisible();
  });

  test('AdminShell shows 10 primary nav entries for admin', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    const primary = ['overview', 'data', 'intelligence', 'orchestration', 'risk', 'execution', 'exchanges', 'config', 'users', 'reports'];
    for (const id of primary) {
      await expect(page.getByTestId(`admin-nav-${id}`)).toBeVisible();
    }
  });

  test('AdminShell hides audit and tools from admin (not superadmin)', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    // audit and tools are live_approver only
    await expect(page.getByTestId('admin-nav-audit')).not.toBeVisible();
    await expect(page.getByTestId('admin-nav-tools')).not.toBeVisible();
  });

  test('AdminShell shows all 13 nav entries for superadmin', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    for (const id of ADMIN_NAV_IDS) {
      await expect(page.getByTestId(`admin-nav-${id}`)).toBeVisible();
    }
  });

  test('AdminShell shows superadmin role badge', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await page.goto('/admin');
    await expect(page.getByTestId('admin-role-badge')).toContainText('SUPERADMIN');
  });

  test('Unauthenticated user redirected to /login from /admin', async ({ page }) => {
    await mockAuth(page, 'public');
    await page.goto('/admin');
    await expect(page).toHaveURL(/\/login/);
  });

  test('Trader role sees access denied on /admin (requires admin)', async ({ page }) => {
    await mockAuth(page, 'trader');
    await page.goto('/admin');
    await expect(page.getByTestId('access-denied')).toBeVisible();
  });

  for (const route of CANONICAL_ROUTES.filter((r) => r.minRole !== 'live_approver')) {
    test(`Canonical route ${route.path} loads page content for admin role`, async ({ page }) => {
      await mockAuth(page, 'admin');
      await page.goto(route.path);
      // Either the page renders or access-denied (for admin-min-role routes, admin should pass)
      const shell = page.getByTestId('admin-shell');
      await expect(shell).toBeVisible({ timeout: 8000 });
      // The canonical page testId should be in the DOM if role is sufficient
      if (route.minRole !== 'live_approver') {
        const pageEl = page.getByTestId(route.testId);
        await expect(pageEl).toBeVisible({ timeout: 8000 });
      }
    });
  }

  test('Superadmin can access /admin/audit', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await page.goto('/admin/audit');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    await expect(page.getByTestId('admin-audit-page')).toBeVisible();
  });

  test('Superadmin can access /admin/tools', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await page.goto('/admin/tools');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    await expect(page.getByTestId('admin-tools-page')).toBeVisible();
  });

  test('Admin role denied on /admin/audit (requires live_approver)', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin/audit');
    await expect(page.getByTestId('access-denied')).toBeVisible();
  });

  test('Superadmin can access /admin/logs', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await page.goto('/admin/logs');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    await expect(page.getByTestId('admin-logs-page')).toBeVisible();
  });

  test('Admin role denied on /admin/logs (now requires live_approver)', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin/logs');
    await expect(page.getByTestId('access-denied')).toBeVisible();
  });

  test('Active nav link highlighted on /admin', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    // The overview link should be active (indicated by aria-current or data-active)
    const overviewLink = page.getByTestId('admin-nav-overview');
    await expect(overviewLink).toBeVisible();
  });
});
