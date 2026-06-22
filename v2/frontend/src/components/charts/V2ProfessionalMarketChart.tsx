import { useEffect, useMemo, useRef, useState } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  LineSeries,
  LineStyle,
  createChart,
  type CandlestickData,
  type HistogramData,
  type IChartApi,
  type ISeriesApi,
  type LineData,
  type UTCTimestamp,
} from 'lightweight-charts';
import { ageClass, fmtAge, usePayloadFile } from '../../hooks/usePayloadFile';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import {
  formatBps,
  formatCompactNumber,
  formatPercent,
} from '../../data/allTimeframeSignals';
import type { MarketCandlesData } from '../../types/apiV2';

export const V2_PROFESSIONAL_MARKET_CHART_BASE_PATH = '/operator_runtime/v2_professional_market_chart/latest';

interface ChartCandle {
  time?: number;
  open_time_ms?: number;
  close_time_ms?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  quote_volume?: number | null;
  trade_count?: number | null;
  taker_buy_base_volume?: number | null;
  taker_buy_quote_volume?: number | null;
}

interface ChartLinePoint {
  time?: number;
  value?: number | null;
}

interface ChartVolumePoint extends ChartLinePoint {
  color?: string;
}

interface ChartSignal {
  status?: string;
  selected_action?: string | null;
  confidence_calibrated?: number | null;
  expected_move_bps?: number | null;
  expected_move_after_cost_bps?: number | null;
  price_target?: number | null;
  price_target_after_cost?: number | null;
  target_line_value?: number | null;
  prediction_id?: string | null;
  signal_id?: string | null;
  source_prediction_key?: string | null;
  source_signal_key?: string | null;
  age_seconds?: number | null;
  live_gate?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
}

interface ChartTa {
  status?: string;
  source_redis_key?: string;
  generated_utc?: string;
  library_used?: string;
  trainer_consumable?: boolean;
  no_zero_fill?: boolean;
  indicator_count?: number;
  indicators?: Record<string, unknown>;
}

interface ProfessionalChartPayload {
  schema_version?: string;
  status?: string;
  blocker?: string | null;
  generated_est?: string;
  generated_utc?: string;
  symbol?: string;
  timeframe?: string;
  chart_source?: string;
  source_type?: string;
  source_redis_key?: string;
  source_event_age_seconds?: number | null;
  source_stale_after_seconds?: number | null;
  candle_count?: number;
  latest_candle?: ChartCandle | null;
  candles?: ChartCandle[];
  volume?: ChartVolumePoint[];
  overlays?: Record<string, ChartLinePoint[] | undefined>;
  ta?: ChartTa | null;
  signal?: ChartSignal | null;
  lineage?: Record<string, unknown>;
  live_gate?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
}

interface ProfessionalManifestRow {
  path?: string;
  status?: string;
  symbol?: string;
  timeframe?: string;
  candle_count?: number;
  latest_close?: number | null;
  signal_action?: string | null;
  price_target_after_cost?: number | null;
  source_type?: string;
  source_redis_key?: string;
  source_event_age_seconds?: number | null;
}

interface ProfessionalManifestPayload {
  status?: string;
  generated_est?: string;
  generated_utc?: string;
  symbols?: string[];
  symbols_count?: number;
  timeframes?: string[];
  timeframe?: string;
  total_payload_count?: number;
  current_payload_count?: number;
  current_symbol_all_timeframe_count?: number;
  non_current_payloads?: ProfessionalManifestRow[];
  status_counts?: Record<string, number>;
  payloads?: Record<string, ProfessionalManifestRow>;
}

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function normalizeSymbols(symbols: string[]): string[] {
  const seen = new Set<string>();
  return symbols
    .map((symbol) => symbol.trim().toUpperCase())
    .filter((symbol) => {
      if (!symbol || seen.has(symbol)) return false;
      seen.add(symbol);
      return true;
    })
    .sort((a, b) => a.localeCompare(b));
}

function normalizeTimeframes(timeframes: string[]): string[] {
  const preferred = ['1m', '5m', '15m', '1h', '4h'];
  const unique = [...new Set(timeframes.map((tf) => tf.trim()).filter(Boolean))];
  return unique.sort((a, b) => {
    const ai = preferred.indexOf(a);
    const bi = preferred.indexOf(b);
    return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi) || a.localeCompare(b);
  });
}

function payloadKey(symbol: string, timeframe: string): string {
  return `${symbol}:${timeframe}`;
}

function statusText(value: string | null | undefined, fallback = 'loading'): string {
  if (!value) return fallback;
  const text = value
    .replaceAll('blocked_human_only', 'archived human-only packet')
    .replaceAll('LIVE BLOCKED', 'archived packet blocked')
    .replaceAll('live_symbols=[]', 'no live symbols')
    .replaceAll('execution_live_symbols=[]', 'no execution symbols')
    .replaceAll('MISSING_EVIDENCE', 'Connecting stream')
    .replaceAll('MISSING_SOURCE', 'Connecting stream');
  if (text === 'CURRENT') return 'Current';
  if (/^[A-Z0-9_:-]+$/.test(text) || text.includes('_')) {
    return text.replace(/[_-]+/g, ' ').toLowerCase().replace(/^./u, (char) => char.toUpperCase());
  }
  return text;
}

function evidenceText(value: unknown, fallback = 'Unavailable'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'Available' : 'Unavailable';
  if (typeof value === 'number' && Number.isFinite(value)) return value.toLocaleString('en-US');
  if (typeof value === 'string') return statusText(value, fallback);
  if (Array.isArray(value)) return value.length > 0 ? `${value.length.toLocaleString('en-US')} items` : fallback;
  return 'Available';
}

function marketChartPath(symbol: string, timeframe: string): string {
  return `${V2_PROFESSIONAL_MARKET_CHART_BASE_PATH}/${symbol}_${timeframe}_chart.json`;
}

function money(value: unknown): string {
  const n = finite(value);
  if (n === null) return 'Connecting stream';
  if (Math.abs(n) >= 1000) return `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  if (Math.abs(n) >= 1) return `$${n.toLocaleString('en-US', { maximumFractionDigits: 4 })}`;
  return `$${n.toLocaleString('en-US', { maximumFractionDigits: 8 })}`;
}

function compactNumber(value: unknown): string {
  const n = finite(value);
  if (n === null) return 'Connecting stream';
  return n.toLocaleString('en-US', { maximumFractionDigits: 6 });
}

function cssVar(name: string, fallback: string): string {
  const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
  return value || fallback;
}

function toUtcTimestamp(value: unknown): UTCTimestamp | null {
  const n = finite(value);
  if (n === null || n <= 0) return null;
  return Math.floor(n) as UTCTimestamp;
}

function normalizeCandles(rawCandles: ChartCandle[] | undefined): CandlestickData<UTCTimestamp>[] {
  return (rawCandles ?? [])
    .map((candle) => {
      const time = toUtcTimestamp(candle.time);
      const open = finite(candle.open);
      const high = finite(candle.high);
      const low = finite(candle.low);
      const close = finite(candle.close);
      if (time === null || open === null || high === null || low === null || close === null) return null;
      if (open <= 0 || high <= 0 || low <= 0 || close <= 0) return null;
      return { time, open, high, low, close };
    })
    .filter((row): row is CandlestickData<UTCTimestamp> => row !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function normalizeLine(points: ChartLinePoint[] | undefined): LineData<UTCTimestamp>[] {
  return (points ?? [])
    .map((point) => {
      const time = toUtcTimestamp(point.time);
      const value = finite(point.value);
      if (time === null || value === null) return null;
      return { time, value };
    })
    .filter((row): row is LineData<UTCTimestamp> => row !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function normalizeVolume(points: ChartVolumePoint[] | undefined, candles: CandlestickData<UTCTimestamp>[]): HistogramData<UTCTimestamp>[] {
  const candleByTime = new Map(candles.map((candle) => [Number(candle.time), candle]));
  const rows: HistogramData<UTCTimestamp>[] = [];
  for (const point of points ?? []) {
    const time = toUtcTimestamp(point.time);
    const value = finite(point.value);
    if (time === null || value === null) continue;
    const candle = candleByTime.get(Number(time));
    const color = point.color ?? (candle && candle.close >= candle.open ? 'rgba(45, 223, 123, 0.34)' : 'rgba(242, 85, 90, 0.34)');
    rows.push({ time, value, color });
  }
  return rows.sort((a, b) => Number(a.time) - Number(b.time));
}

function normalizeCandleVolume(rawCandles: ChartCandle[] | undefined): HistogramData<UTCTimestamp>[] {
  return (rawCandles ?? [])
    .map((candle): HistogramData<UTCTimestamp> | null => {
      const time = toUtcTimestamp(candle.time);
      const value = finite(candle.volume);
      const open = finite(candle.open);
      const close = finite(candle.close);
      if (time === null || value === null) return null;
      return {
        time,
        value,
        color: open !== null && close !== null && close >= open ? 'rgba(45, 223, 123, 0.34)' : 'rgba(242, 85, 90, 0.34)',
      };
    })
    .filter((row): row is HistogramData<UTCTimestamp> => row !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function indicator(indicators: Record<string, unknown> | undefined, key: string): number | null {
  return finite(indicators?.[key]);
}

export function V2ProfessionalMarketChart({
  defaultSymbol = 'BTCUSDT',
  defaultTimeframe = '1m',
  height = 360,
}: {
  defaultSymbol?: string;
  defaultTimeframe?: string;
  height?: number;
}): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const sma20SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ema20SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const ema50SeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbUpperSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const bbLowerSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const targetSeriesRef = useRef<ISeriesApi<'Line'> | null>(null);
  const [selectedSymbol, setSelectedSymbol] = useState('');
  const [selectedTimeframe, setSelectedTimeframe] = useState('');
  const { data: manifest, error: manifestError, ageSeconds: manifestAge } = usePayloadFile<ProfessionalManifestPayload>(
    `${V2_PROFESSIONAL_MARKET_CHART_BASE_PATH}/operator_dashboard_payload.json`,
    5_000,
  );

  const symbols = useMemo(() => normalizeSymbols(manifest?.symbols ?? []), [manifest?.symbols]);
  const timeframes = useMemo(
    () => normalizeTimeframes(manifest?.timeframes ?? [manifest?.timeframe ?? defaultTimeframe]),
    [defaultTimeframe, manifest?.timeframe, manifest?.timeframes],
  );
  const resolvedSymbol = symbols.includes(selectedSymbol)
    ? selectedSymbol
    : symbols.includes(defaultSymbol.toUpperCase()) ? defaultSymbol.toUpperCase() : symbols[0] ?? defaultSymbol.toUpperCase();
  const resolvedTimeframe = timeframes.includes(selectedTimeframe)
    ? selectedTimeframe
    : timeframes.includes(defaultTimeframe) ? defaultTimeframe : timeframes[0] ?? defaultTimeframe;
  const resolvedPath = marketChartPath(resolvedSymbol, resolvedTimeframe);
  const { data: chartPayload, error: chartError, ageSeconds: chartAge } = usePayloadFile<ProfessionalChartPayload>(
    resolvedPath,
    2_000,
  );
  const {
    envelope: typedCandlesEnvelope,
    error: typedCandlesError,
  } = useRealtimeResource<MarketCandlesData>({
    url: `/api/v2/market/${resolvedSymbol}/candles?timeframe=${resolvedTimeframe}`,
    source: '/api/v2/market/{symbol}/candles',
    pollIntervalMs: 2_000,
    staleThresholdMs: 10_000,
    mode: 'read_only',
    initialFetch: true,
    httpFallback: true,
  });

  const currentPayloadCount = finite(manifest?.current_payload_count) ?? 0;
  const totalPayloadCount = finite(manifest?.total_payload_count) ?? Object.keys(manifest?.payloads ?? {}).length;
  const typedRawCandles = typedCandlesEnvelope?.data?.candles ?? [];
  const typedCandles = useMemo(() => normalizeCandles(typedRawCandles), [typedRawCandles]);
  const fallbackCandles = useMemo(() => normalizeCandles(chartPayload?.candles), [chartPayload?.candles]);
  const useTypedCandles = typedCandlesEnvelope?.source_type !== 'unavailable' && typedCandles.length > 0;
  const chartCurrent = useTypedCandles || chartPayload?.status === 'CURRENT';
  const candles = useTypedCandles ? typedCandles : (chartCurrent ? fallbackCandles : []);
  const typedVolume = useMemo(() => normalizeCandleVolume(typedRawCandles), [typedRawCandles]);
  const fallbackVolume = useMemo(() => normalizeVolume(chartPayload?.volume, candles), [candles, chartPayload?.volume]);
  const volume = useTypedCandles ? typedVolume : fallbackVolume;
  const overlays = chartPayload?.overlays ?? {};
  const sma20 = useMemo(() => normalizeLine(overlays.sma20), [overlays.sma20]);
  const ema20 = useMemo(() => normalizeLine(overlays.ema20), [overlays.ema20]);
  const ema50 = useMemo(() => normalizeLine(overlays.ema50), [overlays.ema50]);
  const bbUpper = useMemo(() => normalizeLine(overlays.bb_upper), [overlays.bb_upper]);
  const bbLower = useMemo(() => normalizeLine(overlays.bb_lower), [overlays.bb_lower]);
  const targetLine = useMemo(() => normalizeLine(overlays.price_target), [overlays.price_target]);
  const typedLatestCandle = typedRawCandles[typedRawCandles.length - 1] ?? null;
  const latestCandle = useTypedCandles
    ? typedLatestCandle
    : chartPayload?.latest_candle ?? chartPayload?.candles?.[chartPayload.candles.length - 1] ?? null;
  const taIndicators = chartPayload?.ta?.indicators;
  const rsi14 = indicator(taIndicators, 'rsi_14');
  const macd = indicator(taIndicators, 'macd');
  const macdSignal = indicator(taIndicators, 'macd_signal');
  const typedAgeSeconds = typedCandlesEnvelope?.lag_ms === null || typedCandlesEnvelope?.lag_ms === undefined
    ? null
    : Math.round(typedCandlesEnvelope.lag_ms / 1000);
  const effectiveAge = typedAgeSeconds ?? chartAge;
  const candleSourceType = typedCandlesEnvelope?.source_type ?? chartPayload?.source_type ?? 'unavailable';
  const chartStatusLabel = chartCurrent
    ? (useTypedCandles ? 'Current candle source' : 'Fallback chart data current')
    : 'Chart stream connecting';
  const chartSourceLabel = candleSourceType === 'static_payload'
    ? 'Fallback candle data'
    : candleSourceType === 'api' || candleSourceType === 'repository'
      ? 'Current candle source'
      : 'Connecting stream';
  const selectedSignalLabel = statusText(chartPayload?.signal?.selected_action, 'Connecting stream');
  const emptyReason = chartError
      ? 'Chart stream is connecting to the current market source.'
    : typedCandlesError
      ? 'Candle source is connecting.'
    : !chartCurrent
      ? typedCandlesEnvelope?.warnings?.[0] ? 'Current candle source is connecting.' : chartPayload?.blocker ? statusText(chartPayload.blocker, 'Chart stream connecting') : `${resolvedSymbol} ${resolvedTimeframe} chart stream connecting`
      : candles.length === 0
        ? 'Chart data is current but contains no valid positive candles'
        : null;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    const chart = createChart(container, {
      width: container.clientWidth,
      height,
      layout: {
        background: { type: ColorType.Solid, color: cssVar('--chart-bg', '#0f141c') },
        textColor: cssVar('--text-mid', '#aab6c5'),
      },
      grid: {
        vertLines: { color: 'rgba(107, 121, 138, 0.18)' },
        horzLines: { color: 'rgba(107, 121, 138, 0.18)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(107, 121, 138, 0.24)',
        scaleMargins: { top: 0.08, bottom: 0.24 },
      },
      timeScale: {
        borderColor: 'rgba(107, 121, 138, 0.24)',
        timeVisible: true,
        secondsVisible: false,
      },
      crosshair: {
        vertLine: { color: 'rgba(245, 165, 36, 0.55)', width: 1 },
        horzLine: { color: 'rgba(245, 165, 36, 0.55)', width: 1 },
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#2ddf7b',
      downColor: '#f2555a',
      borderVisible: false,
      wickUpColor: '#2ddf7b',
      wickDownColor: '#f2555a',
    });
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: 'rgba(107, 121, 138, 0.32)',
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volumeSeries.priceScale().applyOptions({
      scaleMargins: { top: 0.78, bottom: 0 },
    });
    const sma20Series = chart.addSeries(LineSeries, {
      color: '#f5a524',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'SMA20',
    });
    const ema20Series = chart.addSeries(LineSeries, {
      color: '#2f8cff',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'EMA20',
    });
    const ema50Series = chart.addSeries(LineSeries, {
      color: '#b685ff',
      lineWidth: 2,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'EMA50',
    });
    const bbUpperSeries = chart.addSeries(LineSeries, {
      color: 'rgba(170, 182, 197, 0.58)',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'BB upper',
    });
    const bbLowerSeries = chart.addSeries(LineSeries, {
      color: 'rgba(170, 182, 197, 0.58)',
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      title: 'BB lower',
    });
    const targetSeries = chart.addSeries(LineSeries, {
      color: '#ff5ea8',
      lineWidth: 2,
      lineStyle: LineStyle.Dashed,
      priceLineVisible: true,
      lastValueVisible: true,
      title: 'AI target',
    });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    sma20SeriesRef.current = sma20Series;
    ema20SeriesRef.current = ema20Series;
    ema50SeriesRef.current = ema50Series;
    bbUpperSeriesRef.current = bbUpperSeries;
    bbLowerSeriesRef.current = bbLowerSeries;
    targetSeriesRef.current = targetSeries;

    const resize = () => {
      chart.resize(container.clientWidth, height);
    };
    const observer = new ResizeObserver(resize);
    observer.observe(container);
    resize();

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
      sma20SeriesRef.current = null;
      ema20SeriesRef.current = null;
      ema50SeriesRef.current = null;
      bbUpperSeriesRef.current = null;
      bbLowerSeriesRef.current = null;
      targetSeriesRef.current = null;
    };
  }, [height]);

  useEffect(() => {
    candleSeriesRef.current?.setData(candles);
    volumeSeriesRef.current?.setData(volume);
    sma20SeriesRef.current?.setData(sma20);
    ema20SeriesRef.current?.setData(ema20);
    ema50SeriesRef.current?.setData(ema50);
    bbUpperSeriesRef.current?.setData(bbUpper);
    bbLowerSeriesRef.current?.setData(bbLower);
    targetSeriesRef.current?.setData(targetLine);
    if (candles.length > 0) {
      chartRef.current?.timeScale().fitContent();
    }
  }, [bbLower, bbUpper, candles, ema20, ema50, sma20, targetLine, volume]);

  const evidenceRows = [
    ['Market source', chartSourceLabel],
    ['Manifest status', manifestError ? 'Manifest unavailable' : evidenceText(manifest?.status, 'Manifest pending')],
    ['Chart fallback status', chartError ? 'Fallback chart unavailable' : evidenceText(chartPayload?.status, 'Fallback chart pending')],
    ['Typed candle source', evidenceText(typedCandlesEnvelope?.source_type, 'Candle source connecting')],
    ['Typed candle endpoint', typedCandlesEnvelope?.endpoint ? 'Typed market candle API' : 'Candle API connecting'],
    ['Typed candle warnings', typedCandlesEnvelope?.warnings?.length ? `${typedCandlesEnvelope.warnings.length.toLocaleString('en-US')} warnings` : 'No active warnings'],
    ['Source freshness', fmtAge(effectiveAge)],
    ['Observed candles', candles.length.toLocaleString('en-US')],
    ['Overlay coverage', `SMA20 ${sma20.length.toLocaleString('en-US')} · EMA20 ${ema20.length.toLocaleString('en-US')} · EMA50 ${ema50.length.toLocaleString('en-US')} · target ${targetLine.length.toLocaleString('en-US')}`],
    ['Indicator evidence', chartPayload?.ta ? 'Indicator metadata available' : 'Indicator metadata pending'],
    ['Signal evidence', chartPayload?.signal ? 'Signal metadata available' : 'Signal metadata pending'],
    ['Trading posture', 'Live market chart'],
  ] as const;

  return (
    <div
      className="v2-professional-market-chart"
      data-testid="v2-professional-market-chart"
      data-symbol={resolvedSymbol}
      data-timeframe={resolvedTimeframe}
      data-source-type={candleSourceType}
    >
      <div className="v2-professional-market-chart__toolbar">
        <div className="symbols-chart-selector symbols-chart-selector--compact">
          <div>
            <span>Professional OHLCV chart</span>
            <strong>{resolvedSymbol} / {resolvedTimeframe}</strong>
            <small>
              {symbols.length.toLocaleString('en-US')} symbols / {currentPayloadCount.toLocaleString('en-US')} of {totalPayloadCount.toLocaleString('en-US')} market sources current / refreshed {fmtAge(manifestAge)}
            </small>
          </div>
          <select
            aria-label="Select professional chart symbol"
            value={resolvedSymbol}
            onChange={(event) => setSelectedSymbol(event.target.value)}
          >
            {symbols.map((symbol) => (
              <option value={symbol} key={symbol}>{symbol}</option>
            ))}
          </select>
          <select
            aria-label="Select professional chart timeframe"
            value={resolvedTimeframe}
            onChange={(event) => setSelectedTimeframe(event.target.value)}
          >
            {timeframes.map((timeframe) => (
              <option value={timeframe} key={timeframe}>{timeframe}</option>
            ))}
          </select>
        </div>
        <div className="v2-professional-market-chart__chips">
          <span className={`chip solid-${chartCurrent ? 'ok' : 'warn'}`}>{chartStatusLabel}</span>
          <span className={`chip solid-${ageClass(effectiveAge, 30)}`}>{fmtAge(effectiveAge)}</span>
          <span className="chip solid-paper">{chartSourceLabel}</span>
          <span className="chip solid-paper">Live chart</span>
        </div>
      </div>

      <div className="v2-professional-market-chart__layout">
        <div className="v2-professional-market-chart__canvas-shell">
          <div
            ref={containerRef}
            className="v2-professional-market-chart__canvas"
            style={{ minHeight: height }}
          />
          {emptyReason ? (
            <div className="v2-professional-market-chart__empty" role="status">
              Chart stream connecting: {emptyReason}
            </div>
          ) : null}
        </div>
        <aside className="v2-professional-market-chart__metrics" aria-label="Selected professional chart metrics">
          <div>
            <span>Latest close</span>
            <strong>{money(latestCandle?.close)}</strong>
            <small>Source freshness {fmtAge(effectiveAge)}</small>
          </div>
          <div>
            <span>Range / volume</span>
            <strong>{money(latestCandle?.high)} / {money(latestCandle?.low)}</strong>
            <small>base {compactNumber(latestCandle?.volume)} · quote {compactNumber(latestCandle?.quote_volume)} · trades {compactNumber(latestCandle?.trade_count)}</small>
          </div>
          <div>
            <span>Technical analysis</span>
            <strong>RSI {compactNumber(rsi14)}</strong>
            <small>MACD {compactNumber(macd)} / signal {compactNumber(macdSignal)} · {chartPayload?.ta?.library_used ? 'Indicator method available' : 'Indicator method pending'}</small>
          </div>
          <div>
            <span>AI signal</span>
            <strong>{selectedSignalLabel}</strong>
            <small>
              confidence {formatPercent(chartPayload?.signal?.confidence_calibrated)} · age {fmtAge(chartPayload?.signal?.age_seconds ?? null)}
            </small>
          </div>
          <div>
            <span>Expected move</span>
            <strong>{formatBps(chartPayload?.signal?.expected_move_after_cost_bps)}</strong>
            <small>target {formatCompactNumber(chartPayload?.signal?.price_target_after_cost ?? chartPayload?.signal?.price_target)}</small>
          </div>
          <div>
            <span>Observed candles</span>
            <strong>{candles.length.toLocaleString('en-US')}</strong>
            <small>
              volume bars {volume.length.toLocaleString('en-US')} · SMA20 {sma20.length.toLocaleString('en-US')} · EMA50 {ema50.length.toLocaleString('en-US')} · data integrity {chartPayload?.ta?.no_zero_fill === true ? 'confirmed' : 'not confirmed'}
            </small>
          </div>
        </aside>
      </div>

      <details className="v2-professional-market-chart__source">
        <summary>Data evidence</summary>
        <div className="v2-professional-market-chart__evidence-grid">
          {evidenceRows.map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{value}</strong>
            </div>
          ))}
        </div>
      </details>
    </div>
  );
}
