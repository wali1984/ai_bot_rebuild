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
  { from: '/admin/ingestors',            to: '/admin/data' },
  // Intelligence
  { from: '/admin/trainer',              to: '/admin/intelligence' },
  { from: '/admin/ai-brain',             to: '/admin/model-state' },
  // Orchestration
  { from: '/admin/orchestrator',         to: '/admin/orchestration' },
  { from: '/admin/orchestrator-admin',   to: '/admin/orchestration' },
  { from: '/admin/traders',              to: '/admin/orchestration' },
  { from: '/admin/strategy-admin',       to: '/admin/orchestration' },
  // Risk
  { from: '/admin/risk-control',         to: '/admin/risk' },
  { from: '/admin/readiness',            to: '/admin/risk' },
  // Execution
  { from: '/admin/execution-admin',      to: '/admin/execution' },
  // Exchanges
  { from: '/admin/exchange-manager',     to: '/admin/exchanges' },
  // Config
  { from: '/admin/config-admin',         to: '/admin/config' },
  // Reports
  { from: '/admin/report-center',        to: '/admin/reports' },
  { from: '/admin/operator-proof-dashboard', to: '/admin/evidence' },
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
  // /system/* namespace
  { from: '/system/executive-summary',   to: '/admin/executive-status' },
  { from: '/system/build-code-review',   to: '/admin/codex-review-center' },
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
  { from: '/ingestors',                  to: '/markets/ingestors' },
  { from: '/providers',                  to: '/markets/ingestors' },
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

  test('/live-canary serves the dedicated canonical live-canary surface', async ({ page }) => {
    await page.goto('/live-canary');
    await expect(page).toHaveURL(/\/live-canary$/);
    await expect(page.getByTestId('page-live-canary')).toBeVisible();
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText('Live Canary Runtime Truth');
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText('/api/v2/live-canary/status');
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText('/api/v2/a-plus/inventory');
  });

  test('/providers serves canonical provider truth without retired active panels', async ({ page }) => {
    await page.goto('/providers');
    await expect(page).toHaveURL(/\/markets\/ingestors/);
    await expect(page.getByTestId('page-markets-ingestors')).toBeVisible();
    await expect(page.getByTestId('provider-truth-panel')).toContainText('/api/v2/providers/status');
    await expect(page.getByTestId('provider-card-coinank')).toContainText('CoinAnk');
    await expect(page.getByTestId('provider-card-coinglass')).toContainText('CoinGlass');
    await expect(page.getByTestId('provider-card-moralis')).toContainText('Moralis');
    await expect(page.getByTestId('provider-card-santiment')).toContainText(/Santiment|Sanbase/);
    await expect(page.getByTestId('provider-truth-panel')).not.toContainText(/Alpha Vantage|LunarCrush|Nansen/i);
  });

  test('/markets exposes required provider coverage for route truth crawl', async ({ page }) => {
    await page.goto('/markets');
    await expect(page.getByTestId('page-markets')).toBeVisible();
    await expect(page.getByTestId('market-provider-coverage')).toContainText('/api/v2/providers/status');
    await expect(page.getByTestId('market-provider-coinank')).toContainText('CoinAnk');
    await expect(page.getByTestId('market-provider-coinglass')).toContainText('CoinGlass');
    await expect(page.getByTestId('market-provider-moralis')).toContainText('Moralis');
    await expect(page.getByTestId('market-provider-santiment')).toContainText(/Santiment|Sanbase/);
    await expect(page.getByTestId('market-provider-coverage')).not.toContainText(/Alpha Vantage|LunarCrush|Nansen/i);
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
