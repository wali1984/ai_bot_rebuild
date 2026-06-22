import { expect, test } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';
import { STATUS_PAGE_FORBIDDEN_TERMS } from './helpers/forbiddenStrings';

const STATUS_RESPONSE = {
  platform_status: 'available',
  api_status: 'available',
  data_status: 'degraded',
  paper_mode: true,
  live_trading_enabled: false,
  incidents: [],
  updated_at: '2026-06-13T00:00:00Z',
  source: 'test-status-contract',
  endpoint: '/api/v2/status',
  stale: false,
  warnings: ['Some market data sources are fallback snapshots.'],
  market_stream: {
    symbol: 'BTCUSDT',
    status: 'stale',
    source: 'Read-only public market stream',
    last_frame_at: '2026-06-13T00:00:00Z',
    lag_ms: 4500,
    stale: true,
  },
  market_stream_alert: {
    status: 'active',
    severity: 'warning',
    summary: 'Market stream freshness is degraded or unavailable.',
    action: 'Fallback market data remains labeled until stream freshness recovers.',
    stale_for_ms: 4500,
  },
  market_stream_alert_history: {
    symbol: 'BTCUSDT',
    event_count: 2,
    active_count: 1,
    latest: {
      recorded_at: '2026-06-13T00:00:00Z',
      severity: 'warning',
      summary: 'Market stream freshness is degraded or unavailable.',
      action: 'Fallback market data remains labeled until stream freshness recovers.',
    },
    production_alerting_integrated: false,
    public_market_data_only: true,
  },
  market_stream_alert_notifier: {
    provider: 'webhook',
    configured: true,
    enabled: false,
    delivery_supported: false,
    delivered: false,
    last_delivery_at: null,
    last_status_code: null,
    last_error: 'Webhook disabled.',
    production_alerting_integrated: false,
    public_market_data_only: true,
  },
  derivatives_data: {
    status: 'pending',
    source: 'Derivatives source evidence pending',
    funding: 'verified',
    open_interest: 'verified',
    liquidations: 'pending',
    long_short: 'pending',
    basis: 'pending',
    exchange_comparison: 'pending',
    stale: true,
    missing_count: 4,
  },
};

test.beforeEach(async ({ page }) => {
  await mockAuth(page, 'public');
  await page.route('**/api/v2/status', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(STATUS_RESPONSE) });
  });
  await page.route('**/operator_runtime/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'PRESENT_CURRENT',
        generated_at: '2026-06-13T00:00:00Z',
        symbols: ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'],
        live_gate: 'paper_mode',
      }),
    });
  });
  await page.route('**/v2_top10_dashboards/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'PRESENT_CURRENT',
        generated_at: '2026-06-13T00:00:00Z',
        rows: [{ symbol: 'BTCUSDT' }, { symbol: 'ETHUSDT' }],
      }),
    });
  });
});

test.describe('Public status redesign', () => {
  test('renders a public-safe status page without authentication', async ({ page }) => {
    await gotoAs(page, '/status');

    await expect(page.getByTestId('page-public-status')).toBeVisible();
    await expect(page.locator('body')).toContainText(/Platform availability/i);
    await expect(page.locator('body')).toContainText(/API availability/i);
    await expect(page.locator('body')).toContainText(/Market stream/i);
    await expect(page.locator('body')).toContainText(/Derivatives data/i);
    await expect(page.locator('body')).toContainText(/Stream alert/i);
    await expect(page.locator('body')).toContainText(/Alert history/i);
    await expect(page.locator('body')).toContainText(/Alert delivery/i);
    await expect(page.getByTestId('realtime-data-atlas-public')).toBeVisible();
    await expect(page.locator('body')).toContainText(/Realtime data health/i);
    await expect(page.locator('body')).toContainText(/data feeds available/i);
  });

  test('shows paper/read-only posture and live trading disabled state', async ({ page }) => {
    await gotoAs(page, '/status');

    await expect(page.locator('body')).toContainText(/Paper mode active|Paper \/ read-only mode|read-only/i);
    await expect(page.locator('body')).toContainText(/Live trading disabled/i);
  });

  test('shows freshness, incidents, and last updated context', async ({ page }) => {
    await gotoAs(page, '/status');

    await expect(page.locator('body')).toContainText(/Market data freshness|Data freshness/i);
    await expect(page.locator('body')).toContainText(/Market stream freshness is degraded|Fallback market data remains labeled/i);
    await expect(page.locator('body')).toContainText(/Production alerting pending/i);
    await expect(page.locator('body')).toContainText(/Outbound alert delivery is configured but disabled/i);
    await expect(page.locator('body')).toContainText(/Signal data freshness|Signal/i);
    await expect(page.locator('body')).toContainText(/Derivatives source evidence pending|Derivatives data/i);
    await expect(page.locator('body')).toContainText(/Incidents|Maintenance/i);
    await expect(page.locator('body')).toContainText(/Last updated|Updated/i);
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
