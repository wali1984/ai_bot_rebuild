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
import { useMarketDataStream } from '../../hooks/useMarketDataStream';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { formatAge, formatCompact, formatPrice } from '../../lib/tradeFormatters';
import type { ApiV2Envelope, MarketCandle, MarketCandlesData, MarketIndicatorsData } from '../../types/apiV2';
import type { ValidatedDataEnvelope } from '../../types/dataContract';
import { MissingDataState, TradePanel } from './TradeShared';

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '4h', '1d', '1w'] as const;

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

function latestIndicatorValue(points: { value?: number | null }[] | undefined): number | null {
  for (let index = (points?.length ?? 0) - 1; index >= 0; index -= 1) {
    const value = finite(points?.[index]?.value);
    if (value !== null) return value;
  }
  return null;
}

function vwapFromCandles(candles: ChartCandle[]): number | null {
  let notional = 0;
  let volumeSum = 0;
  for (const candle of candles) {
    const close = finite(candle.close);
    const volume = finite(candle.volume);
    if (close === null || volume === null || volume <= 0) continue;
    notional += close * volume;
    volumeSum += volume;
  }
  return volumeSum > 0 ? notional / volumeSum : null;
}

function compactIndicator(value: number | null, digits = 2): string {
  if (value === null) return '—';
  return value.toLocaleString('en-US', { maximumFractionDigits: digits });
}

function cssVar(name: string, fallback: string): string {
  return getComputedStyle(document.documentElement).getPropertyValue(name).trim() || fallback;
}

function currentMarketSourceType(sourceType: ApiV2Envelope<unknown>['source_type'] | undefined): boolean {
  return sourceType === 'websocket'
    || sourceType === 'api'
    || sourceType === 'repository'
    || sourceType === 'redis_live';
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
    mode: envelope.mode as ApiV2Envelope<T>['mode'],
  };
}

export function candleEnvelopeCanDriveTradingChart(
  envelope: ApiV2Envelope<MarketCandlesData> | null | undefined,
  symbol?: string,
  timeframe?: string,
): boolean {
  const basicValid = Boolean(
    envelope
    && envelope.stale === false
    && currentMarketSourceType(envelope.source_type)
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
  if (!envelope) return 'Indicator source connecting';
  if (envelope.source_type === 'unavailable') return 'Indicator source connecting';
  if (envelope.stale) return 'Stale indicator source';
  if (envelope.source_type === 'static_payload') return 'Static indicators withheld';
  return (envelope.data?.indicator_count ?? 0) > 0 ? 'Indicators available' : 'Indicators connecting';
}

export function TradingChartPanel({ symbol }: { symbol: string }): JSX.Element {
  const [timeframe, setTimeframe] = useState<(typeof TIMEFRAMES)[number]>('1m');
  const [chartKey, setChartKey] = useState(0);
  const marketStream = useMarketDataStream(symbol, 2_000, timeframe);
  const candleUrl = `/api/v2/market/${symbol}/candles?timeframe=${encodeURIComponent(timeframe)}`;
  const indicatorUrl = `/api/v2/market/${symbol}/indicators?timeframe=${encodeURIComponent(timeframe)}`;
  const candleResource = useRealtimeResource<MarketCandlesData>({
    url: candleUrl,
    source: candleUrl,
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 15_000,
    mode: 'read_only',
  });
  const indicatorResource = useRealtimeResource<MarketIndicatorsData>({
    url: indicatorUrl,
    source: indicatorUrl,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });
  const candleEnvelope = useMemo(
    () => resourceEnvelopeToApi(candleResource.envelope, candleUrl),
    [candleResource.envelope, candleUrl],
  );
  const indicatorEnvelope = useMemo(
    () => resourceEnvelopeToApi(indicatorResource.envelope, indicatorUrl),
    [indicatorResource.envelope, indicatorUrl],
  );
  const loading = candleResource.loading && !candleEnvelope;
  const error = candleResource.error;
  const shellRef = useRef<HTMLElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const fittedOnceRef = useRef(false);
  const typedCandlesAreRealtime = candleEnvelopeCanDriveTradingChart(candleEnvelope, symbol, timeframe);
  const streamCandlesAreRealtime = candleEnvelopeCanDriveTradingChart(marketStream.candles, symbol, timeframe);
  const typedRawCandles = typedCandlesAreRealtime ? candleEnvelope?.data?.candles ?? [] : [];
  const streamRawCandles = streamCandlesAreRealtime ? marketStream.candles?.data?.candles ?? [] : [];
  const rawCandles = typedRawCandles.length >= 20
    ? typedRawCandles
    : streamRawCandles.length >= 20
      ? streamRawCandles
      : typedRawCandles.length
        ? typedRawCandles
        : streamRawCandles;
  const activeCandleEnvelope = typedRawCandles.length >= 20 || (typedRawCandles.length > 0 && streamRawCandles.length < 20)
    ? candleEnvelope
    : streamRawCandles.length > 0
      ? marketStream.candles
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
  const hasResourceCandleFeed = typedCandlesAreRealtime && typedRawCandles.length > 0 && candleResource.envelope.freshness_status === 'fresh';
  const chartReady = candles.length > 0 && (typedCandlesAreRealtime || streamCandlesAreRealtime || hasLiveCandle);
  const activeLagMs = activeCandleEnvelope?.lag_ms;
  const ageSeconds = activeLagMs === null || activeLagMs === undefined
    ? null
    : Math.round(activeLagMs / 1000);
  const sourcePosture = candleEnvelope?.source_type === 'static_payload'
    ? 'Fallback candles withheld'
    : candleEnvelope?.stale
    ? 'Stale candles withheld'
    : hasNativeLiveCandle
      ? 'Public market stream + candle source'
    : hasLiveCandle
      ? 'Live market stream + candle source'
    : hasResourceCandleFeed
      ? 'WebSocket candle source'
    : currentMarketSourceType(candleEnvelope?.source_type)
        ? 'Current candle source'
      : 'Connecting stream';
  const liveCandleLabel = marketStream.liveCandle
    ? marketStream.liveCandle.is_final === false
      ? 'Forming display-only'
      : 'Closed stream update'
    : hasResourceCandleFeed
      ? 'WebSocket candle feed'
      : 'Waiting for stream';
  const indicatorPosture = indicatorSourceLabel(indicatorEnvelope);
  const indicatorTitle = indicatorEnvelope?.warnings?.join(' ') || 'Indicator source has not returned yet.';
  const indicatorData = indicatorEnvelope?.data;
  const indicatorSnapshot = indicatorData?.indicator_snapshot;
  const ema20Value = latestIndicatorValue(indicatorData?.ema20);
  const ema50Value = latestIndicatorValue(indicatorData?.ema50);
  const vwapValue = useMemo(() => vwapFromCandles(displayRawCandles), [displayRawCandles]);
  const rsiValue = finite(indicatorSnapshot?.rsi_14);
  const macdValue = finite(indicatorSnapshot?.macd);

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
          <span title={indicatorTitle}>MA20 {formatPrice(ema20Value)}</span>
          <span title={indicatorTitle}>EMA50 {formatPrice(ema50Value)}</span>
          <span title="Volume-weighted average derived from displayed candle volume.">VWAP {formatPrice(vwapValue)}</span>
          <span title={indicatorTitle}>RSI {compactIndicator(rsiValue, 1)}</span>
          <span title={indicatorTitle}>MACD {compactIndicator(macdValue, 4)}</span>
        </div>

        <div className="trade-chart-canvas-wrap">
          <div ref={canvasRef} className="trade-chart-canvas" key={chartKey} />
          {loading ? <div className="trade-chart-loading">Connecting chart stream</div> : null}
          {!loading && (!chartReady || error) ? (
            <MissingDataState
              title="Candles connecting"
              detail={error ? 'Candle stream is reconnecting through the shared market resource.' : activeCandleEnvelope?.warnings?.[0] ?? 'A current market data source is required before the chart can be treated as current evidence.'}
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
