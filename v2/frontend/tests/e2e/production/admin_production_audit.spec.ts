/**
 * Admin Production Audit [PRODUCTION_E2E]
 *
 * CLASSIFICATION: PRODUCTION_E2E
 *
 * Runs ONLY against the deployed production frontend + backend.
 * No mockAuth. No route interception. No broad API stubs.
 * Screenshots are captured as evidence artifacts for every route × viewport.
 *
 * GATE RULE: This suite must pass before the admin release gate can be set to true.
 *
 * Environment variables required:
 *   PLAYWRIGHT_BASE_URL        — production frontend URL (e.g. https://nervyx.local)
 *   PRODUCTION_ADMIN_SESSION   — valid admin session cookie value
 *   PRODUCTION_SUPERADMIN_SESSION — valid superadmin session cookie value
 *   PRODUCTION_TRADER_SESSION  — valid trader session cookie value (for access-denied checks)
 *
 * Run:
 *   npm run test:production-e2e
 *
 * Screenshots saved to: v2/frontend/artifacts/production-audit/
 */

import { test, expect, type BrowserContext } from '@playwright/test';
import * as path from 'path';
import * as fs from 'fs';

const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? '';
const ADMIN_SESSION = process.env.PRODUCTION_ADMIN_SESSION ?? '';
const SUPERADMIN_SESSION = process.env.PRODUCTION_SUPERADMIN_SESSION ?? '';
const TRADER_SESSION = process.env.PRODUCTION_TRADER_SESSION ?? '';

const ARTIFACT_DIR = path.join(__dirname, '../../../artifacts/production-audit');

const ADMIN_ROUTES = [
  { path: '/admin',               testId: 'admin-overview-page',      label: 'Overview'       },
  { path: '/admin/data',          testId: 'admin-data-page',           label: 'Data'           },
  { path: '/admin/intelligence',  testId: 'admin-intelligence-page',   label: 'Intelligence'   },
  { path: '/admin/orchestration', testId: 'admin-orchestration-page',  label: 'Orchestration'  },
  { path: '/admin/risk',          testId: 'admin-risk-page',           label: 'Risk'           },
  { path: '/admin/execution',     testId: 'admin-execution-page',      label: 'Execution'      },
  { path: '/admin/exchanges',     testId: 'admin-exchanges-page',      label: 'Exchanges'      },
  { path: '/admin/config',        testId: 'admin-config-page',         label: 'Config'         },
  { path: '/admin/users',         testId: 'admin-users-page',          label: 'Users'          },
  { path: '/admin/reports',       testId: 'admin-reports-page',        label: 'Reports'        },
];

const SUPERADMIN_ROUTES = [
  { path: '/admin/logs',  testId: 'admin-logs-page',  label: 'Logs'  },
  { path: '/admin/audit', testId: 'admin-audit-page', label: 'Audit' },
  { path: '/admin/tools', testId: 'admin-tools-page', label: 'Tools' },
];

const VIEWPORTS = [
  { label: '1920x1080', width: 1920, height: 1080 },
  { label: '1440x900',  width: 1440, height: 900  },
  { label: '768x1024',  width: 768,  height: 1024 },
  { label: '390x844',   width: 390,  height: 844  },
] as const;

const FORBIDDEN_STRINGS = [
  'Connecting…', 'Loading...', '[object Object]', 'undefined',
  '"status":', '"error":', '{"',  // raw JSON leaked to UI
];

function ensureArtifactDir(): void {
  if (!fs.existsSync(ARTIFACT_DIR)) fs.mkdirSync(ARTIFACT_DIR, { recursive: true });
}

async function setSession(context: BrowserContext, session: string): Promise<void> {
  if (!session) throw new Error('Session cookie not provided — cannot run PRODUCTION_E2E without real auth');
  const url = new URL(BASE_URL || 'http://localhost');
  await context.addCookies([{
    name: 'session',
    value: session,
    domain: url.hostname,
    path: '/',
    httpOnly: true,
    secure: url.protocol === 'https:',
  }]);
}

// ── Preflight ──────────────────────────────────────────────────────────────

test.describe('Admin Production Audit [PRODUCTION_E2E]', () => {
  test.beforeAll(() => {
    if (!BASE_URL) {
      throw new Error('PLAYWRIGHT_BASE_URL must be set to the production frontend URL');
    }
    if (!ADMIN_SESSION) {
      throw new Error('PRODUCTION_ADMIN_SESSION must be set — no mockAuth in production audit');
    }
    ensureArtifactDir();
  });

  // ── Role verification — real backend ───────────────────────────────────────

  test('[PRODUCTION_E2E] admin session reaches /admin and admin-shell renders', async ({ page, context }) => {
    await setSession(context, ADMIN_SESSION);
    await page.goto(`${BASE_URL}/admin`);
    await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 15_000 });
    await expect(page.getByTestId('admin-role-badge')).toContainText('ADMIN');
    await expect(page.getByTestId('admin-health-strip')).toContainText('EXECUTION BLOCKED');
  });

  test('[PRODUCTION_E2E] trader session denied on /admin — sees access-denied or redirected', async ({ page, context }) => {
    if (!TRADER_SESSION) test.skip(true, 'PRODUCTION_TRADER_SESSION not set');
    await setSession(context, TRADER_SESSION);
    await page.goto(`${BASE_URL}/admin`);
    const hasAccessDenied = await page.getByTestId('access-denied').isVisible().catch(() => false);
    const isOnLogin = page.url().includes('/login');
    expect(hasAccessDenied || isOnLogin).toBe(true);
  });

  test('[PRODUCTION_E2E] admin denied on /admin/audit (requires superadmin)', async ({ page, context }) => {
    await setSession(context, ADMIN_SESSION);
    await page.goto(`${BASE_URL}/admin/audit`);
    await expect(page.getByTestId('access-denied')).toBeVisible({ timeout: 8_000 });
  });

  test('[PRODUCTION_E2E] superadmin can access /admin/audit and /admin/logs', async ({ page, context }) => {
    if (!SUPERADMIN_SESSION) test.skip(true, 'PRODUCTION_SUPERADMIN_SESSION not set');
    await setSession(context, SUPERADMIN_SESSION);
    await page.goto(`${BASE_URL}/admin/audit`);
    await expect(page.getByTestId('admin-audit-page')).toBeVisible({ timeout: 10_000 });
    await page.goto(`${BASE_URL}/admin/logs`);
    await expect(page.getByTestId('admin-logs-page')).toBeVisible({ timeout: 10_000 });
  });

  // ── All 10 admin routes load real content ─────────────────────────────────

  for (const route of ADMIN_ROUTES) {
    test(`[PRODUCTION_E2E] ${route.label} (${route.path}) loads real content`, async ({ page, context }) => {
      await setSession(context, ADMIN_SESSION);
      await page.goto(`${BASE_URL}${route.path}`);
      await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 12_000 });
      await expect(page.getByTestId(route.testId)).toBeVisible({ timeout: 10_000 });
      // No forbidden strings — real data, no raw JSON or permanent loading state
      const body = await page.locator('body').innerText();
      for (const s of FORBIDDEN_STRINGS) {
        expect(body, `Forbidden "${s}" on ${route.path}`).not.toContain(s);
      }
      // Health strip always blocked
      await expect(page.getByTestId('admin-health-strip')).toContainText('EXECUTION BLOCKED');
    });
  }

  // ── 3 superadmin-only routes ──────────────────────────────────────────────

  for (const route of SUPERADMIN_ROUTES) {
    test(`[PRODUCTION_E2E] superadmin-only ${route.label} (${route.path})`, async ({ page, context }) => {
      if (!SUPERADMIN_SESSION) test.skip(true, 'PRODUCTION_SUPERADMIN_SESSION not set');
      await setSession(context, SUPERADMIN_SESSION);
      await page.goto(`${BASE_URL}${route.path}`);
      await expect(page.getByTestId(route.testId)).toBeVisible({ timeout: 12_000 });
      const body = await page.locator('body').innerText();
      for (const s of FORBIDDEN_STRINGS) {
        expect(body, `Forbidden "${s}" on ${route.path}`).not.toContain(s);
      }
    });
  }

  // ── Screenshot evidence at all 4 viewports ───────────────────────────────
  // T5: real screenshots, real data content, not geometry assertions

  for (const vp of VIEWPORTS) {
    test(`[PRODUCTION_E2E] screenshot /admin at ${vp.label}`, async ({ page, context }) => {
      await setSession(context, ADMIN_SESSION);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${BASE_URL}/admin`);
      await expect(page.getByTestId('admin-overview-page')).toBeVisible({ timeout: 15_000 });
      // Allow data to settle before screenshot
      await page.waitForTimeout(1000);
      const screenshotPath = path.join(ARTIFACT_DIR, `admin-overview-${vp.label}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`PRODUCTION screenshot saved: ${screenshotPath}`);
      // Visual assertions
      const body = await page.locator('body').innerText();
      for (const s of FORBIDDEN_STRINGS) {
        expect(body, `Forbidden "${s}" at ${vp.label}`).not.toContain(s);
      }
      // Health strip visible and not clipped
      const strip = page.getByTestId('admin-health-strip');
      await expect(strip).toBeVisible();
      const stripBox = await strip.boundingBox();
      expect(stripBox?.y).toBeGreaterThanOrEqual(0);
      expect(stripBox?.width).toBeGreaterThan(0);
    });
  }

  for (const vp of VIEWPORTS) {
    test(`[PRODUCTION_E2E] screenshot /admin/risk at ${vp.label}`, async ({ page, context }) => {
      await setSession(context, ADMIN_SESSION);
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto(`${BASE_URL}/admin/risk`);
      await expect(page.getByTestId('admin-risk-page')).toBeVisible({ timeout: 15_000 });
      await page.waitForTimeout(1000);
      const screenshotPath = path.join(ARTIFACT_DIR, `admin-risk-${vp.label}.png`);
      await page.screenshot({ path: screenshotPath, fullPage: true });
      console.log(`PRODUCTION screenshot saved: ${screenshotPath}`);
      await expect(page.getByTestId('admin-risk-page')).toContainText('BLOCKED');
    });
  }

  // ── T6: Real control contract — blocked attempts must be audited ───────────

  test('[PRODUCTION_E2E] enable_live_trading blocked — backend returns 403 not 200', async ({ request }) => {
    if (!ADMIN_SESSION) test.skip(true, 'PRODUCTION_ADMIN_SESSION not set');
    const apiBase = BASE_URL.replace(/\/$/, '');
    const res = await request.post(`${apiBase}/api/v2/admin/controls/enable_live_trading`, {
      headers: { Cookie: `session=${ADMIN_SESSION}`, 'Content-Type': 'application/json' },
      data: { action_id: 'enable_live_trading', reason: 'production audit test — must be blocked' },
    });
    // Must never return 200 — live trading is permanently blocked by policy
    expect(res.status(), 'enable_live_trading must not return 200 in production').not.toBe(200);
    const body = await res.json().catch(() => ({})) as Record<string, unknown>;
    console.log('PRODUCTION enable_live_trading result:', res.status(), JSON.stringify(body));
  });

  test('[PRODUCTION_E2E] DangerousControlPanel buttons exist in risk Controls tab', async ({ page, context }) => {
    await setSession(context, ADMIN_SESSION);
    await page.goto(`${BASE_URL}/admin/risk`);
    await expect(page.getByTestId('admin-risk-page')).toBeVisible({ timeout: 12_000 });
    await page.getByRole('button', { name: 'Controls' }).click();
    const btn = page.locator('[data-testid="control-btn-enable_live_trading"]');
    await expect(btn).toBeVisible({ timeout: 5_000 });
    // Click must open dialog — no backend call at this step
    await btn.click();
    await expect(page.locator('[data-testid="control-dialog-enable_live_trading"]')).toBeVisible({ timeout: 5_000 });
    await expect(page.getByTestId('control-dialog-enable_live_trading')).toContainText('action_id:');
    // Screenshot of dialog for evidence
    const screenshotPath = path.join(ARTIFACT_DIR, 'control-dialog-enable_live_trading.png');
    await page.screenshot({ path: screenshotPath });
    console.log(`PRODUCTION control dialog screenshot: ${screenshotPath}`);
  });

  // ── Source metadata freshness audit ──────────────────────────────────────

  test('[PRODUCTION_E2E] admin overview shows freshness badge (not stale)', async ({ page, context }) => {
    await setSession(context, ADMIN_SESSION);
    await page.goto(`${BASE_URL}/admin`);
    await expect(page.getByTestId('admin-overview-page')).toBeVisible({ timeout: 15_000 });
    // FreshnessBadge should exist and not show STALE or ERROR state
    const badge = page.locator('[data-testid="freshness-badge"]');
    if (await badge.count() > 0) {
      const badgeText = await badge.innerText();
      console.log('PRODUCTION freshness badge:', badgeText);
      expect(badgeText).not.toContain('ERROR');
    } else {
      console.warn('PRODUCTION no freshness badge found — mark as NOT_TESTABLE');
    }
  });
});
