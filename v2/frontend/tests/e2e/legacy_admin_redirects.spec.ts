/**
 * Legacy Admin Redirect E2E
 *
 * Verifies that every legacy admin path in MERGED_LEGACY_PATHS redirects
 * to its canonical destination. Uses admin auth to bypass page-level access
 * gates and focus purely on routing behavior.
 */

import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

const REDIRECT_TABLE: Array<{ from: string; to: string }> = [
  // Overview
  { from: '/admin/war-room',              to: '/admin' },
  { from: '/admin/system',               to: '/admin' },
  { from: '/admin/system-health',        to: '/admin' },
  // Data
  { from: '/admin/monitor-center',       to: '/admin/data' },
  { from: '/admin/ingestors',            to: '/admin/data' },
  // Intelligence
  { from: '/admin/trainer',              to: '/admin/intelligence' },
  { from: '/admin/trainer-admin',        to: '/admin/intelligence' },
  { from: '/admin/trainer-prediction-monitor', to: '/admin/intelligence' },
  { from: '/admin/model-state',          to: '/admin/intelligence' },
  { from: '/admin/ai-brain',             to: '/admin/intelligence' },
  { from: '/admin/signal-explainability',to: '/admin/intelligence' },
  // Orchestration
  { from: '/admin/orchestrator',         to: '/admin/orchestration' },
  { from: '/admin/orchestrator-admin',   to: '/admin/orchestration' },
  { from: '/admin/traders',              to: '/admin/orchestration' },
  { from: '/admin/strategy-admin',       to: '/admin/orchestration' },
  // Risk
  { from: '/admin/risk-control',         to: '/admin/risk' },
  { from: '/admin/readiness',            to: '/admin/risk' },
  { from: '/admin/live-readiness',       to: '/admin/risk' },
  { from: '/admin/external-manual-position-quarantine', to: '/admin/risk' },
  // Execution
  { from: '/admin/execution-admin',      to: '/admin/execution' },
  // Exchanges
  { from: '/admin/exchange-manager',     to: '/admin/exchanges' },
  // Config
  { from: '/admin/config-admin',         to: '/admin/config' },
  // Reports
  { from: '/admin/report-center',        to: '/admin/reports' },
  { from: '/admin/executive-status',     to: '/admin/reports' },
  { from: '/admin/evidence',             to: '/admin/reports' },
  // Logs
  { from: '/admin/logs-errors',          to: '/admin/logs' },
  // Audit
  { from: '/admin/audit-ledger',         to: '/admin/audit' },
  // Tools
  { from: '/admin/scripts',              to: '/admin/tools' },
  { from: '/admin/script-registry',      to: '/admin/tools' },
  { from: '/admin/coverage-system-atlas',to: '/admin/tools' },
  { from: '/admin/claude-admin-ai',      to: '/admin/tools' },
  { from: '/admin/ollama-local-assistant', to: '/admin/tools' },
  { from: '/admin/codex-review-center',  to: '/admin/tools' },
  // /system/* namespace
  { from: '/system/health',              to: '/admin' },
  { from: '/system/risk-controllers',    to: '/admin/risk' },
  { from: '/system/exchanges',           to: '/admin/exchanges' },
  { from: '/system/config',              to: '/admin/config' },
  { from: '/system/logs',                to: '/admin/logs' },
  { from: '/system/trainer',             to: '/admin/intelligence' },
  { from: '/system/orchestrator',        to: '/admin/orchestration' },
  { from: '/system/execution',           to: '/admin/execution' },
  { from: '/system/audit-ledger',        to: '/admin/audit' },
  { from: '/system/readiness',           to: '/admin/risk' },
  { from: '/system/reports',             to: '/admin/reports' },
  // Trader/public legacy
  { from: '/mission-control',            to: '/dashboard' },
  { from: '/market',                     to: '/markets' },
  { from: '/trader',                     to: '/trade' },
];

test.describe('Legacy Admin Redirects', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page, 'superadmin');
    // Stub all admin and data APIs to prevent network errors
    await page.route('**/api/v2/admin/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ services: [], active_incidents: [], generated_at: new Date().toISOString() }) });
    });
    await page.route('**/api/v2/risk/status', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ live_blocked: true }) });
    });
    await page.route('**/api/v2/**', async (route) => {
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
    });
  });

  for (const { from, to } of REDIRECT_TABLE) {
    test(`${from} → ${to}`, async ({ page }) => {
      await page.goto(from);
      await expect(page).toHaveURL(new RegExp(to.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')), { timeout: 6000 });
    });
  }

  test('No double-redirect loops: /admin stays at /admin', async ({ page }) => {
    await page.goto('/admin');
    await expect(page).toHaveURL('/admin');
    await expect(page.getByTestId('admin-shell')).toBeVisible();
  });

  test('All canonical admin paths serve content, not more redirects', async ({ page }) => {
    const canonicals = ['/admin', '/admin/data', '/admin/intelligence', '/admin/orchestration',
      '/admin/risk', '/admin/execution', '/admin/exchanges', '/admin/config',
      '/admin/users', '/admin/reports', '/admin/logs', '/admin/audit', '/admin/tools'];
    for (const path of canonicals) {
      await page.goto(path);
      // URL should not change further (no redirect loop)
      await expect(page).toHaveURL(path);
    }
  });
});
