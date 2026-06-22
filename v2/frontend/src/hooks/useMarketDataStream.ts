import { useEffect, useState } from 'react';
import type { ApiV2Envelope, MarketCandle, MarketCandlesData, MarketDepthData, MarketTickerData, RecentTradesData } from '../types/apiV2';

interface MarketStreamMessage {
  type?: string;
  ticker?: ApiV2Envelope<MarketTickerData>;
  depth?: ApiV2Envelope<MarketDepthData>;
  trades?: ApiV2Envelope<RecentTradesData>;
  candles?: ApiV2Envelope<MarketCandlesData>;
  stream_health?: Record<string, unknown>;
  received_at?: string;
  stale?: boolean;
  warnings?: string[];
}

export interface MarketDataStreamState {
  connected: boolean;
  nativeConnected: boolean;
  streamSource: 'binance_usdm_public_websocket' | 'safe_api_contract_stream' | 'unavailable';
  ticker: ApiV2Envelope<MarketTickerData> | null;
  depth: ApiV2Envelope<MarketDepthData> | null;
  trades: ApiV2Envelope<RecentTradesData> | null;
  candles: ApiV2Envelope<MarketCandlesData> | null;
  liveCandle: MarketCandle | null;
  streamHealth: Record<string, unknown> | null;
  receivedAt: string | null;
  stale: boolean;
  warnings: string[];
  error: string | null;
}

const marketDataStreamCache = new Map<string, MarketDataStreamState>();

function initialMarketDataStreamState(): MarketDataStreamState {
  return {
    connected: false,
    nativeConnected: false,
    streamSource: 'unavailable',
    ticker: null,
    depth: null,
    trades: null,
    candles: null,
    liveCandle: null,
    streamHealth: null,
    receivedAt: null,
    stale: true,
    warnings: ['Market stream has not connected yet'],
    error: null,
  };
}

function marketDataStreamCacheKey(symbol: string | null, timeframe: string | null): string | null {
  return symbol && timeframe ? `${symbol}:${timeframe}` : null;
}

function initialCachedMarketDataStreamState(symbol: string | null, timeframe: string | null): MarketDataStreamState {
  const key = marketDataStreamCacheKey(symbol, timeframe);
  const cached = key ? marketDataStreamCache.get(key) : null;
  if (!cached) return initialMarketDataStreamState();
  return {
    ...cached,
    connected: false,
    nativeConnected: false,
    stale: true,
    warnings: uniqueWarnings([...cached.warnings, 'Reconnecting market stream']),
  };
}

function rememberMarketDataStreamState(key: string | null, state: MarketDataStreamState): void {
  if (
    key
    && !state.stale
    && (state.ticker || state.depth || state.trades || state.candles)
  ) {
    marketDataStreamCache.set(key, state);
  }
}

function safeMarketStreamSymbol(symbol: string): string | null {
  const normalized = symbol.trim().toUpperCase();
  return normalized && /^[A-Z0-9]+$/.test(normalized) ? normalized : null;
}

const MARKET_STREAM_TIMEFRAMES = new Set(['1m', '3m', '5m', '15m', '1h', '4h', '1d', '1w']);

function safeMarketStreamTimeframe(timeframe: string): string | null {
  const normalized = timeframe.trim();
  return MARKET_STREAM_TIMEFRAMES.has(normalized) ? normalized : null;
}

function streamUrls(symbol: string, intervalMs: number, timeframe: string): string[] {
  const safeSymbol = safeMarketStreamSymbol(symbol);
  const safeTimeframe = safeMarketStreamTimeframe(timeframe);
  if (!safeSymbol || !safeTimeframe) return [];
  const origin = typeof window === 'undefined' ? 'https://nervyx.local' : window.location.origin;
  const protocol = origin.startsWith('https:') ? 'wss:' : 'ws:';
  const lowerSymbol = safeSymbol.toLowerCase();
  const nativeStreams = [
    `${lowerSymbol}@ticker`,
    `${lowerSymbol}@bookTicker`,
    `${lowerSymbol}@markPrice@1s`,
    `${lowerSymbol}@depth20@100ms`,
    `${lowerSymbol}@aggTrade`,
    `${lowerSymbol}@trade`,
    `${lowerSymbol}@kline_${safeTimeframe}`,
  ].join('/');
  const backendUrls = ['/api/v2/ws/market-data', '/ws/market-data'].map((path) => {
    const url = new URL(path, origin);
    url.protocol = protocol;
    url.searchParams.set('symbol', safeSymbol);
    url.searchParams.set('interval_ms', String(intervalMs));
    url.searchParams.set('timeframe', safeTimeframe);
    return url.toString();
  });
  // Backend proxy is primary; Binance direct WSS is fallback so the browser
  // always goes through the V2 backend first.  REST is the final fallback
  // at the TradingChartPanel layer; see CLAUDE.md "Unified Binance data".
  return [...backendUrls, `wss://fstream.binance.com/stream?streams=${nativeStreams}`];
}

function streamIdleRotateMs(intervalMs: number): number {
  return Math.max(3_500, intervalMs * 2);
}

function numeric(value: unknown): number | null {
  const next = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(next) ? next : null;
}

function nowIso(): string {
  return new Date().toISOString();
}

function timestampMilliseconds(value: unknown): number | null {
  const eventTime = numeric(value);
  if (eventTime === null) return null;
  return eventTime > 10_000_000_000 ? eventTime : eventTime * 1000;
}

function eventIso(value: unknown): string {
  const eventTime = timestampMilliseconds(value);
  return new Date(eventTime ?? Date.now()).toISOString();
}

function lagMs(value: unknown): number | null {
  const eventTime = timestampMilliseconds(value);
  return eventTime === null ? null : Math.max(0, Date.now() - eventTime);
}

function envelope<T>(
  symbol: string,
  endpoint: string,
  source: string,
  eventTime: unknown,
  data: T,
  warnings: string[],
  missingFields: string[] = [],
): ApiV2Envelope<T> {
  return {
    data,
    source,
    source_type: 'api',
    endpoint,
    timestamp: eventIso(eventTime),
    received_at: nowIso(),
    lag_ms: lagMs(eventTime),
    stale: false,
    missing_fields: missingFields,
    warnings,
    symbol,
    exchange: 'Binance USD-M',
    mode: 'read_only',
  };
}

function publicStreamWarnings(extra?: string): string[] {
  return [
    'Binance USD-M public WebSocket market stream',
    ...(extra ? [extra] : []),
  ];
}

function uniqueWarnings(warnings: string[]): string[] {
  return [...new Set(warnings)];
}

function markEnvelopeStale<T>(
  current: ApiV2Envelope<T> | null,
  warnings: string[],
): ApiV2Envelope<T> | null {
  if (!current) return null;
  return {
    ...current,
    received_at: nowIso(),
    stale: true,
    warnings: uniqueWarnings([...current.warnings, ...warnings]),
  };
}

function markMarketStreamStale(
  current: MarketDataStreamState,
  error: string | null,
  warnings: string[],
): MarketDataStreamState {
  const staleWarnings = uniqueWarnings(warnings);
  return {
    ...current,
    connected: false,
    nativeConnected: false,
    ticker: markEnvelopeStale(current.ticker, staleWarnings),
    depth: markEnvelopeStale(current.depth, staleWarnings),
    trades: markEnvelopeStale(current.trades, staleWarnings),
    candles: markEnvelopeStale(current.candles, staleWarnings),
    stale: true,
    liveCandle: null,
    error,
    warnings: uniqueWarnings([...current.warnings, ...staleWarnings]),
  };
}

function mergeTickerData(
  prior: MarketTickerData | null | undefined,
  patch: Partial<MarketTickerData>,
): MarketTickerData {
  return {
    symbol: patch.symbol ?? prior?.symbol ?? 'BTCUSDT',
    last_price: patch.last_price ?? prior?.last_price ?? null,
    mark_price: patch.mark_price ?? prior?.mark_price ?? null,
    index_price: patch.index_price ?? prior?.index_price ?? null,
    change_1h: patch.change_1h ?? prior?.change_1h ?? null,
    change_4h: patch.change_4h ?? prior?.change_4h ?? null,
    change_24h: patch.change_24h ?? prior?.change_24h ?? null,
    high_24h: patch.high_24h ?? prior?.high_24h ?? null,
    low_24h: patch.low_24h ?? prior?.low_24h ?? null,
    volume_24h: patch.volume_24h ?? prior?.volume_24h ?? null,
    turnover_24h: patch.turnover_24h ?? prior?.turnover_24h ?? null,
    funding_rate: patch.funding_rate ?? prior?.funding_rate ?? null,
    next_funding: patch.next_funding ?? prior?.next_funding ?? null,
    open_interest: patch.open_interest ?? prior?.open_interest ?? null,
    open_interest_change: patch.open_interest_change ?? prior?.open_interest_change ?? null,
    bid: patch.bid ?? prior?.bid ?? null,
    ask: patch.ask ?? prior?.ask ?? null,
    spread_bps: patch.spread_bps ?? prior?.spread_bps ?? null,
  };
}

function tickerMissingFields(data: MarketTickerData): string[] {
  return [
    'last_price',
    'mark_price',
    'index_price',
    'change_24h',
    'high_24h',
    'low_24h',
    'volume_24h',
    'turnover_24h',
    'funding_rate',
    'next_funding',
    'open_interest',
    'bid',
    'ask',
    'spread_bps',
  ].filter((field) => data[field as keyof MarketTickerData] == null);
}

function normalizeDepthRows(rows: unknown): Array<[number | null, number | null]> {
  if (!Array.isArray(rows)) return [];
  const normalized: Array<[number | null, number | null]> = [];
  for (const row of rows) {
    if (!Array.isArray(row)) continue;
    const price = numeric(row[0]);
    const size = numeric(row[1]);
    if (price === null || size === null) continue;
    normalized.push([price, size]);
  }
  return normalized;
}

function envelopeSymbol(envelope: ApiV2Envelope<unknown> | null | undefined): string | null {
  const direct = envelope?.symbol;
  const data = envelope?.data;
  const dataSymbol = data && typeof data === 'object' && 'symbol' in data ? (data as { symbol?: unknown }).symbol : null;
  const symbolValue = direct ?? dataSymbol;
  return typeof symbolValue === 'string' && symbolValue.trim() ? symbolValue.trim().toUpperCase() : null;
}

function candlesTimeframe(envelope: ApiV2Envelope<MarketCandlesData> | null | undefined): string | null {
  const value = envelope?.data?.timeframe;
  return typeof value === 'string' && value.trim() ? value.trim() : null;
}

function matchesRequestedSymbol(envelope: ApiV2Envelope<unknown> | null | undefined, symbol: string): boolean {
  const nextSymbol = envelopeSymbol(envelope);
  return nextSymbol !== null && nextSymbol === symbol.toUpperCase();
}

function matchesRequestedCandles(
  envelopeValue: ApiV2Envelope<MarketCandlesData> | null | undefined,
  symbol: string,
  timeframe: string,
): boolean {
  const nextTimeframe = candlesTimeframe(envelopeValue);
  return matchesRequestedSymbol(envelopeValue, symbol) && nextTimeframe === timeframe;
}

function candleEnvelopeCanDriveRealtime(
  envelopeValue: ApiV2Envelope<MarketCandlesData> | null | undefined,
): boolean {
  return Boolean(
    envelopeValue
    && envelopeValue.stale === false
    && (envelopeValue.source_type === 'api' || envelopeValue.source_type === 'repository'),
  );
}

function nativeStreamMatchesRequest(stream: string, symbol: string, timeframe: string): boolean {
  const [streamSymbol, ...channelParts] = stream.split('@');
  const channel = channelParts.join('@');
  if (!streamSymbol || !channel) return false;
  if (streamSymbol.toUpperCase() !== symbol.toUpperCase()) return false;
  if (channel.startsWith('kline_')) {
    return channel.slice('kline_'.length) === timeframe;
  }
  return ['ticker', 'bookTicker', 'markPrice@1s', 'depth20@100ms', 'aggTrade', 'trade'].includes(channel);
}

function validNativeOhlc(candle: MarketCandle): boolean {
  const open = numeric(candle.open);
  const high = numeric(candle.high);
  const low = numeric(candle.low);
  const close = numeric(candle.close);
  if (open === null || high === null || low === null || close === null) return false;
  if (open <= 0 || high <= 0 || low <= 0 || close <= 0) return false;
  return low <= open && low <= close && high >= open && high >= close;
}

function validEnvelopeCandle(candle: MarketCandle | null | undefined): candle is MarketCandle {
  return Boolean(candle && validNativeOhlc(candle));
}

function candleIdentity(candle: MarketCandle): number | null {
  return timestampMilliseconds(candle.open_time_ms ?? candle.time);
}

function mergeStreamCandleHistory(
  prior: MarketCandle[],
  candle: MarketCandle,
  limit = 240,
): MarketCandle[] {
  const nextIdentity = candleIdentity(candle);
  const byTime = new Map<number, MarketCandle>();
  for (const row of prior) {
    if (!validEnvelopeCandle(row)) continue;
    const identity = candleIdentity(row);
    if (identity === null) continue;
    byTime.set(identity, row);
  }
  if (nextIdentity !== null) byTime.set(nextIdentity, candle);
  return [...byTime.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, row]) => row)
    .slice(-limit);
}

function handleNativeMessage(
  current: MarketDataStreamState,
  payload: Record<string, unknown>,
  symbol: string,
  timeframe: string,
): MarketDataStreamState {
  const stream = String(payload.stream ?? '');
  const data = payload.data && typeof payload.data === 'object' ? payload.data as Record<string, unknown> : {};
  if (!nativeStreamMatchesRequest(stream, symbol, timeframe)) {
    return current;
  }
  const receivedAt = nowIso();
  const endpoint = `wss://fstream.binance.com/stream ${stream}`;
  const next: MarketDataStreamState = {
    ...current,
    connected: true,
    nativeConnected: true,
    streamSource: 'binance_usdm_public_websocket',
    receivedAt,
    stale: false,
    error: null,
    warnings: publicStreamWarnings(),
  };

  if (stream.endsWith('@ticker')) {
    const tickerData = mergeTickerData(current.ticker?.data, {
      symbol,
      last_price: numeric(data.c),
      change_24h: numeric(data.P) === null ? null : Number(data.P) / 100,
      high_24h: numeric(data.h),
      low_24h: numeric(data.l),
      volume_24h: numeric(data.v),
      turnover_24h: numeric(data.q),
    });
    next.ticker = envelope<MarketTickerData>(
      symbol,
      endpoint,
      'binance_usdm_public_24h_ticker_ws',
      data.E ?? Date.now(),
      tickerData,
      publicStreamWarnings('24h ticker stream does not include signed account data'),
      tickerMissingFields(tickerData),
    );
    return next;
  }

  if (stream.includes('@markPrice')) {
    const nextFundingTime = numeric(data.T);
    const tickerData = mergeTickerData(current.ticker?.data, {
      symbol,
      mark_price: numeric(data.p),
      index_price: numeric(data.i),
      funding_rate: numeric(data.r),
      next_funding: nextFundingTime === null ? null : eventIso(nextFundingTime),
    });
    next.ticker = envelope<MarketTickerData>(
      symbol,
      endpoint,
      'binance_usdm_public_mark_price_ws',
      data.E ?? Date.now(),
      tickerData,
      publicStreamWarnings('Mark-price stream does not include signed account data'),
      tickerMissingFields(tickerData),
    );
    return next;
  }

  if (stream.endsWith('@bookTicker')) {
    const bid = numeric(data.b);
    const ask = numeric(data.a);
    const midPrice = bid !== null && ask !== null ? (bid + ask) / 2 : null;
    const spreadBps = bid !== null && ask !== null && midPrice !== null && midPrice > 0
      ? ((ask - bid) / midPrice) * 10_000
      : null;
    const tickerData = mergeTickerData(current.ticker?.data, {
      symbol,
      bid,
      ask,
      spread_bps: spreadBps,
    });
    next.ticker = envelope<MarketTickerData>(
      symbol,
      endpoint,
      'binance_usdm_public_book_ticker_ws',
      data.E ?? Date.now(),
      tickerData,
      publicStreamWarnings('Book ticker stream does not include 24h, funding, or open-interest fields'),
      tickerMissingFields(tickerData),
    );
    return next;
  }

  if (stream.includes('@depth20')) {
    const bids = normalizeDepthRows(data.bids ?? data.b);
    const asks = normalizeDepthRows(data.asks ?? data.a);
    const bestBid = bids[0]?.[0] ?? null;
    const bestAsk = asks[0]?.[0] ?? null;
    const mid = bestBid !== null && bestAsk !== null ? (bestBid + bestAsk) / 2 : null;
    next.depth = envelope<MarketDepthData>(
      symbol,
      endpoint,
      'binance_usdm_public_depth_ws',
      data.E ?? Date.now(),
      {
        symbol,
        bids,
        asks,
        spread_bps: bestBid !== null && bestAsk !== null && mid !== null && mid > 0 ? ((bestAsk - bestBid) / mid) * 10_000 : null,
        depth_type: 'binance_public_depth20_stream',
      },
      publicStreamWarnings(),
      bids.length && asks.length ? [] : ['bids', 'asks'],
    );
    return next;
  }

  if (stream.endsWith('@trade') || stream.endsWith('@aggTrade')) {
    const price = numeric(data.p);
    const size = numeric(data.q);
    if (price !== null && size !== null) {
      const trade = {
        time: eventIso(data.T ?? data.E ?? Date.now()),
        price,
        size,
        side: data.m === true ? 'sell' as const : 'buy' as const,
      };
      const prior = current.trades?.data?.trades ?? [];
      next.trades = envelope<RecentTradesData>(
        symbol,
        endpoint,
        'binance_usdm_public_trade_ws',
        data.T ?? data.E ?? Date.now(),
        { symbol, trades: [trade, ...prior].slice(0, 48) },
        publicStreamWarnings(),
      );
    }
    return next;
  }

  if (stream.includes('@kline_')) {
    const kline = data.k && typeof data.k === 'object' ? data.k as Record<string, unknown> : {};
    const openTimeMs = numeric(kline.t);
    const closeTimeMs = numeric(kline.T);
    const candle: MarketCandle = {
      time: openTimeMs === null ? undefined : Math.floor(openTimeMs / 1000),
      open_time_ms: openTimeMs ?? undefined,
      close_time_ms: closeTimeMs ?? undefined,
      open: numeric(kline.o) ?? undefined,
      high: numeric(kline.h) ?? undefined,
      low: numeric(kline.l) ?? undefined,
      close: numeric(kline.c) ?? undefined,
      volume: numeric(kline.v) ?? undefined,
      quote_volume: numeric(kline.q),
      trade_count: numeric(kline.n),
      taker_buy_base_volume: numeric(kline.V),
      taker_buy_quote_volume: numeric(kline.Q),
      is_final: kline.x === true,
      source: 'binance_usdm_public_kline_ws',
    };
    const missingFields = [
      candle.open == null ? 'open' : null,
      candle.high == null ? 'high' : null,
      candle.low == null ? 'low' : null,
      candle.close == null ? 'close' : null,
      !validNativeOhlc(candle) ? 'valid_ohlc' : null,
    ].filter((field): field is string => field !== null);
    if (!validNativeOhlc(candle)) {
      return {
        ...next,
        candles: current.candles,
        liveCandle: current.liveCandle,
        warnings: uniqueWarnings([
          ...next.warnings,
          `Invalid public kline frame ignored before chart update: ${missingFields.join(', ')}`,
        ]),
      };
    }
    next.liveCandle = candle;
    const priorStreamCandles = matchesRequestedCandles(current.candles, symbol, timeframe)
      ? current.candles?.data?.candles ?? []
      : [];
    const candleHistory = mergeStreamCandleHistory(priorStreamCandles, candle);
    next.candles = envelope<MarketCandlesData>(
      symbol,
      endpoint,
      'binance_usdm_public_kline_ws',
      data.E ?? closeTimeMs ?? Date.now(),
      { symbol, timeframe, candles: candleHistory, candle_count: candleHistory.length },
      publicStreamWarnings(candle.is_final ? 'Closed candle stream update' : 'Forming candle is display-only and is not treated as final evidence'),
      [],
    );
    return next;
  }

  return next;
}

function handleBackendSnapshotMessage(
  payload: MarketStreamMessage & Record<string, unknown>,
  safeSymbol: string,
  timeframe: string,
  current: MarketDataStreamState | null = null,
): MarketDataStreamState | null {
  const ticker = matchesRequestedSymbol(payload.ticker, safeSymbol) ? payload.ticker ?? null : null;
  const depth = matchesRequestedSymbol(payload.depth, safeSymbol) ? payload.depth ?? null : null;
  const trades = matchesRequestedSymbol(payload.trades, safeSymbol) ? payload.trades ?? null : null;
  const candles = matchesRequestedCandles(payload.candles, safeSymbol, timeframe) ? payload.candles ?? null : null;
  if (payload.ticker && ticker === null) return null;
  if (payload.depth && depth === null) return null;
  if (payload.trades && trades === null) return null;
  if (payload.candles && candles === null) return null;
  const nextTicker = payload.ticker ? ticker : current?.ticker ?? null;
  const nextDepth = payload.depth ? depth : current?.depth ?? null;
  const nextTrades = payload.trades ? trades : current?.trades ?? null;
  const nextCandles = payload.candles ? candles : current?.candles ?? null;
  const snapshotStale = Boolean(payload.stale);
  const snapshotWarnings = uniqueWarnings([
    ...(payload.warnings ?? []),
    ...(snapshotStale ? ['Market stream snapshot is stale'] : []),
  ]);
  const candleSnapshotProvided = Boolean(payload.candles);
  const candleSnapshotCurrent = candleEnvelopeCanDriveRealtime(candles);
  const streamedCandles = candleSnapshotProvided && candleSnapshotCurrent ? candles?.data?.candles ?? [] : [];
  const validStreamedCandle = streamedCandles.filter(validEnvelopeCandle).at(-1) ?? null;
  const invalidRealtimeCandles = streamedCandles.length > 0 && validStreamedCandle === null;
  const liveCandle = snapshotStale
    ? null
    : candleSnapshotProvided && !candleSnapshotCurrent
    ? null
    : validStreamedCandle ?? current?.liveCandle ?? null;
  const backendNative = payload.source === 'binance_usdm_public_websocket_adapter';
  const warnings = uniqueWarnings([
    ...snapshotWarnings,
    ...(invalidRealtimeCandles ? ['Invalid backend stream candle frame ignored before chart update'] : []),
  ]);
  return {
    connected: true,
    nativeConnected: backendNative,
    streamSource: backendNative ? 'binance_usdm_public_websocket' : 'safe_api_contract_stream',
    ticker: snapshotStale ? markEnvelopeStale(nextTicker, snapshotWarnings) : nextTicker,
    depth: snapshotStale ? markEnvelopeStale(nextDepth, snapshotWarnings) : nextDepth,
    trades: snapshotStale ? markEnvelopeStale(nextTrades, snapshotWarnings) : nextTrades,
    candles: snapshotStale ? markEnvelopeStale(nextCandles, snapshotWarnings) : nextCandles,
    liveCandle,
    streamHealth: payload.stream_health ?? null,
    receivedAt: payload.received_at ?? null,
    stale: snapshotStale,
    warnings,
    error: null,
  };
}

export function useMarketDataStream(symbol: string, intervalMs = 2000, timeframe = '1m'): MarketDataStreamState {
  const safeSymbol = safeMarketStreamSymbol(symbol);
  const safeTimeframe = safeMarketStreamTimeframe(timeframe);
  const cacheKey = marketDataStreamCacheKey(safeSymbol, safeTimeframe);
  const [state, setState] = useState<MarketDataStreamState>(() => initialCachedMarketDataStreamState(safeSymbol, safeTimeframe));

  useEffect(() => {
    if (!safeSymbol || !safeTimeframe) {
      setState({
        ...initialMarketDataStreamState(),
        error: !safeSymbol ? 'Invalid market stream symbol' : 'Invalid market stream timeframe',
        warnings: [!safeSymbol ? 'Invalid market stream symbol' : 'Invalid market stream timeframe'],
      });
      return undefined;
    }
    const targets = streamUrls(safeSymbol, intervalMs, safeTimeframe);
    if (!targets.length || typeof WebSocket === 'undefined') return undefined;
    let active = true;
    let retry: number | null = null;
    let idleTimer: number | null = null;
    let socket: WebSocket | null = null;
    let targetIndex = 0;
    const clearIdleTimer = () => {
      if (idleTimer !== null) {
        window.clearTimeout(idleTimer);
        idleTimer = null;
      }
    };
    const armIdleTimer = () => {
      clearIdleTimer();
      idleTimer = window.setTimeout(() => {
        if (
          !active
          || !socket
          || socket.readyState === WebSocket.CLOSING
          || socket.readyState === WebSocket.CLOSED
        ) return;
        setState((current) => ({
          ...markMarketStreamStale(
            current,
            'Market stream idle',
            ['Market stream endpoint was idle; rotating to the next source'],
          ),
        }));
        socket.close();
      }, streamIdleRotateMs(intervalMs));
    };

    const connect = () => {
      const target = targets[targetIndex % targets.length];
      targetIndex += 1;
      socket = new WebSocket(target);
      armIdleTimer();
      socket.onopen = () => {
        if (!active) return;
        setState((current) => ({
          ...current,
          connected: true,
          receivedAt: nowIso(),
          error: null,
          warnings: current.warnings.filter((warning) => warning !== 'Market stream unavailable'),
        }));
      };
      socket.onmessage = (event) => {
        if (!active) return;
        try {
          const payload = JSON.parse(String(event.data)) as MarketStreamMessage & Record<string, unknown>;
          if (typeof payload.stream === 'string' && payload.data && typeof payload.data === 'object') {
            clearIdleTimer();
            setState((current) => {
              const next = handleNativeMessage(current, payload, safeSymbol, safeTimeframe);
              rememberMarketDataStreamState(cacheKey, next);
              return next;
            });
            armIdleTimer();
            return;
          }
          if (payload.type !== 'market_snapshot') return;
          clearIdleTimer();
          setState((current) => {
            const next = handleBackendSnapshotMessage(payload, safeSymbol, safeTimeframe, current) ?? current;
            rememberMarketDataStreamState(cacheKey, next);
            return next;
          });
          armIdleTimer();
        } catch {
          setState((current) => ({ ...current, error: 'Market stream message could not be parsed' }));
        }
      };
      socket.onerror = () => {
        if (!active) return;
        clearIdleTimer();
        setState((current) => ({
          ...markMarketStreamStale(current, 'Market stream unavailable', ['Market stream unavailable']),
        }));
        socket?.close();
      };
      socket.onclose = () => {
        if (!active) return;
        clearIdleTimer();
        setState((current) => ({
          ...markMarketStreamStale(current, current.error, ['Reconnecting market stream']),
        }));
        retry = window.setTimeout(connect, 2500);
      };
    };

    setState(() => {
      const cached = initialCachedMarketDataStreamState(safeSymbol, safeTimeframe);
      if (cached.ticker || cached.depth || cached.trades || cached.candles) {
        return {
          ...cached,
          warnings: uniqueWarnings([...cached.warnings, `Connecting market stream for ${safeSymbol} ${safeTimeframe}`]),
        };
      }
      return {
        ...initialMarketDataStreamState(),
        warnings: [`Connecting market stream for ${safeSymbol} ${safeTimeframe}`],
      };
    });
    connect();
    return () => {
      active = false;
      clearIdleTimer();
      if (retry !== null) window.clearTimeout(retry);
      socket?.close();
    };
  }, [cacheKey, intervalMs, safeSymbol, safeTimeframe]);

  return state;
}

export const marketDataStreamTestHooks = {
  eventIso,
  handleBackendSnapshotMessage,
  handleNativeMessage,
  initialMarketDataStreamState,
  markMarketStreamStale,
  markEnvelopeStale,
  marketDataStreamCache,
  marketDataStreamCacheKey,
  nativeStreamMatchesRequest,
  safeMarketStreamSymbol,
  safeMarketStreamTimeframe,
  streamIdleRotateMs,
  streamUrls,
  timestampMilliseconds,
};
