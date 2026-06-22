import { useEffect, useMemo, useRef, useState } from 'react';
import { Maximize2, RotateCcw } from 'lucide-react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { getV2MarketCandles, getV2MarketIndicators } from '../../api/v2Market';
import { useMarketDataStream } from '../../hooks/useMarketDataStream';
import { formatAge, formatCompact, formatPrice } from '../../lib/tradeFormatters';
import type { ApiV2Envelope, MarketCandle, MarketCandlesData, MarketIndicatorsData } from '../../types/apiV2';
import { MissingDataState, TradePanel } from './TradeShared';

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '4h', '1d', '1w'] as const;
const BINANCE_USDM_KLINES_URL = 'https://fapi.binance.com/fapi/v1/klines';

interface ChartCandle {
  time?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  is_final?: boolean;
  source?: string;
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function klineNumber(value: unknown): number | null {
  if (typeof value === 'number') return finite(value);
  if (typeof value === 'string' && value.trim()) return finite(Number(value));
  return null;
}

function timestampSeconds(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.floor(value > 1_000_000_000_000 ? value / 1000 : value);
  }
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return timestampSeconds(numeric);
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
  }
  return null;
}

function toUtc(value: unknown): UTCTimestamp | null {
  const n = timestampSeconds(value);
  return n === null || n <= 0 ? null : n as UTCTimestamp;
}

function candleTime(candle: ChartCandle): number | null {
  return timestampSeconds(candle.time) ?? timestampSeconds((candle as MarketCandle).open_time_ms);
}

function validOhlc(open: number, high: number, low: number, close: number): boolean {
  if (open <= 0 || high <= 0 || low <= 0 || close <= 0) return false;
  return low <= open && low <= close && high >= open && high >= close;
}

function publicRestKlineEnvelope(symbol: string, timeframe: string, rows: unknown): ApiV2Envelope<MarketCandlesData> | null {
  if (!Array.isArray(rows)) return null;
  const now = Date.now();
  const candles = rows
    .map((row): MarketCandle | null => {
      if (!Array.isArray(row)) return null;
      const openTime = klineNumber(row[0]);
      const open = klineNumber(row[1]);
      const high = klineNumber(row[2]);
      const low = klineNumber(row[3]);
      const close = klineNumber(row[4]);
      const volume = klineNumber(row[5]);
      const closeTime = klineNumber(row[6]);
      if (openTime === null || open === null || high === null || low === null || close === null || !validOhlc(open, high, low, close)) return null;
      return {
        time: Math.floor(openTime / 1000),
        open_time_ms: openTime,
        close_time_ms: closeTime ?? undefined,
        open,
        high,
        low,
        close,
        volume: volume ?? undefined,
        quote_volume: klineNumber(row[7]),
        trade_count: klineNumber(row[8]),
        taker_buy_base_volume: klineNumber(row[9]),
        taker_buy_quote_volume: klineNumber(row[10]),
        is_final: closeTime === null ? undefined : closeTime <= now,
        source: 'binance_usdm_public_rest_poll',
      };
    })
    .filter((row): row is MarketCandle => row !== null);
  if (!candles.length) return null;
  const latest = candles.at(-1);
  const latestEventTime = latest?.close_time_ms ?? latest?.open_time_ms ?? now;
  return {
    data: { symbol, timeframe, candles, candle_count: candles.length },
    source: 'Public REST candle source',
    source_type: 'api',
    endpoint: `${BINANCE_USDM_KLINES_URL}?symbol=${symbol}&interval=${timeframe}&limit=240`,
    timestamp: new Date(latestEventTime).toISOString(),
    received_at: new Date(now).toISOString(),
    lag_ms: Math.max(0, now - latestEventTime),
    stale: false,
    missing_fields: [],
    warnings: ['Public REST candle source. Latest candle can be forming and display-only.'],
    symbol,
    exchange: 'Binance USD-M',
    mode: 'read_only',
  };
}

function normalizeCandles(candles: ChartCandle[] | undefined): CandlestickData<UTCTimestamp>[] {
  return (candles ?? [])
    .map((candle) => {
      const time = toUtc(candleTime(candle));
      const open = finite(candle.open);
      const high = finite(candle.high);
      const low = finite(candle.low);
      const close = finite(candle.close);
      if (time === null || open === null || high === null || low === null || close === null) return null;
      if (!validOhlc(open, high, low, close)) return null;
      return { time, open, high, low, close };
    })
    .filter((row): row is CandlestickData<UTCTimestamp> => row !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function normalizeVolume(candles: ChartCandle[] | undefined): HistogramData<UTCTimestamp>[] {
  return (candles ?? [])
    .map((candle): HistogramData<UTCTimestamp> | null => {
      const time = toUtc(candleTime(candle));
      const value = finite(candle.volume);
      const open = finite(candle.open);
      const close = finite(candle.close);
      if (time === null || value === null) return null;
      return {
        time,
        value,
        color: open !== null && close !== null && close >= open ? 'rgba(18, 184, 134, 0.34)' : 'rgba(255, 107, 107, 0.34)',
      };
    })
    .filter((row): row is HistogramData<UTCTimestamp> => row !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

export function candleEnvelopeCanDriveTradingChart(
  envelope: ApiV2Envelope<MarketCandlesData> | null | undefined,
  symbol?: string,
  timeframe?: string,
): boolean {
  const basicValid = Boolean(
    envelope
    && envelope.stale === false
    && (envelope.source_type === 'api' || envelope.source_type === 'repository')
    && Array.isArray(envelope.data?.candles)
  );
  if (!basicValid) return false;
  if (symbol) {
    const envelopeSymbol = envelope?.symbol ?? envelope?.data?.symbol;
    if (typeof envelopeSymbol !== 'string' || envelopeSymbol.toUpperCase() !== symbol.toUpperCase()) return false;
  }
  if (timeframe) {
    const envelopeTimeframe = envelope?.data?.timeframe;
    if (typeof envelopeTimeframe !== 'string' || envelopeTimeframe !== timeframe) return false;
  }
  return true;
}

export function indicatorSourceLabel(envelope: ApiV2Envelope<MarketIndicatorsData> | null): string {
  if (!envelope) return 'Indicator source unavailable';
  if (envelope.source_type === 'unavailable') return 'Indicator source unavailable';
  if (envelope.stale) return 'Stale indicator source';
  if (envelope.source_type === 'static_payload') return 'Static indicators withheld';
  return envelope.data?.controls_enabled ? 'Indicators available' : 'Indicators unavailable';
}

export function TradingChartPanel({ symbol }: { symbol: string }): JSX.Element {
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>('1m');
  const [chartKey, setChartKey] = useState(0);
  const [candleEnvelope, setCandleEnvelope] = useState<ApiV2Envelope<MarketCandlesData> | null>(null);
  const [publicRestEnvelope, setPublicRestEnvelope] = useState<ApiV2Envelope<MarketCandlesData> | null>(null);
  const [indicatorEnvelope, setIndicatorEnvelope] = useState<ApiV2Envelope<MarketIndicatorsData> | null>(null);
  const marketStream = useMarketDataStream(symbol, 2_000, timeframe);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const shellRef = useRef<HTMLElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const fittedOnceRef = useRef(false);
  const typedCandlesAreRealtime = candleEnvelopeCanDriveTradingChart(candleEnvelope, symbol, timeframe);
  const publicRestCandlesAreRealtime = candleEnvelopeCanDriveTradingChart(publicRestEnvelope, symbol, timeframe);
  const typedRawCandles = typedCandlesAreRealtime ? candleEnvelope?.data?.candles ?? [] : [];
  const publicRestRawCandles = publicRestCandlesAreRealtime ? publicRestEnvelope?.data?.candles ?? [] : [];
  const rawCandles = typedRawCandles.length >= 20
    ? typedRawCandles
    : publicRestRawCandles.length >= 20
      ? publicRestRawCandles
      : typedRawCandles.length
        ? typedRawCandles
        : publicRestRawCandles;
  const activeCandleEnvelope = typedRawCandles.length >= 20 || (typedRawCandles.length > 0 && publicRestRawCandles.length < 20)
    ? candleEnvelope
    : publicRestRawCandles.length > 0
      ? publicRestEnvelope
      : candleEnvelope;
  const displayRawCandles = useMemo(() => {
    const base = [...rawCandles];
    const live = marketStream.liveCandle as MarketCandle | null;
    if (!live || live.time == null || live.open == null || live.high == null || live.low == null || live.close == null) {
      return base;
    }
    if (!validOhlc(live.open, live.high, live.low, live.close)) return base;
    const liveTime = candleTime(live);
    if (liveTime === null) return base;
    const withoutDuplicate = base.filter((row) => {
      const rowTime = candleTime(row);
      return rowTime !== liveTime;
    });
    return [...withoutDuplicate, { ...live, time: liveTime }];
  }, [marketStream.liveCandle, rawCandles]);
  const candles = useMemo(() => normalizeCandles(displayRawCandles), [displayRawCandles]);
  const volume = useMemo(() => normalizeVolume(displayRawCandles), [displayRawCandles]);
  const latest = candles[candles.length - 1];
  const hasLiveCandle = marketStream.liveCandle !== null && marketStream.stale === false;
  const hasNativeLiveCandle = marketStream.streamSource === 'binance_usdm_public_websocket' && hasLiveCandle;
  const chartReady = candles.length > 0 && (typedCandlesAreRealtime || publicRestCandlesAreRealtime || hasLiveCandle);
  const activeLagMs = activeCandleEnvelope?.lag_ms;
  const ageSeconds = activeLagMs === null || activeLagMs === undefined
    ? null
    : Math.round(activeLagMs / 1000);
  const sourcePosture = candleEnvelope?.source_type === 'static_payload' && !publicRestCandlesAreRealtime
    ? 'Fallback candles withheld'
    : candleEnvelope?.stale && !publicRestCandlesAreRealtime
    ? 'Stale candles withheld'
    : hasNativeLiveCandle
      ? 'Public market stream + candle source'
    : hasLiveCandle
      ? 'Live market stream + candle source'
    : publicRestCandlesAreRealtime
      ? 'Current public exchange candles'
      : candleEnvelope?.source_type === 'api' || candleEnvelope?.source_type === 'repository'
        ? 'Current candle source'
      : 'Data source unavailable';
  const liveCandleLabel = marketStream.liveCandle
    ? marketStream.liveCandle.is_final === false
      ? 'Forming display-only'
      : 'Closed stream update'
    : 'Waiting for stream';
  const indicatorPosture = indicatorSourceLabel(indicatorEnvelope);
  const indicatorTitle = indicatorEnvelope?.warnings?.join(' ') || 'Indicator source has not returned yet.';

  useEffect(() => {
    let active = true;
    setLoading(true);

    async function load(): Promise<void> {
      try {
        const [nextCandles, nextIndicators] = await Promise.all([
          getV2MarketCandles(symbol, timeframe),
          getV2MarketIndicators(symbol, timeframe),
        ]);
        if (!active) return;
        setCandleEnvelope(nextCandles);
        setIndicatorEnvelope(nextIndicators);
        setError(null);
      } catch (err) {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'Candle endpoint unavailable');
      } finally {
        if (active) setLoading(false);
      }
    }

    void load();
    const interval = window.setInterval(load, 3_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [symbol, timeframe]);

  // REST is backup only: fetch from Binance public klines only when the
  // backend candle source has fewer than 20 candles or is stale/absent.
  // Backend source is always tried first (see CLAUDE.md "Unified Binance data").
  const backendCandlesSufficient = typedCandlesAreRealtime && typedRawCandles.length >= 20;

  useEffect(() => {
    if (backendCandlesSufficient) {
      // Backend source is healthy — do not make a direct Binance REST request.
      setPublicRestEnvelope(null);
      return undefined;
    }
    let active = true;
    setPublicRestEnvelope(null);

    async function loadPublicRestCandles(): Promise<void> {
      try {
        const params = new URLSearchParams({ symbol: symbol.toUpperCase(), interval: timeframe, limit: '240' });
        // REST backup reason: backend candle source absent or insufficient.
        const response = await fetch(`${BINANCE_USDM_KLINES_URL}?${params.toString()}`);
        if (!response.ok) throw new Error(`Binance public kline fallback failed: ${response.status}`);
        const rows = await response.json();
        if (active) setPublicRestEnvelope(publicRestKlineEnvelope(symbol.toUpperCase(), timeframe, rows));
      } catch {
        if (active) setPublicRestEnvelope(null);
      }
    }

    void loadPublicRestCandles();
    const interval = window.setInterval(loadPublicRestCandles, 5_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [symbol, timeframe, backendCandlesSufficient]);

  useEffect(() => {
    fittedOnceRef.current = false;
  }, [symbol, timeframe]);

  useEffect(() => {
    const container = canvasRef.current;
    if (!container) return undefined;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: 430,
      layout: {
        background: { type: ColorType.Solid, color: cssVar('--chart-bg', '#071018') },
        textColor: cssVar('--text-secondary', '#9ab0c6'),
      },
      grid: {
        vertLines: { color: 'rgba(130, 150, 179, 0.16)' },
        horzLines: { color: 'rgba(130, 150, 179, 0.16)' },
      },
      rightPriceScale: { borderColor: 'rgba(130, 150, 179, 0.22)', scaleMargins: { top: 0.08, bottom: 0.24 } },
      timeScale: { borderColor: 'rgba(130, 150, 179, 0.22)', timeVisible: true },
      crosshair: {
        vertLine: { color: 'rgba(220, 164, 62, 0.55)' },
        horzLine: { color: 'rgba(220, 164, 62, 0.55)' },
      },
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#12b886',
      downColor: '#ff6b6b',
      borderVisible: false,
      wickUpColor: '#12b886',
      wickDownColor: '#ff6b6b',
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    const resize = () => chart.resize(container.clientWidth, 430);
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();
    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, [chartKey]);

  useEffect(() => {
    candleSeriesRef.current?.setData(candles);
    volumeSeriesRef.current?.setData(volume);
    if (!fittedOnceRef.current && candles.length) {
      chartRef.current?.timeScale().fitContent();
      fittedOnceRef.current = true;
    }
  }, [candles, volume]);

  function resetView(): void {
    chartRef.current?.timeScale().fitContent();
    setChartKey((value) => value + 1);
  }

  function fullscreen(): void {
    void shellRef.current?.requestFullscreen?.();
  }

  return (
    <section ref={shellRef} className="trade-chart-shell trade-mobile-panel" data-mobile-panel="chart" data-testid="chart-panel">
      <TradePanel
        title="Candlestick Chart"
        kicker={`${symbol} chart`}
        actions={(
          <>
            <span className="trade-chart-age">{formatAge(ageSeconds)}</span>
            <button type="button" className="trade-icon-button" onClick={resetView} title="Reset view" aria-label="Reset chart view">
              <RotateCcw size={16} />
            </button>
            <button type="button" className="trade-icon-button" onClick={fullscreen} title="Fullscreen" aria-label="Open chart fullscreen">
              <Maximize2 size={16} />
            </button>
          </>
        )}
      >
        <div className="trade-chart-toolbar" aria-label="Chart timeframes">
          {TIMEFRAMES.map((item) => (
            <button
              type="button"
              className={timeframe === item ? 'is-active' : ''}
              onClick={() => setTimeframe(item)}
              key={item}
            >
              {item}
            </button>
          ))}
          <span title={indicatorTitle}>MA unavailable</span>
          <span title={indicatorTitle}>EMA unavailable</span>
          <span title={indicatorTitle}>VWAP unavailable</span>
          <span title={indicatorTitle}>RSI unavailable</span>
          <span title={indicatorTitle}>MACD unavailable</span>
        </div>

        <div className="trade-chart-canvas-wrap">
          <div ref={canvasRef} className="trade-chart-canvas" key={chartKey} />
          {loading ? <div className="trade-chart-loading">Loading chart data</div> : null}
          {!loading && (!chartReady || error) ? (
            <MissingDataState
              title="Candles unavailable"
              detail={error ? 'Candle data is unavailable from the current market source.' : activeCandleEnvelope?.warnings?.[0] ?? 'A current market data source is required before the chart can be treated as current evidence.'}
              endpoint={activeCandleEnvelope?.endpoint ?? '/api/v2/market/{symbol}/candles'}
              compact
            />
          ) : null}
        </div>

        <div className="trade-chart-stats">
          <div><span>Last close</span><strong>{formatPrice(latest?.close)}</strong></div>
          <div><span>Candles</span><strong>{candles.length.toLocaleString('en-US')}</strong></div>
          <div><span>Volume bars</span><strong>{formatCompact(volume.length)}</strong></div>
          <div><span>Source</span><strong title="Current market data source and stale/fallback state">{sourcePosture}</strong></div>
          <div><span>Indicators</span><strong title="Indicator availability for this symbol and timeframe">{indicatorPosture}</strong></div>
          <div><span>Candle update</span><strong title="Unfinished candles are displayed only and are not treated as final evidence.">{liveCandleLabel}</strong></div>
        </div>
      </TradePanel>
    </section>
  );
}
