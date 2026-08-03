import { useEffect, useMemo, useRef, useState } from 'react';
import {
  createChart,
  CandlestickSeries,
  HistogramSeries,
  LineSeries,
  ColorType,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useMarketDataStream } from '../../hooks/useMarketDataStream';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { ApiV2Envelope, MarketCandlesData, MarketDerivativesData, MarketIndicatorsData } from '../../types/apiV2';
import type { ValidatedDataEnvelope } from '../../types/dataContract';

// ─── Types ───────────────────────────────────────────────────────────────────

export interface ProChartProps {
  symbol: string;
  timeframe: string;
  exchange?: string;
  height?: number;
}

interface CoinAnkOverlay {
  oi_kline:      Array<{ time: number; value: number }>;
  net_long:      Array<{ time: number; value: number }>;
  funding_kline: Array<{ time: number; value: number }>;
  ls_kline:      Array<{ time: number; value: number }>;
  cvd:           Array<{ time: number; value: number }>;
  stats: {
    market_cap:   number | null;
    total_oi:     number | null;
    ls_ratio:     number | null;
    funding_rate: number | null;
    fear_greed:   number | null;
  };
}

interface ChartCandle {
  time?: number | string;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
}

interface ChartVolume {
  time?: number | string;
  value?: number | null;
}

interface ChartLine {
  time?: number | string;
  value?: number | null;
}

interface ChartPayload {
  status?: string;
  candles?: ChartCandle[];
  volume?: ChartVolume[];
  overlays?: {
    ema20?: ChartLine[];
    ema50?: ChartLine[];
    sma20?: ChartLine[];
    bb_upper?: ChartLine[];
    bb_lower?: ChartLine[];
    bb_middle?: ChartLine[];
    price_target?: ChartLine[];
  };
  signal?: {
    selected_action?: string | null;
    confidence_calibrated?: number | null;
    target_line_value?: number | null;
  };
}

type IndicatorField = keyof Pick<MarketIndicatorsData, 'ema20' | 'ema50' | 'bb_upper' | 'bb_lower' | 'bb_middle' | 'ai_target'>;

function sortedUniqueByTime<T extends { time?: number }>(rows: T[]): T[] {
  const byTime = new Map<number, T>();
  for (const row of rows) {
    if (row.time == null || !Number.isFinite(row.time)) continue;
    byTime.set(row.time, row);
  }
  return [...byTime.values()].sort((a, b) => Number(a.time) - Number(b.time));
}

function timestampSeconds(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Math.floor(value > 1_000_000_000_000 ? value / 1000 : value);
  }
  if (typeof value === 'string' && value.trim()) {
    const numeric = Number(value);
    if (Number.isFinite(numeric)) return timestampSeconds(numeric);
    const parsed = Date.parse(value);
    if (Number.isFinite(parsed)) return Math.floor(parsed / 1000);
  }
  return undefined;
}

function numericValue(value: unknown): number | null {
  const next = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(next) ? next : null;
}

function candleTimeSeconds(row: { time?: unknown; open_time_ms?: unknown } | null | undefined): number | undefined {
  return timestampSeconds(row?.time) ?? timestampSeconds(row?.open_time_ms);
}

function validOhlc(open: unknown, high: unknown, low: unknown, close: unknown): boolean {
  if (
    typeof open !== 'number'
    || typeof high !== 'number'
    || typeof low !== 'number'
    || typeof close !== 'number'
    || !Number.isFinite(open)
    || !Number.isFinite(high)
    || !Number.isFinite(low)
    || !Number.isFinite(close)
  ) return false;
  if (open <= 0 || high <= 0 || low <= 0 || close <= 0) return false;
  return low <= open && low <= close && high >= open && high >= close;
}

function typedEnvelopeMatchesChart(
  envelope: ApiV2Envelope<MarketCandlesData> | null | undefined,
  symbol: string,
  timeframe: string,
): boolean {
  if (!envelope) return false;
  const envelopeSymbol = envelope.symbol ?? envelope.data?.symbol;
  const envelopeTimeframe = envelope.data?.timeframe;
  return (
    typeof envelopeSymbol === 'string'
    && envelopeSymbol.toUpperCase() === symbol.toUpperCase()
    && typeof envelopeTimeframe === 'string'
    && envelopeTimeframe === timeframe
  );
}

function currentMarketSourceType(sourceType: ApiV2Envelope<unknown>['source_type'] | undefined): boolean {
  return sourceType === 'websocket'
    || sourceType === 'api'
    || sourceType === 'repository'
    || sourceType === 'redis_live';
}

function typedEnvelopeCanDriveRealtimeChart(
  envelope: ApiV2Envelope<MarketCandlesData> | null | undefined,
  symbol: string,
  timeframe: string,
): boolean {
  if (!typedEnvelopeMatchesChart(envelope, symbol, timeframe)) return false;
  return (
    envelope?.stale === false
    && currentMarketSourceType(envelope.source_type)
  );
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
    symbol: envelope.symbol,
    exchange: envelope.exchange,
    mode: envelope.mode as ApiV2Envelope<T>['mode'],
  };
}

function utcTimestamp(value: unknown): UTCTimestamp | null {
  const seconds = timestampSeconds(value);
  return seconds == null ? null : seconds as UTCTimestamp;
}

function overlayFromDerivatives(
  envelope: ApiV2Envelope<MarketDerivativesData> | null | undefined,
): CoinAnkOverlay | null {
  const data = envelope?.data;
  if (!data || envelope?.source_type === 'unavailable') return null;
  const funding = (data.funding_history ?? [])
    .map((row) => {
      const time = timestampSeconds(row.time);
      const value = numericValue(row.value);
      return time != null && value != null ? { time, value } : null;
    })
    .filter((row): row is { time: number; value: number } => row !== null);
  const oi = (data.open_interest_history ?? [])
    .map((row) => {
      const time = timestampSeconds(row.time);
      const value = numericValue(row.notional) ?? numericValue(row.value);
      return time != null && value != null ? { time, value } : null;
    })
    .filter((row): row is { time: number; value: number } => row !== null);
  if (!funding.length && !oi.length && data.long_short_ratio == null) return null;
  return {
    oi_kline: oi,
    funding_kline: funding,
    net_long: [],
    ls_kline: [],
    cvd: [],
    stats: {
      market_cap: null,
      total_oi: oi.at(-1)?.value ?? data.open_interest ?? null,
      ls_ratio: data.long_short_ratio,
      funding_rate: data.funding_rate ?? funding.at(-1)?.value ?? null,
      fear_greed: null,
    },
  };
}

function derivativeEnvelopeCanDriveOverlay(
  envelope: ApiV2Envelope<MarketDerivativesData> | null | undefined,
): boolean {
  return Boolean(
    overlayFromDerivatives(envelope)
    && envelope?.stale === false
    && currentMarketSourceType(envelope.source_type)
  );
}

interface ProChartSeriesClearTarget {
  setData(rows: never[]): void;
}

function clearDerivativeOverlaySeries(
  oiSeries: ProChartSeriesClearTarget | null | undefined,
  netLongSeries: ProChartSeriesClearTarget | null | undefined,
  netShortSeries: ProChartSeriesClearTarget | null | undefined,
): void {
  oiSeries?.setData([]);
  netLongSeries?.setData([]);
  netShortSeries?.setData([]);
}

function indicatorEnvelopeCanEnableControls(
  envelope: ApiV2Envelope<MarketIndicatorsData> | null | undefined,
  symbol: string,
  timeframe: string,
): boolean {
  const data = envelope?.data;
  if (!data || envelope?.stale !== false) return false;
  if (!currentMarketSourceType(envelope.source_type)) return false;
  if (data.symbol.toUpperCase() !== symbol.toUpperCase() || data.timeframe !== timeframe) return false;
  return data.controls_enabled === true && data.indicator_count > 0;
}

function indicatorSeriesAvailable(
  envelope: ApiV2Envelope<MarketIndicatorsData> | null | undefined,
  symbol: string,
  timeframe: string,
  fields: IndicatorField[],
): boolean {
  if (!indicatorEnvelopeCanEnableControls(envelope, symbol, timeframe)) return false;
  const data = envelope?.data;
  return Boolean(data && fields.some((field) => Array.isArray(data[field]) && data[field].length > 0));
}

function indicatorControlTitle(
  envelope: ApiV2Envelope<MarketIndicatorsData> | null | undefined,
  symbol: string,
  timeframe: string,
  fields: IndicatorField[],
  availableTitle: string,
  unavailableLabel: string,
): string {
  if (indicatorSeriesAvailable(envelope, symbol, timeframe, fields)) return availableTitle;
  const scope = `${symbol.toUpperCase()} ${timeframe}`;
  if (indicatorEnvelopeCanEnableControls(envelope, symbol, timeframe)) {
    return `Indicator source connecting for ${scope}; ${unavailableLabel} series are pending from the current typed indicator source. Static chart-file indicators are withheld.`;
  }
  if (!envelope) return `Indicator source connecting for ${scope}; ${unavailableLabel} requires current typed indicator evidence. Static chart-file indicators are withheld.`;
  if (envelope.source_type === 'static_payload') {
    return `Indicator source connecting for ${scope}; static chart-file source is withheld until current typed indicator evidence exists.`;
  }
  if (envelope.stale) {
    return `Indicator source connecting for ${scope}; ${unavailableLabel} source is stale and current typed indicator evidence is required.`;
  }
  return `Indicator source connecting for ${scope}; ${envelope.warnings?.[0] ?? `${unavailableLabel} source connecting`}. Static chart-file indicators are withheld.`;
}

function indicatorEvidenceSummary(
  envelope: ApiV2Envelope<MarketIndicatorsData> | null | undefined,
  symbol: string,
  timeframe: string,
): string {
  const available: string[] = [];
  if (indicatorSeriesAvailable(envelope, symbol, timeframe, ['ema20', 'ema50'])) available.push('EMA');
  if (indicatorSeriesAvailable(envelope, symbol, timeframe, ['bb_upper', 'bb_lower', 'bb_middle'])) available.push('Bollinger Bands');
  if (indicatorSeriesAvailable(envelope, symbol, timeframe, ['ai_target'])) available.push('AI target');
  if (available.length) {
    const missingAi = available.includes('AI target') ? '' : ' AI target remains source-pending.';
    return `Current typed indicator overlays available: ${available.join(', ')}.${missingAi} Static chart-file overlays are withheld.`;
  }
  if (indicatorEnvelopeCanEnableControls(envelope, symbol, timeframe)) {
    return 'Current typed indicator source is connected, but no overlay series are available for the selected controls. Static chart-file overlays are withheld.';
  }
  if (!envelope) return 'Indicator source connecting. Static chart-file overlays are withheld.';
  if (envelope.source_type === 'static_payload') return 'Static chart-file indicators are withheld until current typed indicator evidence exists.';
  if (envelope.stale) return 'Indicator source is stale. Static chart-file overlays are withheld.';
  return `${envelope.warnings?.[0] ?? 'Indicator source connecting'}. Static chart-file overlays are withheld.`;
}

function chartLineFromIndicatorSeries(rows: ChartLine[] | undefined): ChartLine[] {
  return sortedUniqueByTime(
    (rows ?? [])
      .map((row) => {
        const time = timestampSeconds(row.time);
        const value = numericValue(row.value);
        return time != null && value != null ? { time, value } : null;
      })
      .filter((row): row is { time: number; value: number } => row !== null),
  );
}

function indicatorOverlayFromEnvelope(
  envelope: ApiV2Envelope<MarketIndicatorsData> | null | undefined,
  symbol: string,
  timeframe: string,
): NonNullable<ChartPayload['overlays']> {
  if (!indicatorEnvelopeCanEnableControls(envelope, symbol, timeframe)) return {};
  const data = envelope?.data;
  if (!data) return {};
  return {
    ema20: chartLineFromIndicatorSeries(data.ema20),
    ema50: chartLineFromIndicatorSeries(data.ema50),
    bb_upper: chartLineFromIndicatorSeries(data.bb_upper),
    bb_lower: chartLineFromIndicatorSeries(data.bb_lower),
    bb_middle: chartLineFromIndicatorSeries(data.bb_middle),
    price_target: chartLineFromIndicatorSeries(data.ai_target),
  };
}

function latestLineValue(rows: ChartLine[] | undefined): number | null {
  const latest = chartLineFromIndicatorSeries(rows).at(-1);
  return latest?.value ?? null;
}

export function proChartStreamDomainStatus(envelope: ApiV2Envelope<unknown> | null): { label: string; title: string } {
  if (!envelope) return { label: 'Connecting', title: 'Realtime source is connecting for this data domain.' };
  const current = envelope.stale === false && currentMarketSourceType(envelope.source_type);
  if (current) {
    const source = String(envelope.source ?? '').toLowerCase();
    const endpoint = String(envelope.endpoint ?? '').toLowerCase();
    const liveSource = (
      source.includes('binance_usdm_public_websocket')
      || source.endsWith('_ws')
      || endpoint.startsWith('wss://')
    );
    return {
      label: liveSource ? 'Realtime' : 'Current',
      title: `${liveSource ? 'Live realtime market stream' : 'Current market data'} · ${envelope.received_at ?? 'received time unavailable'}`,
    };
  }
  return {
    label: envelope.stale ? 'Stale' : 'Connecting',
    title: `${envelope.stale ? 'Stale market data' : 'Market chart source connecting'} · ${envelope.warnings?.[0] ?? 'Current chart source connecting'}`,
  };
}

function realtimeChartPayload(
  displayCandles: ChartCandle[],
  displayVolume: ChartVolume[],
  liveCandle: { is_final?: boolean } | null | undefined,
  overlays: ChartPayload['overlays'] = {},
  signal: ChartPayload['signal'] = undefined,
): ChartPayload {
  return {
    status: liveCandle?.is_final === false ? 'CURRENT_WITH_PARTIAL_STREAM_CANDLE' : 'CURRENT',
    candles: displayCandles,
    volume: displayVolume,
    overlays,
    signal,
  };
}

function proChartLiveCandleLabel({
  stale,
  liveCandle,
  candleIsStreamBacked,
  hasStreamFrame,
  streamSource,
  connected,
}: {
  stale: boolean;
  liveCandle: { is_final?: boolean } | null | undefined;
  candleIsStreamBacked: boolean;
  hasStreamFrame: boolean;
  streamSource: 'binance_usdm_public_websocket' | 'safe_api_contract_stream' | 'unavailable';
  connected: boolean;
}): string {
  if (stale) return 'Stream data stale';
  if (liveCandle) {
    if (!candleIsStreamBacked) return 'Current candle update';
    return liveCandle.is_final === false ? 'Stream forming candle' : 'Stream closed candle';
  }
  if (hasStreamFrame) return streamSource === 'safe_api_contract_stream' ? 'Resource stream connected' : 'Stream connected';
  return connected ? 'Waiting for stream frame' : 'Stream reconnecting';
}

function mergeRealtimeCandleRows(
  baseRows: MarketCandlesData['candles'],
  streamRows: MarketCandlesData['candles'],
): MarketCandlesData['candles'] {
  if (!streamRows.length) return baseRows;
  const byTime = new Map<number, MarketCandlesData['candles'][number]>();
  for (const row of [...baseRows, ...streamRows]) {
    const time = candleTimeSeconds(row);
    if (
      time == null
      || !validOhlc(row.open, row.high, row.low, row.close)
    ) {
      continue;
    }
    byTime.set(time, row);
  }
  return [...byTime.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, row]) => row);
}

// ─── Color constants ──────────────────────────────────────────────────────────

const C = {
  buy:      '#00d4a3',
  sell:     '#f6465d',
  ai:       '#6c63ff',
  buyDim:   'rgba(0,212,163,0.22)',
  sellDim:  'rgba(246,70,93,0.22)',
  oiUp:     'rgba(0,212,163,0.60)',
  oiDown:   'rgba(246,70,93,0.60)',
  netLong:  'rgba(0,212,163,0.70)',
  netShort: 'rgba(246,70,93,0.70)',
  bg:       '#0a0e14',
  grid:     'rgba(255,255,255,0.04)',
  text:     '#7d8fa8',
  border:   'rgba(255,255,255,0.06)',
} as const;

// ─── ProChart component ───────────────────────────────────────────────────────

export function ProChart({ symbol, timeframe, exchange: _exchange = 'Binance', height = 640 }: ProChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const fittedOnceRef = useRef(false);
  const marketStream = useMarketDataStream(symbol, 2_000, timeframe);

  // Series refs — pane 0 (main)
  const candleRef  = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef     = useRef<ISeriesApi<'Histogram'>   | null>(null);
  const ema20Ref   = useRef<ISeriesApi<'Line'>        | null>(null);
  const ema50Ref   = useRef<ISeriesApi<'Line'>        | null>(null);
  const bbUpperRef = useRef<ISeriesApi<'Line'>        | null>(null);
  const bbLowerRef = useRef<ISeriesApi<'Line'>        | null>(null);
  const targetRef  = useRef<ISeriesApi<'Line'>        | null>(null);

  // Series refs — pane 1 (OI), pane 2 (Long/Short)
  const oiRef       = useRef<ISeriesApi<'Histogram'> | null>(null);
  const netLongRef  = useRef<ISeriesApi<'Histogram'> | null>(null);
  const netShortRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  // Indicator toggles
  const [showOI,  setShowOI]  = useState(false);
  const [showLS,  setShowLS]  = useState(false);
  const [showBB,  setShowBB]  = useState(false);
  const [showEMA, setShowEMA] = useState(false);
  const [showAI,  setShowAI]  = useState(false);

  const candleUrl = `/api/v2/market/${symbol}/candles?timeframe=${encodeURIComponent(timeframe)}`;
  const indicatorUrl = `/api/v2/market/${symbol}/indicators?timeframe=${encodeURIComponent(timeframe)}`;
  const derivativeUrl = `/api/v2/market/${symbol}/derivatives?timeframe=${encodeURIComponent(timeframe)}`;
  const candleResource = useRealtimeResource<MarketCandlesData>({
    url: candleUrl,
    source: candleUrl,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
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
  const derivativeResource = useRealtimeResource<MarketDerivativesData>({
    url: derivativeUrl,
    source: derivativeUrl,
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
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
  const derivativeEnvelope = useMemo(
    () => resourceEnvelopeToApi(derivativeResource.envelope, derivativeUrl),
    [derivativeResource.envelope, derivativeUrl],
  );
  const overlay = useMemo(
    () => derivativeEnvelopeCanDriveOverlay(derivativeEnvelope) ? overlayFromDerivatives(derivativeEnvelope) : null,
    [derivativeEnvelope],
  );

  const activeChartPayload = useMemo<ChartPayload | null>(() => {
    const typedEnvelopeRealtime = typedEnvelopeCanDriveRealtimeChart(candleEnvelope, symbol, timeframe);
    const typedRows = typedEnvelopeRealtime ? candleEnvelope?.data?.candles ?? [] : [];
    const streamRows = marketStream.candles && typedEnvelopeCanDriveRealtimeChart(marketStream.candles, symbol, timeframe)
      ? marketStream.candles.data?.candles ?? []
      : [];
    const baseRows = typedRows.length >= 20
      ? typedRows
      : streamRows.length >= 20
        ? streamRows
        : typedRows.length > 0
          ? typedRows
          : streamRows;
    const chartRows = mergeRealtimeCandleRows(baseRows, streamRows);
    const liveCandle = marketStream.liveCandle;
    const typedCandles = chartRows
      .map((row) => {
        const time = candleTimeSeconds(row);
        if (
          time == null
          || !validOhlc(row.open, row.high, row.low, row.close)
        ) {
          return null;
        }
        return {
          time,
          open: row.open,
          high: row.high,
          low: row.low,
          close: row.close,
        };
      })
      .filter((row): row is { time: number; open: number; high: number; low: number; close: number } => row !== null)
      .sort((a, b) => Number(a.time) - Number(b.time));
    const liveTime = candleTimeSeconds(liveCandle);
    const displayCandles = sortedUniqueByTime(liveCandle && liveTime != null && validOhlc(liveCandle.open, liveCandle.high, liveCandle.low, liveCandle.close)
      ? [
          ...typedCandles.filter((row) => row.time !== liveTime),
          {
            time: liveTime,
            open: liveCandle.open,
            high: liveCandle.high,
            low: liveCandle.low,
            close: liveCandle.close,
          },
        ]
      : typedCandles);

    const displayVolume = sortedUniqueByTime(
      chartRows
        .map((row) => {
          const time = candleTimeSeconds(row);
          return time == null || row.volume == null ? null : { time, value: row.volume };
        })
        .filter((row): row is { time: number; value: number } => row !== null)
        .filter((row) => row.time !== liveTime)
        .concat(liveCandle && liveTime != null && liveCandle.volume != null ? [{ time: liveTime, value: liveCandle.volume }] : []),
    );

    if (((typedEnvelopeRealtime || streamRows.length > 0) && typedCandles.length > 0) || displayCandles.length > 0) {
      const indicatorOverlays = indicatorOverlayFromEnvelope(indicatorEnvelope, symbol, timeframe);
      const aiTarget = latestLineValue(indicatorOverlays.price_target);
      return realtimeChartPayload(
        displayCandles,
        displayVolume,
        liveCandle,
        indicatorOverlays,
        aiTarget == null ? undefined : { target_line_value: aiTarget },
      );
    }

    return null;
  }, [marketStream.candles, marketStream.liveCandle, symbol, timeframe, candleEnvelope, indicatorEnvelope]);

  const typedEnvelopeUsable = typedEnvelopeMatchesChart(candleEnvelope, symbol, timeframe);
  const typedEnvelopeRealtime = typedEnvelopeCanDriveRealtimeChart(candleEnvelope, symbol, timeframe);
  const streamCandlesRealtime = typedEnvelopeCanDriveRealtimeChart(marketStream.candles, symbol, timeframe);
  const hasStreamFrame = Boolean(
    marketStream.receivedAt
    && (
      marketStream.ticker
      || marketStream.depth
      || marketStream.trades
      || marketStream.candles
      || marketStream.liveCandle
    ),
  );
  const chartSourceLabel = marketStream.streamSource === 'binance_usdm_public_websocket' && (marketStream.liveCandle || streamCandlesRealtime)
    ? 'Native public stream + candle source'
    : typedEnvelopeRealtime
    ? 'Current candle source'
    : typedEnvelopeUsable && (candleEnvelope?.source_type === 'static_payload' || candleEnvelope?.stale)
      ? 'Fallback/stale candles withheld'
    : activeChartPayload
	      ? hasStreamFrame
	        ? marketStream.streamSource === 'safe_api_contract_stream'
	          ? 'Current resource stream data'
	          : 'Live stream chart data'
          : 'Current chart data'
        : 'Candle source connecting';
  const indicatorSummary = indicatorEvidenceSummary(indicatorEnvelope, symbol, timeframe);
  const chartSourceTitle = typedEnvelopeRealtime && candleEnvelope
    ? `Current candle data is available. ${indicatorSummary}${marketStream.liveCandle?.is_final === false ? ' Forming stream candle is display-only, not final evidence.' : ''}`
    : typedEnvelopeUsable && candleEnvelope
        ? `Candle data is stale or fallback-only and is withheld from the primary chart until a current market data source is available.${marketStream.liveCandle?.is_final === false ? ' Forming stream candle is display-only, not final evidence.' : ''}`
    : candleEnvelope && !typedEnvelopeUsable
      ? 'Candle source symbol/timeframe did not match the active chart and was ignored.'
    : 'Waiting for candle source.';

  // ─── Chart initialization ─────────────────────────────────────────────────
  // Re-create chart when height or timeframe changes so secondsVisible is correct.
  useEffect(() => {
    fittedOnceRef.current = false;
  }, [symbol, timeframe]);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      width:  containerRef.current.clientWidth,
      height: height,
      layout: {
        background: { type: ColorType.Solid, color: C.bg },
        textColor: C.text,
        fontSize: 11,
        fontFamily: "'JetBrains Mono', 'IBM Plex Mono', ui-monospace, monospace",
      },
      grid: {
        vertLines: { color: C.grid },
        horzLines: { color: C.grid },
      },
      crosshair: {
        vertLine: { color: 'rgba(255,255,255,0.2)', labelBackgroundColor: '#1a2230' },
        horzLine: { color: 'rgba(255,255,255,0.2)', labelBackgroundColor: '#1a2230' },
      },
      rightPriceScale: {
        borderColor: C.border,
        scaleMargins: { top: 0.05, bottom: 0.1 },
      },
      timeScale: {
        borderColor: C.border,
        timeVisible: true,
        secondsVisible: timeframe === '1m',
      },
    });

    // Pane 0 — Candlestick (main)
    candleRef.current = chart.addSeries(CandlestickSeries, {
      upColor:         C.buy,
      downColor:       C.sell,
      borderUpColor:   C.buy,
      borderDownColor: C.sell,
      wickUpColor:     C.buy,
      wickDownColor:   C.sell,
    });

    // Pane 0 — Volume (secondary scale pinned to bottom of pane 0)
    volRef.current = chart.addSeries(HistogramSeries, {
      priceScaleId: 'volume',
      priceFormat:  { type: 'volume' },
    });
    chart.priceScale('volume').applyOptions({ scaleMargins: { top: 0.85, bottom: 0 } });

    // Pane 0 — EMA 20 (amber)
    ema20Ref.current = chart.addSeries(LineSeries, {
      color: '#f59e0b', lineWidth: 1, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // Pane 0 — EMA 50 (blue)
    ema50Ref.current = chart.addSeries(LineSeries, {
      color: '#3b82f6', lineWidth: 1, lineStyle: LineStyle.Solid,
      priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false,
    });

    // Pane 0 — Bollinger Bands
    const bbOpts = {
      color: 'rgba(108,99,255,0.5)', lineWidth: 1 as const, lineStyle: LineStyle.Dashed,
      priceLineVisible: false, lastValueVisible: false,
    };
    bbUpperRef.current = chart.addSeries(LineSeries, bbOpts);
    bbLowerRef.current = chart.addSeries(LineSeries, bbOpts);

    // Pane 0 — AI target price
    targetRef.current = chart.addSeries(LineSeries, {
      color: C.ai, lineWidth: 1, lineStyle: LineStyle.Dotted,
      priceLineVisible: true, lastValueVisible: true,
    });

    // Pane 1 — Open Interest histogram (optional - wrapped in try-catch for v5 compat)
    try {
      oiRef.current = chart.addSeries(HistogramSeries, { color: C.oiUp }, 1);
      netLongRef.current  = chart.addSeries(HistogramSeries, { color: C.netLong  }, 2);
      netShortRef.current = chart.addSeries(HistogramSeries, { color: C.netShort }, 2);
    } catch {
      oiRef.current = null;
      netLongRef.current = null;
      netShortRef.current = null;
    }

    chartRef.current = chart;

    const ro = new ResizeObserver(() => {
      if (containerRef.current) chart.applyOptions({ width: containerRef.current.clientWidth });
    });
    ro.observe(containerRef.current);

    return () => {
      ro.disconnect();
      chart.remove();
      chartRef.current = null;
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [height, timeframe]);

  // ─── OHLCV data updates ───────────────────────────────────────────────────
  useEffect(() => {
    if (!activeChartPayload) {
      candleRef.current?.setData([]);
      volRef.current?.setData([]);
      ema20Ref.current?.setData([]);
      ema50Ref.current?.setData([]);
      bbUpperRef.current?.setData([]);
      bbLowerRef.current?.setData([]);
      targetRef.current?.setData([]);
      return;
    }

    const chartPayload = activeChartPayload;

    const validNumber = (value: unknown): value is number => typeof value === 'number' && Number.isFinite(value);

    // Candles
    const candleRows = sortedUniqueByTime(
      (chartPayload.candles ?? [])
        .map(c => {
          const time = utcTimestamp(c.time);
          return time !== null && validOhlc(c.open, c.high, c.low, c.close)
            ? { time, open: c.open!, high: c.high!, low: c.low!, close: c.close! }
            : null;
        })
        .filter((row): row is { time: UTCTimestamp; open: number; high: number; low: number; close: number } => row !== null),
    );
    candleRef.current?.setData(candleRows);

    // Volume (color by candle direction)
    const byTime = new Map(candleRows.map(c => [Number(c.time), c]));
    const volumeRows = sortedUniqueByTime(
      (chartPayload.volume ?? []).reduce<Array<{ time: UTCTimestamp; value: number; color: string }>>((acc, v) => {
        const time = utcTimestamp(v.time);
        if (time === null || !validNumber(v.value)) return acc;
        const candle = byTime.get(Number(time));
        const color = (candle?.close ?? 0) >= (candle?.open ?? 0) ? C.buyDim : C.sellDim;
        acc.push({ time, value: v.value, color });
        return acc;
      }, []),
    );
    volRef.current?.setData(volumeRows);

    // Overlays
    const ov = chartPayload.overlays ?? {};
    const toLine = (arr: ChartLine[] | undefined) =>
      sortedUniqueByTime(
        (arr ?? [])
          .map(p => {
            const time = utcTimestamp(p.time);
            return time !== null && validNumber(p.value) ? { time, value: p.value } : null;
          })
          .filter((row): row is { time: UTCTimestamp; value: number } => row !== null),
      );

    if (ema20Ref.current) ema20Ref.current.setData(showEMA ? toLine(ov.ema20) : []);
    if (ema50Ref.current) ema50Ref.current.setData(showEMA ? toLine(ov.ema50) : []);
    if (bbUpperRef.current) bbUpperRef.current.setData(showBB ? toLine(ov.bb_upper) : []);
    if (bbLowerRef.current) bbLowerRef.current.setData(showBB ? toLine(ov.bb_lower) : []);

    // AI target line — extend from last candle to horizon
    const targetVal = chartPayload.signal?.target_line_value;
    const lastCandle = (chartPayload.candles ?? []).at(-1);
    const lastCandleTime = utcTimestamp(lastCandle?.time);
    if (targetRef.current) {
      if (showAI && validNumber(targetVal) && lastCandleTime !== null) {
        targetRef.current.setData([{ time: lastCandleTime, value: targetVal }]);
      } else {
        targetRef.current.setData([]);
      }
    }

    if (!fittedOnceRef.current && candleRows.length > 0) {
      chartRef.current?.timeScale().fitContent();
      fittedOnceRef.current = true;
    }
  }, [activeChartPayload, showBB, showEMA, showAI]);

  // ─── CoinAnk overlay updates ──────────────────────────────────────────────
  useEffect(() => {
    if (!overlay) {
      clearDerivativeOverlaySeries(oiRef.current, netLongRef.current, netShortRef.current);
      return;
    }

    const toHist = (
      arr: Array<{ time: number; value: number }>,
      color: string,
    ) =>
      sortedUniqueByTime(
        arr
          .map(p => {
            const time = utcTimestamp(p.time);
            return time !== null && Number.isFinite(p.value) ? { time, value: p.value, color } : null;
          })
          .filter((row): row is { time: UTCTimestamp; value: number; color: string } => row !== null),
      );

    // OI — color by direction
    if (oiRef.current && showOI && overlay.oi_kline?.length) {
      const data = toHist(overlay.oi_kline, C.oiUp);
      for (let i = 1; i < data.length; i++) {
        data[i].color = data[i].value >= data[i - 1].value ? C.oiUp : C.oiDown;
      }
      oiRef.current.setData(data);
    } else {
      oiRef.current?.setData([]);
    }

    // Net Long (positive)
    if (netLongRef.current && showLS && overlay.net_long?.length) {
      netLongRef.current.setData(toHist(overlay.net_long, C.netLong));
    } else {
      netLongRef.current?.setData([]);
    }
    // Net Short (negative — negate so bars point down)
    if (netShortRef.current && showLS && overlay.net_long?.length) {
      const neg = overlay.net_long.map(p => ({ ...p, value: -Math.abs(p.value) }));
      netShortRef.current.setData(toHist(neg, C.netShort));
    } else {
      netShortRef.current?.setData([]);
    }
  }, [overlay, showOI, showLS]);

  // ─── Signal badge ─────────────────────────────────────────────────────────
  const sig    = activeChartPayload?.signal;
  const sigDir = sig?.selected_action?.includes('BUY') ? 'LONG'
               : sig?.selected_action?.includes('SELL') ? 'SHORT' : null;
  const conf   = sig?.confidence_calibrated;

  // Stats bar formatters
  const stats = overlay?.stats;
  const fmtOI = (v: number | null) => v != null ? `$${(v / 1e6).toFixed(2)}M` : 'Connecting stream';
  const fmtLS = (v: number | null) => v != null ? v.toFixed(2) : 'Connecting stream';
  const fmtFR = (v: number | null) => v != null ? `${(v * 100).toFixed(4)}%` : 'Connecting stream';
  const streamDomainChips = [
    ['Price stream', proChartStreamDomainStatus(marketStream.ticker)],
    ['Depth stream', proChartStreamDomainStatus(marketStream.depth)],
    ['Trades stream', proChartStreamDomainStatus(marketStream.trades)],
  ] as const;
  const candleSource = String(marketStream.candles?.source ?? candleEnvelope?.source ?? '').toLowerCase();
  const candleIsStreamBacked = !marketStream.stale
    && marketStream.streamSource !== 'unavailable'
    && (candleSource.includes('websocket') || candleSource.includes('stream') || hasStreamFrame);
  const liveCandleLabel = proChartLiveCandleLabel({
    stale: marketStream.stale,
    liveCandle: marketStream.liveCandle,
    candleIsStreamBacked,
    hasStreamFrame,
    streamSource: marketStream.streamSource,
    connected: marketStream.connected,
  });
  const emaFields: IndicatorField[] = ['ema20', 'ema50'];
  const bbFields: IndicatorField[] = ['bb_upper', 'bb_lower', 'bb_middle'];
  const aiTargetFields: IndicatorField[] = ['ai_target'];
  const emaControlAvailable = indicatorSeriesAvailable(indicatorEnvelope, symbol, timeframe, emaFields);
  const bbControlAvailable = indicatorSeriesAvailable(indicatorEnvelope, symbol, timeframe, bbFields);
  const aiTargetControlAvailable = indicatorSeriesAvailable(indicatorEnvelope, symbol, timeframe, aiTargetFields);
  const emaControlTitle = indicatorControlTitle(indicatorEnvelope, symbol, timeframe, emaFields, 'Toggle EMA overlay', 'EMA');
  const bbControlTitle = indicatorControlTitle(indicatorEnvelope, symbol, timeframe, bbFields, 'Toggle Bollinger Bands overlay', 'Bollinger Bands');
  const aiTargetControlTitle = indicatorControlTitle(indicatorEnvelope, symbol, timeframe, aiTargetFields, 'Toggle AI target overlay', 'AI target');
  const oiControlAvailable = Boolean(overlay?.oi_kline?.length);
  const lsControlAvailable = Boolean(overlay?.net_long?.length || overlay?.ls_kline?.length);

  return (
    <div className="prochart">
      {/* Indicator toggle bar */}
      <div className="prochart__controls">
        <button
          className={`prochart__toggle ${showEMA ? 'active' : ''}`}
          disabled={!emaControlAvailable}
          title={emaControlTitle}
          onClick={() => setShowEMA(v => !v)}
        >
          {emaControlAvailable ? 'EMA' : 'EMA pending'}
        </button>
        <button
          className={`prochart__toggle ${showBB  ? 'active' : ''}`}
          disabled={!bbControlAvailable}
          title={bbControlTitle}
          onClick={() => setShowBB(v  => !v)}
        >
          {bbControlAvailable ? 'BB' : 'BB pending'}
        </button>
        <button
          className={`prochart__toggle ${showAI  ? 'active' : ''}`}
          disabled={!aiTargetControlAvailable}
          title={aiTargetControlTitle}
          onClick={() => setShowAI(v  => !v)}
        >
          {aiTargetControlAvailable ? 'AI Target' : 'AI target pending'}
        </button>
        <span className="prochart__divider" />
        <button
          className={`prochart__toggle ${showOI  ? 'active' : ''}`}
          disabled={!oiControlAvailable}
          title={oiControlAvailable ? 'Toggle open-interest overlay' : 'Open-interest overlay source connecting'}
          onClick={() => setShowOI(v  => !v)}
        >
          {oiControlAvailable ? 'OI' : 'OI pending'}
        </button>
        <button
          className={`prochart__toggle ${showLS  ? 'active' : ''}`}
          disabled={!lsControlAvailable}
          title={lsControlAvailable ? 'Toggle long/short overlay' : 'Long/short overlay source connecting'}
          onClick={() => setShowLS(v  => !v)}
        >
          {lsControlAvailable ? 'L/S' : 'L/S pending'}
        </button>
        <div className="prochart__source" title={chartSourceTitle}>{chartSourceLabel}</div>
        <div className="prochart__source" title="Unfinished stream candles are display-only and are not final model evidence.">{liveCandleLabel}</div>
        {streamDomainChips.map(([label, status]) => (
          <div key={label} className="prochart__source" title={status.title}>
            {label}: {status.label}
          </div>
        ))}
        {sigDir && conf != null && (
          <div className={`prochart__signal prochart__signal--${sigDir.toLowerCase()}`}>
            {sigDir} {(conf * 100).toFixed(0)}%
          </div>
        )}
      </div>

      {/* Chart canvas */}
      <div ref={containerRef} className="prochart__canvas" style={{ height }} />
      {!activeChartPayload ? (
        <div className="chart-empty-state" role="status">
          Current candle data is connecting. Static or stale chart snapshots are withheld from the primary chart until a current market data source is available.
        </div>
      ) : null}

      {/* Pane labels (float left) */}
      <div className="prochart__pane-labels" aria-hidden="true">
        <span style={{ top: '5%' }}>Price</span>
        {showOI && <span style={{ top: '60%' }}>Open Interest</span>}
        {showLS && <span style={{ top: '77%' }}>Long / Short</span>}
      </div>

      {/* Stats strip */}
      {stats && (
        <div className="prochart__stats">
          <span>OI: <strong>{fmtOI(stats.total_oi)}</strong></span>
          <span>
            L/S: <strong className={stats.ls_ratio != null && stats.ls_ratio > 1 ? 'text-buy' : 'text-sell'}>
              {fmtLS(stats.ls_ratio)}
            </strong>
          </span>
          <span>
            Funding: <strong className={stats.funding_rate != null && stats.funding_rate > 0 ? 'text-buy' : 'text-sell'}>
              {fmtFR(stats.funding_rate)}
            </strong>
          </span>
          {stats.market_cap != null && <span>MCap: <strong>${(stats.market_cap / 1e9).toFixed(2)}B</strong></span>}
          {stats.fear_greed != null && <span>F&amp;G: <strong>{stats.fear_greed.toFixed(0)}</strong></span>}
        </div>
      )}
    </div>
  );
}

export const proChartTestHooks = {
  clearDerivativeOverlaySeries,
  derivativeEnvelopeCanDriveOverlay,
  indicatorEnvelopeCanEnableControls,
  indicatorControlTitle,
  indicatorEvidenceSummary,
  indicatorOverlayFromEnvelope,
  indicatorSeriesAvailable,
  mergeRealtimeCandleRows,
  overlayFromDerivatives,
  proChartStreamDomainStatus,
  proChartLiveCandleLabel,
  realtimeChartPayload,
  typedEnvelopeCanDriveRealtimeChart,
  typedEnvelopeMatchesChart,
  validOhlc,
};
