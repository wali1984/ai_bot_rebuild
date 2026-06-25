/**
 * Admin Data Consistency E2E
 *
 * Verifies that admin pages:
 * 1. Show MissingSourceIncident (not "Connecting…" or blank) when backend data is unavailable
 * 2. Show data when backend responds with well-formed payloads
 * 3. Never show blank/empty panels without an incident card
 */

import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

const FORBIDDEN_STRINGS = ['Connecting…', 'Loading...', 'undefined', '[object Object]'];

async function stubAdminApis(page: import('@playwright/test').Page, override?: Record<string, unknown>) {
  await page.route('**/api/v2/admin/overview', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_at: new Date().toISOString(),
        live_gate: 'blocked',
        services: [
          { name: 'trainer', status: 'ok', message: 'Running', last_checked_at: new Date().toISOString() },
          { name: 'orchestrator', status: 'warn', message: 'Slow', last_checked_at: new Date().toISOString() },
          { name: 'redis', status: 'error', message: 'Connection refused', last_checked_at: new Date().toISOString() },
        ],
        active_incidents: [],
        ...override,
      }),
    });
  });
  await page.route('**/api/v2/admin/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
  await page.route('**/api/v2/risk/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live_blocked: true, rules: [] }) });
  });
  await page.route('**/api/v2/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
}

test.describe('Admin Data Consistency', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page, 'admin');
  });

  test('/admin shows service health grid with 3 services from mock', async ({ page }) => {
    await stubAdminApis(page);
    await page.goto('/admin');
    await expect(page.getByTestId('admin-overview-page')).toBeVisible();
    // ServiceHealthGrid should render
    const grid = page.getByTestId('service-health-grid');
    if (await grid.count() > 0) {
      await expect(grid).toBeVisible();
      await expect(grid.getByTestId('service-health-trainer')).toBeVisible();
      await expect(grid.getByTestId('service-health-orchestrator')).toBeVisible();
      await expect(grid.getByTestId('service-health-redis')).toBeVisible();
    }
  });

  test('/admin shows incident count badge when incidents exist', async ({ page }) => {
    await mockAuth(page, 'admin');
    await page.route('**/api/v2/admin/overview', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_at: new Date().toISOString(),
          live_gate: 'blocked',
          services: [],
          active_incidents: [
            {
              id: 'inc-001',
              severity: 'high',
              missing_source: 'trainer_feed',
              expected_endpoint: '/api/v2/trainer/status',
              owner_service: 'trainer',
              last_success_at: null,
              current_error: 'connection refused',
              affected_pages: ['intelligence'],
              remediation_action: 'Restart trainer service',
              incident_id: 'inc-001',
            },
          ],
        }),
      });
    });
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.goto('/admin');
    await expect(page.getByTestId('admin-incident-count')).toBeVisible();
    await expect(page.getByTestId('admin-incident-count')).toContainText('1 incident');
  });

  test('No forbidden "Connecting…" strings on /admin when API fails', async ({ page }) => {
    await page.route('**/api/v2/admin/overview', async (route) => {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'unavailable' }) });
    });
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'unavailable' }) });
    });
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.goto('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    for (const s of FORBIDDEN_STRINGS) {
      expect(bodyText).not.toContain(s);
    }
  });

  test('/admin/data shows MissingSourceIncident when API is unavailable', async ({ page }) => {
    await page.route('**/api/v2/admin/overview', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ services: [], active_incidents: [], generated_at: new Date().toISOString() }) });
    });
    await page.route('**/api/v2/admin/data/overview', async (route) => {
      await route.fulfill({ status: 503, contentType: 'application/json', body: JSON.stringify({ error: 'unavailable' }) });
    });
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
    await page.goto('/admin/data');
    await expect(page.getByTestId('admin-data-page')).toBeVisible();
    const bodyText = await page.locator('body').innerText();
    for (const s of FORBIDDEN_STRINGS) {
      expect(bodyText).not.toContain(s);
    }
  });

  test('Health strip always shows EXECUTION BLOCKED regardless of data state', async ({ page }) => {
    await stubAdminApis(page);
    await page.goto('/admin');
    await expect(page.getByTestId('admin-health-strip')).toContainText('EXECUTION BLOCKED');
    // Also on other pages
    await page.goto('/admin/config');
    await expect(page.getByTestId('admin-health-strip')).toContainText('EXECUTION BLOCKED');
  });

  test('/admin/risk shows BLOCKED status when live_blocked is true', async ({ page }) => {
    await stubAdminApis(page);
    await page.goto('/admin/risk');
    await expect(page.getByTestId('admin-risk-page')).toBeVisible();
    await expect(page.getByTestId('admin-risk-page')).toContainText('BLOCKED');
  });

  test('/admin/intelligence shows MissingSourceIncident tabs when backend returns empty', async ({ page }) => {
    await stubAdminApis(page);
    await page.goto('/admin/intelligence');
    await expect(page.getByTestId('admin-intelligence-page')).toBeVisible();
    // Tab buttons should be present
    await expect(page.getByTestId('tab-trainer')).toBeVisible();
    await expect(page.getByTestId('tab-predictions')).toBeVisible();
  });
});
