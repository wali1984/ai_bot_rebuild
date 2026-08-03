import { test, expect } from '@playwright/test';
import { mockAuth } from './helpers/auth';

test.describe('trader runtime truth routes', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page, 'trader');
    await page.route('**/api/v2/market/overview**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          data: { tickers: [] },
          source: '/api/v2/market/overview',
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
        }),
      });
    });
  });

  test('/risk renders trader-safe liquidation hedge squeeze truth without admin RBAC', async ({ page }) => {
    await page.route('**/api/v2/mobile/risk-status**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'mobile_risk_status_v2',
          source: '/api/v2/mobile/risk-status',
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          live_gate: { gate: 'blocked_human_only', label: 'OPERATOR GATED', places_real_order: false },
          places_real_order: false,
          routes_to_live: false,
          kill_switch_active: false,
          real_trader_readiness: { live_ready: false, order_submitted: false, test_order_submitted: false },
          adaptive_hedge_cross_margin: {
            hedge_state: 'NO_HEDGE',
            portfolio_liquidation_buffer_usd: 998.12,
            maintenance_margin_estimate_usd: 12.4,
            margin_call_risk: 'LOW',
          },
          preemptive_edge_control: {
            advanced_indicator_status: 'CURRENT',
            advanced_indicators: { sweep_risk_can_block_or_reduce: true },
          },
        }),
      });
    });
    const adminOverviewCalls: string[] = [];
    await page.route('**/api/v2/admin/overview**', async (route) => {
      adminOverviewCalls.push(route.request().url());
      await route.abort();
    });

    await page.goto('/risk');

    await expect(page).toHaveURL(/\/risk$/);
    await expect(page.getByTestId('access-denied')).toHaveCount(0);
    await expect(page.getByTestId('page-risk')).toBeVisible();
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText('/api/v2/mobile/risk-status');
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Liquidation buffer/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Hedge state/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Squeeze risk/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Kill switch/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Operator approval/i);
    expect(adminOverviewCalls).toEqual([]);
  });

  test('/live-canary renders trader-safe dry-run and A+ truth without admin RBAC', async ({ page }) => {
    await page.route('**/api/v2/live-canary/status**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'control_center_live_canary_status_v1',
          source: '/api/v2/live-canary/status',
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            selected_a_plus_candidate: null,
            why_none: 'NO_A_PLUS_CANDIDATE',
            dry_run: true,
            operator_approval_required: true,
            no_mutation_flags: {
              real_order_attempted: false,
              real_order_submitted: false,
              test_order_submitted: false,
              leverage_changed: false,
              margin_mode_changed: false,
              places_real_order: false,
              routes_to_live: false,
            },
            order_builder_dry_run: { mode: 'dry_run' },
            hedge_plan: { required: false },
          },
        }),
      });
    });
    await page.route('**/api/v2/a-plus/inventory**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'control_center_a_plus_inventory_v1',
          source: '/api/v2/a-plus/inventory',
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            evaluated_candidates: 42,
            a_plus_candidates: 0,
            live_ready_rows: 0,
            counts_as_final_a_plus: false,
          },
        }),
      });
    });
    const adminOverviewCalls: string[] = [];
    await page.route('**/api/v2/admin/overview**', async (route) => {
      adminOverviewCalls.push(route.request().url());
      await route.abort();
    });

    await page.goto('/live-canary');

    await expect(page).toHaveURL(/\/live-canary$/);
    await expect(page.getByTestId('access-denied')).toHaveCount(0);
    await expect(page.getByTestId('page-live-canary')).toBeVisible();
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText('/api/v2/live-canary/status');
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText('/api/v2/a-plus/inventory');
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText(/Dry run/i);
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText(/Operator approval required/i);
    await expect(page.getByTestId('cockpit-live-canary-runtime-truth')).toContainText(/NO_ORDER_TEST_LEVERAGE_MARGIN_MUTATION/i);
    expect(adminOverviewCalls).toEqual([]);
  });
});
