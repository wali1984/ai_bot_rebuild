import { useMemo, useState } from 'react';
import { useSymbolData } from './useSymbolData';
import { typedPortfolioMatchesCurrentScope, usePaperAccountTruth } from './usePaperAccountTruth';
import { usePaperActivityStream } from './usePaperActivityStream';
import { useTraderContext } from './useTraderContext';
import { useMarketDataStream, type MarketDataStreamState } from './useMarketDataStream';
import { useRealtimeResource } from './useRealtimeResource';
import { finite } from '../lib/tradeFormatters';
import type { AccountReadinessData, ApiV2Envelope, AuditEventsData, ExchangeReadOnlyAccountData, ExecutionsData, MarketDepthData, MarketTickerData, OrdersData, PortfolioData, PositionsData, RecentTradesData, SignalData } from '../types/apiV2';
import type { ValidatedDataEnvelope } from '../types/dataContract';

// Merge stream ticker (may be partial) over API ticker so API data fills any gaps from partial WebSocket frames
function mergeTickerFallback(
  stream: MarketTickerData | null | undefined,
  api: MarketTickerData | null | undefined,
): MarketTickerData | null {
  if (!stream && !api) return null;
  if (!api) return stream ?? null;
  if (!stream) return api;
  return {
    symbol: stream.symbol ?? api.symbol,
    last_price: stream.last_price ?? api.last_price,
    mark_price: stream.mark_price ?? api.mark_price,
    index_price: stream.index_price ?? api.index_price,
    change_1h: stream.change_1h ?? api.change_1h,
    change_4h: stream.change_4h ?? api.change_4h,
    change_24h: stream.change_24h ?? api.change_24h,
    high_24h: stream.high_24h ?? api.high_24h,
    low_24h: stream.low_24h ?? api.low_24h,
    volume_24h: stream.volume_24h ?? api.volume_24h,
    turnover_24h: stream.turnover_24h ?? api.turnover_24h,
    funding_rate: stream.funding_rate ?? api.funding_rate,
    next_funding: stream.next_funding ?? api.next_funding,
    open_interest: stream.open_interest ?? api.open_interest,
    open_interest_change: stream.open_interest_change ?? api.open_interest_change,
    bid: stream.bid ?? api.bid,
    ask: stream.ask ?? api.ask,
    spread_bps: stream.spread_bps ?? api.spread_bps,
  };
}

export interface TradePosition {
  symbol?: string;
  side?: string;
  quantity?: number;
  notional?: number;
  entry_price?: number;
  current_price?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  opened_utc?: string;
}

function uniqueSymbols(values: Array<string | undefined>): string[] {
  const symbols = values
    .map((value) => value?.trim().toUpperCase())
    .filter((value): value is string => typeof value === 'string' && value.length > 0 && /^[A-Z0-9]+$/.test(value));
  return [...new Set(symbols.length ? symbols : ['BTCUSDT'])];
}

export function tradeTerminalSymbolUniverse({
  terminalSymbol,
  marketFeedSymbol,
  watchlist,
  positions,
}: {
  terminalSymbol?: string;
  marketFeedSymbol?: string;
  watchlist?: string[];
  positions?: Array<{ symbol?: string }>;
}): string[] {
  return uniqueSymbols([
    terminalSymbol,
    marketFeedSymbol,
    ...(watchlist ?? []),
    ...((positions ?? []).map((position) => position.symbol)),
    'BTCUSDT',
  ]);
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function tradePositions(value: unknown): TradePosition[] {
  if (!Array.isArray(value)) return [];
  return value.filter((row): row is TradePosition => Boolean(row) && typeof row === 'object');
}

function tradeRecords(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((row): row is Record<string, unknown> => Boolean(row) && typeof row === 'object');
}

function paperActivityTradePositions(value: unknown): TradePosition[] {
  return tradeRecords(value).map((row) => ({
    symbol: symbolToken(row.symbol) ?? undefined,
    side: typeof row.side === 'string' ? row.side : undefined,
    quantity: finite(row.net_quantity) ?? finite(row.quantity) ?? undefined,
    notional: finite(row.notional_usd) ?? finite(row.notional) ?? undefined,
    entry_price: finite(row.avg_entry_price) ?? finite(row.entry_price) ?? undefined,
    current_price: finite(row.last_mark_price) ?? finite(row.current_price) ?? undefined,
    unrealized_pnl: finite(row.unrealized_pnl) ?? undefined,
    unrealized_pnl_pct: finite(row.unrealized_pnl_pct) ?? (
      finite(row.unrealized_pnl_bps) !== null ? (finite(row.unrealized_pnl_bps) as number) / 10000 : undefined
    ),
    opened_utc: typeof row.opened_utc === 'string'
      ? row.opened_utc
      : typeof row.opened_est === 'string'
        ? row.opened_est
        : undefined,
  }));
}

function scopeToken(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function symbolToken(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim().toUpperCase() : null;
}

function rowMatchesSymbol(row: Record<string, unknown>, symbol: string): boolean {
  if (!Object.keys(row).length) return true;
  const rowSymbol = symbolToken(row.symbol ?? row.market_symbol);
  return rowSymbol === symbol.toUpperCase();
}

export function envelopeMatchesTraderScope(data: unknown, traderId: string | null, paperAccountId: string | null): boolean {
  if (!data || typeof data !== 'object' || !traderId || !paperAccountId) return false;
  const recordData = data as Record<string, unknown>;
  return (
    recordData.account_specific === true
    && scopeToken(recordData.trader_id) === traderId
    && scopeToken(recordData.paper_account_id) === paperAccountId
  );
}

export function exchangeReadOnlyMatchesTraderScope(
  data: ExchangeReadOnlyAccountData | null | undefined,
  traderId: string | null,
  paperAccountId: string | null,
): data is ExchangeReadOnlyAccountData {
  return Boolean(
    data
    && traderId
    && paperAccountId
    && scopeToken(data.trader_id) === traderId
    && scopeToken(data.paper_account_id) === paperAccountId
    && data.read_only === true
    && data.live_trading_enabled === false
  );
}

export function accountRowMatchesTraderScope(
  row: Record<string, unknown>,
  traderId: string | null,
  paperAccountId: string | null,
): boolean {
  if (!traderId || !paperAccountId) return false;
  const rowTraderId = scopeToken(row.trader_id);
  const rowPaperAccountId = scopeToken(row.paper_account_id);
  if (rowTraderId || rowPaperAccountId) {
    return rowTraderId === traderId && rowPaperAccountId === paperAccountId;
  }
  return false;
}

function scopedTradeRecords(
  rows: Array<Record<string, unknown>>,
  data: unknown,
  traderId: string | null,
  paperAccountId: string | null,
): Array<Record<string, unknown>> {
  const envelopeScoped = envelopeMatchesTraderScope(data, traderId, paperAccountId);
  return envelopeScoped
    ? rows.filter((row) => accountRowMatchesTraderScope(row, traderId, paperAccountId))
    : [];
}

function scopedRecord(
  row: Record<string, unknown>,
  data: unknown,
  traderId: string | null,
  paperAccountId: string | null,
): Record<string, unknown> {
  if (!Object.keys(row).length) return {};
  const envelopeScoped = envelopeMatchesTraderScope(data, traderId, paperAccountId);
  return envelopeScoped && accountRowMatchesTraderScope(row, traderId, paperAccountId) ? row : {};
}

function activitySourceLabel<T>(
  envelope: ApiV2Envelope<T> | null | undefined,
  scoped: boolean,
  scopedLabel: string,
  fallback: string,
): string {
  if (!scoped) return fallback;
  if (!envelope || envelope.source_type === 'unavailable') return fallback;
  if (envelope.source_type === 'static_payload' || envelope.stale) return 'Fallback data';
  if (envelope.source_type === 'repository') return scopedLabel;
  if (envelope.source_type === 'api') return scopedLabel;
  return scopedLabel;
}

function currentSourceType(sourceType: ApiV2Envelope<unknown>['source_type'] | undefined): boolean {
  return sourceType === 'websocket'
    || sourceType === 'api'
    || sourceType === 'repository'
    || sourceType === 'redis_live';
}

function marketSourceLabel<T>(
  envelope: ApiV2Envelope<T> | null | undefined,
  currentLabel: string,
  fallback: string,
): string {
  if (!envelope || envelope.source_type === 'unavailable') return fallback;
  if (envelope.source_type === 'static_payload') return 'Fallback market data';
  if (envelope.stale) return 'Stale market data';
  return currentLabel;
}

function marketStreamSourceLabel(stream: Pick<MarketDataStreamState, 'streamSource' | 'connected' | 'stale'>): string {
  if (stream.stale) return 'Market stream stale; using shared resource fallback';
  if (stream.streamSource === 'binance_usdm_public_websocket') return 'Native public market stream connected';
  if (stream.connected) return 'Live market stream connected';
  return 'Market stream reconnecting; using shared resource fallback';
}

function accountSourceLabel<T>(
  envelope: ApiV2Envelope<T> | null | undefined,
  scoped: boolean,
  scopedLabel: string,
  fallback: string,
): string {
  if (!scoped) return fallback;
  if (!envelope || envelope.source_type === 'unavailable') return fallback;
  if (envelope.source_type === 'static_payload' || envelope.stale) return 'Fallback account data withheld';
  return scopedLabel;
}

function scopedTradePositions(
  rows: TradePosition[],
  data: unknown,
  traderId: string | null,
  paperAccountId: string | null,
): TradePosition[] {
  return scopedTradeRecords(
    rows.map((row) => row as Record<string, unknown>),
    data,
    traderId,
    paperAccountId,
  ) as TradePosition[];
}

function envelopeSymbol(envelope: ApiV2Envelope<unknown> | null | undefined): string | null {
  const direct = envelope?.symbol;
  const data = envelope?.data;
  const dataSymbol = data && typeof data === 'object' && 'symbol' in data ? (data as { symbol?: unknown }).symbol : null;
  const value = direct ?? dataSymbol;
  return typeof value === 'string' && value.trim() ? value.trim().toUpperCase() : null;
}

function envelopeMatchesSymbol(envelope: ApiV2Envelope<unknown> | null | undefined, symbol: string): boolean {
  if (!envelope) return false;
  const requested = symbol.toUpperCase();
  const direct = typeof envelope.symbol === 'string' && envelope.symbol.trim()
    ? envelope.symbol.trim().toUpperCase()
    : null;
  const data = envelope.data;
  const dataSymbol = data && typeof data === 'object' && 'symbol' in data && typeof (data as { symbol?: unknown }).symbol === 'string'
    ? String((data as { symbol?: unknown }).symbol).trim().toUpperCase()
    : null;
  if (direct && direct !== requested) return false;
  if (dataSymbol && dataSymbol !== requested) return false;
  return Boolean(direct || dataSymbol);
}

function realtimeEnvelopeMatchesSymbol<T>(
  envelope: ApiV2Envelope<T> | null | undefined,
  symbol: string,
): envelope is ApiV2Envelope<T> {
	  return Boolean(
	    envelope
	    && envelope.stale === false
	    && currentSourceType(envelope.source_type)
	    && envelopeMatchesSymbol(envelope, symbol),
	  );
}

export function tradeAccountScopeKey(traderId: string | null, paperAccountId: string | null): string {
  const trader = traderId?.trim() || 'public';
  const paper = paperAccountId?.trim() || 'no-paper-account';
  return `${trader}:${paper}`;
}

function isoTimestamp(value: number | string | null | undefined): string | null {
  if (typeof value === 'string' && value.trim()) return value;
  if (typeof value === 'number' && Number.isFinite(value)) return new Date(value).toISOString();
  return null;
}

function apiSourceType(value: ValidatedDataEnvelope<unknown>['source_type']): ApiV2Envelope<unknown>['source_type'] {
  if (value === 'repository' || value === 'redis_live' || value === 'static_payload' || value === 'unavailable') return value;
  if (value === 'websocket' || value === 'stream' || value === 'sse') return 'websocket';
  if (value === 'api' || value === 'cache') return 'api';
  return 'unavailable';
}

function apiMode(value: ValidatedDataEnvelope<unknown>['mode']): ApiV2Envelope<unknown>['mode'] {
  if (value === 'paper' || value === 'read_only' || value === 'live_blocked') return value;
  return 'read_only';
}

function apiEnvelopeFromResource<T>(
  envelope: ValidatedDataEnvelope<T>,
  endpoint: string,
): ApiV2Envelope<T> | null {
  if (envelope.data === null || envelope.data === undefined) return null;
  const receivedAt = isoTimestamp(envelope.received_at) ?? new Date().toISOString();
  return {
    data: envelope.data,
    source: envelope.source,
    source_type: apiSourceType(envelope.source_type) as ApiV2Envelope<T>['source_type'],
    endpoint: envelope.endpoint ?? endpoint,
    timestamp: isoTimestamp(envelope.timestamp) ?? receivedAt,
    received_at: receivedAt,
    lag_ms: envelope.lag_ms,
    stale: envelope.freshness_status === 'stale' || envelope.freshness_status === 'offline' || envelope.freshness_status === 'unavailable',
    missing_fields: envelope.missing_fields,
    warnings: envelope.warnings,
    symbol: envelope.symbol ?? (envelope.data && typeof envelope.data === 'object' && 'symbol' in envelope.data ? String((envelope.data as { symbol?: unknown }).symbol ?? '') || null : null),
    exchange: envelope.exchange ?? null,
    mode: apiMode(envelope.mode) as ApiV2Envelope<T>['mode'],
    trader_context: (envelope as unknown as { trader_context?: ApiV2Envelope<T>['trader_context'] }).trader_context ?? null,
    account_scope: (envelope as unknown as { account_scope?: ApiV2Envelope<T>['account_scope'] }).account_scope ?? null,
  };
}

interface TradeMarketOverviewData {
  symbols?: string[];
}

export function useTradeTerminal() {
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const paperAccountTruth = usePaperAccountTruth(8_000, { requireTraderScope: true });
  const traderContext = useTraderContext();
  const paperActivity = usePaperActivityStream(1000);
  const traderScopeKey = tradeAccountScopeKey(traderContext.traderId, traderContext.paperAccountId);
  const marketOverview = useRealtimeResource<TradeMarketOverviewData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const marketSymbols = useMemo(
    () => (marketOverview.envelope.data?.symbols ?? []).filter((s): s is string => typeof s === 'string' && s.length > 0),
    [marketOverview.envelope.data],
  );

  const paperActivityPositionRows = paperActivityTradePositions(paperActivity.data.positions);
  const paperActivityOrderRows = tradeRecords(paperActivity.data.orders);
  const paperActivityOpenOrderRows = tradeRecords(paperActivity.data.open_orders);
  const paperActivityExecutionRows = tradeRecords(paperActivity.data.fills).length
    ? tradeRecords(paperActivity.data.fills)
    : tradeRecords(paperActivity.data.executions);
  const paperActivityAuditRows = tradeRecords(paperActivity.data.audit_events);
  const paperActivityAvailable = Boolean(
    paperActivity.connected
    || paperActivity.source === 'http_fallback'
    || paperActivityPositionRows.length
    || paperActivityOrderRows.length
    || paperActivityExecutionRows.length
    || paperActivityAuditRows.length
  );
  const accountStreamsEnabled = !traderContext.loading;
  const activityFallbackStreamsEnabled = accountStreamsEnabled && !paperActivityAvailable;
  const portfolioResource = useRealtimeResource<PortfolioData>({
    url: '/api/v2/portfolio',
    source: '/api/v2/portfolio',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: accountStreamsEnabled,
    mode: 'paper',
  });
  const positionsResource = useRealtimeResource<PositionsData>({
    url: '/api/v2/account/positions',
    source: '/api/v2/account/positions',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: activityFallbackStreamsEnabled,
    mode: 'paper',
  });
  const ordersResource = useRealtimeResource<OrdersData>({
    url: '/api/v2/execution/orders',
    source: '/api/v2/execution/orders',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: activityFallbackStreamsEnabled,
    mode: 'paper',
  });
  const executionsResource = useRealtimeResource<ExecutionsData>({
    url: '/api/v2/execution/executions',
    source: '/api/v2/execution/executions',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: activityFallbackStreamsEnabled,
    mode: 'paper',
  });
  const auditEventsResource = useRealtimeResource<AuditEventsData>({
    url: '/api/v2/execution/audit-events',
    source: '/api/v2/execution/audit-events',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: activityFallbackStreamsEnabled,
    mode: 'paper',
  });
  const accountReadinessResource = useRealtimeResource<AccountReadinessData>({
    url: '/api/v2/account/readiness',
    source: '/api/v2/account/readiness',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: accountStreamsEnabled,
    mode: 'paper',
  });
  const exchangeReadOnlyResource = useRealtimeResource<ExchangeReadOnlyAccountData>({
    url: '/api/v2/account/exchange-readonly',
    source: '/api/v2/account/exchange-readonly',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: accountStreamsEnabled,
    mode: 'read_only',
  });
  const typedPortfolio = apiEnvelopeFromResource(portfolioResource.envelope, '/api/v2/portfolio');
  const typedPositions = apiEnvelopeFromResource(positionsResource.envelope, '/api/v2/account/positions');
  const typedOrders = apiEnvelopeFromResource(ordersResource.envelope, '/api/v2/execution/orders');
  const typedExecutions = apiEnvelopeFromResource(executionsResource.envelope, '/api/v2/execution/executions');
  const typedAuditEvents = apiEnvelopeFromResource(auditEventsResource.envelope, '/api/v2/execution/audit-events');
  const typedAccountReadiness = apiEnvelopeFromResource(accountReadinessResource.envelope, '/api/v2/account/readiness');
  const typedExchangeReadOnly = apiEnvelopeFromResource(exchangeReadOnlyResource.envelope, '/api/v2/account/exchange-readonly');
  const typedPositionRows = typedPositions?.data
    ? scopedTradePositions(tradePositions(typedPositions.data.positions), typedPositions.data, traderContext.traderId, traderContext.paperAccountId)
    : null;
  const positions = paperActivityPositionRows.length ? paperActivityPositionRows : typedPositionRows ?? [];
  const symbols = useMemo(
    () => {
      const base = tradeTerminalSymbolUniverse({
        watchlist: traderContext.user?.watchlist,
        positions,
      });
      if (marketSymbols.length > 0) {
        const combined = [...new Set([...base, ...marketSymbols])];
        return combined.sort((a, b) => {
          const aBase = base.includes(a);
          const bBase = base.includes(b);
          if (aBase && !bBase) return -1;
          if (!aBase && bBase) return 1;
          return a.localeCompare(b);
        });
      }
      return base;
    },
    [positions, traderContext.user?.watchlist, marketSymbols],
  );
  const symbol = symbols.includes(selectedSymbol) ? selectedSymbol : symbols[0];
  const signalPath = `/api/v2/signals?symbol=${encodeURIComponent(symbol)}`;
  const depthPath = `/api/v2/market/${encodeURIComponent(symbol)}/depth`;
  const tradesPath = `/api/v2/market/${encodeURIComponent(symbol)}/trades`;
  const signalsResource = useRealtimeResource<SignalData>({
    url: signalPath,
    source: signalPath,
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: accountStreamsEnabled,
    mode: 'paper',
  });
  const depthResource = useRealtimeResource<MarketDepthData>({
    url: depthPath,
    source: depthPath,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 9_000,
    mode: 'read_only',
  });
  const tradesResource = useRealtimeResource<RecentTradesData>({
    url: tradesPath,
    source: tradesPath,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 9_000,
    mode: 'read_only',
  });
  const typedSignals = apiEnvelopeFromResource(signalsResource.envelope, signalPath);
  const typedDepth = apiEnvelopeFromResource(depthResource.envelope, depthPath);
  const typedTrades = apiEnvelopeFromResource(tradesResource.envelope, tradesPath);
  const typedOrdersScoped = envelopeMatchesTraderScope(typedOrders?.data, traderContext.traderId, traderContext.paperAccountId);
  const typedExecutionsScoped = envelopeMatchesTraderScope(typedExecutions?.data, traderContext.traderId, traderContext.paperAccountId);
  const typedAuditEventsScoped = envelopeMatchesTraderScope(typedAuditEvents?.data, traderContext.traderId, traderContext.paperAccountId);
  const typedSignalsScoped = envelopeMatchesTraderScope(typedSignals?.data, traderContext.traderId, traderContext.paperAccountId);
  const typedOrderRows = typedOrders?.data
    ? scopedTradeRecords(tradeRecords(typedOrders.data.orders), typedOrders.data, traderContext.traderId, traderContext.paperAccountId)
    : [];
	  const typedOrdersRepositoryScoped = Boolean(
	    currentSourceType(typedOrders?.source_type)
	    && typedOrdersScoped,
	  );
  const typedExecutionRows = typedExecutions?.data
    ? scopedTradeRecords(tradeRecords(typedExecutions.data.executions), typedExecutions.data, traderContext.traderId, traderContext.paperAccountId)
    : [];
  const typedAuditEventRows = typedAuditEvents?.data
    ? scopedTradeRecords(tradeRecords(typedAuditEvents.data.audit_events), typedAuditEvents.data, traderContext.traderId, traderContext.paperAccountId)
    : [];
  const { detail: typedMarket } = useSymbolData(symbol);
  const marketStream = useMarketDataStream(symbol);
  const streamTickerEnvelope = realtimeEnvelopeMatchesSymbol(marketStream.ticker, symbol) ? marketStream.ticker : null;
  const streamDepthEnvelope = realtimeEnvelopeMatchesSymbol(marketStream.depth, symbol) ? marketStream.depth : null;
  const streamTradesEnvelope = realtimeEnvelopeMatchesSymbol(marketStream.trades, symbol) ? marketStream.trades : null;
  const typedDepthEnvelope = envelopeMatchesSymbol(typedDepth, symbol) ? typedDepth : null;
  const typedTradesEnvelope = envelopeMatchesSymbol(typedTrades, symbol) ? typedTrades : null;
  const typedTicker = mergeTickerFallback(streamTickerEnvelope?.data, typedMarket.data);
  const typedPortfolioScoped = typedPortfolioMatchesCurrentScope(typedPortfolio, traderContext.traderId, traderContext.paperAccountId);
  const typedPortfolioData = typedPortfolioScoped ? typedPortfolio?.data ?? null : null;
  const typedExchangeReadOnlyData = exchangeReadOnlyMatchesTraderScope(
    typedExchangeReadOnly?.data,
    traderContext.traderId,
    traderContext.paperAccountId,
  )
    ? typedExchangeReadOnly?.data ?? null
    : null;
  const typedDepthData = streamDepthEnvelope?.data ?? typedDepthEnvelope?.data;
  const typedTradeRows = streamTradesEnvelope?.data?.trades ?? typedTradesEnvelope?.data?.trades ?? [];
  const depthBids = typedDepthData?.bids ?? [];
  const depthAsks = typedDepthData?.asks ?? [];
  const bestDepthBid = depthBids[0];
  const bestDepthAsk = depthAsks[0];
  const depthBidPrice = finite(bestDepthBid?.[0]);
  const depthBidSize = finite(bestDepthBid?.[1]);
  const depthAskPrice = finite(bestDepthAsk?.[0]);
  const depthAskSize = finite(bestDepthAsk?.[1]);
  const rawTypedSignal = typedSignals?.data ? record(typedSignals.data.active_signal) : {};
  const scopedTypedSignal = typedSignals?.data
    ? scopedRecord(rawTypedSignal, typedSignals.data, traderContext.traderId, traderContext.paperAccountId)
    : {};
  const scopedSignalAvailable = rowMatchesSymbol(scopedTypedSignal, symbol) && Object.keys(scopedTypedSignal).length > 0;
	  const redisPaperSignalAvailable = Boolean(
	    typedSignals
	    && currentSourceType(typedSignals.source_type)
	    && typedSignals.data?.account_specific === false
    && envelopeMatchesSymbol(typedSignals, symbol)
    && rowMatchesSymbol(rawTypedSignal, symbol)
    && Object.keys(rawTypedSignal).length > 0,
  );
  const typedSignal = scopedSignalAvailable ? scopedTypedSignal : redisPaperSignalAvailable ? rawTypedSignal : {};
  const signal = typedSignal;
  const hasSignal = Object.keys(signal).length > 0;
  const signalSource = hasSignal
    ? scopedSignalAvailable
      ? activitySourceLabel(typedSignals, typedSignalsScoped, 'Trader signal source', 'Signal source connecting')
      : redisPaperSignalAvailable
        ? 'Current forecast evidence source'
        : 'Signal source connecting'
    : 'Signal source connecting';
  const signalFreshness = hasSignal
    ? typedSignals?.stale
      ? 'Stale signal data'
      : scopedSignalAvailable
        ? 'Trader-scoped signal source'
        : redisPaperSignalAvailable
          ? 'Current forecast evidence'
          : typedSignals?.source_type === 'static_payload'
            ? 'Fallback signal data'
            : 'Signal source connecting'
    : 'Signal source connecting';
  const risk: Record<string, unknown> = {};
  const lastPrice = finite(typedTicker?.last_price);
  const bid = finite(typedTicker?.bid) ?? depthBidPrice;
  const ask = finite(typedTicker?.ask) ?? depthAskPrice;
  const spreadAbs = bid !== null && ask !== null ? Math.max(0, ask - bid) : null;
  const spreadPct = spreadAbs !== null && lastPrice ? spreadAbs / lastPrice : null;
  const accountEquity = finite(typedPortfolioData?.equity) ?? paperAccountTruth.account.equity;
  const availablePaperBalance = accountEquity;
  const paperActivitySummary = record(paperActivity.data.summary);
  const streamRealizedPnl = finite(paperActivitySummary.realized_pnl_usd);
  const streamUnrealizedPnl = finite(paperActivitySummary.unrealized_pnl_usd);
  const streamOpenNotional = finite(paperActivitySummary.total_open_notional);
  const accountRealizedPnl = streamRealizedPnl ?? typedPortfolioData?.realized_pnl ?? null;
  const accountUnrealizedPnl = streamUnrealizedPnl ?? typedPortfolioData?.unrealized_pnl ?? null;
  const accountTotalPnl = accountRealizedPnl != null && accountUnrealizedPnl != null
    ? accountRealizedPnl + accountUnrealizedPnl
    : null;

  const tickerSource = streamTickerEnvelope
    ? marketSourceLabel(streamTickerEnvelope, 'Live market stream', 'Market ticker source connecting')
    : marketSourceLabel(typedMarket, 'Current market data', 'Market ticker source connecting');
  const orderBookSource = streamDepthEnvelope
    ? marketSourceLabel(streamDepthEnvelope, 'Live order book stream', 'Order book source connecting')
    : marketSourceLabel(typedDepthEnvelope, 'Current order book source', 'Order book source connecting');
  const depthSource = streamDepthEnvelope
    ? marketSourceLabel(streamDepthEnvelope, 'Live market depth stream', 'Depth source connecting')
    : marketSourceLabel(typedDepthEnvelope, 'Current market depth source', 'Depth source connecting');
  const tradesSource = streamTradesEnvelope
    ? marketSourceLabel(streamTradesEnvelope, 'Live trades stream', 'Recent trades source connecting')
    : marketSourceLabel(typedTradesEnvelope, 'Current recent trades source', 'Recent trades source connecting');
  const hasTraderPaperScope = Boolean(traderContext.traderId && traderContext.paperAccountId);
  const traderPaperAccountFallback = hasTraderPaperScope
    ? 'Trader-specific account source connecting'
    : 'Sign in to view trader-specific account';
  const portfolioSource = accountSourceLabel(
    typedPortfolio,
    typedPortfolioScoped,
    'Trader account source',
    paperAccountTruth.account.reason ?? traderPaperAccountFallback,
  );
  const exchangeReadSource = typedExchangeReadOnlyData
    ? 'Exchange account source'
    : 'Account access source connecting';

  return {
    symbol,
    symbols,
    setSelectedSymbol,
    sources: {
      typedPortfolio: typedPortfolio?.endpoint ?? '/api/v2/portfolio',
      typedPositions: typedPositions?.endpoint ?? '/api/v2/account/positions',
      typedOrders: typedOrders?.endpoint ?? '/api/v2/execution/orders',
      typedExecutions: typedExecutions?.endpoint ?? '/api/v2/execution/executions',
      typedAuditEvents: typedAuditEvents?.endpoint ?? '/api/v2/execution/audit-events',
      typedAccountReadiness: typedAccountReadiness?.endpoint ?? '/api/v2/account/readiness',
      typedExchangeReadOnly: typedExchangeReadOnly?.endpoint ?? '/api/v2/account/exchange-readonly',
      typedSignals: typedSignals?.endpoint ?? `/api/v2/signals?symbol=${symbol}`,
      typedDepth: typedDepthEnvelope?.endpoint ?? '/api/v2/market/{symbol}/depth',
      typedTrades: typedTradesEnvelope?.endpoint ?? '/api/v2/market/{symbol}/trades',
      marketStream: marketStream.connected ? '/ws/market-data' : 'shared market resource fallback',
      marketDetail: typedMarket.endpoint,
      paperAccountTruth: typedPortfolio?.endpoint ?? '/api/v2/portfolio',
    },
    terminal: {
      payload: null,
      error: null,
      loading: false,
      ageSeconds: null,
    },
    portfolio: {
      payload: null,
      positions,
      openPositions: positions.filter((position) => (position.quantity ?? 0) !== 0),
      error: null,
      ageSeconds: null,
    },
    activity: {
      orders: paperActivityOrderRows.length ? paperActivityOrderRows : typedOrderRows,
      openOrders: paperActivityOpenOrderRows.length ? paperActivityOpenOrderRows : (paperActivityOrderRows.length ? paperActivityOrderRows : typedOrderRows).filter((row) => {
        const status = String(row.status ?? row.order_status ?? '').toLowerCase();
        return !status || !/(filled|canceled|cancelled|rejected|expired|closed)/.test(status);
      }),
      executions: paperActivityExecutionRows.length ? paperActivityExecutionRows : typedExecutionRows,
      auditEvents: paperActivityAuditRows.length ? paperActivityAuditRows : typedAuditEventRows,
      auditPolicy: typedAuditEvents?.data?.audit_policy ?? null,
      auditLedger: typedAuditEvents?.data?.audit_ledger ?? null,
      orderHistory: paperActivityOrderRows.length ? paperActivityOrderRows : typedOrderRows,
      sources: {
        orders: paperActivityOrderRows.length ? 'Execution activity stream' : activitySourceLabel(typedOrders, typedOrdersScoped, 'Trader order source', 'Order source connecting'),
        executions: paperActivityExecutionRows.length ? 'Execution activity stream' : activitySourceLabel(typedExecutions, typedExecutionsScoped, 'Trader execution source', 'Execution source connecting'),
        auditEvents: paperActivityAuditRows.length ? 'Execution activity stream' : activitySourceLabel(typedAuditEvents, typedAuditEventsScoped, 'Execution audit source', 'Execution audit event source connecting'),
        signals: signalSource,
      },
      missing: {
        orders: typedOrders?.missing_fields ?? ['orders'],
        executions: typedExecutions?.missing_fields ?? ['executions'],
        auditEvents: typedAuditEvents?.missing_fields ?? ['audit_events'],
        signals: typedSignals?.missing_fields ?? ['active_signal'],
      },
      warnings: {
        orders: typedOrders?.warnings ?? [],
        executions: typedExecutions?.warnings ?? [],
        auditEvents: typedAuditEvents?.warnings ?? [],
        signals: typedSignals?.warnings ?? [],
      },
      actionPolicy: {
        localPaperOrdersRepository: typedOrdersRepositoryScoped,
      },
    },
    paper: {
      payload: paperActivity.envelope,
      activity: paperActivity.data,
      connected: paperActivity.connected,
      source: paperActivity.source,
      loading: paperActivity.loading,
      error: paperActivity.error,
      warnings: paperActivity.warnings,
      stale: paperActivity.stale,
      ageSeconds: null,
    },
    mode: {
      label: 'Live Trading',
      liveGate: 'Live platform',
      traderState: 'Live Trading',
    },
    market: {
      lastPrice,
      markPrice: typedTicker?.mark_price ?? null,
      indexPrice: typedTicker?.index_price ?? null,
      change24h: typedTicker?.change_24h ?? null,
      high24h: typedTicker?.high_24h ?? null,
      low24h: typedTicker?.low_24h ?? null,
      volume24h: typedTicker?.volume_24h ?? null,
      turnover24h: typedTicker?.turnover_24h ?? null,
      fundingRate: typedTicker?.funding_rate ?? null,
      nextFunding: typedTicker?.next_funding ?? null,
      openInterest: typedTicker?.open_interest ?? null,
      openInterestChange: typedTicker?.open_interest_change ?? null,
      bid,
      ask,
      spreadAbs,
      spreadPct,
      spreadBps: typedTicker?.spread_bps ?? null,
      bookBidSize: depthBidSize,
      bookAskSize: depthAskSize,
      bookImbalance: null,
      depthLevels: {
        bids: depthBids,
        asks: depthAsks,
      },
      recentTrades: typedTradeRows,
      sources: {
        ticker: tickerSource,
        price: tickerSource,
        funding: typedTicker?.funding_rate != null || typedTicker?.next_funding != null ? tickerSource : 'Funding source connecting',
        openInterest: typedTicker?.open_interest != null || typedTicker?.open_interest_change != null ? tickerSource : 'Open interest source connecting',
        volume: typedTicker?.volume_24h != null || typedTicker?.turnover_24h != null ? tickerSource : 'Volume source connecting',
        orderBook: orderBookSource,
        depth: depthSource,
        trades: tradesSource,
        stream: marketStreamSourceLabel(marketStream),
      },
    },
    account: {
      equity: accountEquity,
      realizedPnl: accountRealizedPnl,
      unrealizedPnl: accountUnrealizedPnl,
      totalPnl: accountTotalPnl,
      totalNotional: streamOpenNotional,
      availablePaperBalance,
      exchangeAvailableBalance: typedExchangeReadOnlyData?.account_snapshot?.available_balance ?? null,
      exchangeReadSource,
      exchangeReadStatus: typedExchangeReadOnlyData && currentSourceType(typedExchangeReadOnly?.source_type)
        ? 'Account verified'
        : typedExchangeReadOnly?.source_type === 'unavailable'
          ? 'Account access source connecting'
          : typedExchangeReadOnly
            ? 'Account withheld until trader scope is verified'
            : 'Account access source connecting',
      requiredInitialMargin: null,
      paperCurrency: paperAccountTruth.account.currency,
      source: portfolioSource,
      reason: !typedPortfolioScoped
        ? traderPaperAccountFallback
        : paperAccountTruth.account.reason ?? typedPortfolio?.warnings?.[0] ?? traderPaperAccountFallback,
      generatedAt: typedPortfolioScoped ? typedPortfolio?.timestamp ?? paperAccountTruth.account.generatedAt : paperAccountTruth.account.generatedAt,
      scope: traderContext.accountScopeLabel,
    },
    trader: {
      displayName: traderContext.displayName,
      traderId: traderContext.traderId,
      paperAccountId: traderContext.paperAccountId,
      accountLabel: traderContext.accountLabel,
      exchangeLabel: traderContext.exchangeLabel,
      accountScopeLabel: traderContext.accountScopeLabel,
      accountBindingStatus: traderContext.accountBindingStatus,
      accountBindingVerified: traderContext.accountBindingVerified,
      credentialStatus: traderContext.credentialStatus,
      credentialStatusDetail: traderContext.credentialStatusDetail,
      accountReadinessStatus: typedAccountReadiness?.data?.account_specific || hasTraderPaperScope
        ? 'Trader account linked'
        : typedAccountReadiness?.data?.account_scope === 'authenticated_trader'
          ? 'Trader account linked; readiness incomplete'
          : 'Sign in for trader readiness',
      accountReadinessDetail: typedAccountReadiness?.warnings?.join(' ') ?? 'Trader account readiness source connecting',
      accountReadinessMissing: typedAccountReadiness?.missing_fields ?? ['trader_account_repository'],
      accountReadinessScopeVerified: typedAccountReadiness?.account_scope?.scope_verified ?? false,
      exchangeReadStatus: typedExchangeReadOnlyData && currentSourceType(typedExchangeReadOnly?.source_type)
        ? 'Account verified'
        : typedExchangeReadOnly?.warnings?.[0] ?? 'Account access source connecting',
      exchangeReadDetail: typedExchangeReadOnlyData
        ? typedExchangeReadOnly?.warnings?.join(' ') ?? 'Exchange account source connecting'
        : 'Account access source connecting',
      readOnly: traderContext.readOnly,
      liveTradingEnabled: traderContext.liveTradingEnabled,
    },
    signal: {
      direction: hasSignal ? signal.selected_action ?? signal.action ?? signal.actionable_reason_code ?? 'Signal connecting' : 'Signal connecting',
      confidence: signal.confidence_calibrated ?? signal.confidence ?? null,
      strategy: hasSignal ? signal.strategy ?? signal.strategy_id ?? 'Strategy connecting' : 'Strategy connecting',
      modelVersion: hasSignal ? signal.model_version ?? signal.model_source ?? 'Model connecting' : 'Model connecting',
      entry: signal.entry ?? signal.entry_price ?? null,
      target1: signal.target_1 ?? signal.price_target ?? null,
      target2: signal.target_2 ?? null,
      target3: signal.target_3 ?? null,
      stop: signal.stop ?? signal.stop_loss ?? null,
      invalidation: signal.invalidation ?? null,
      riskDecision: signal.risk_result ?? signal.risk_decision ?? risk.risk_result ?? risk.risk_reason_code ?? 'Risk result connecting',
      expectedMoveAfterCostBps: signal.expected_move_after_cost_bps ?? null,
      dataCoveragePercent: signal.data_coverage_percent ?? null,
      targetLabel: signal.target_label ?? 'Price target',
      lineageSummary: signal.lineage_summary ?? null,
      paperFillAllowed: signal.paper_fill_allowed === true,
      source: signalSource,
      freshness: signalFreshness,
    },
  };
}

export type TradeTerminalState = ReturnType<typeof useTradeTerminal>;

export const tradeTerminalTestHooks = {
  accountRowMatchesTraderScope,
  activitySourceLabel,
  envelopeMatchesSymbol,
  envelopeMatchesTraderScope,
  exchangeReadOnlyMatchesTraderScope,
  marketStreamSourceLabel,
  realtimeEnvelopeMatchesSymbol,
  rowMatchesSymbol,
  scopedRecord,
  scopedTradeRecords,
  tradeTerminalSymbolUniverse,
  uniqueSymbols,
};
