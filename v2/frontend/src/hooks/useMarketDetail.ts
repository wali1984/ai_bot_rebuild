import { useMemo } from 'react';
import { safeV2MarketSymbol } from '../api/v2Market';
import { unavailableV2Response } from '../api/v2Shared';
import { useMarketDataStream } from './useMarketDataStream';
import { useRealtimeResource } from './useRealtimeResource';
import { useTraderContext } from './useTraderContext';
import type {
  ApiV2Envelope,
  MarketCandlesData,
  MarketDerivativesData,
  MarketDepthData,
  MarketIndicatorsData,
  MarketTickerData,
  RecentTradesData,
  SignalData,
} from '../types/apiV2';
import type { ValidatedDataEnvelope } from '../types/dataContract';
import { useSymbolData } from './useSymbolData';

export interface MarketDetailState {
  symbol: string;
  ticker: ApiV2Envelope<MarketTickerData>;
  candles: ApiV2Envelope<MarketCandlesData>;
  indicators: ApiV2Envelope<MarketIndicatorsData>;
  depth: ApiV2Envelope<MarketDepthData>;
  trades: ApiV2Envelope<RecentTradesData>;
  derivatives: ApiV2Envelope<MarketDerivativesData>;
  signals: ApiV2Envelope<SignalData>;
  loading: boolean;
}

function initialCandles(symbol: string): ApiV2Envelope<MarketCandlesData> {
  return unavailableV2Response<MarketCandlesData>(
    `/api/v2/market/${symbol}/candles`,
    ['candles'],
    'Candle endpoint has not returned yet.',
    { symbol },
  );
}

function initialIndicators(symbol: string): ApiV2Envelope<MarketIndicatorsData> {
  return unavailableV2Response<MarketIndicatorsData>(
    `/api/v2/market/${symbol}/indicators`,
    ['ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target', 'indicator_repository'],
    'Indicator source has not returned yet.',
    { symbol },
  );
}

function initialDepth(symbol: string): ApiV2Envelope<MarketDepthData> {
  return unavailableV2Response<MarketDepthData>(
    `/api/v2/market/${symbol}/depth`,
    ['bids', 'asks', 'spread'],
    'Depth endpoint has not returned yet.',
    { symbol },
  );
}

function initialTrades(symbol: string): ApiV2Envelope<RecentTradesData> {
  return unavailableV2Response<RecentTradesData>(
    `/api/v2/market/${symbol}/trades`,
    ['trades', 'trade_stream'],
    'Recent trades endpoint has not returned yet.',
    { symbol },
  );
}

function initialDerivatives(symbol: string): ApiV2Envelope<MarketDerivativesData> {
  return unavailableV2Response<MarketDerivativesData>(
    `/api/v2/market/${symbol}/derivatives`,
    ['funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis'],
    'Derivatives endpoint has not returned yet.',
    { symbol },
  );
}

function initialSignals(): ApiV2Envelope<SignalData> {
  return unavailableV2Response<SignalData>(
    '/api/v2/signals',
    ['active_signal'],
    'Signal endpoint has not returned yet.',
    { mode: 'paper' },
  );
}

function signalSymbol(signal: ApiV2Envelope<SignalData>): string | null {
  const activeSignal = signal.data?.active_signal;
  const rawSymbol = activeSignal && typeof activeSignal === 'object' ? activeSignal.symbol ?? activeSignal.market_symbol : null;
  return typeof rawSymbol === 'string' && rawSymbol.trim() ? rawSymbol.trim().toUpperCase() : null;
}

function scopeToken(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function signalMatchesTraderScope(
  signal: ApiV2Envelope<SignalData>,
  traderId: string | null,
  paperAccountId: string | null,
): boolean {
  const data = signal.data;
  if (!data) return false;
  const accountSpecific = data.account_specific === true || signal.account_scope?.scope_verified === true;
  if (!traderId || !paperAccountId) return !accountSpecific;
  if (!accountSpecific) return false;
  const dataTraderId = scopeToken(data.trader_id);
  const dataPaperAccountId = scopeToken(data.paper_account_id);
  const proofMatches = (
    signal.account_scope?.scope_verified === true
    && scopeToken(signal.account_scope.trader_id) === traderId
    && scopeToken(signal.account_scope.paper_account_id) === paperAccountId
  );
  return (dataTraderId === traderId && dataPaperAccountId === paperAccountId) || proofMatches;
}

function signalForSymbol(signal: ApiV2Envelope<SignalData>, symbol: string): ApiV2Envelope<SignalData> {
  if (!signal.data?.active_signal) return signal;
  const nextSymbol = signalSymbol(signal);
  if (nextSymbol === symbol.toUpperCase()) return signal;
  return {
    ...signal,
    data: {
      ...signal.data,
      active_signal: null,
    },
    missing_fields: [...new Set([...signal.missing_fields, 'active_signal_symbol_match'])],
    warnings: [
      ...signal.warnings,
      nextSymbol
        ? `Active signal was withheld because it belongs to ${nextSymbol}.`
        : 'Active signal was withheld because symbol evidence is unavailable.',
    ],
  };
}

function signalForTraderAndSymbol(
  signal: ApiV2Envelope<SignalData>,
  symbol: string,
  traderId: string | null,
  paperAccountId: string | null,
  requireAccountScope: boolean,
): ApiV2Envelope<SignalData> {
  const symbolScoped = signalForSymbol(signal, symbol);
  if (!symbolScoped.data?.active_signal || !requireAccountScope) return symbolScoped;
  if (signalMatchesTraderScope(symbolScoped, traderId, paperAccountId)) return symbolScoped;
  return {
    ...symbolScoped,
    data: {
      ...symbolScoped.data,
      active_signal: null,
    },
    missing_fields: [...new Set([...symbolScoped.missing_fields, 'trader_signal_scope'])],
    warnings: [
      ...symbolScoped.warnings,
      'Active signal was withheld because it is not scoped to this trader account.',
    ],
  };
}

function envelopeSymbol(envelope: ApiV2Envelope<unknown> | null | undefined): string | null {
  const direct = envelope?.symbol;
  const data = envelope?.data;
  const dataSymbol = data && typeof data === 'object' && 'symbol' in data ? (data as { symbol?: unknown }).symbol : null;
  const value = direct ?? dataSymbol;
  return typeof value === 'string' && value.trim() ? value.trim().toUpperCase() : null;
}

function envelopeTimeframe(envelope: ApiV2Envelope<unknown> | null | undefined): string | null {
  const data = envelope?.data;
  const value = data && typeof data === 'object' && 'timeframe' in data ? (data as { timeframe?: unknown }).timeframe : null;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function currentReadOnlyEnvelope<T>(
  envelope: ApiV2Envelope<T> | null | undefined,
  expectedSymbol?: string | null,
  expectedTimeframe?: string | null,
): ApiV2Envelope<T> | null {
  if (
    !envelope
    || envelope.stale !== false
    || !(
      envelope.source_type === 'websocket'
      || envelope.source_type === 'api'
      || envelope.source_type === 'repository'
      || envelope.source_type === 'redis_live'
    )
  ) return null;
  if (expectedSymbol && envelopeSymbol(envelope) !== expectedSymbol.toUpperCase()) return null;
  if (expectedTimeframe && envelopeTimeframe(envelope) !== expectedTimeframe) return null;
  return envelope;
}

function resourceEnvelopeToApi<T>(
  envelope: ValidatedDataEnvelope<T>,
  endpoint: string,
): ApiV2Envelope<T> | null {
  if (envelope.data === null || envelope.data === undefined) return null;
  const receivedAt = envelope.received_at ?? Date.now();
  const timestamp = envelope.timestamp ?? receivedAt;
  return {
    data: envelope.data,
    source: envelope.source,
    source_type: envelope.source_type as ApiV2Envelope<T>['source_type'],
    endpoint: envelope.endpoint ?? endpoint,
    timestamp: typeof timestamp === 'number' ? new Date(timestamp).toISOString() : null,
    received_at: typeof receivedAt === 'number' ? new Date(receivedAt).toISOString() : new Date().toISOString(),
    lag_ms: envelope.lag_ms,
    stale: envelope.freshness_status === 'stale' || envelope.freshness_status === 'offline' || envelope.data_quality_status === 'invalid',
    missing_fields: envelope.missing_fields,
    warnings: envelope.warnings,
    symbol: envelope.symbol ?? null,
    exchange: envelope.exchange ?? null,
    mode: envelope.mode as ApiV2Envelope<T>['mode'],
    trader_context: (envelope as unknown as { trader_context?: ApiV2Envelope<T>['trader_context'] }).trader_context ?? null,
    account_scope: (envelope as unknown as { account_scope?: ApiV2Envelope<T>['account_scope'] }).account_scope ?? null,
  };
}

export function useMarketDetail(symbol: string): MarketDetailState {
  const safeSymbol = safeV2MarketSymbol(symbol);
  const querySymbol = safeSymbol ?? '';
  const displaySymbol = safeSymbol ?? 'Invalid market symbol';
  const { detail: ticker, loading: tickerLoading } = useSymbolData(querySymbol);
  const traderContext = useTraderContext();
  const marketStream = useMarketDataStream(querySymbol);
  const candlesPath = safeSymbol ? `/api/v2/market/${safeSymbol}/candles?timeframe=1m` : '/api/v2/market/{symbol}/candles?timeframe=1m';
  const indicatorsPath = safeSymbol ? `/api/v2/market/${safeSymbol}/indicators?timeframe=1m` : '/api/v2/market/{symbol}/indicators?timeframe=1m';
  const depthPath = safeSymbol ? `/api/v2/market/${safeSymbol}/depth` : '/api/v2/market/{symbol}/depth';
  const tradesPath = safeSymbol ? `/api/v2/market/${safeSymbol}/trades` : '/api/v2/market/{symbol}/trades';
  const derivativesPath = safeSymbol ? `/api/v2/market/${safeSymbol}/derivatives` : '/api/v2/market/{symbol}/derivatives';
  const signalsPath = safeSymbol ? `/api/v2/signals?symbol=${encodeURIComponent(safeSymbol)}` : '/api/v2/signals?symbol={symbol}';
  const resourcesEnabled = Boolean(safeSymbol);
  const candlesResource = useRealtimeResource<MarketCandlesData>({
    url: candlesPath,
    source: candlesPath,
    source_type: 'websocket',
    pollIntervalMs: 4_000,
    staleThresholdMs: 16_000,
    enabled: resourcesEnabled,
    mode: 'read_only',
  });
  const indicatorsResource = useRealtimeResource<MarketIndicatorsData>({
    url: indicatorsPath,
    source: indicatorsPath,
    source_type: 'websocket',
    pollIntervalMs: 4_000,
    staleThresholdMs: 30_000,
    enabled: resourcesEnabled,
    mode: 'read_only',
  });
  const depthResource = useRealtimeResource<MarketDepthData>({
    url: depthPath,
    source: depthPath,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 12_000,
    enabled: resourcesEnabled,
    mode: 'read_only',
  });
  const tradesResource = useRealtimeResource<RecentTradesData>({
    url: tradesPath,
    source: tradesPath,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 12_000,
    enabled: resourcesEnabled,
    mode: 'read_only',
  });
  const derivativesResource = useRealtimeResource<MarketDerivativesData>({
    url: derivativesPath,
    source: derivativesPath,
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 30_000,
    enabled: resourcesEnabled,
    mode: 'read_only',
  });
  const signalsResource = useRealtimeResource<SignalData>({
    url: signalsPath,
    source: signalsPath,
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 24_000,
    enabled: resourcesEnabled,
    mode: 'paper',
  });
  const candles = useMemo<ApiV2Envelope<MarketCandlesData>>(
    () => (safeSymbol ? resourceEnvelopeToApi(candlesResource.envelope, candlesPath) ?? initialCandles(safeSymbol) : unavailableV2Response<MarketCandlesData>('/api/v2/market/{symbol}/candles', ['symbol', 'candles'], 'Enter a valid market symbol.')),
    [candlesPath, candlesResource.envelope, safeSymbol],
  );
  const indicators = useMemo<ApiV2Envelope<MarketIndicatorsData>>(
    () => (safeSymbol ? resourceEnvelopeToApi(indicatorsResource.envelope, indicatorsPath) ?? initialIndicators(safeSymbol) : unavailableV2Response<MarketIndicatorsData>('/api/v2/market/{symbol}/indicators', ['symbol', 'ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target'], 'Enter a valid market symbol.')),
    [indicatorsPath, indicatorsResource.envelope, safeSymbol],
  );
  const depth = useMemo<ApiV2Envelope<MarketDepthData>>(
    () => (safeSymbol ? resourceEnvelopeToApi(depthResource.envelope, depthPath) ?? initialDepth(safeSymbol) : unavailableV2Response<MarketDepthData>('/api/v2/market/{symbol}/depth', ['symbol', 'bids', 'asks', 'spread'], 'Enter a valid market symbol.')),
    [depthPath, depthResource.envelope, safeSymbol],
  );
  const trades = useMemo<ApiV2Envelope<RecentTradesData>>(
    () => (safeSymbol ? resourceEnvelopeToApi(tradesResource.envelope, tradesPath) ?? initialTrades(safeSymbol) : unavailableV2Response<RecentTradesData>('/api/v2/market/{symbol}/trades', ['symbol', 'trades', 'trade_stream'], 'Enter a valid market symbol.')),
    [safeSymbol, tradesPath, tradesResource.envelope],
  );
  const derivatives = useMemo<ApiV2Envelope<MarketDerivativesData>>(
    () => (safeSymbol ? resourceEnvelopeToApi(derivativesResource.envelope, derivativesPath) ?? initialDerivatives(safeSymbol) : unavailableV2Response<MarketDerivativesData>('/api/v2/market/{symbol}/derivatives', ['symbol', 'funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis'], 'Enter a valid market symbol.')),
    [derivativesPath, derivativesResource.envelope, safeSymbol],
  );
  const signals = useMemo<ApiV2Envelope<SignalData>>(() => {
    const envelope = safeSymbol
      ? resourceEnvelopeToApi(signalsResource.envelope, signalsPath) ?? initialSignals()
      : unavailableV2Response<SignalData>('/api/v2/signals?symbol={symbol}', ['symbol', 'active_signal'], 'Enter a valid market symbol.', { mode: 'paper' });
    return signalForTraderAndSymbol(
      envelope,
      safeSymbol ?? querySymbol,
      traderContext.traderId,
      traderContext.paperAccountId,
      Boolean(traderContext.user),
    );
  }, [querySymbol, safeSymbol, signalsPath, signalsResource.envelope, traderContext.paperAccountId, traderContext.traderId, traderContext.user]);

  const realtimeTicker = currentReadOnlyEnvelope(marketStream.ticker, querySymbol);
  const realtimeCandles = currentReadOnlyEnvelope(marketStream.candles, querySymbol, '1m');
  const realtimeDepth = currentReadOnlyEnvelope(marketStream.depth, querySymbol);
  const realtimeTrades = currentReadOnlyEnvelope(marketStream.trades, querySymbol);

  return {
    symbol: displaySymbol,
    ticker: realtimeTicker ?? ticker,
    candles: realtimeCandles ?? candles,
    indicators,
    depth: realtimeDepth ?? depth,
    trades: realtimeTrades ?? trades,
    derivatives,
    signals,
    loading: Boolean(safeSymbol) && (
      tickerLoading
      || candlesResource.loading
      || indicatorsResource.loading
      || depthResource.loading
      || tradesResource.loading
      || derivativesResource.loading
      || signalsResource.loading
    ),
  };
}

export const marketDetailTestHooks = {
  currentReadOnlyEnvelope,
  signalForTraderAndSymbol,
  signalMatchesTraderScope,
  signalForSymbol,
};
