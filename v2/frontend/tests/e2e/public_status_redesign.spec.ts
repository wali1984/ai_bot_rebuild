import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';
import { STATUS_PAGE_FORBIDDEN_TERMS } from './helpers/forbiddenStrings';

const STATUS_RESPONSE = {
  live_gate_status: 'enabled_operator_approved',
  runtime_state: 'CURRENT',
  public_route_failed_count: 0,
  supervisor_health: 'CURRENT',
};

const MARKET_RESPONSE = {
  data: {
    count: 628,
    symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
  },
  source: 'mocked market overview',
  source_type: 'api',
  endpoint: '/api/v2/market/overview',
  timestamp: '2026-06-13T00:00:00Z',
  received_at: '2026-06-13T00:00:01Z',
  lag_ms: 1000,
  stale: false,
  missing_fields: [],
  warnings: [],
  mode: 'read_only',
};

test.beforeEach(async ({ page }) => {
  await mockAuth(page, 'public');
  await page.route('**/api/v2/public/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STATUS_RESPONSE) });
  });
  await page.route('**/api/v2/market/overview', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(MARKET_RESPONSE) });
  });
});

test.describe('Public status redesign', () => {
  test('uses resource WebSocket streams instead of interval polling', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/public-status/index.tsx'), 'utf8');

    expect(source).toContain("useRealtimeResource<PublicStatusData>");
    expect(source).toContain("url: '/api/v2/public/status'");
    expect(source).toContain("url: '/api/v2/market/overview'");
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain("fetch('/api/v2/public/status')");
    expect(source).not.toContain("fetch('/api/v2/market/overview')");
  });

  test('renders a public-safe status page without authentication', async ({ page }) => {
    await gotoAs(page, '/status');

    await expect(page.getByTestId('page-public-status')).toBeVisible();
    await expect(page.locator('body')).toContainText(/NERVYX ONE Status/i);
    await expect(page.locator('body')).toContainText(/Platform/i);
    await expect(page.locator('body')).toContainText(/Market Data/i);
    await expect(page.locator('body')).toContainText(/Signal Feed/i);
    await expect(page.locator('body')).toContainText(/Order Routing/i);
    await expect(page.locator('body')).toContainText(/628 symbols in universe/i);
    await expect(page.locator('body')).toContainText(/Status updates from live resource streams/i);
  });

  test('shows guarded public posture without paper or disabled-live wording', async ({ page }) => {
    await gotoAs(page, '/status');

    const body = page.locator('body');
    await expect(body).toContainText(/Risk-gated/i);
    await expect(body).toContainText(/Guarded/i);
    await expect(body).not.toContainText(/paper only|paper mode|read-only|read only|live trading disabled|simulated/i);
  });

  test('shows freshness, maintenance, and capability context', async ({ page }) => {
    await gotoAs(page, '/status');

    await expect(page.locator('body')).toContainText(/Data Freshness/i);
    await expect(page.locator('body')).toContainText(/Status and market feeds update through resource WebSockets/i);
    await expect(page.locator('body')).toContainText(/Scheduled Maintenance/i);
    await expect(page.locator('body')).toContainText(/Platform Capabilities/i);
  });

  test('does not expose forbidden internal status terms', async ({ page }) => {
    await gotoAs(page, '/status');

    const body = page.locator('body');
    for (const term of [...STATUS_PAGE_FORBIDDEN_TERMS, 'operator', 'mission control', 'war room', 'payload']) {
      await expect(body).not.toContainText(new RegExp(term, 'i'));
    }
  });

  test('keeps legacy simple status public-safe without raw source paths', async ({ page }) => {
    await page.route('**/operator_runtime/frontend_truth/**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          plain_english_summary: 'Read-only platform status from /operator_runtime/frontend_truth/latest/frontend_truth_payload.json',
          current_goal: 'Keep live trading disabled while source payloads are validated.',
          live_gate: 'LIVE_TRADING_DISABLED',
          paper_edge_status: 'PENDING',
          trainer_parity_status: 'PENDING',
          decision_quality_status: 'PENDING',
          shutdown_recommendation: 'BLOCKED',
          blockers_simple: ['Missing source: /operator_runtime/frontend_truth/latest/frontend_truth_payload.json'],
          page_cards: [
            {
              id: 'status',
              title: 'Platform status',
              color: 'yellow',
              summary: 'Status source payload is stale.',
              why_it_matters: 'Raw operator_runtime paths must not be public.',
              what_needs_to_happen_next: 'Refresh the public status source.',
              evidence_paths: ['/operator_runtime/frontend_truth/latest/frontend_truth_payload.json'],
              source_status: 'STALE',
            },
          ],
          stale_payloads: ['/operator_runtime/frontend_truth/latest/frontend_truth_payload.json'],
          missing_payloads: ['/operator_runtime/private/latest/secret_payload.json'],
        }),
      });
    });

    await gotoAs(page, '/status-simple');

    const body = page.locator('body');
    await expect(page.getByTestId('page-user-status')).toBeVisible();
    await expect(body).toContainText(/Public status summary|status source/i);
    await expect(body).not.toContainText(/operator_runtime|frontend_truth_payload|secret_payload|raw operator/i);
    await expect(body).not.toContainText(/payload/i);
    await expect(page.locator('code')).toHaveCount(0);
  });

  test('does not render stack traces or default-visible raw JSON', async ({ page }) => {
    await gotoAs(page, '/status');

    await expect(page.locator('pre')).toHaveCount(0);
    await expect(page.locator('body')).not.toContainText(/\{\s*"platform_status"|Traceback|Error:/i);
  });

  for (const viewport of [
    { width: 1920, height: 1080 },
    { width: 1440, height: 900 },
    { width: 768, height: 1024 },
    { width: 390, height: 844 },
  ]) {
    test(`has no horizontal scroll at ${viewport.width}x${viewport.height}`, async ({ page }) => {
      await page.setViewportSize(viewport);
      await gotoAs(page, '/status');

      const hasHorizontalScroll = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      expect(hasHorizontalScroll).toBe(false);
    });
  }
});
