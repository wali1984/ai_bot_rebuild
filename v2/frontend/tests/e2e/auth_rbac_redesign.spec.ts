import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';

const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
] as const;

type TestRole = 'viewer' | 'trader' | 'admin' | 'superadmin';

function user(role: TestRole) {
  return {
    id: `${role}-id`,
    trader_id: role === 'viewer' ? null : `${role}-trader`,
    username: role,
    email: `${role}@example.com`,
    role,
    paper_account_id: null,
    exchange_accounts: [],
    watchlist: [],
    alert_preferences: {},
    is_active: true,
    created_at: '2026-06-13T00:00:00Z',
    updated_at: '2026-06-13T00:00:00Z',
    last_login: null,
  };
}

async function mockAuth(page: Page, initialRole: TestRole | null): Promise<void> {
  let currentRole = initialRole;
  await page.route('**/api/auth/me', async (route) => {
    if (!currentRole) {
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'authentication_required' }) });
      return;
    }
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ user: user(currentRole) }) });
  });
  await page.route('**/api/auth/logout', async (route) => {
    currentRole = null;
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
  await page.route('**/api/auth/login', async (route) => {
    currentRole = 'admin';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ access_token: 'test-token', token_type: 'bearer', user: user('admin') }),
    });
  });
}

function screenshotPath(name: string): string {
  const root = path.resolve(process.cwd(), '..', 'screenshots', 'final');
  mkdirSync(root, { recursive: true });
  return path.join(root, name);
}

async function noHorizontalScroll(page: Page): Promise<void> {
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
}

test.describe('auth rbac redesign', () => {
  for (const viewport of VIEWPORTS) {
    test(`login renders professional form and captures ${viewport.name}`, async ({ page }) => {
      await mockAuth(page, null);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await gotoAs(page, '/login');
      await expect(page.getByTestId('page-login')).toBeVisible();
      await expect(page.getByLabel('Email')).toBeVisible();
      await expect(page.getByPlaceholder('Enter password')).toBeVisible();
      await expect(page.getByRole('button', { name: /^Sign in$/ })).toBeVisible();
      await expect(page.getByText(/role selector|demo admin|fake admin|local role/i)).toHaveCount(0);
      await noHorizontalScroll(page);
      await page.screenshot({ path: screenshotPath(`login-${viewport.name}.png`), fullPage: true });
    });

    test(`unauthenticated admin route captures gate ${viewport.name}`, async ({ page }) => {
      await mockAuth(page, null);
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await gotoAs(page, '/admin');
      await page.waitForLoadState('networkidle').catch(() => undefined);
      await expect(page).toHaveURL(/\/login/);
      await expect(page.getByTestId('admin-main')).toHaveCount(0);
      await noHorizontalScroll(page);
      await page.screenshot({ path: screenshotPath(`admin-auth-gate-${viewport.name}.png`), fullPage: true });
    });

    test(`authenticated admin dashboard captures ${viewport.name}`, async ({ page }) => {
      await mockAuth(page, 'admin');
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await gotoAs(page, '/admin');
      await expect(page.getByTestId('admin-main')).toBeVisible();
      await expect(page.getByTestId('admin-nav')).toBeVisible();
      await noHorizontalScroll(page);
      await page.screenshot({ path: screenshotPath(`admin-dashboard-${viewport.name}.png`), fullPage: true });
    });
  }

  test('query and browser storage mutations do not grant admin', async ({ page }) => {
    await mockAuth(page, null);
    await gotoAs(page, '/admin?role=admin');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId('admin-nav')).toHaveCount(0);

    await page.evaluate(() => {
      window.sessionStorage.setItem('v2.session.role.shell', 'admin');
      window.localStorage.setItem('v2.session.role.shell', 'superadmin');
    });
    await gotoAs(page, '/admin/system?role=superadmin');
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId('admin-main')).toHaveCount(0);
  });

  test('admin routes reject viewer and trader users without leaking content', async ({ page }) => {
    await mockAuth(page, 'trader');
    await gotoAs(page, '/admin/system');
    await expect(page.getByTestId('access-denied')).toBeVisible();
    await expect(page.getByTestId('admin-main')).toHaveCount(0);
  });

  test('superadmin route rejects admin', async ({ page }) => {
    await mockAuth(page, 'admin');
    await gotoAs(page, '/admin/evidence');
    await expect(page.getByTestId('access-denied')).toBeVisible();
    await expect(page.getByText(/superadmin/i)).toBeVisible();
  });

  test('logout clears backend-confirmed access', async ({ page }) => {
    await mockAuth(page, 'admin');
    await gotoAs(page, '/admin');
    await expect(page.getByTestId('admin-main')).toBeVisible();
    await page.getByRole('button', { name: /Sign out/i }).click();
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByTestId('admin-main')).toHaveCount(0);
  });
});
