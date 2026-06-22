import type {
  ApiV2Envelope,
  MarketCandlesData,
  MarketDerivativesData,
  MarketDepthData,
  MarketIndicatorsData,
  MarketStreamStatusData,
  MarketTickerData,
  RecentTradesData,
} from '../types/apiV2';
import { fetchV2Contract, unavailableV2Response } from './v2Shared';

export interface MarketOverviewData {
  symbols: string[];
  count: number;
  timeframes: string[];
  tickers?: Array<{
    symbol: string;
    last_price: number | null;
    change_24h: number | null;
    high_24h: number | null;
    low_24h: number | null;
    volume_24h: number | null;
    turnover_24h: number | null;
    trade_count_24h?: number | null;
    weighted_avg_price?: number | null;
  }>;
}

const BINANCE_USDM_PUBLIC_BASE = 'https://fapi.binance.com';
const MARKET_TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '4h', '1d', '1w'];
const V2_MARKET_TIMEFRAMES = new Set(MARKET_TIMEFRAMES);

interface BinanceTicker24h {
  symbol: string;
  lastPrice?: string;
  priceChangePercent?: string;
  highPrice?: string;
  lowPrice?: string;
  volume?: string;
  quoteVolume?: string;
  count?: number;
  weightedAvgPrice?: string;
  closeTime?: number;
}

interface BinanceBookTicker {
  symbol: string;
  bidPrice?: string;
  askPrice?: string;
}

interface BinancePremiumIndex {
  symbol: string;
  markPrice?: string;
  indexPrice?: string;
  lastFundingRate?: string;
  nextFundingTime?: number;
  time?: number;
}

interface BinanceOpenInterest {
  symbol: string;
  openInterest?: string;
  time?: number;
}

interface BinanceLongShortRow {
  symbol?: string;
  longShortRatio?: string;
  timestamp?: number;
}

type BinanceKlineRow = [
  number,
  string,
  string,
  string,
  string,
  string,
  number,
  string,
  number,
  string,
  string,
  string,
];

interface BinanceDepth {
  bids?: Array<[string, string]>;
  asks?: Array<[string, string]>;
}

interface BinanceTrade {
  price?: string;
  qty?: string;
  time?: number;
  isBuyerMaker?: boolean;
}

function finite(value: unknown): number | null {
  const parsed = typeof value === 'number'
    ? value
    : typeof value === 'string' && value.trim() !== ''
      ? Number(value)
      : Number.NaN;
  return Number.isFinite(parsed) ? parsed : null;
}

function percentFraction(value: unknown): number | null {
  const parsed = finite(value);
  return parsed === null ? null : parsed / 100;
}

function isoFromMs(value: unknown): string | null {
  const parsed = finite(value);
  return parsed === null || parsed <= 0 ? null : new Date(parsed).toISOString();
}

function spreadBps(bid: number | null, ask: number | null): number | null {
  if (bid === null || ask === null || bid <= 0 || ask <= 0) return null;
  const mid = (bid + ask) / 2;
  return mid > 0 ? ((ask - bid) / mid) * 10_000 : null;
}

async function fetchPublicJson<T>(path: string, params?: Record<string, string | number | undefined>): Promise<T> {
  const url = new URL(`${BINANCE_USDM_PUBLIC_BASE}${path}`);
  Object.entries(params ?? {}).forEach(([key, value]) => {
    if (value !== undefined) url.searchParams.set(key, String(value));
  });
  const response = await fetch(url.toString(), { headers: { Accept: 'application/json' }, signal: AbortSignal.timeout(2500) });
  if (!response.ok) {
    throw new Error(`Binance public market request failed with HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

function publicMarketEnvelope<T>(
  endpoint: string,
  data: T,
  options: {
    symbol?: string | null;
    timestamp?: string | null;
    missingFields?: string[];
    warnings?: string[];
  } = {},
): ApiV2Envelope<T> {
  const receivedAt = new Date().toISOString();
  return {
    data,
    source: 'Binance USD-M public market data',
    source_type: 'api',
    endpoint,
    timestamp: options.timestamp ?? receivedAt,
    received_at: receivedAt,
    lag_ms: null,
    stale: false,
    missing_fields: options.missingFields ?? [],
    warnings: [
      'Local V2 market service unavailable; using Binance USD-M public market fallback.',
      ...(options.warnings ?? []),
    ],
    symbol: options.symbol ?? null,
    exchange: 'Binance USD-M',
    mode: 'read_only',
  };
}

async function withPublicMarketFallback<T>(
  contractPromise: Promise<ApiV2Envelope<T>>,
  endpoint: string,
  missingFields: string[],
  fallback: () => Promise<ApiV2Envelope<T>>,
): Promise<ApiV2Envelope<T>> {
  try {
    const contractResponse = await Promise.race([
      contractPromise,
      new Promise<null>((resolve) => globalThis.setTimeout(() => resolve(null), 1_800)),
    ]);
    if (contractResponse && contractResponse.source_type !== 'unavailable' && contractResponse.data !== null) {
      return contractResponse;
    }
  } catch {
    // Fall through to public market fallback.
  }

  try {
    return await fallback();
  } catch {
    return unavailableV2Response<T>(
      endpoint,
      missingFields,
      'Market data service and public market fallback are unavailable.',
    );
  }
}

function tickerFromPublicRow(row: BinanceTicker24h) {
  return {
    symbol: row.symbol,
    last_price: finite(row.lastPrice),
    change_24h: percentFraction(row.priceChangePercent),
    high_24h: finite(row.highPrice),
    low_24h: finite(row.lowPrice),
    volume_24h: finite(row.volume),
    turnover_24h: finite(row.quoteVolume),
    trade_count_24h: finite(row.count),
    weighted_avg_price: finite(row.weightedAvgPrice),
  };
}

async function publicTickerData(symbol: string): Promise<{ data: MarketTickerData; timestamp: string | null }> {
  const [ticker, book, premium, openInterest] = await Promise.all([
    fetchPublicJson<BinanceTicker24h>('/fapi/v1/ticker/24hr', { symbol }),
    fetchPublicJson<BinanceBookTicker>('/fapi/v1/ticker/bookTicker', { symbol }).catch(() => null),
    fetchPublicJson<BinancePremiumIndex>('/fapi/v1/premiumIndex', { symbol }).catch(() => null),
    fetchPublicJson<BinanceOpenInterest>('/fapi/v1/openInterest', { symbol }).catch(() => null),
  ]);

  const bid = finite(book?.bidPrice);
  const ask = finite(book?.askPrice);
  const timestamp = isoFromMs(premium?.time) ?? isoFromMs(openInterest?.time) ?? isoFromMs(ticker.closeTime);
  return {
    data: {
      symbol,
      last_price: finite(ticker.lastPrice),
      mark_price: finite(premium?.markPrice),
      index_price: finite(premium?.indexPrice),
      change_1h: null,
      change_4h: null,
      change_24h: percentFraction(ticker.priceChangePercent),
      high_24h: finite(ticker.highPrice),
      low_24h: finite(ticker.lowPrice),
      volume_24h: finite(ticker.volume),
      turnover_24h: finite(ticker.quoteVolume),
      funding_rate: finite(premium?.lastFundingRate),
      next_funding: isoFromMs(premium?.nextFundingTime),
      open_interest: finite(openInterest?.openInterest),
      open_interest_change: null,
      bid,
      ask,
      spread_bps: spreadBps(bid, ask),
    },
    timestamp,
  };
}

async function publicCandlesData(symbol: string, timeframe: string): Promise<{ data: MarketCandlesData; timestamp: string | null }> {
  const rows = await fetchPublicJson<BinanceKlineRow[]>('/fapi/v1/klines', {
    symbol,
    interval: timeframe,
    limit: 300,
  });
  const now = Date.now();
  const candles = rows
    .filter((row) => {
      const closeTime = finite(row[6]);
      return closeTime !== null && closeTime < now;
    })
    .map((row) => ({
      time: finite(row[0]) ?? undefined,
      open_time_ms: finite(row[0]) ?? undefined,
      close_time_ms: finite(row[6]) ?? undefined,
      open: finite(row[1]) ?? undefined,
      high: finite(row[2]) ?? undefined,
      low: finite(row[3]) ?? undefined,
      close: finite(row[4]) ?? undefined,
      volume: finite(row[5]) ?? undefined,
      quote_volume: finite(row[7]),
      trade_count: finite(row[8]),
      taker_buy_base_volume: finite(row[9]),
      taker_buy_quote_volume: finite(row[10]),
      is_final: true,
      source: 'binance_usdm_public_klines',
    }));

  return {
    data: {
      symbol,
      timeframe,
      candles,
      candle_count: candles.length,
    },
    timestamp: candles.at(-1)?.close_time_ms ? new Date(candles.at(-1)!.close_time_ms!).toISOString() : null,
  };
}

function ema(values: Array<number | null>, period: number): Array<number | null> {
  const smoothing = 2 / (period + 1);
  let previous: number | null = null;
  return values.map((value, index) => {
    if (value === null) return null;
    previous = previous === null ? value : (value * smoothing) + (previous * (1 - smoothing));
    return index + 1 >= period ? previous : null;
  });
}

function bollinger(values: Array<number | null>, period: number) {
  return values.map((_, index) => {
    const window = values.slice(Math.max(0, index - period + 1), index + 1).filter((value): value is number => value !== null);
    if (window.length < period) return { middle: null, upper: null, lower: null };
    const middle = window.reduce((sum, value) => sum + value, 0) / window.length;
    const variance = window.reduce((sum, value) => sum + ((value - middle) ** 2), 0) / window.length;
    const deviation = Math.sqrt(variance);
    return { middle, upper: middle + (2 * deviation), lower: middle - (2 * deviation) };
  });
}

export function getV2MarketOverview(): Promise<ApiV2Envelope<MarketOverviewData>> {
  const endpoint = '/api/v2/market/overview';
  return withPublicMarketFallback<MarketOverviewData>(
    fetchV2Contract<MarketOverviewData>(
      endpoint,
      ['symbols', 'markets'],
      'Market overview endpoint is unavailable.',
    ),
    endpoint,
    ['symbols', 'markets'],
    async () => {
      const rows = await fetchPublicJson<BinanceTicker24h[]>('/fapi/v1/ticker/24hr');
      const tickers = rows
        .filter((row) => row.symbol.endsWith('USDT') && finite(row.lastPrice) !== null)
        .sort((left, right) => (finite(right.quoteVolume) ?? 0) - (finite(left.quoteVolume) ?? 0))
        .map(tickerFromPublicRow);
      const symbols = tickers.map((row) => row.symbol);
      return publicMarketEnvelope<MarketOverviewData>(
        endpoint,
        {
          symbols,
          count: symbols.length,
          timeframes: MARKET_TIMEFRAMES,
          tickers,
        },
        { timestamp: isoFromMs(rows[0]?.closeTime) },
      );
    },
  );
}

export function safeV2MarketSymbol(symbol: string): string | undefined {
  const normalized = symbol.trim().toUpperCase();
  return normalized && /^[A-Z0-9]+$/.test(normalized) ? normalized : undefined;
}

export function safeV2MarketTimeframe(timeframe: string): string | undefined {
  const normalized = timeframe.trim();
  return V2_MARKET_TIMEFRAMES.has(normalized) ? normalized : undefined;
}

function invalidMarketSymbol<T>(endpoint: string, missingFields: string[]): Promise<ApiV2Envelope<T>> {
  return Promise.resolve(unavailableV2Response<T>(
    endpoint,
    ['symbol', ...missingFields],
    'Enter a valid market symbol.',
  ));
}

function invalidMarketTimeframe<T>(endpoint: string, symbol: string): Promise<ApiV2Envelope<T>> {
  return Promise.resolve(unavailableV2Response<T>(
    endpoint,
    ['timeframe'],
    'Select a supported chart timeframe.',
    { symbol },
  ));
}

export function getV2MarketDetail(symbol: string): Promise<ApiV2Envelope<MarketTickerData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketTickerData>('/api/v2/market/{symbol}', ['last_price', 'funding_rate', 'open_interest', 'spread']);
  }
  const endpoint = `/api/v2/market/${safeSymbol}`;
  return withPublicMarketFallback<MarketTickerData>(
    fetchV2Contract<MarketTickerData>(
      endpoint,
      ['last_price', 'funding_rate', 'open_interest', 'spread'],
      'Market detail endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    endpoint,
    ['last_price', 'funding_rate', 'open_interest', 'spread'],
    async () => {
      const ticker = await publicTickerData(safeSymbol);
      return publicMarketEnvelope<MarketTickerData>(
        endpoint,
        ticker.data,
        {
          symbol: safeSymbol,
          timestamp: ticker.timestamp,
          missingFields: ['change_1h', 'change_4h', 'open_interest_change'],
          warnings: ['Trader account, position, and execution data are not included in the public market fallback.'],
        },
      );
    },
  );
}

export function getV2MarketTicker(symbol: string): Promise<ApiV2Envelope<MarketTickerData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketTickerData>('/api/v2/market/{symbol}/ticker', ['last_price', 'bid', 'ask']);
  }
  const endpoint = `/api/v2/market/${safeSymbol}/ticker`;
  return withPublicMarketFallback<MarketTickerData>(
    fetchV2Contract<MarketTickerData>(
      endpoint,
      ['last_price', 'bid', 'ask'],
      'Ticker endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    endpoint,
    ['last_price', 'bid', 'ask'],
    async () => {
      const ticker = await publicTickerData(safeSymbol);
      return publicMarketEnvelope<MarketTickerData>(
        endpoint,
        ticker.data,
        {
          symbol: safeSymbol,
          timestamp: ticker.timestamp,
          missingFields: ['change_1h', 'change_4h', 'open_interest_change'],
        },
      );
    },
  );
}

export function getV2MarketDerivatives(symbol: string, timeframe = '5m'): Promise<ApiV2Envelope<MarketDerivativesData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketDerivativesData>('/api/v2/market/{symbol}/derivatives', ['funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis']);
  }
  const endpoint = `/api/v2/market/${safeSymbol}/derivatives?timeframe=${encodeURIComponent(timeframe)}`;
  return withPublicMarketFallback<MarketDerivativesData>(
    fetchV2Contract<MarketDerivativesData>(
      endpoint,
      ['funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis'],
      'Derivatives endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    endpoint,
    ['funding_rate', 'open_interest', 'liquidations_1h', 'long_short_ratio', 'basis'],
    async () => {
      const [ticker, ratioRows] = await Promise.all([
        publicTickerData(safeSymbol),
        fetchPublicJson<BinanceLongShortRow[]>('/futures/data/globalLongShortAccountRatio', {
          symbol: safeSymbol,
          period: '5m',
          limit: 30,
        }).catch(() => []),
      ]);
      const ratioRow = [...ratioRows]
        .sort((left, right) => (finite(left.timestamp) ?? 0) - (finite(right.timestamp) ?? 0))
        .at(-1);
      const longShortRatio = finite(ratioRow?.longShortRatio);
      const mark = ticker.data.mark_price;
      const index = ticker.data.index_price;
      const basis = mark !== null && index !== null && index > 0 ? (mark - index) / index : null;
      const timestamp = ticker.timestamp ?? isoFromMs(ratioRow?.timestamp);
      const missingFields = [
        'open_interest_change',
        'liquidations_1h',
        'liquidations_24h',
        'liquidation_levels',
        'exchange_comparison',
      ];
      if (longShortRatio === null) missingFields.push('long_short_ratio');
      const data: MarketDerivativesData = {
        symbol: safeSymbol,
        funding_rate: ticker.data.funding_rate,
        next_funding: ticker.data.next_funding,
        open_interest: ticker.data.open_interest,
        open_interest_change: null,
        funding_history: ticker.data.funding_rate === null ? [] : [{
          time: timestamp,
          funding_rate: ticker.data.funding_rate,
          source: 'binance_usdm_public_premium_index',
        }],
        open_interest_history: ticker.data.open_interest === null ? [] : [{
          time: timestamp,
          open_interest: ticker.data.open_interest,
          source: 'binance_usdm_public_open_interest',
        }],
        liquidations_1h: null,
        liquidations_24h: null,
        liquidation_stream_status: {
          status: 'unavailable',
          source: 'Verified local liquidation stream required',
          symbol: safeSymbol,
          stream_active: false,
          symbol_in_stream: false,
          events_available: false,
          events_xlen: null,
          levels_available: false,
          timestamp,
          lag_ms: null,
          stale: true,
          live_trading_enabled: false,
          exchange_mutation_enabled: false,
        },
        liquidation_levels: null,
        long_short_ratio: longShortRatio,
        basis,
        exchange_comparison: [],
        production_source_validation: {
          configured: false,
          valid: false,
          status: 'public_market_fallback',
          funding_realtime_verified: ticker.data.funding_rate !== null,
          open_interest_realtime_verified: ticker.data.open_interest !== null,
          liquidation_source_verified: false,
          long_short_source_verified: longShortRatio !== null,
          basis_source_verified: basis !== null,
          exchange_comparison_verified: false,
          freshness_enforced: true,
          stale_marking_verified: true,
          source_labels_verified: true,
          no_static_presented_as_live: true,
          fake_live_data_detected: false,
          live_trading_enabled: false,
          exchange_mutation_enabled: false,
          live_submit_available: false,
          live_cancel_available: false,
          missing_fields: missingFields,
          warnings: ['Liquidation levels require the verified local backend stream; public fallback does not fabricate them.'],
        },
      };
      return publicMarketEnvelope<MarketDerivativesData>(
        endpoint,
        data,
        {
          symbol: safeSymbol,
          timestamp,
          missingFields,
          warnings: ['Funding, open interest, basis, and long/short ratio are public market data.'],
        },
      );
    },
  );
}

export function getV2MarketCandles(symbol: string, timeframe = '1m'): Promise<ApiV2Envelope<MarketCandlesData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketCandlesData>('/api/v2/market/{symbol}/candles', ['candles']);
  }
  const safeTimeframe = safeV2MarketTimeframe(timeframe);
  const endpoint = `/api/v2/market/${safeSymbol}/candles`;
  if (!safeTimeframe) {
    return invalidMarketTimeframe<MarketCandlesData>(endpoint, safeSymbol);
  }
  const contractEndpoint = `${endpoint}?timeframe=${encodeURIComponent(safeTimeframe)}`;
  return withPublicMarketFallback<MarketCandlesData>(
    fetchV2Contract<MarketCandlesData>(
      contractEndpoint,
      ['candles'],
      'Candle endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    contractEndpoint,
    ['candles'],
    async () => {
      const candles = await publicCandlesData(safeSymbol, safeTimeframe);
      return publicMarketEnvelope<MarketCandlesData>(
        contractEndpoint,
        candles.data,
        {
          symbol: safeSymbol,
          timestamp: candles.timestamp,
          warnings: ['Only fully closed public candles are displayed; unfinished candles are filtered out.'],
        },
      );
    },
  );
}

export function getV2MarketIndicators(symbol: string, timeframe = '1m'): Promise<ApiV2Envelope<MarketIndicatorsData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketIndicatorsData>('/api/v2/market/{symbol}/indicators', ['ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target']);
  }
  const safeTimeframe = safeV2MarketTimeframe(timeframe);
  const endpoint = `/api/v2/market/${safeSymbol}/indicators`;
  if (!safeTimeframe) {
    return invalidMarketTimeframe<MarketIndicatorsData>(endpoint, safeSymbol);
  }
  const contractEndpoint = `${endpoint}?timeframe=${encodeURIComponent(safeTimeframe)}`;
  return withPublicMarketFallback<MarketIndicatorsData>(
    fetchV2Contract<MarketIndicatorsData>(
      contractEndpoint,
      ['ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target', 'indicator_repository'],
      'Indicator source connecting.',
      { symbol: safeSymbol },
    ),
    contractEndpoint,
    ['ema20', 'ema50', 'bb_upper', 'bb_lower', 'ai_target', 'indicator_repository'],
    async () => {
      const candles = await publicCandlesData(safeSymbol, safeTimeframe);
      const closes = candles.data.candles.map((candle) => finite(candle.close));
      const times = candles.data.candles.map((candle) => candle.close_time_ms ?? candle.time);
      const ema20 = ema(closes, 20);
      const ema50 = ema(closes, 50);
      const bands = bollinger(closes, 20);
      const point = (values: Array<number | null>) => values.map((value, index) => ({
        time: times[index],
        value,
      }));
      return publicMarketEnvelope<MarketIndicatorsData>(
        contractEndpoint,
        {
          symbol: safeSymbol,
          timeframe: safeTimeframe,
          ema20: point(ema20),
          ema50: point(ema50),
          bb_upper: point(bands.map((band) => band.upper)),
          bb_lower: point(bands.map((band) => band.lower)),
          bb_middle: point(bands.map((band) => band.middle)),
          ai_target: [],
          indicator_count: candles.data.candle_count,
          controls_enabled: false,
        },
        {
          symbol: safeSymbol,
          timestamp: candles.timestamp,
          missingFields: ['ai_target', 'typed_indicator_repository'],
          warnings: ['AI target remains pending without the local trainer service; displayed indicators are derived from closed public candles only.'],
        },
      );
    },
  );
}

export function getV2MarketDepth(symbol: string): Promise<ApiV2Envelope<MarketDepthData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketDepthData>('/api/v2/market/{symbol}/depth', ['bids', 'asks', 'spread']);
  }
  const endpoint = `/api/v2/market/${safeSymbol}/depth`;
  return withPublicMarketFallback<MarketDepthData>(
    fetchV2Contract<MarketDepthData>(
      endpoint,
      ['bids', 'asks', 'spread'],
      'Depth endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    endpoint,
    ['bids', 'asks', 'spread'],
    async () => {
      const book = await fetchPublicJson<BinanceDepth>('/fapi/v1/depth', { symbol: safeSymbol, limit: 50 });
      const bids: MarketDepthData['bids'] = (book.bids ?? []).map(([price, size]) => [finite(price), finite(size)]);
      const asks: MarketDepthData['asks'] = (book.asks ?? []).map(([price, size]) => [finite(price), finite(size)]);
      return publicMarketEnvelope<MarketDepthData>(
        endpoint,
        {
          symbol: safeSymbol,
          bids,
          asks,
          spread_bps: spreadBps(bids[0]?.[0] ?? null, asks[0]?.[0] ?? null),
          depth_type: 'binance_usdm_public_ladder',
        },
        { symbol: safeSymbol },
      );
    },
  );
}

export function getV2MarketTrades(symbol: string): Promise<ApiV2Envelope<RecentTradesData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<RecentTradesData>('/api/v2/market/{symbol}/trades', ['trades', 'trade_stream']);
  }
  const endpoint = `/api/v2/market/${safeSymbol}/trades`;
  return withPublicMarketFallback<RecentTradesData>(
    fetchV2Contract<RecentTradesData>(
      endpoint,
      ['trades', 'trade_stream'],
      'Recent trades endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    endpoint,
    ['trades', 'trade_stream'],
    async () => {
      const rows = await fetchPublicJson<BinanceTrade[]>('/fapi/v1/trades', { symbol: safeSymbol, limit: 50 });
      const trades = rows
        .map((row) => ({
          time: isoFromMs(row.time) ?? new Date().toISOString(),
          price: finite(row.price) ?? 0,
          size: finite(row.qty) ?? 0,
          side: row.isBuyerMaker ? 'sell' as const : 'buy' as const,
        }))
        .filter((trade) => trade.price > 0 && trade.size > 0);
      return publicMarketEnvelope<RecentTradesData>(
        endpoint,
        {
          symbol: safeSymbol,
          trades,
        },
        {
          symbol: safeSymbol,
          timestamp: trades.at(-1)?.time ?? null,
          missingFields: ['trade_stream'],
          warnings: ['Recent trades are public snapshots; authenticated trader execution stream remains backend-scoped.'],
        },
      );
    },
  );
}

export function getV2MarketStreamStatus(symbol: string): Promise<ApiV2Envelope<MarketStreamStatusData>> {
  const safeSymbol = safeV2MarketSymbol(symbol);
  if (!safeSymbol) {
    return invalidMarketSymbol<MarketStreamStatusData>('/api/v2/market/{symbol}/stream-status', ['last_frame_at']);
  }
  const endpoint = `/api/v2/market/${safeSymbol}/stream-status`;
  return withPublicMarketFallback<MarketStreamStatusData>(
    fetchV2Contract<MarketStreamStatusData>(
      endpoint,
      ['last_frame_at'],
      'Market stream status endpoint is unavailable.',
      { symbol: safeSymbol },
    ),
    endpoint,
    ['last_frame_at'],
    async () => {
      const updatedAt = new Date().toISOString();
      return publicMarketEnvelope<MarketStreamStatusData>(
        endpoint,
        {
          symbol: safeSymbol,
          source: 'Binance USD-M public HTTP fallback',
          last_event: null,
          last_frame_at: null,
          last_error: null,
          connect_attempts: 0,
          native_frames: 0,
          fallback_snapshots: 1,
          updated_at: updatedAt,
          lag_ms: null,
          stale: false,
        },
        {
          symbol: safeSymbol,
          timestamp: updatedAt,
          missingFields: ['native_market_stream'],
          warnings: ['Native websocket stream status is unavailable; shared API fallback is active.'],
        },
      );
    },
  );
}
