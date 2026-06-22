import { expect, test } from '@playwright/test';
import { gotoAs } from './_shared';

test.describe('Trader signal selector controls', () => {
  test('derivatives liquidation levels support pinned majors and all overview symbols', async ({ page }) => {
    const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'AVAXUSDT', 'DOGEUSDT', 'ADAUSDT', 'PEPEUSDT', 'LINKUSDT'];
    await page.route('**/api/v2/market/overview*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          endpoint: '/api/v2/market/overview',
          source: 'Market overview test source',
          source_type: 'api',
          mode: 'paper',
          received_at: '2026-06-14T20:45:00Z',
          stale: false,
          missing_fields: [],
          warnings: [],
          data: { symbols, count: symbols.length, timeframes: ['1m', '5m'] },
        }),
      });
    });
    await page.route('**/api/v2/market/*', async (route) => {
      const url = new URL(route.request().url());
      const endpoint = url.pathname;
      if (endpoint.endsWith('/overview')) {
        await route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({
            endpoint: '/api/v2/market/overview',
            source: 'Market overview test source',
            source_type: 'api',
            mode: 'paper',
            received_at: '2026-06-14T20:45:00Z',
            stale: false,
            missing_fields: [],
            warnings: [],
            data: { symbols, count: symbols.length, timeframes: ['1m', '5m'] },
          }),
        });
        return;
      }
      const symbol = url.pathname.split('/')[4] ?? 'BTCUSDT';
      const isDerivatives = endpoint.endsWith('/derivatives');
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          endpoint,
          source: 'Derivatives test source',
          source_type: 'api',
          mode: 'paper',
          received_at: '2026-06-14T20:45:00Z',
          stale: false,
          symbol,
          missing_fields: isDerivatives ? [] : ['data'],
          warnings: [],
          data: isDerivatives
            ? {
              funding_rate: 0.0001,
              open_interest: 1000000,
              liquidations_1h: 12000,
              liquidations_24h: 98000,
              long_short_ratio: 1.2,
              basis: 0.0004,
              liquidation_stream_status: { stream_active: true },
              liquidation_levels: {
                long_liquidation_price: 90000,
                short_liquidation_price: 110000,
              },
            }
            : {
              symbol,
              last_price: 100000,
              change_24h: 0.02,
              funding_rate: 0.0001,
              open_interest: 1000000,
            },
        }),
      });
    });

    await gotoAs(page, '/derivatives', 'trader');

    const selector = page.getByLabel('Select derivative symbol');
    await expect(page.getByRole('button', { name: /^BTC$/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^ETH$/ })).toBeVisible();
    await expect(page.getByRole('button', { name: /^SOL$/ })).toBeVisible();
    await expect(selector).toContainText('PEPE');

    await selector.selectOption('PEPEUSDT');
    await expect(page.getByText(/PEPEUSDT Liquidation Levels/i)).toBeVisible();
    await expect(page.getByText(/All coins selectable/i)).toBeVisible();
    await expect(page.getByText(/Long liquidation price/i)).toBeVisible();
  });

  test('shared prediction matrix supports symbol and timeframe toggles', async ({ page }) => {
    const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'AVAXUSDT', 'DOGEUSDT', 'ADAUSDT'];
    const timeframes = ['1m', '5m', '15m'];
    await page.route('**/operator_runtime/v2_signals/latest/signals_payload.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_at: '2026-06-14T20:45:00Z',
          safety: { live_gate: 'blocked_human_only', live_symbols: [], execution_live_symbols: [] },
          summary: {
            symbols_count: symbols.length,
            timeframes_count: timeframes.length,
            prediction_rows_count: symbols.length * timeframes.length,
            present_prediction_count: symbols.length * timeframes.length,
            missing_prediction_count: 0,
            active_signal_count: 0,
            live_gate: 'blocked_human_only',
          },
          prediction_contract: {
            status: 'PRESENT_CURRENT',
            timeframes_covered: timeframes,
            symbols_covered: symbols,
            prediction_rows: symbols.flatMap((symbol) => timeframes.map((timeframe) => ({
              symbol,
              timeframe,
              status: 'PRESENT_CURRENT',
              selected_action: symbol === 'BTCUSDT' ? 'BUY' : symbol === 'ETHUSDT' ? 'SELL' : 'HOLD',
              confidence_calibrated: 0.52,
              expected_move_after_cost_bps: symbol === 'BTCUSDT' ? 12 : -8,
              price_target: 100,
              freshness_seconds: 12,
            }))),
          },
          price_target_generation: { status: 'PRICE_TARGET_READY', validation_status: 'CURRENT', invalid_or_missing_count: 0 },
          signal_publisher: { status: 'CURRENT', signal_count: 0, published_signals: [] },
          signal_lineage: { lineage_rows: [] },
        }),
      });
    });
    await page.route('**/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ live_gate: 'blocked_human_only', live_symbols: [], execution_live_symbols: [] }),
      });
    });
    await page.route('**/operator_runtime/v2_prediction_signal_explanations/latest/prediction_signal_explanations.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'test',
          generated_est: '2026-06-14 20:45:00 EST',
          generated_utc: '2026-06-15T00:45:00Z',
          source: 'test fixture',
          explanation_count: 0,
          unique_symbols: 0,
          unique_timeframes: [],
          summary: {
            prediction_rows: symbols.length * timeframes.length,
            explanation_rows: 0,
            explanation_count: 0,
            unique_symbols: 0,
            unique_timeframes: [],
            paper_accepted_count: 0,
            paper_blocked_count: 0,
            prediction_paper_fill_allowed_count: 0,
            prediction_routes_to_orchestrator_count: 0,
            live_gate: 'blocked_human_only',
          },
          plain_english_overview: ['Small selector-control fixture for symbol and timeframe toggles.'],
          explanations: [],
          issues_and_next_fixes: [],
        }),
      });
    });

    await gotoAs(page, '/signals', 'trader');

    const panel = page.locator('#realtime-tf-matrix-signals, #realtime-tf-matrix-signals-admin').first();
    await expect(panel).toBeVisible();
    await expect(panel.getByText('5m is the default focus window')).toBeVisible();

    const matrixSymbols = panel.locator('.realtime-tf-symbol');
    await expect(matrixSymbols.filter({ hasText: /^BTC$/ })).toBeVisible();
    await expect(matrixSymbols.filter({ hasText: /^ETH$/ })).toBeVisible();
    await expect(matrixSymbols.filter({ hasText: /^SOL$/ })).toBeVisible();

    await panel.getByRole('button', { name: /BTC/ }).first().click();
    await expect(matrixSymbols.filter({ hasText: /^BTC$/ })).toHaveCount(0);

    await panel.locator('.symbol-picker .symbol-chip').filter({ hasText: /^BTC$/ }).first().click();
    await expect(matrixSymbols.filter({ hasText: /^BTC$/ })).toBeVisible();

    const header = panel.locator('.realtime-tf-matrix__row--head');
    const headerCells = header.locator('span');
    await expect(headerCells.filter({ hasText: /^5m$/ })).toBeVisible();
    await panel.locator('.tf-picker__btn').filter({ hasText: /^15m$/ }).click();
    await expect(headerCells.filter({ hasText: /^15m$/ })).toBeVisible();

    await panel.locator('.tf-picker__btn').filter({ hasText: /^5m$/ }).click();
    await expect(headerCells.filter({ hasText: /^5m$/ })).toHaveCount(0);
    await expect(headerCells.filter({ hasText: /^15m$/ })).toBeVisible();

    await panel.getByRole('button', { name: 'Core timeframe focus' }).click();
    await expect(headerCells.filter({ hasText: /^5m$/ })).toBeVisible();
    await expect(headerCells.filter({ hasText: /^15m$/ })).toHaveCount(0);
  });

  test('shared prediction matrix hydrates missing cells from signal contracts', async ({ page }) => {
    await page.route('**/operator_runtime/v2_signals/latest/signals_payload.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_at: '2026-06-14T20:45:00Z',
          safety: { live_gate: 'blocked_human_only', live_symbols: [], execution_live_symbols: [] },
          summary: {
            symbols_count: 0,
            timeframes_count: 0,
            prediction_rows_count: 0,
            present_prediction_count: 0,
            missing_prediction_count: 0,
            active_signal_count: 0,
            live_gate: 'blocked_human_only',
          },
          prediction_contract: {
            status: 'MISSING_STATIC_SOURCE',
            timeframes_covered: [],
            symbols_covered: [],
            prediction_rows: [],
          },
          signal_publisher: { status: 'MISSING_STATIC_SOURCE', signal_count: 0, published_signals: [] },
          signal_lineage: { lineage_rows: [] },
        }),
      });
    });
    await page.route('**/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ live_gate: 'blocked_human_only', live_symbols: [], execution_live_symbols: [] }),
      });
    });
    await page.route('**/operator_runtime/v2_prediction_signal_explanations/latest/prediction_signal_explanations.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'test',
          generated_utc: '2026-06-15T00:45:00Z',
          explanation_count: 0,
          unique_symbols: 0,
          unique_timeframes: [],
          summary: { prediction_rows: 0, explanation_rows: 0, explanation_count: 0, unique_symbols: 0, unique_timeframes: [] },
          explanations: [],
          issues_and_next_fixes: [],
        }),
      });
    });
    await page.route('**/api/v2/signals?*', async (route) => {
      const url = new URL(route.request().url());
      const symbol = url.searchParams.get('symbol') ?? 'BTCUSDT';
      const endpoint = `${url.pathname}${url.search}`;
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          endpoint,
          source: `Redis paper signal publisher v2:signals:paper:${symbol}:5m`,
          source_type: 'repository',
          mode: 'paper',
          timestamp: '2026-06-15T14:43:36Z',
          received_at: '2026-06-15T14:43:38Z',
          lag_ms: 2000,
          stale: false,
          missing_fields: [],
          warnings: ['V2 Redis paper signal loaded before marking active signal unavailable'],
          data: {
            active_signal: {
              symbol,
              timeframe: '5m',
              selected_action: symbol === 'ETHUSDT' ? 'short' : 'long',
              confidence: 0.61,
              confidence_calibrated: 0.61,
              expected_move_after_cost_bps: symbol === 'ETHUSDT' ? -14.5 : 18.25,
              price_target_after_cost: symbol === 'ETHUSDT' ? 1800 : 69000,
              last_price: symbol === 'ETHUSDT' ? 1812 : 67500,
              blocked_reason: '',
              risk_result: 'Paper risk gate passed',
              paper_state: 'Paper preview only',
              orchestrator_state: 'Routing preview only',
            },
            account_specific: false,
            public_paper_signal: true,
          },
        }),
      });
    });

    await gotoAs(page, '/signals', 'trader');

    const panel = page.locator('#realtime-tf-matrix-signals, #realtime-tf-matrix-signals-admin').first();
    await expect(panel).toBeVisible();
    await expect(panel.locator('.realtime-tf-cell').first()).toContainText(/Buy \/ Long|Sell \/ Short/);
    await expect(panel.locator('.realtime-tf-cell__empty')).toHaveCount(0);
    await expect(page.locator('#realtime-active-signals-signals')).toContainText(/active signal rows/i);
  });

  test('trader signal panel withholds account-specific rows for other trader scopes', async ({ page }) => {
    await page.route('**/operator_runtime/v2_signals/latest/signals_payload.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_at: '2026-06-14T20:45:00Z',
          generated_est: '2026-06-14 20:45:00 EST',
          safety: { live_gate: 'blocked_human_only', live_symbols: [], execution_live_symbols: [] },
          summary: {
            symbols_count: 2,
            timeframes_count: 1,
            prediction_rows_count: 2,
            present_prediction_count: 2,
            missing_prediction_count: 0,
            active_signal_count: 2,
            live_gate: 'blocked_human_only',
          },
          prediction_contract: {
            status: 'PRESENT_CURRENT',
            timeframes_covered: ['5m'],
            symbols_covered: ['BTCUSDT', 'XRPUSDT'],
            prediction_rows: [],
          },
          price_target_generation: { status: 'PRICE_TARGET_READY', validation_status: 'CURRENT', invalid_or_missing_count: 0 },
          signal_publisher: {
            status: 'CURRENT',
            signal_count: 2,
            published_signals: [
              {
                symbol: 'BTCUSDT',
                timeframe: '5m',
                action: 'BUY',
                confidence: 0.72,
                price_target: 101000,
                last_price: 100000,
                trader_id: 'trader-wajidali1984',
                paper_account_id: 'paper-wajidali1984',
                account_specific: true,
                risk_status_label: 'Risk passed',
                orchestrator_status_label: 'Routing passed',
                paper_status_label: 'Paper preview only',
                generated_est: '2026-06-14 20:45:00 EST',
              },
              {
                symbol: 'XRPUSDT',
                timeframe: '5m',
                action: 'SELL',
                confidence: 0.65,
                price_target: 2,
                last_price: 2.2,
                trader_id: 'trader-other',
                paper_account_id: 'paper-other',
                account_specific: true,
                risk_status_label: 'Risk passed',
                orchestrator_status_label: 'Routing passed',
                paper_status_label: 'Paper preview only',
                generated_est: '2026-06-14 20:45:00 EST',
              },
            ],
          },
          signal_lineage: { lineage_rows: [] },
        }),
      });
    });
    await page.route('**/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ live_gate: 'blocked_human_only', live_symbols: [], execution_live_symbols: [] }),
      });
    });
    await page.route('**/operator_runtime/v2_prediction_signal_explanations/latest/prediction_signal_explanations.json*', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'test',
          generated_est: '2026-06-14 20:45:00 EST',
          generated_utc: '2026-06-15T00:45:00Z',
          source: 'test fixture',
          explanation_count: 0,
          unique_symbols: 0,
          unique_timeframes: [],
          summary: {
            prediction_rows: 0,
            explanation_rows: 0,
            explanation_count: 0,
            unique_symbols: 0,
            unique_timeframes: [],
            paper_accepted_count: 0,
            paper_blocked_count: 0,
            prediction_paper_fill_allowed_count: 0,
            prediction_routes_to_orchestrator_count: 0,
            live_gate: 'blocked_human_only',
          },
          plain_english_overview: [],
          explanations: [],
          issues_and_next_fixes: [],
        }),
      });
    });

    await gotoAs(page, '/signals', 'trader');

    const activePanel = page.locator('#realtime-active-signals-signals');
    await expect(activePanel).toBeVisible();
    await expect(activePanel).toContainText('Showing 1 of 2 active signal rows');
    await expect(activePanel).toContainText('1 account-specific signal row withheld for this trader scope');
    await expect(activePanel).toContainText('BTC');
    await expect(activePanel).not.toContainText('XRP');
  });

  test('derivatives liquidation selector updates selected coin cards', async ({ page }) => {
    await gotoAs(page, '/derivatives', 'trader');

    const selector = page.locator('#symbol-selector');
    const levels = page.locator('#liq-levels');
    const cards = levels.locator('.liq-card__symbol');

    await expect(selector).toBeVisible();
    await expect(levels).toBeVisible();
    await expect(cards.filter({ hasText: /^BTC/ })).toBeVisible();
    await expect(cards.filter({ hasText: /^ETH/ })).toBeVisible();
    await expect(cards.filter({ hasText: /^SOL/ })).toBeVisible();

    await selector.locator('.symbol-chip--active').filter({ hasText: /^SOL/ }).first().click();
    await expect(cards.filter({ hasText: /^SOL/ })).toHaveCount(0);

    await selector.locator('.symbol-chip').filter({ hasText: /^SOL$/ }).first().click();
    await expect(cards.filter({ hasText: /^SOL/ })).toBeVisible();
  });
});
