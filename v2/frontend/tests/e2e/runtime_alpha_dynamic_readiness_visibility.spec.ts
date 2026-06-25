import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth, type TestAuthRole } from './helpers/auth';

const PUBLIC_ROUTES: Array<{ path: string; role: TestAuthRole; expectedUrl?: RegExp }> = [
  { path: '/dashboard', role: 'trader' },
  { path: '/ai-predictions', role: 'trader' },
  { path: '/ai-predictions/model-state', role: 'trader', expectedUrl: /\/ai-predictions$/ },
  { path: '/signals', role: 'trader' },
  { path: '/trade', role: 'trader' },
  { path: '/trade/paper', role: 'trader', expectedUrl: /\/trade$/ },
  { path: '/portfolio', role: 'trader' },
  { path: '/backtests', role: 'trader' },
];

const ADMIN_DIAGNOSTIC_ROUTES: Array<{ path: string; role: TestAuthRole; expectedUrl?: RegExp }> = [
  { path: '/admin/model-state', role: 'admin' },
];

const LEGACY_SYSTEM_ROUTES: Array<{ path: string; role: TestAuthRole }> = [
  { path: '/system/trainer', role: 'admin' },
  { path: '/system/risk-controllers', role: 'admin' },
  { path: '/system/readiness', role: 'superadmin' },
];

function escapedRoute(path: string): RegExp {
  return new RegExp(`${path.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')}$`);
}

async function assertRuntimeAlphaPanel(page: Page): Promise<void> {
  const panel = page.getByTestId('runtime-alpha-dynamic-readiness-panel').first();
  await expect(panel).toBeVisible({ timeout: 15_000 });
  await panel.scrollIntoViewIfNeeded();
  await expect(panel).toContainText(/Local Trainer|Runtime Alpha/i);
}

async function gotoRoute(page: Page, path: string, role: TestAuthRole): Promise<void> {
  await mockAuth(page, role);
  await page.goto(path, { waitUntil: 'commit' });
}

test.describe('runtime alpha dynamic readiness visibility', () => {
  for (const route of PUBLIC_ROUTES) {
    test(`${route.path} hides the trainer/runtime-alpha proof panel from trader surfaces`, async ({ page }) => {
      await gotoRoute(page, route.path, route.role);
      await page.waitForLoadState('domcontentloaded').catch(() => undefined);
      await expect(page).toHaveURL(route.expectedUrl ?? escapedRoute(route.path));
      await expect(page.getByTestId('runtime-alpha-dynamic-readiness-panel')).toHaveCount(0);
      await expect(page.locator('body')).not.toContainText(/Local Trainer Runtime Proof|Runtime Alpha|operator_dashboard|payload/i);
    });
  }

  for (const route of ADMIN_DIAGNOSTIC_ROUTES) {
    test(`${route.path} shows the trainer/runtime-alpha proof panel for admin diagnostics`, async ({ page }) => {
      await gotoRoute(page, route.path, route.role);
      await page.waitForLoadState('domcontentloaded').catch(() => undefined);
      await expect(page).toHaveURL(route.expectedUrl ?? escapedRoute(route.path));
      await assertRuntimeAlphaPanel(page);
    });
  }

  for (const route of LEGACY_SYSTEM_ROUTES) {
    test(`${route.path} fails closed instead of exposing trainer/runtime-alpha diagnostics`, async ({ page }) => {
      await gotoAs(page, route.path, route.role);
      await page.waitForLoadState('domcontentloaded').catch(() => undefined);
      await expect(page).toHaveURL(/\/login/);
      await expect(page.getByTestId('runtime-alpha-dynamic-readiness-panel')).toHaveCount(0);
    });
  }
});
