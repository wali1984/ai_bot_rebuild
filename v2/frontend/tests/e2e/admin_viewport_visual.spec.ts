/**
 * Admin Viewport Visual Tests (T5) — CLASSIFICATION: COMPONENT_MOCK
 *
 * Structural geometry checks at 4 canonical viewports with mocked auth + API.
 * These are COMPONENT_MOCK: they verify layout integrity, not real data content.
 *
 * Real screenshot capture with actual data content →
 *   tests/e2e/production/admin_production_audit.spec.ts [PRODUCTION_E2E]
 *
 * Viewports:  1920×1080 | 1440×900 | 768×1024 | 390×844
 */

import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

// CLASSIFICATION: COMPONENT_MOCK

const VIEWPORTS = [
  { label: '1920x1080', width: 1920, height: 1080 },
  { label: '1440x900',  width: 1440, height: 900  },
  { label: '768x1024',  width: 768,  height: 1024 },
  { label: '390x844',   width: 390,  height: 844  },
] as const;

test.describe('Admin Viewport Visual [COMPONENT_MOCK]', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page, 'admin');
    // LIFO: broad route first, specific last
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.route('**/api/v2/risk/status', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live_blocked: true }) });
    });
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ services: [], active_incidents: [], generated_at: new Date().toISOString(), live_blocked: true }) });
    });
  });

  // ── Core shell structure at every viewport ────────────────────────────────
  for (const vp of VIEWPORTS) {
    test(`[${vp.label}] admin shell renders with health strip and main content`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/admin');
      await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId('admin-health-strip')).toBeVisible();
      await expect(page.getByTestId('admin-main')).toBeVisible();
      // Health strip is in the visible viewport (not clipped off-top)
      const stripBox = await page.getByTestId('admin-health-strip').boundingBox();
      if (stripBox) {
        expect(stripBox.y).toBeGreaterThanOrEqual(0);
        expect(stripBox.width).toBeGreaterThan(0);
        expect(stripBox.height).toBeGreaterThan(0);
      }
    });
  }

  // ── EXECUTION BLOCKED always visible in health strip ─────────────────────
  for (const vp of VIEWPORTS) {
    test(`[${vp.label}] EXECUTION BLOCKED always shown in health strip`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/admin');
      await expect(page.getByTestId('admin-health-strip')).toContainText('EXECUTION BLOCKED');
    });
  }

  // ── Left nav visible at tablet and desktop ────────────────────────────────
  for (const vp of VIEWPORTS.filter(v => v.width >= 768)) {
    test(`[${vp.label}] left nav visible and not clipped`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/admin');
      await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10_000 });
      const nav = page.getByTestId('admin-left-nav');
      await expect(nav).toBeVisible();
      const navBox = await nav.boundingBox();
      if (navBox) {
        expect(navBox.x).toBeGreaterThanOrEqual(0);
        expect(navBox.width).toBeGreaterThan(0);
      }
    });
  }

  // ── Risk page structural check at every viewport ──────────────────────────
  for (const vp of VIEWPORTS) {
    test(`[${vp.label}] admin risk page shows BLOCKED and gate banner`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/admin/risk');
      await expect(page.getByTestId('admin-risk-page')).toBeVisible({ timeout: 10_000 });
      await expect(page.getByTestId('admin-risk-page')).toContainText('BLOCKED');
    });
  }

  // ── Overview page at every viewport ──────────────────────────────────────
  for (const vp of VIEWPORTS) {
    test(`[${vp.label}] admin overview page renders without forbidden strings`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/admin');
      await expect(page.getByTestId('admin-overview-page')).toBeVisible({ timeout: 10_000 });
      const body = await page.locator('body').innerText();
      for (const forbidden of ['Connecting…', 'Loading...', 'undefined', '[object Object]']) {
        expect(body).not.toContain(forbidden);
      }
    });
  }

  // ── No horizontal scroll at desktop viewports ────────────────────────────
  for (const vp of VIEWPORTS.filter(v => v.width >= 1440)) {
    test(`[${vp.label}] no horizontal overflow on /admin`, async ({ page }) => {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto('/admin');
      await expect(page.getByTestId('admin-shell')).toBeVisible({ timeout: 10_000 });
      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      expect(scrollWidth).toBeLessThanOrEqual(vp.width + 4); // 4px rounding tolerance
    });
  }
});
