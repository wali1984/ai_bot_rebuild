import { useEffect, useState } from 'react';
import { getV2MarketCandles, getV2MarketDepth, getV2MarketDerivatives, getV2MarketIndicators, getV2MarketTrades, safeV2MarketSymbol } from '../api/v2Market';
import { getV2Signals } from '../api/v2Signals';
import { unavailableV2Response } from '../api/v2Shared';
import { useMarketDataStream } from './useMarketDataStream';
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
  if (!envelope || envelope.stale !== false || (envelope.source_type !== 'api' && envelope.source_type !== 'repository')) return null;
  if (expectedSymbol && envelopeSymbol(envelope) !== expectedSymbol.toUpperCase()) return null;
  if (expectedTimeframe && envelopeTimeframe(envelope) !== expectedTimeframe) return null;
  return envelope;
}

export function useMarketDetail(symbol: string): MarketDetailState {
  const safeSymbol = safeV2MarketSymbol(symbol);
  const querySymbol = safeSymbol ?? '';
  const displaySymbol = safeSymbol ?? 'Invalid market symbol';
  const { detail: ticker, loading: tickerLoading } = useSymbolData(querySymbol);
  const traderContext = useTraderContext();
  const marketStream = useMarketDataStream(querySymbol);
  const [candles, setCandles] = useState<ApiV2Envelope<MarketCandlesData>>(() => safeSymbol ? initialCandles(safeSymbol) : unavailableV2Response('/api/v2/market/{symbol}/candles', ['symbol', 'candles'], 'Enter a valid market symbol.'));
  const [indicators, setIndicators] = useState<ApiV2Envelope<MarketIndicatorsData>>(() => safeSymbol ? initialIndicators(safeSymbol) : unavailableV2Response('/api/v2/market/{symbol}/indicators', ['symbol', 'ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target'], 'Enter a valid market symbol.'));
  const [depth, setDepth] = useState<ApiV2Envelope<MarketDepthData>>(() => safeSymbol ? initialDepth(safeSymbol) : unavailableV2Response('/api/v2/market/{symbol}/depth', ['symbol', 'bids', 'asks', 'spread'], 'Enter a valid market symbol.'));
  const [trades, setTrades] = useState<ApiV2Envelope<RecentTradesData>>(() => safeSymbol ? initialTrades(safeSymbol) : unavailableV2Response('/api/v2/market/{symbol}/trades', ['symbol', 'trades', 'trade_stream'], 'Enter a valid market symbol.'));
  const [derivatives, setDerivatives] = useState<ApiV2Envelope<MarketDerivativesData>>(() => safeSymbol ? initialDerivatives(safeSymbol) : unavailableV2Response('/api/v2/market/{symbol}/derivatives', ['symbol', 'funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis'], 'Enter a valid market symbol.'));
  const [signals, setSignals] = useState<ApiV2Envelope<SignalData>>(() => initialSignals());
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    if (!safeSymbol) {
      setCandles(unavailableV2Response('/api/v2/market/{symbol}/candles', ['symbol', 'candles'], 'Enter a valid market symbol.'));
      setIndicators(unavailableV2Response('/api/v2/market/{symbol}/indicators', ['symbol', 'ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target'], 'Enter a valid market symbol.'));
      setDepth(unavailableV2Response('/api/v2/market/{symbol}/depth', ['symbol', 'bids', 'asks', 'spread'], 'Enter a valid market symbol.'));
      setTrades(unavailableV2Response('/api/v2/market/{symbol}/trades', ['symbol', 'trades', 'trade_stream'], 'Enter a valid market symbol.'));
      setDerivatives(unavailableV2Response('/api/v2/market/{symbol}/derivatives', ['symbol', 'funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis'], 'Enter a valid market symbol.'));
      setSignals(unavailableV2Response('/api/v2/signals?symbol={symbol}', ['symbol', 'active_signal'], 'Enter a valid market symbol.', { mode: 'paper' }));
      setLoading(false);
      return undefined;
    }
    const requestSymbol = safeSymbol;
    let active = true;
    setLoading(true);

    async function load(): Promise<void> {
      const [nextCandles, nextIndicators, nextDepth, nextTrades, nextDerivatives, nextSignals] = await Promise.all([
        getV2MarketCandles(requestSymbol),
        getV2MarketIndicators(requestSymbol),
        getV2MarketDepth(requestSymbol),
        getV2MarketTrades(requestSymbol),
        getV2MarketDerivatives(requestSymbol),
        getV2Signals(requestSymbol),
      ]);
      if (!active) return;
      setCandles(nextCandles);
      setIndicators(nextIndicators);
      setDepth(nextDepth);
      setTrades(nextTrades);
      setDerivatives(nextDerivatives);
      setSignals(signalForTraderAndSymbol(
        nextSignals,
        requestSymbol,
        traderContext.traderId,
        traderContext.paperAccountId,
        Boolean(traderContext.user),
      ));
      setLoading(false);
    }

    void load();
    const interval = window.setInterval(load, 4_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [safeSymbol, traderContext.paperAccountId, traderContext.traderId, traderContext.user]);

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
    loading: loading || tickerLoading,
  };
}

export const marketDetailTestHooks = {
  currentReadOnlyEnvelope,
  signalForTraderAndSymbol,
  signalMatchesTraderScope,
  signalForSymbol,
};
