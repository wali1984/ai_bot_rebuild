import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';
import { selectPrimaryExchangeAccount } from '../../src/hooks/useTraderContext';
import { tradeAccountScopeKey, tradeTerminalTestHooks } from '../../src/hooks/useTradeTerminal';
import { resolvePaperAccountTruth, resolveTypedPortfolioAccount, typedPortfolioMatchesCurrentScope } from '../../src/hooks/usePaperAccountTruth';
import { paperPreviewMatchesTraderScope } from '../../src/components/trade/PaperOrderTicket';
import { openOrdersTableTestHooks } from '../../src/components/trade/OpenOrdersTable';
import { safeOrderEnvelopeSymbol } from '../../src/api/v2Orders';
import type { ApiV2Envelope, OrderPreviewData, PortfolioData } from '../../src/types/apiV2';

const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
] as const;

const FORBIDDEN_STRINGS = [
  'AI BOT V2',
  'Control Plane',
  'Admin',
  'Operator',
  'War Room',
  'Mission Control',
  'Codex',
  'Claude',
  'Ollama',
  'payload',
  'gap matrix',
  'proof',
  'local role',
  'role override',
  'raw audit ledger',
  'migration',
  'script',
  'build validation',
  'coverage',
  'quarantine',
] as const;

test('selects the backend-confirmed scoped read-only exchange account first', () => {
  const user = {
    id: 'user-wajid',
    trader_id: 'trader-wajidali1984',
    username: 'wajidali1984',
    email: 'wajidali1984@hotmail.com',
    role: 'trader' as const,
    paper_account_id: 'paper-wajidali1984',
    watchlist: [],
    alert_preferences: {},
    is_active: true,
    created_at: '2026-06-13T00:00:00Z',
    updated_at: '2026-06-13T00:00:00Z',
    last_login: null,
    exchange_accounts: [],
  };
  const unsafeFirst = {
    id: 'binance-other',
    trader_id: 'trader-other',
    paper_account_id: 'paper-other',
    exchange: 'binance',
    label: 'Other trader Binance',
    account_type: 'usd_m_futures',
    mode: 'read_only',
    read_only: true,
    live_trading_enabled: false,
    status: 'credential_source_pending',
  };
  const scopedSecond = {
    id: 'binance-wajid',
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-wajidali1984',
    exchange: 'binance',
    label: 'Wajid Binance Futures',
    account_type: 'usd_m_futures',
    mode: 'read_only',
    read_only: true,
    live_trading_enabled: false,
    status: 'credential_source_pending',
  };

  expect(selectPrimaryExchangeAccount([unsafeFirst, scopedSecond], user)?.id).toBe('binance-wajid');
});

test('does not select mismatched exchange metadata for the active trader account', () => {
  const user = {
    id: 'user-wajid',
    trader_id: 'trader-wajidali1984',
    username: 'wajidali1984',
    email: 'wajidali1984@hotmail.com',
    role: 'trader' as const,
    paper_account_id: 'paper-wajidali1984',
    watchlist: [],
    alert_preferences: {},
    is_active: true,
    created_at: '2026-06-13T00:00:00Z',
    updated_at: '2026-06-13T00:00:00Z',
    last_login: null,
    exchange_accounts: [],
  };
  const otherTraderAccount = {
    id: 'binance-other',
    trader_id: 'trader-other',
    paper_account_id: 'paper-other',
    exchange: 'binance',
    label: 'Other trader Binance',
    account_type: 'usd_m_futures',
    mode: 'read_only',
    read_only: true,
    live_trading_enabled: false,
    status: 'credential_source_pending',
  };
  const unscopedAccount = {
    id: 'binance-unscoped',
    exchange: 'binance',
    label: 'Unscoped Binance',
    account_type: 'usd_m_futures',
    mode: 'read_only',
    read_only: true,
    live_trading_enabled: false,
    status: 'credential_source_pending',
  };
  const wrongPaperAccount = {
    id: 'binance-wrong-paper',
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-other',
    exchange: 'binance',
    label: 'Wrong paper account Binance',
    account_type: 'usd_m_futures',
    mode: 'read_only',
    read_only: true,
    live_trading_enabled: false,
    status: 'credential_source_pending',
  };

  expect(selectPrimaryExchangeAccount([otherTraderAccount, unscopedAccount], user)).toBeNull();
  expect(selectPrimaryExchangeAccount([wrongPaperAccount], user)).toBeNull();
  expect(selectPrimaryExchangeAccount([unscopedAccount], null)).toBeNull();
  expect(selectPrimaryExchangeAccount([wrongPaperAccount], { ...user, paper_account_id: null })).toBeNull();
});

test('changes trade account scope key on trader or paper-account switch', () => {
  expect(tradeAccountScopeKey('trader-wajidali1984', 'paper-wajidali1984')).toBe('trader-wajidali1984:paper-wajidali1984');
  expect(tradeAccountScopeKey('trader-wajidali1984', 'paper-other')).not.toBe(
    tradeAccountScopeKey('trader-wajidali1984', 'paper-wajidali1984'),
  );
  expect(tradeAccountScopeKey('trader-other', 'paper-wajidali1984')).not.toBe(
    tradeAccountScopeKey('trader-wajidali1984', 'paper-wajidali1984'),
  );
  expect(tradeAccountScopeKey(null, null)).toBe('public:no-paper-account');
});

test('filters typed activity rows to explicit active trader and paper account scope', () => {
  const rows = [
    {
      order_id: 'paper-good',
      trader_id: 'trader-wajidali1984',
      paper_account_id: 'paper-wajidali1984',
    },
    {
      order_id: 'paper-other',
      trader_id: 'trader-other',
      paper_account_id: 'paper-other',
    },
    {
      order_id: 'paper-unscoped',
    },
  ];
  const scopedEnvelopeData = {
    account_specific: true,
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-wajidali1984',
  };

  expect(
    tradeTerminalTestHooks.scopedTradeRecords(
      rows,
      scopedEnvelopeData,
      'trader-wajidali1984',
      'paper-wajidali1984',
    ).map((row) => row.order_id),
  ).toEqual(['paper-good']);
  expect(
    tradeTerminalTestHooks.scopedTradeRecords(
      rows,
      { ...scopedEnvelopeData, paper_account_id: 'paper-other' },
      'trader-wajidali1984',
      'paper-wajidali1984',
    ).map((row) => row.order_id),
  ).toEqual([]);
  expect(tradeTerminalTestHooks.accountRowMatchesTraderScope(rows[1], 'trader-wajidali1984', 'paper-wajidali1984')).toBe(false);
  expect(tradeTerminalTestHooks.accountRowMatchesTraderScope(rows[0], 'trader-wajidali1984', 'paper-wajidali1984')).toBe(true);
  expect(tradeTerminalTestHooks.accountRowMatchesTraderScope(rows[2], 'trader-wajidali1984', 'paper-wajidali1984')).toBe(false);
});

test('requires typed portfolio and signal envelopes to match active trader scope', () => {
  const scopedEnvelopeData = {
    account_specific: true,
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-wajidali1984',
  };
  const wrongEnvelopeData = {
    ...scopedEnvelopeData,
    paper_account_id: 'paper-other',
  };
  const scopedSignal = {
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-wajidali1984',
    selected_action: 'buy',
    confidence: 0.72,
  };
  const wrongSignal = {
    selected_action: 'sell',
    confidence: 0.91,
    trader_id: 'trader-other',
    paper_account_id: 'paper-other',
  };

  expect(tradeTerminalTestHooks.envelopeMatchesTraderScope(scopedEnvelopeData, 'trader-wajidali1984', 'paper-wajidali1984')).toBe(true);
  expect(tradeTerminalTestHooks.envelopeMatchesTraderScope(wrongEnvelopeData, 'trader-wajidali1984', 'paper-wajidali1984')).toBe(false);
  expect(
    tradeTerminalTestHooks.scopedRecord(
      scopedSignal,
      scopedEnvelopeData,
      'trader-wajidali1984',
      'paper-wajidali1984',
    ),
  ).toEqual(scopedSignal);
  expect(
    tradeTerminalTestHooks.scopedRecord(
      scopedSignal,
      wrongEnvelopeData,
      'trader-wajidali1984',
      'paper-wajidali1984',
    ),
  ).toEqual({});
  expect(
    tradeTerminalTestHooks.scopedRecord(
      wrongSignal,
      scopedEnvelopeData,
      'trader-wajidali1984',
      'paper-wajidali1984',
    ),
  ).toEqual({});
});

test('requires exchange read-only account payloads to match active trader scope', () => {
  const account = {
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-wajidali1984',
    exchange_account_id: 'binance-readonly-wajidali1984',
    exchange: 'binance',
    account_type: 'usdm_futures',
    account_specific: true,
    read_only: true,
    live_trading_enabled: false as const,
    account_snapshot: { available_balance: 1000 },
    positions: [],
    positions_count: 0,
    trade_permission_status: 'Read-only account verified',
    margin_mode_evidence: null,
    leverage_evidence: null,
  };

  expect(tradeTerminalTestHooks.exchangeReadOnlyMatchesTraderScope(
    account,
    'trader-wajidali1984',
    'paper-wajidali1984',
  )).toBe(true);
  expect(tradeTerminalTestHooks.exchangeReadOnlyMatchesTraderScope(
    { ...account, paper_account_id: 'paper-other' },
    'trader-wajidali1984',
    'paper-wajidali1984',
  )).toBe(false);
  expect(tradeTerminalTestHooks.exchangeReadOnlyMatchesTraderScope(
    { ...account, live_trading_enabled: true as never },
    'trader-wajidali1984',
    'paper-wajidali1984',
  )).toBe(false);
  expect(tradeTerminalTestHooks.exchangeReadOnlyMatchesTraderScope(
    { ...account, read_only: false },
    'trader-wajidali1984',
    'paper-wajidali1984',
  )).toBe(false);
});

test('requires signal rows to include selected-symbol evidence before rendering', () => {
  expect(tradeTerminalTestHooks.rowMatchesSymbol({ symbol: 'BTCUSDT' }, 'BTCUSDT')).toBe(true);
  expect(tradeTerminalTestHooks.rowMatchesSymbol({ market_symbol: 'BTCUSDT' }, 'BTCUSDT')).toBe(true);
  expect(tradeTerminalTestHooks.rowMatchesSymbol({ symbol: 'ETHUSDT' }, 'BTCUSDT')).toBe(false);
  expect(tradeTerminalTestHooks.rowMatchesSymbol({ selected_action: 'buy', confidence: 0.72 }, 'BTCUSDT')).toBe(false);
  expect(tradeTerminalTestHooks.rowMatchesSymbol({}, 'BTCUSDT')).toBe(true);
});

test('filters malformed symbols out of the trade terminal symbol selector', () => {
  expect(tradeTerminalTestHooks.uniqueSymbols(['btcusdt', 'BTC/USDT', 'ethusdt..', 'ETHUSDT'])).toEqual(['BTCUSDT', 'ETHUSDT']);
  expect(tradeTerminalTestHooks.uniqueSymbols(['BTC/USDT', undefined])).toEqual(['BTCUSDT']);
});

test('includes authenticated trader watchlist symbols in the trade terminal selector', () => {
  expect(tradeTerminalTestHooks.tradeTerminalSymbolUniverse({
    terminalSymbol: 'BTCUSDT',
    marketFeedSymbol: 'ethusdt',
    watchlist: ['BNBUSDT', 'SOLUSDT', 'bad/symbol', 'ETHUSDT'],
    positions: [{ symbol: 'XRPUSDT' }],
  })).toEqual(['BTCUSDT', 'ETHUSDT', 'BNBUSDT', 'SOLUSDT', 'XRPUSDT']);
});

test('requires typed paper-account truth to match the active trader and paper account', () => {
  const portfolio: ApiV2Envelope<PortfolioData> = {
    data: {
      equity: 1000,
      realized_pnl: 12,
      realized_net_pnl_usd: 2,
      realized_pnl_usd: 12,
      unrealized_pnl: -3,
      unrealized_pnl_usd: -1,
      total_pnl_usd: 1,
      pnl_source_key: 'v2:portfolio:state',
      pnl_source_route: '/api/v2/portfolio',
      pnl_source_type: 'CANONICAL_CURRENT_SESSION_RUNTIME',
      positions: [],
      mode: 'paper' as const,
      trader_id: 'trader-wajidali1984',
      paper_account_id: 'paper-wajidali1984',
      account_scope: 'authenticated_trader' as const,
      account_specific: true,
    },
    source: 'test portfolio repository',
    source_type: 'repository' as const,
    endpoint: '/api/v2/portfolio',
    timestamp: '2026-06-13T03:00:00Z',
    received_at: '2026-06-13T03:00:01Z',
    lag_ms: 1000,
    stale: false,
    missing_fields: [],
    warnings: [],
    mode: 'paper' as const,
    account_scope: {
      scope: 'authenticated_trader',
      trader_id: 'trader-wajidali1984',
      paper_account_id: 'paper-wajidali1984',
      authenticated: true,
      actor_scope_present: true,
      data_account_specific: true,
      scope_verified: true,
      live_trading_enabled: false,
      exchange_mutation_enabled: false,
      warnings: [],
    },
  };

  expect(typedPortfolioMatchesCurrentScope(portfolio, 'trader-wajidali1984', 'paper-wajidali1984')).toBe(true);
  expect(typedPortfolioMatchesCurrentScope(portfolio, 'trader-other', 'paper-wajidali1984')).toBe(false);
  expect(typedPortfolioMatchesCurrentScope(portfolio, 'trader-wajidali1984', 'paper-other')).toBe(false);
    expect(typedPortfolioMatchesCurrentScope(
      {
        ...portfolio,
        data: {
          equity: 1000,
          realized_pnl: 12,
          unrealized_pnl: -3,
          positions: [],
          mode: 'paper',
          trader_id: 'trader-other',
          paper_account_id: 'paper-wajidali1984',
          account_scope: 'authenticated_trader',
          account_specific: true,
        },
      },
    'trader-wajidali1984',
    'paper-wajidali1984',
  )).toBe(false);
  expect(resolveTypedPortfolioAccount(portfolio, 'trader-wajidali1984', 'paper-wajidali1984').equity).toBe(1000);
  expect(resolveTypedPortfolioAccount(portfolio, 'trader-wajidali1984', 'paper-wajidali1984').realizedPnl).toBe(2);
  expect(resolveTypedPortfolioAccount(portfolio, 'trader-wajidali1984', 'paper-wajidali1984').unrealizedPnl).toBe(-1);
  expect(resolveTypedPortfolioAccount(portfolio, 'trader-wajidali1984', 'paper-wajidali1984').totalPnl).toBe(1);
  expect(resolveTypedPortfolioAccount(portfolio, 'trader-wajidali1984', 'paper-wajidali1984').source).toBe('v2:portfolio:state');
  expect(resolveTypedPortfolioAccount(portfolio, 'trader-other', 'paper-wajidali1984').equity).toBeNull();
    expect(resolveTypedPortfolioAccount(
      {
        ...portfolio,
        data: {
          equity: 1000,
          realized_pnl: Number.NaN,
          unrealized_pnl: 5,
          positions: [],
          mode: 'paper',
          trader_id: 'trader-wajidali1984',
          paper_account_id: 'paper-wajidali1984',
          account_scope: 'authenticated_trader',
          account_specific: true,
        },
      },
    'trader-wajidali1984',
    'paper-wajidali1984',
  ).totalPnl).toBeNull();
});

test('unscoped paper-account truth prefers canonical portfolio PnL source fields', () => {
  const account = resolvePaperAccountTruth(
    { paper_equity: 9999, paper_pnl: 110, paper_realized_pnl_usd: 77, paper_unrealized_pnl_usd: 33 },
    { paper_current_session_equity: 9999, paper_current_session_pnl: 110 },
    {
      generated_utc: '2026-07-09T02:30:00Z',
      account_mode: 'paper',
      equity: 3000,
      cash_balance: 3000,
      realized_net_pnl_usd: 0,
      realized_pnl_usd: 77,
      unrealized_pnl_usd: 0,
      total_pnl_usd: 0,
      open_positions_count: 0,
      closed_positions_count: 0,
      pnl_source_key: 'v2:portfolio:state',
      pnl_source_route: '/api/v2/portfolio',
      pnl_source_type: 'CANONICAL_CURRENT_SESSION_RUNTIME',
      paper_equity_source: 'legacy-paper-equity',
    },
  );

  expect(account.equity).toBe(3000);
  expect(account.realizedPnl).toBe(0);
  expect(account.unrealizedPnl).toBe(0);
  expect(account.totalPnl).toBe(0);
  expect(account.source).toBe('v2:portfolio:state');
});

test('requires paper preview scope to match the active trader and paper account', () => {
  const preview: OrderPreviewData = {
    allowed: true,
    mode: 'paper',
    reason: 'paper_preview_ready',
    friendly_reason: 'Paper order can be staged',
    estimated_notional: 100,
    estimated_fee: 0.04,
    estimated_margin: 100,
    available_paper_balance: 1000,
    trader_id: 'trader-wajidali1984',
    paper_account_id: 'paper-wajidali1984',
    account_scope: 'authenticated_trader',
    risk_checks: [],
  };

  expect(paperPreviewMatchesTraderScope(preview, 'trader-wajidali1984', 'paper-wajidali1984')).toBe(true);
  expect(paperPreviewMatchesTraderScope(preview, 'trader-other', 'paper-wajidali1984')).toBe(false);
  expect(paperPreviewMatchesTraderScope(preview, 'trader-wajidali1984', 'paper-other')).toBe(false);
  expect(paperPreviewMatchesTraderScope({ ...preview, allowed: false }, 'trader-wajidali1984', 'paper-wajidali1984')).toBe(false);
  expect(paperPreviewMatchesTraderScope(preview, null, 'paper-wajidali1984')).toBe(false);
});

test('does not reflect malformed paper order symbols into unavailable envelopes', () => {
  expect(safeOrderEnvelopeSymbol(' btcusdt ')).toBe('BTCUSDT');
  expect(safeOrderEnvelopeSymbol('btcusdt../')).toBeUndefined();
  expect(safeOrderEnvelopeSymbol('ETH-USDT')).toBeUndefined();
  expect(safeOrderEnvelopeSymbol('')).toBeUndefined();
});

test('shows local paper actions only for explicit local paper repository rows', () => {
  expect(openOrdersTableTestHooks.rowIsPaperOnly({
    id: 'paper-order-1',
    order_id: 'paper-order-1',
    mode: 'paper',
    audit_event: 'paper_order_staged_local',
    exchange_mutation_enabled: false,
    live_transport_enabled: false,
  })).toBe(true);
  expect(openOrdersTableTestHooks.rowIsPaperOnly({
    id: 'paper-order-2',
    order_id: 'paper-order-2',
    mode: 'paper',
    exchange_mutation_enabled: false,
    live_transport_enabled: false,
  })).toBe(false);
  expect(openOrdersTableTestHooks.rowIsPaperOnly({
    id: 'live-order-1',
    order_id: 'live-order-1',
    mode: 'paper',
    audit_event: 'paper_order_staged_local',
    live_transport_enabled: true,
  })).toBe(false);
});

async function openTrade(page: Page): Promise<void> {
  await gotoAs(page, '/trade', 'trader');
  await page.waitForLoadState('domcontentloaded').catch(() => undefined);
  await expect(page.getByTestId('page-trader')).toBeVisible({ timeout: 10_000 });
}

async function bodyText(page: Page): Promise<string> {
  return page.locator('body').innerText();
}

async function mockApiV2Unavailable(page: Page, options: { unscopedFallbackEquity?: number; typedActivity?: boolean; typedActivitySourceType?: 'repository' | 'static_payload'; auth?: 'public' | 'wajidali1984' } = {}): Promise<void> {
  await page.route('**/api/auth/me', async (route) => {
    if (options.auth === 'wajidali1984') {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'user-wajidali1984',
            trader_id: 'trader-wajidali1984',
            username: 'wajidali1984',
            email: 'wajidali1984@hotmail.com',
            role: 'trader',
            paper_account_id: 'paper-wajidali1984',
            exchange_accounts: [
              {
                id: 'binance-wajidali1984',
                trader_id: 'trader-wajidali1984',
                paper_account_id: 'paper-wajidali1984',
                exchange: 'binance',
                label: 'Wajid Ali Binance Futures',
                account_type: 'usd_m_futures',
                mode: 'read_only',
                read_only: true,
                live_trading_enabled: false,
                status: 'credential_source_pending',
                credential_status: {
                  source_type: 'environment_reference',
                  configured: false,
                  status: 'credential_source_pending',
                  read_only_required: true,
                  live_trading_enabled: false,
                  raw_credential_value_exposed: false,
                },
              },
            ],
            watchlist: ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],
            alert_preferences: {},
            is_active: true,
            created_at: '2026-06-13T00:00:00Z',
            updated_at: '2026-06-13T00:00:00Z',
            last_login: '2026-06-13T00:00:00Z',
          },
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: null }),
    });
  });

  await page.route('**/operator_runtime/**', async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname.includes('/v2_portfolio_state/')) {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_utc: '2026-06-13T03:00:00Z',
          equity: options.unscopedFallbackEquity ?? null,
          realized_pnl_usd: 1234,
          unrealized_pnl_usd: 567,
          positions: [{ symbol: 'BTCUSDT', quantity: 9, open_position: true }],
        }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });

  await page.route('**/v2_*/**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({}),
    });
  });

  await page.route('**/api/v2/**', async (route) => {
    const url = new URL(route.request().url());
    const endpoint = url.pathname;
    const symbolMatch = endpoint.match(/\/api\/v2\/market\/([^/]+)/);
    const typedActivitySourceType = options.typedActivitySourceType ?? 'repository';
    const typedActivityData = options.typedActivity && endpoint === '/api/v2/execution/orders'
      ? {
          orders: [
            {
              id: 'paper-order-1',
              order_id: 'paper-order-1',
              time: '2026-06-13T03:00:00Z',
              symbol: 'BTCUSDT',
              side: 'buy',
              order_type: 'limit',
              price: 100000,
              quantity: 0.01,
              filled: 0,
              status: 'open',
              mode: 'paper',
              audit_event: 'paper_order_staged_local',
              source_status: 'paper_order_repository_update',
              exchange_mutation_enabled: false,
              live_transport_enabled: false,
              trader_id: 'trader-wajidali1984',
              paper_account_id: 'paper-wajidali1984',
            },
          ],
          trader_id: 'trader-wajidali1984',
          paper_account_id: 'paper-wajidali1984',
          account_scope: 'authenticated_trader',
          account_specific: true,
        }
        : options.typedActivity && endpoint === '/api/v2/execution/executions'
        ? {
            executions: [
              {
                time: '2026-06-13T03:01:00Z',
                symbol: 'BTCUSDT',
                side: 'buy',
                price: 100010,
                quantity: 0.01,
                fee: 0.4,
                slippage_bps: 1.2,
                source: 'paper_repository',
                risk_result: 'fee_gate_allowed',
                evidence: 'technical reference available',
                trader_id: 'trader-wajidali1984',
                paper_account_id: 'paper-wajidali1984',
              },
            ],
            trader_id: 'trader-wajidali1984',
            paper_account_id: 'paper-wajidali1984',
            account_scope: 'authenticated_trader',
            account_specific: true,
          }
        : options.typedActivity && endpoint === '/api/v2/execution/audit-events'
          ? {
              audit_events: [
                {
                  id: 'audit-paper-fill-1',
                  audit_id: 'audit-paper-fill-1',
                  audit_event: 'paper_order_filled_local',
                  action: 'fill',
                  order_id: 'paper-order-1',
                  trader_id: 'trader-wajidali1984',
                  paper_account_id: 'paper-wajidali1984',
                  mode: 'paper',
                  created_at: '2026-06-13T03:02:00Z',
                  source: 'Local paper repository audit',
                  exchange_mutation_enabled: false,
                  live_transport_enabled: false,
                },
              ],
              trader_id: 'trader-wajidali1984',
              paper_account_id: 'paper-wajidali1984',
              account_scope: 'authenticated_trader',
              account_specific: true,
            }
        : options.typedActivity && endpoint === '/api/v2/signals'
          ? {
              active_signal: {
                symbol: 'BTCUSDT',
                trader_id: 'trader-wajidali1984',
                paper_account_id: 'paper-wajidali1984',
                selected_action: 'BUY',
                confidence_calibrated: 0.72,
                strategy: 'trend follow',
                model_version: 'paper model',
                entry: 100000,
                target_1: 101000,
                stop: 99000,
                risk_result: 'fee_gate_allowed',
              },
              trader_id: 'trader-wajidali1984',
              paper_account_id: 'paper-wajidali1984',
              account_scope: 'authenticated_trader',
              account_specific: true,
            }
          : null;
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: endpoint === '/api/v2/orders/preview'
          ? {
            allowed: false,
            mode: 'paper_preview_unverified',
            reason: 'trader_session_required',
            friendly_reason: 'Sign in for trader-specific paper preview',
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
            risk_checks: [{ name: 'submit_endpoint', passed: false }],
          }
          : typedActivityData,
        source: typedActivityData ? 'test paper repository' : 'unavailable',
        source_type: typedActivityData ? typedActivitySourceType : 'unavailable',
        endpoint,
        timestamp: typedActivityData ? '2026-06-13T03:00:00Z' : null,
        received_at: '2026-06-13T03:00:00Z',
        lag_ms: typedActivityData ? 0 : null,
        stale: !typedActivityData,
        missing_fields: typedActivityData ? [] : ['data'],
        warnings: typedActivityData ? ['Trader-scoped paper repository fixture.'] : ['Endpoint unavailable in Playwright dev server.'],
        symbol: symbolMatch?.[1] ?? null,
        exchange: symbolMatch ? 'Binance USD-M' : null,
        mode: endpoint === '/api/v2/orders/preview' ? 'paper_preview_unverified' : endpoint.includes('/execution/') || endpoint === '/api/v2/signals' ? 'paper' : 'read_only',
      }),
    });
  });
}

async function mockAuthenticatedTrader(page: Page): Promise<void> {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: {
          id: 'user-wajidali1984',
          trader_id: 'trader-wajidali1984',
          username: 'wajidali1984',
          email: 'wajidali1984@hotmail.com',
          role: 'trader',
          paper_account_id: 'paper-wajidali1984',
          exchange_accounts: [
            {
              id: 'binance-wajidali1984',
              trader_id: 'trader-wajidali1984',
              paper_account_id: 'paper-wajidali1984',
              exchange: 'binance',
              label: 'Wajid Ali Binance Futures',
              account_type: 'usd_m_futures',
              mode: 'read_only',
              read_only: true,
              live_trading_enabled: false,
              status: 'credential_source_pending',
              credential_status: {
                source_type: 'environment',
                configured: false,
                status: 'credential_source_pending',
                read_only_required: true,
                live_trading_enabled: false,
                raw_credential_value_exposed: false,
                checked_at: '2026-06-13T03:00:00Z',
              },
              created_at: '2026-06-13T00:00:00Z',
              updated_at: '2026-06-13T00:00:00Z',
            },
          ],
          watchlist: ['BTCUSDT'],
          alert_preferences: {},
          is_active: true,
          created_at: '2026-06-13T00:00:00Z',
          updated_at: '2026-06-13T00:00:00Z',
          last_login: null,
        },
      }),
    });
  });
}

test.describe('trade terminal redesign', () => {
  test('renders without console errors', async ({ page }) => {
    await mockApiV2Unavailable(page);
    const errors: string[] = [];
    page.on('console', (message) => {
      if (message.type() === 'error') errors.push(message.text());
    });
    await openTrade(page);
    expect(errors).toEqual([]);
  });

  for (const viewport of VIEWPORTS) {
    test(`has no body horizontal scroll and captures ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openTrade(page);

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        bodyClientWidth: document.body.clientWidth,
      }));

      expect(Math.max(overflow.scrollWidth, overflow.bodyScrollWidth)).toBeLessThanOrEqual(
        Math.max(overflow.clientWidth, overflow.bodyClientWidth) + 1,
      );

      const root = path.resolve(process.cwd(), '..', 'screenshots', 'final');
      mkdirSync(root, { recursive: true });
      await page.screenshot({
        path: path.join(root, `trade-${viewport.name}.png`),
        fullPage: true,
      });
    });
  }

  test('does not show forbidden trader copy or raw backend enums', async ({ page }) => {
    await openTrade(page);
    const text = await bodyText(page);
    for (const forbidden of FORBIDDEN_STRINGS) {
      expect(text, `forbidden public /trade string: ${forbidden}`).not.toMatch(new RegExp(forbidden, 'i'));
    }
    expect(text).not.toMatch(/\b[A-Z]{3,}_[A-Z0-9_]+\b/);
    expect(text).not.toMatch(/\b[a-z]+_[a-z0-9_]*_[a-z0-9_]+\b/);
    expect(text).not.toMatch(/operator_runtime|v2_portfolio_state|runtime_pages_payload/i);
  });

  test('shows live-platform posture and terminal modules', async ({ page }) => {
    await openTrade(page);
    await expect(page.getByTestId('live-platform-badge')).toBeVisible();
    await expect(page.getByTestId('chart-panel')).toBeVisible();
    await expect(page.getByTestId('order-book-panel')).toBeVisible();
    await expect(page.getByTestId('market-depth-panel')).toBeVisible();
    await expect(page.getByTestId('recent-trades-tape')).toBeVisible();
    await expect(page.getByTestId('paper-order-ticket')).toBeVisible();
    await expect(page.getByTestId('trade-bottom-tabs')).toBeVisible();
  });

  test('shows trader-specific account and safe account access status without secrets', async ({ page }) => {
    await mockApiV2Unavailable(page);
    await page.unroute('**/api/auth/me');
    await mockAuthenticatedTrader(page);
    await openTrade(page);
    await page.getByRole('tab', { name: 'System' }).click();
    const text = await bodyText(page);
    expect(text).toContain('wajidali1984');
    expect(text).toContain('Wajid Ali Binance Futures');
    expect(text).toContain('BINANCE USD M FUTURES');
    expect(text).toContain('Account Scope');
    expect(text).toContain('Trader account linked');
    // credential_source_pending is a hard-unavailable state, labeled honestly
    // as unavailable rather than as a transient "connecting".
    expect(text).toContain('Account access unavailable — credential source not configured');
    expect(text).not.toMatch(/api[_ -]?key|api[_ -]?secret|private[_ -]?key|test-read-only-key|test-read-only-secret/i);
    expect(text).not.toMatch(/credential_source_pending/);
  });

  test('does not display unscoped fallback runtime equity as trader balance', async ({ page }) => {
    await mockApiV2Unavailable(page, { unscopedFallbackEquity: 777777 });
    await openTrade(page);

    const text = await bodyText(page);
    expect(text).not.toMatch(/777,?777/);
    expect(text).toMatch(/Sign in to view trader-specific account|Trader-specific account source connecting|Account access source connecting|Account access unavailable/i);
  });

  test('blocks invalid staged orders with friendly copy and has no live submit action', async ({ page }) => {
    await openTrade(page);
    await expect(page.getByRole('button', { name: /Place Buy/i })).toBeDisabled();
    await expect(page.getByText('Enter a quantity greater than zero.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Place Live/i })).toHaveCount(0);
  });

  test('shows required tabs and specific missing endpoint states', async ({ page }) => {
    await openTrade(page);
    for (const tab of ['Positions', 'Open Orders', 'Executions', 'Order History', 'Signal Evidence']) {
      await expect(page.getByRole('tab', { name: tab })).toBeVisible();
    }
    await expect(page.getByTestId('order-book-panel')).toBeVisible();
    await expect(page.getByTestId('recent-trades-tape')).toBeVisible();
    await expect(page.getByText(/Risk result connecting|Trader-specific account source connecting|Account access source connecting|Account access unavailable|Sign in for trader-specific account/i).first()).toBeVisible();
    await expect(page.getByTestId('chart-panel')).toBeVisible();
  });

  test('renders typed staged orders, executions, and signal evidence without live actions', async ({ page }) => {
    await mockApiV2Unavailable(page, { typedActivity: true, auth: 'wajidali1984' });
    await openTrade(page);

    await page.getByRole('tab', { name: 'Open Orders' }).click();
    const openOrders = page.getByTestId('open-orders-table');
    await expect(openOrders).toBeVisible();
    const openOrdersText = await openOrders.innerText();
    if (openOrdersText.includes('No open orders')) {
      expect(openOrdersText).toContain('execution engine fills intents synchronously');
    } else {
      expect(openOrdersText).toMatch(/[A-Z0-9]{2,}USDT/);
      expect(openOrdersText).toContain('Fill');
      expect(openOrdersText).toContain('Cancel');
    }
    expect(openOrdersText).not.toMatch(/Fill live|Cancel live|Place live/i);

    await page.getByRole('tab', { name: 'Executions' }).click();
    const executionsTable = page.getByTestId('executions-table');
    await expect(executionsTable).not.toContainText(/Loading execution history/i, { timeout: 10_000 });
    const executionsText = await executionsTable.innerText();
    expect(executionsText).toMatch(/[A-Z0-9]{2,}USDT|No execution fills/i);
    expect(executionsText).not.toMatch(/Fill live|Cancel live|Place live|live order submitted/i);

    await page.getByRole('tab', { name: 'Signal Evidence' }).click();
    await expect(page.getByTestId('signal-evidence-panel')).toContainText(/Trader-scoped signal source|Signal source connecting|Execution activity stream|Current forecast evidence|Stale signal content|Stale signal data/i);
    await expect(page.getByTestId('paper-audit-events')).toContainText('Execution audit events');
    await expect(page.getByTestId('paper-audit-events')).toContainText(/Order filled|Execution repository audit|runtime|No execution audit events/i);
    await expect(page.getByTestId('paper-audit-events')).not.toContainText(/paper_order_filled_local|paper_repository/i);
    await expect(page.getByRole('button', { name: /Place Live/i })).toHaveCount(0);
  });

  test('keeps staged row actions disabled unless orders endpoint is repository-backed', async ({ page }) => {
    await mockApiV2Unavailable(page, {
      typedActivity: true,
      typedActivitySourceType: 'static_payload',
      auth: 'wajidali1984',
    });
    await openTrade(page);

    await page.getByRole('tab', { name: 'Open Orders' }).click();
    const openOrders = page.getByTestId('open-orders-table');
    await expect(openOrders).toBeVisible();
    const openOrdersText = await openOrders.innerText();
    if (openOrdersText.includes('No open orders')) {
      expect(openOrdersText).toContain('execution engine fills intents synchronously');
    } else {
      expect(openOrdersText).toMatch(/[A-Z0-9]{2,}USDT/);
      expect(openOrdersText).toContain('Action unavailable');
      expect(openOrdersText).not.toContain('Fill paper');
      expect(openOrdersText).not.toContain('Cancel paper');
    }
    expect(openOrdersText).not.toMatch(/Fill live|Cancel live|Place live/i);
  });

  test('mobile layout uses segmented modules without wide tables', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openTrade(page);
    await expect(page.getByRole('navigation', { name: 'Trade modules' })).toBeVisible();
    await page.getByRole('button', { name: /Positions/i }).click();
    await expect(page.getByTestId('trade-bottom-tabs')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
