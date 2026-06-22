import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';

async function mockDerivativesRuntime(page: Page): Promise<void> {
  const symbols = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'PEPEUSDT'];
  await page.route('**/operator_runtime/v2_derivatives/latest/derivatives_payload.json*', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        generated_utc: '2026-06-14T20:45:00Z',
        modules: {
          funding: {
            rows: symbols.map((symbol, index) => ({
              symbol,
              funding_rate: index % 2 === 0 ? 0.0001 : -0.00008,
              next_funding_time: Date.now() + 3_600_000,
              mark_price: symbol === 'PEPEUSDT' ? 0.000012 : 100000 - index * 10000,
            })),
          },
          open_interest: {
            rows: symbols.map((symbol, index) => ({
              symbol,
              open_interest: 1000 + index * 100,
            })),
          },
          long_short: {
            rows: symbols.map((symbol, index) => ({
              symbol,
              long_short_ratio: 1.2 + index * 0.1,
            })),
          },
          liquidations: {
            rows: symbols.map((symbol, index) => ({
              symbol,
              levels_count: 2 + index,
              long_level: symbol === 'PEPEUSDT' ? 0.00001 : 90000 - index * 1000,
              short_level: symbol === 'PEPEUSDT' ? 0.000014 : 110000 + index * 1000,
              long_distance_pct: 1.1 + index,
              short_distance_pct: 2.2 + index,
            })),
          },
        },
      }),
    });
  });
}

interface MatrixFixtureRow {
  symbol: string;
  timeframe: string;
  action: string;
  side: string;
  confidence: number;
  live_gate: string;
  paper_fill_gate_status: string;
  price_target_after_cost: number;
  expected_move_bps: number;
}

async function mockSignalsMatrix(page: Page, rows: MatrixFixtureRow[]): Promise<void> {
  const envelopeForPath = (pathWithQuery: string) => {
    const url = new URL(pathWithQuery, 'http://test.local');
    const requestedSymbols = (url.searchParams.get('symbols') ?? '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    const requestedTimeframes = (url.searchParams.get('timeframes') ?? '')
      .split(',')
      .map((value) => value.trim())
      .filter(Boolean);
    const filtered = rows.filter((row) => (
      (!requestedSymbols.length || requestedSymbols.includes(row.symbol))
      && (!requestedTimeframes.length || requestedTimeframes.includes(row.timeframe))
    ));

    return {
      endpoint: `${url.pathname}${url.search}`,
      source: '/api/v2/signals/matrix',
      source_type: 'websocket',
      mode: 'read_only',
      timestamp: '2026-06-15T14:43:36Z',
      received_at: '2026-06-15T14:43:38Z',
      lag_ms: 0,
      stale: false,
      missing_fields: [],
      warnings: [],
      data: {
        rows: filtered.map((row, index) => ({
          ...row,
          actionable: row.paper_fill_gate_status === 'ready',
          risk_state: row.paper_fill_gate_status === 'ready' ? 'allow' : 'blocked',
          orchestrator_state: row.paper_fill_gate_status === 'ready' ? 'routed' : 'gated',
          paper_fill_status: row.paper_fill_gate_status,
          data_coverage_percent: 96,
          market_state_integrity_score: 98,
          generated_at: '2026-06-15T14:43:36Z',
          age_seconds: 12 + index,
          signal_id: `sig-${row.symbol}-${row.timeframe}`,
          prediction_id: `pred-${row.symbol}-${row.timeframe}`,
          price_target: row.price_target_after_cost,
        })),
        count: filtered.length,
        symbols: [...new Set(rows.map((row) => row.symbol))],
        symbol_count: new Set(rows.map((row) => row.symbol)).size,
        timeframes: [...new Set(rows.map((row) => row.timeframe))],
        missing: [],
      },
    };
  };

  await (page as unknown as {
    routeWebSocket: Page['routeWebSocket'];
  }).routeWebSocket('**/api/v2/ws/resource?path=%2Fapi%2Fv2%2Fsignals%2Fmatrix**', async (ws) => {
    const path = new URL(ws.url()).searchParams.get('path') ?? '/api/v2/signals/matrix';
    ws.send(JSON.stringify(envelopeForPath(path)));
  });

  await page.route('**/api/v2/signals/matrix**', async (route) => {
    const url = new URL(route.request().url());
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(envelopeForPath(`${url.pathname}${url.search}`)),
    });
  });
}

test.describe('Trader signal selector controls', () => {
  test('derivatives liquidation levels stream renders current rows', async ({ page }) => {
    await mockDerivativesRuntime(page);
    await gotoAs(page, '/derivatives', 'trader');

    await expect(page.getByTestId('page-derivatives')).toBeVisible();
    await page.getByRole('button', { name: 'Liquidations' }).click();
    await expect(page.getByText('BTC/USDT')).toBeVisible();
    await expect(page.getByText('Long Level')).toBeVisible();
    await expect(page.getByText('Short Level')).toBeVisible();
  });

  test('shared signal matrix supports symbol and timeframe controls', async ({ page }) => {
    await mockSignalsMatrix(page, [
      { symbol: 'BTCUSDT', timeframe: '5m', action: 'long', side: 'long', confidence: 0.72, live_gate: 'blocked_human_only', paper_fill_gate_status: 'ready', price_target_after_cost: 69000, expected_move_bps: 18.25 },
      { symbol: 'ETHUSDT', timeframe: '5m', action: 'short', side: 'short', confidence: 0.61, live_gate: 'blocked_human_only', paper_fill_gate_status: 'gated', price_target_after_cost: 1800, expected_move_bps: -14.5 },
      { symbol: 'SOLUSDT', timeframe: '15m', action: 'hold', side: 'hold', confidence: 0.52, live_gate: 'blocked_human_only', paper_fill_gate_status: 'gated', price_target_after_cost: 160, expected_move_bps: 1.5 },
    ]);

    await gotoAs(page, '/signals', 'trader');

    await expect(page.getByTestId('page-signals')).toBeVisible();
    const table = page.locator('table').filter({ hasText: 'Direction' }).first();
    await expect(table).toBeVisible();
    await expect(table.getByRole('cell', { name: 'BTCUSDT' })).toBeVisible();
    await expect(table.getByRole('cell', { name: 'ETHUSDT' })).toBeVisible();

    await page.getByRole('button', { name: /^BTC$/ }).first().click();
    await expect(table.getByRole('cell', { name: 'BTCUSDT' })).toHaveCount(0);
    await expect(table.getByRole('cell', { name: 'ETHUSDT' })).toBeVisible();

    await page.getByRole('button', { name: /^15m$/ }).first().click();
    await expect(table.getByRole('cell', { name: 'SOLUSDT' })).toHaveCount(0);
    await expect(table.getByRole('cell', { name: 'ETHUSDT' })).toBeVisible();
  });

  test('shared signal matrix hydrates routed rows from the matrix contract', async ({ page }) => {
    await mockSignalsMatrix(page, [
      { symbol: 'BTCUSDT', timeframe: '5m', action: 'long', side: 'long', confidence: 0.72, live_gate: 'blocked_human_only', paper_fill_gate_status: 'ready', price_target_after_cost: 69000, expected_move_bps: 18.25 },
      { symbol: 'ETHUSDT', timeframe: '5m', action: 'short', side: 'short', confidence: 0.61, live_gate: 'blocked_human_only', paper_fill_gate_status: 'gated', price_target_after_cost: 1800, expected_move_bps: -14.5 },
    ]);

    await gotoAs(page, '/signals', 'trader');

    await expect(page.getByTestId('page-signals')).toBeVisible();
    const table = page.locator('table').filter({ hasText: 'Direction' }).first();
    await expect(table.getByText('▲ LONG')).toBeVisible();
    await expect(table.getByText('▼ SHORT')).toBeVisible();
    await expect(table.getByText('EXECUTION READY', { exact: true })).toBeVisible();
    await expect(table.getByText('GATED', { exact: true })).toBeVisible();
    await expect(table.getByText('$69,000.00')).toBeVisible();
  });

  test('signal routing filters hide gated rows when viewing execution-ready signals', async ({ page }) => {
    await mockSignalsMatrix(page, [
      { symbol: 'BTCUSDT', timeframe: '5m', action: 'long', side: 'long', confidence: 0.72, live_gate: 'blocked_human_only', paper_fill_gate_status: 'ready', price_target_after_cost: 69000, expected_move_bps: 18.25 },
      { symbol: 'XRPUSDT', timeframe: '5m', action: 'short', side: 'short', confidence: 0.65, live_gate: 'blocked_human_only', paper_fill_gate_status: 'blocked', price_target_after_cost: 2, expected_move_bps: -9.5 },
    ]);

    await gotoAs(page, '/signals', 'trader');

    const table = page.locator('table').filter({ hasText: 'Direction' }).first();
    await expect(table.getByRole('cell', { name: 'BTCUSDT' })).toBeVisible();
    await expect(table.getByRole('cell', { name: 'XRPUSDT' })).toBeVisible();
    await page.getByRole('button', { name: 'Ready' }).click();
    await expect(table.getByRole('cell', { name: 'BTCUSDT' })).toBeVisible();
    await expect(table.getByRole('cell', { name: 'XRPUSDT' })).toHaveCount(0);
  });

  test('derivatives liquidation and long-short tabs render streamed rows', async ({ page }) => {
    await mockDerivativesRuntime(page);
    await gotoAs(page, '/derivatives', 'trader');

    await page.getByRole('button', { name: 'Liquidations' }).click();
    await expect(page.getByText('Long Distance')).toBeVisible();
    await expect(page.getByText('BTC/USDT')).toBeVisible();

    await page.getByRole('button', { name: 'Long / Short' }).click();
    await expect(page.getByText('L/S Ratio')).toBeVisible();
    await expect(page.getByText(/Long-heavy|Balanced/i).first()).toBeVisible();
  });
});
