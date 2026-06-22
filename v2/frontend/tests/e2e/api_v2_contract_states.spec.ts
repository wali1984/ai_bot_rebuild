import { expect, test, type Page, type Route } from '@playwright/test';
import { createV2Alert, safeAlertMutationSymbol } from '../../src/api/v2Alerts';
import { fetchV2Contract } from '../../src/api/v2Shared';
import { getV2MarketIndicators, safeV2MarketSymbol, safeV2MarketTimeframe } from '../../src/api/v2Market';
import { getV2Signals } from '../../src/api/v2Signals';
import { marketDetailTestHooks } from '../../src/hooks/useMarketDetail';
import type { ApiV2Envelope, SignalData } from '../../src/types/apiV2';

function contract(endpoint: string, options: {
  data?: unknown;
  sourceType?: 'api' | 'repository' | 'redis_live' | 'static_payload' | 'unavailable';
  missingFields?: string[];
  warnings?: string[];
  symbol?: string | null;
  mode?: 'paper' | 'read_only' | 'live_blocked' | 'paper_preview_unverified';
} = {}) {
  const sourceType = options.sourceType ?? 'unavailable';
  return {
    data: options.data ?? null,
    source: sourceType === 'unavailable' ? 'unavailable' : 'test fallback source',
    source_type: sourceType,
    endpoint,
    timestamp: sourceType === 'unavailable' ? null : '2026-06-13T03:00:00Z',
    received_at: '2026-06-13T03:00:01Z',
    lag_ms: sourceType === 'unavailable' ? null : 1000,
    stale: sourceType === 'unavailable',
    missing_fields: options.missingFields ?? [],
    warnings: options.warnings ?? (sourceType === 'static_payload' ? ['Static fallback data; not live.'] : []),
    symbol: options.symbol ?? null,
    exchange: options.symbol ? 'Binance USD-M' : null,
    mode: options.mode ?? 'read_only',
  };
}

async function installApiContractRoutes(page: Page): Promise<void> {
  await page.route('**/api/v2/**', async (route: Route) => {
    const request = route.request();
    const url = new URL(request.url());
    const endpoint = url.pathname;
    let payload: ReturnType<typeof contract>;

    if (endpoint === '/api/v2/orders/preview') {
      const body = request.postDataJSON() as { mode?: string; quantity?: number; symbol?: string } | null;
      payload = contract(endpoint, {
        data: {
          allowed: false,
          mode: body?.mode === 'live' ? 'live_blocked' : 'paper_preview_unverified',
          reason: body?.mode === 'live' ? 'live_mode_rejected' : 'trader_session_required',
          friendly_reason: body?.mode === 'live' ? 'Live order preview is blocked' : 'Sign in for trader-specific paper preview',
          estimated_notional: null,
          estimated_fee: null,
          estimated_margin: null,
          available_paper_balance: null,
          paper_execution_policy: {
            submit_policy: 'authenticated_trader_local_paper_staging',
            fill_policy: 'no_automatic_fill',
            execution_policy: 'executions_require_separate_verified_paper_fill_service',
            cancel_policy: 'local_repository_cancel_only',
            live_transport_enabled: false,
            exchange_mutation_enabled: false,
          },
          risk_checks: [
            { name: 'mode', passed: body?.mode !== 'live' },
            { name: 'quantity', passed: Boolean(body?.quantity && body.quantity > 0) },
            { name: 'submit_endpoint', passed: false },
          ],
        },
        missingFields: ['available_paper_balance'],
        warnings: ['Preview only; no order state is changed.'],
        symbol: body?.symbol ?? 'BTCUSDT',
        mode: body?.mode === 'live' ? 'live_blocked' : 'paper_preview_unverified',
      });
    } else if (endpoint === '/api/v2/market/overview') {
      payload = contract(endpoint, {
        data: {
          symbols: ['BTCUSDT'],
          count: 1,
          timeframes: ['1m'],
          tickers: [
            {
              symbol: 'BTCUSDT',
              last_price: 100000,
              change_24h: 0.01,
              high_24h: 101000,
              low_24h: 99000,
              volume_24h: 1000,
              turnover_24h: 100000000,
              trade_count_24h: 100,
              weighted_avg_price: 100100,
            },
          ],
        },
        sourceType: 'api',
        mode: 'read_only',
      });
    } else if (endpoint === '/api/v2/market/BTCUSDT') {
      payload = contract(endpoint, {
        data: {
          symbol: 'BTCUSDT',
          last_price: 100000,
          mark_price: 100002,
          index_price: 99990,
          change_24h: 0.01,
          high_24h: 101000,
          low_24h: 99000,
          volume_24h: 1000,
          turnover_24h: 100000000,
          funding_rate: 0.0001,
          next_funding: '2026-06-13T08:00:00Z',
          open_interest: 12345,
          spread_bps: 0.4,
        },
        sourceType: 'api',
        missingFields: ['change_1h', 'change_4h', 'open_interest_change'],
        symbol: 'BTCUSDT',
      });
    } else if (endpoint === '/api/v2/market/BTCUSDT/depth') {
      payload = contract(endpoint, {
        data: { symbol: 'BTCUSDT', bids: [[99999, 1]], asks: [[100001, 1]], spread_bps: 0.2, depth_type: 'binance_public_ladder' },
        sourceType: 'api',
        symbol: 'BTCUSDT',
      });
    } else if (endpoint === '/api/v2/market/BTCUSDT/trades') {
      payload = contract(endpoint, {
        data: { symbol: 'BTCUSDT', trades: [{ time: '2026-06-13T03:00:00Z', price: 100000, size: 0.1, side: 'buy' }] },
        sourceType: 'api',
        missingFields: ['trade_stream'],
        symbol: 'BTCUSDT',
      });
    } else if (endpoint === '/api/v2/market/BTCUSDT/derivatives') {
      payload = contract(endpoint, {
        data: {
          symbol: 'BTCUSDT',
          funding_rate: 0.0001,
          next_funding: '2026-06-13T08:00:00Z',
          open_interest: 12345,
          open_interest_change: null,
          funding_history: [],
          open_interest_history: [],
          liquidations_1h: null,
          liquidations_24h: null,
          long_short_ratio: null,
          basis: null,
          exchange_comparison: [],
          production_source_validation: {
            configured: false,
            valid: false,
            status: 'pending',
            live_trading_enabled: false,
            exchange_mutation_enabled: false,
            missing_fields: ['derivatives_realtime_source_artifact'],
            warnings: ['Production derivatives realtime/source validation artifact is not configured'],
          },
        },
        sourceType: 'api',
        missingFields: ['production_derivatives_realtime_source_validation'],
        symbol: 'BTCUSDT',
      });
    } else if (endpoint === '/api/v2/account/positions') {
      payload = contract(endpoint, {
        data: {
          positions: [{ symbol: 'BTCUSDT', side: 'short', quantity: 1 }],
          trader_id: null,
          paper_account_id: null,
          account_scope: 'public_read_only',
          account_specific: false,
        },
        sourceType: 'redis_live',
        warnings: ['Public paper activity position fallback; not a live account API'],
        mode: 'paper',
      });
    } else if (endpoint === '/api/v2/account/readiness') {
      payload = contract(endpoint, {
        data: {
          trader_id: null,
          paper_account_id: null,
          account_scope: 'public_read_only',
          account_specific: false,
          account_present: false,
          repository_status: 'unavailable',
          repository_kind: 'unavailable',
          tenant_isolation_status: 'unavailable',
          unique_paper_account_scope: false,
          paper_account_uniqueness_enforced: false,
          trader_scope_required: false,
          production_repository: false,
          durable_database_repository: false,
          production_writer_validation: 'pending',
          migration_status: 'pending',
          backup_restore_status: 'missing',
          retention_policy_status: 'missing',
          trader_account_scope_smoke_status: 'missing',
          trader_account_scope_smoke_artifact_valid: false,
          production_trader_repository_smoke_status: 'missing',
          production_trader_repository_smoke_artifact_valid: false,
          supported_local_domains: [],
          contains_credentials: false,
          live_trading_enabled: false,
          exchange_mutation_enabled: false,
        },
        missingFields: ['trader_session', 'trader_account_repository'],
        warnings: ['Sign in to view trader-specific account readiness'],
        mode: 'paper',
      });
    } else if (endpoint === '/api/v2/execution/audit-events') {
      payload = contract(endpoint, {
        data: {
          audit_events: [{ event_type: 'PAPER_FILL_ACCEPTED' }],
          audit_policy: {
            tamper_evident: true,
            production_durable_store: false,
            live_mutation_prohibited: true,
          },
          audit_ledger: {
            append_only_local_file: true,
            production_durable_store: false,
            live_mutation_prohibited: true,
          },
          audit_ledger_events: [{ event_type: 'PAPER_FILL_ACCEPTED' }],
        },
        sourceType: 'redis_live',
        warnings: ['Public paper activity audit fallback; local paper evidence only'],
        mode: 'paper',
      });
    } else if (endpoint === '/api/v2/alerts') {
      payload = contract(endpoint, {
        data: {
          alerts: [],
          supported_alert_types: ['Price movement', 'Funding rate', 'Signal change'],
          preferences: null,
          delivery_channels: [],
          create_enabled: false,
          edit_enabled: false,
          mute_enabled: false,
          delivery_enabled: false,
          audit_logging_enabled: false,
          account_scope: 'public_read_only',
          account_specific: false,
        },
        missingFields: ['alert_repository', 'notification_delivery'],
        warnings: ['Alert actions are unavailable.'],
        mode: 'read_only',
      });
    } else if (endpoint === '/api/v2/market/BTCUSDT/candles') {
      payload = contract(endpoint, { missingFields: ['candles'], symbol: 'BTCUSDT' });
    } else if (endpoint === '/api/v2/market/BTCUSDT/indicators') {
      payload = contract(endpoint, {
        data: {
          symbol: 'BTCUSDT',
          timeframe: '1m',
          ema20: [],
          ema50: [],
          bb_upper: [],
          bb_lower: [],
          bb_middle: [],
          ai_target: [],
          indicator_count: 0,
          controls_enabled: false,
        },
        missingFields: ['typed_indicator_repository'],
        warnings: ['Indicator source unavailable.'],
        symbol: 'BTCUSDT',
      });
    } else {
      payload = contract(endpoint, { missingFields: ['data'] });
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(payload),
    });
  });
}

async function fetchContract(page: Page, endpoint: string, init?: RequestInit): Promise<Record<string, unknown>> {
  return page.evaluate(
    async ({ endpoint: target, init: requestInit }) => {
      const response = await fetch(target, requestInit);
      return response.json();
    },
    { endpoint, init },
  );
}

function expectContract(payload: Record<string, unknown>, endpoint: string): void {
  expect(payload.endpoint).toBe(endpoint);
  expect(payload).toHaveProperty('source');
  expect(['api', 'repository', 'redis_live', 'static_payload', 'unavailable']).toContain(payload.source_type);
  expect(payload).toHaveProperty('received_at');
  expect(payload).toHaveProperty('stale');
  expect(Array.isArray(payload.missing_fields)).toBe(true);
  expect(Array.isArray(payload.warnings)).toBe(true);
  expect(['paper', 'read_only', 'live_blocked', 'paper_preview_unverified']).toContain(payload.mode);
}

test('api v2 helper includes backend session credentials by default', async () => {
  const originalFetch = globalThis.fetch;
  let observedInit: RequestInit | undefined;
  globalThis.fetch = (async (_input: RequestInfo | URL, init?: RequestInit) => {
    observedInit = init;
    return new Response(
      JSON.stringify(contract('/api/v2/portfolio', { mode: 'paper', missingFields: ['positions'] })),
      { status: 200, headers: { 'content-type': 'application/json' } },
    );
  }) as typeof fetch;

  try {
    const response = await fetchV2Contract('/api/v2/portfolio', ['positions'], 'Portfolio endpoint unavailable.', { mode: 'paper' });
    expectContract(response as unknown as Record<string, unknown>, '/api/v2/portfolio');
    expect(observedInit?.credentials).toBe('include');
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test.describe('api v2 API states', () => {
  test.beforeEach(async ({ page }) => {
    await installApiContractRoutes(page);
    await page.goto('/');
  });

  test('market endpoints return source and freshness API states', async ({ page }) => {
    for (const endpoint of [
      '/api/v2/market/overview',
      '/api/v2/market/BTCUSDT',
      '/api/v2/market/BTCUSDT/candles',
      '/api/v2/market/BTCUSDT/indicators',
      '/api/v2/market/BTCUSDT/depth',
      '/api/v2/market/BTCUSDT/trades',
      '/api/v2/market/BTCUSDT/derivatives',
    ]) {
      const payload = await fetchContract(page, endpoint);
      expectContract(payload, endpoint);
    }
  });

  test('frontend market and signal API helpers reject malformed symbols and unsupported timeframes', async () => {
    expect(safeV2MarketSymbol(' btcusdt ')).toBe('BTCUSDT');
    expect(safeV2MarketSymbol('btcusdt../')).toBeUndefined();
    expect(safeV2MarketSymbol('ETH-USDT')).toBeUndefined();
    expect(safeV2MarketTimeframe('5m')).toBe('5m');
    expect(safeV2MarketTimeframe('2m')).toBeUndefined();
    expect(safeV2MarketTimeframe('1m@trade')).toBeUndefined();

    const invalidSignal = await getV2Signals('btcusdt../');
    expectContract(invalidSignal as unknown as Record<string, unknown>, '/api/v2/signals?symbol={symbol}');
    expect(invalidSignal.source_type).toBe('unavailable');
    expect(invalidSignal.symbol).toBeNull();
    expect(invalidSignal.missing_fields).toContain('symbol');
    expect(invalidSignal.warnings).toContain('Enter a valid market symbol.');

    const invalidIndicators = await getV2MarketIndicators('btcusdt../', '1m');
    expectContract(invalidIndicators as unknown as Record<string, unknown>, '/api/v2/market/{symbol}/indicators');
    expect(invalidIndicators.source_type).toBe('unavailable');
    expect(invalidIndicators.symbol).toBeNull();
    expect(invalidIndicators.missing_fields).toContain('symbol');
    expect(invalidIndicators.warnings).toContain('Enter a valid market symbol.');

    const invalidIndicatorTimeframe = await getV2MarketIndicators('BTCUSDT', '2m');
    expectContract(invalidIndicatorTimeframe as unknown as Record<string, unknown>, '/api/v2/market/BTCUSDT/indicators');
    expect(invalidIndicatorTimeframe.source_type).toBe('unavailable');
    expect(invalidIndicatorTimeframe.symbol).toBe('BTCUSDT');
    expect(invalidIndicatorTimeframe.missing_fields).toContain('timeframe');
  });

  test('market detail signal guard withholds mismatched authenticated trader signal', async () => {
    const signal = contract('/api/v2/signals?symbol=BTCUSDT', {
      data: {
        active_signal: { symbol: 'BTCUSDT', selected_action: 'long', confidence: 0.7 },
        trader_id: 'trader-other',
        paper_account_id: 'paper-other',
        account_scope: 'authenticated_trader',
        account_specific: true,
      },
      sourceType: 'repository',
      symbol: 'BTCUSDT',
      mode: 'paper',
    });

    const scoped = marketDetailTestHooks.signalForTraderAndSymbol(
      signal as ApiV2Envelope<SignalData>,
      'BTCUSDT',
      'trader-wajidali1984',
      'paper-wajidali1984',
      true,
    );

    expect(scoped.data?.active_signal).toBeNull();
    expect(scoped.missing_fields).toContain('trader_signal_scope');
    expect(scoped.warnings.join(' ')).toContain('not scoped to this trader account');
  });

  test('paper and account endpoints expose paper/read-only states', async ({ page }) => {
    const positions = await fetchContract(page, '/api/v2/account/positions');
    expectContract(positions, '/api/v2/account/positions');
    expect(positions.mode).toBe('paper');
    expect(positions.source_type).toBe('redis_live');
    expect(positions.missing_fields).not.toContain('positions');
    expect((positions.data as Record<string, unknown>).account_specific).toBe(false);

    const readiness = await fetchContract(page, '/api/v2/account/readiness');
    expectContract(readiness, '/api/v2/account/readiness');
    expect(readiness.mode).toBe('paper');
    expect(readiness.missing_fields).toContain('trader_account_repository');
    expect((readiness.data as Record<string, unknown>).account_specific).toBe(false);
    expect((readiness.data as Record<string, unknown>).live_trading_enabled).toBe(false);
    expect((readiness.data as Record<string, unknown>).exchange_mutation_enabled).toBe(false);
    expect(JSON.stringify(readiness).toLowerCase()).not.toContain('api_secret');

    const auditEvents = await fetchContract(page, '/api/v2/execution/audit-events');
    expectContract(auditEvents, '/api/v2/execution/audit-events');
    expect(auditEvents.mode).toBe('paper');
    expect(auditEvents.source_type).toBe('redis_live');
    expect(auditEvents.missing_fields).not.toContain('audit_events');
    expect(((auditEvents.data as Record<string, unknown>).audit_ledger as Record<string, unknown>).append_only_local_file).toBe(true);
    expect(JSON.stringify(auditEvents).toLowerCase()).not.toContain('"mode":"live"');
  });

  test('alerts endpoint exposes structured unavailable state without enabled actions', async ({ page }) => {
    const alerts = await fetchContract(page, '/api/v2/alerts');

    expectContract(alerts, '/api/v2/alerts');
    expect(alerts.source_type).toBe('unavailable');
    expect(alerts.missing_fields).toContain('alert_repository');
    expect(alerts.missing_fields).toContain('notification_delivery');
    const data = alerts.data as Record<string, unknown>;
    expect(data.create_enabled).toBe(false);
    expect(data.delivery_enabled).toBe(false);
    expect(Array.isArray(data.supported_alert_types)).toBe(true);
  });

  test('frontend alert API helper rejects malformed mutation symbols before fetch', async () => {
    expect(safeAlertMutationSymbol(' btcusdt ')).toBe('BTCUSDT');
    expect(safeAlertMutationSymbol('btcusdt../')).toBeUndefined();
    expect(safeAlertMutationSymbol('')).toBeUndefined();

    const invalidAlert = await createV2Alert({
      alert_type: 'Price movement',
      symbol: 'btcusdt../',
      condition: 'Last price above',
      threshold: 125000,
    });
    expectContract(invalidAlert as unknown as Record<string, unknown>, '/api/v2/alerts');
    expect(invalidAlert.source_type).toBe('unavailable');
    expect(invalidAlert.missing_fields).toContain('symbol');
    expect(invalidAlert.warnings).toContain('Enter a valid market symbol.');
  });

  test('order preview rejects live mode and does not expose submit success', async ({ page }) => {
    const preview = await fetchContract(page, '/api/v2/orders/preview', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: 'BTCUSDT',
        side: 'buy',
        order_type: 'market',
        quantity: 1,
        mode: 'live',
      }),
    });

    expectContract(preview, '/api/v2/orders/preview');
    expect(preview.mode).toBe('live_blocked');
    expect((preview.data as Record<string, unknown>).allowed).toBe(false);
    expect((preview.data as Record<string, unknown>).reason).toBe('live_mode_rejected');
  });

  test('missing fields are explicit and static fallback is not presented as live', async ({ page }) => {
    const market = await fetchContract(page, '/api/v2/market/BTCUSDT');
    expectContract(market, '/api/v2/market/BTCUSDT');
    expect(market.source_type).toBe('api');
    expect(market.mode).toBe('read_only');
    expect(market.missing_fields).toContain('change_1h');
    expect(JSON.stringify(market).toLowerCase()).not.toContain('"mode":"live"');
  });
});
