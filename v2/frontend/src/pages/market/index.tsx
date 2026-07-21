/**
 * Market Detail Page — /market/:symbol
 *
 * Professional candlestick chart page using lightweight-charts.
 * Layout: Symbol header | Chart (70%) + Stats sidebar (30%) | AI Signal + Derivatives + Source
 *
 * Auth: page is in the 'app' surface (TraderShell). Unauthenticated users are
 * redirected to /login?returnTo=/market/:symbol by TraderShell before this
 * component mounts. If auth state resolves to no-user mid-session, an inline
 * overlay prompts sign-in without a full-page redirect.
 */
import { useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
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
import { Activity, AlertTriangle, ChevronRight, Sparkles, TrendingDown, TrendingUp, ShieldCheck } from 'lucide-react';
import { safeV2MarketSymbol } from '../../api/v2Market';
import { useMarketDataStream } from '../../hooks/useMarketDataStream';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { CanonicalMetricValue } from '../../components/data/CanonicalMetric';
import type { CanonicalMetric } from '../../selectors/accountSelectors';
import { selectMarketBySymbol, selectMarketMetric } from '../../selectors/marketSelectors';
import { SymbolIntelSection } from './intelPanels';
import type {
  ApiV2Envelope,
  MarketCandlesData,
  MarketDepthData,
  MarketDerivativesData,
  MarketIndicatorsData,
  MarketTickerData,
  RecentTradesData,
} from '../../types/apiV2';
import './marketDetail.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TickerData {
  symbol: string;
  last_price: number | null;
  mark_price: number | null;
  index_price: number | null;
  change_1h?: number | null;
  change_4h?: number | null;
  change_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  turnover_24h: number | null;
  funding_rate: number | null;
  next_funding: string | null;
  open_interest: number | null;
  bid?: number | null;
  ask?: number | null;
  spread_bps?: number | null;
}

interface CandleRow {
  time: number;
  open_time_ms?: number;
  close_time_ms?: number;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface SignalData {
  selected_action?: string | null;
  confidence?: number | null;
  entry?: number | null;
  target_1?: number | null;
  stop?: number | null;
  risk_reward?: number | null;
  /** Trainer-declared freshness of the prediction (e.g. 'LIVE' | 'STALE'). */
  source_freshness?: string | null;
  generated_at?: string | null;
  market_age_seconds?: number | null;
}

// ---------------------------------------------------------------------------
// Symbol enrichment types — mirrors /api/v2/market/{symbol} Redis enrichment
// blocks. Every field optional/nullable: alts with sparser data must render
// honest '—' instead of crashing.
// ---------------------------------------------------------------------------

interface LongShortBlock {
  long_short_ratio?: number | null;
  long_account_ratio?: number | null;
  short_account_ratio?: number | null;
  period?: string | null;
  fetched_utc?: string | null;
}

interface FundingDetailBlock {
  funding_rate?: number | null;
  basis_bps?: number | null;
  next_funding_time?: string | null;
  estimated_settle_price?: number | null;
}

interface CoinglassBlock {
  open_interest_usd?: number | null;
  open_interest_delta_1h_usd?: number | null;
  funding_rate_zscore?: number | null;
  next_funding_minutes?: number | null;
}

interface RegimeBlock {
  regime?: string | null;
  confidence?: number | null;
  htf_trend?: string | null;
  rsi_zone?: string | null;
  macd_direction?: string | null;
  market_risk_state?: string | null;
  generated_utc?: string | null;
}

interface TaSummaryBlock {
  indicator_count?: number | null;
  candle_count?: number | null;
  closed_candles_only?: boolean | null;
  generated_utc?: string | null;
}

interface LiquidationLevelsBlock {
  distance_to_long_liq_bps?: number | null;
  distance_to_short_liq_bps?: number | null;
  liquidation_cascade_risk?: number | null;
  levels_count_long?: number | null;
  levels_count_short?: number | null;
  nearest_level_above?: number | null;
  nearest_level_below?: number | null;
  sweep_target_short?: number | null;
  sweep_target_short_distance_bps?: number | null;
  sweep_target_long?: number | null;
  sweep_target_long_distance_bps?: number | null;
  updated_ts_ms?: number | null;
}

interface LiquidationEnhancedBlock {
  cascade_probability?: number | null;
  predicted_long_liq_zone?: number | null;
  predicted_short_liq_zone?: number | null;
  market_stress_indicator?: number | null;
}

interface LiquidationFlowBlock {
  notional_1h?: number | null;
  count_1h?: number | null;
  direction_bias_1h?: number | null;
  notional_24h?: number | null;
  count_24h?: number | null;
}

interface SymbolEnrichment {
  change_7d?: number | null;
  market_cap_rank?: number | null;
  market_cap_usd?: number | null;
  basis_bps?: number | null;
  next_funding_time?: string | null;
  liquidation_cascade_risk?: number | null;
  distance_to_long_liq_bps?: number | null;
  distance_to_short_liq_bps?: number | null;
  distance_to_nearest_liq_bps?: number | null;
  liq_notional_1h?: number | null;
  liq_count_1h?: number | null;
  liq_direction_bias_1h?: number | null;
  rsi_1m?: number | null;
  atr_1m?: number | null;
  adx_1m?: number | null;
  htf_trend?: string | null;
  rsi_zone?: string | null;
  macd_direction?: string | null;
  altdata_symbol_score?: number | null;
  altdata_symbol_rank?: number | null;
  coinank_derivatives_score?: number | null;
  open_interest_delta_1h_usd?: number | null;
  coinglass_open_interest_usd?: number | null;
  taker_buy_ratio?: number | null;
  taker_flow_trade_count?: number | null;
  ta_1m?: TaSummaryBlock | null;
  liquidation_levels?: LiquidationLevelsBlock | null;
  liquidation_enhanced?: LiquidationEnhancedBlock | null;
  liquidation_flow?: LiquidationFlowBlock | null;
  long_short?: LongShortBlock | null;
  funding_detail?: FundingDetailBlock | null;
  coinglass?: CoinglassBlock | null;
  regime_1m?: RegimeBlock | null;
}

type EnrichedTickerData = MarketTickerData & SymbolEnrichment;

function envelopeMatchesSymbol<T extends { symbol?: string | null }>(
  envelope: ApiV2Envelope<T> | null | undefined,
  expectedSymbol: string,
): envelope is ApiV2Envelope<T> {
  if (!envelope || envelope.stale !== false) return false;
  const dataSymbol = envelope.data?.symbol;
  const envelopeSymbol = envelope.symbol;
  const symbolValue = dataSymbol ?? envelopeSymbol;
  return (
    typeof symbolValue === 'string'
    && symbolValue.toUpperCase() === expectedSymbol.toUpperCase()
  );
}

function streamTickerForSymbol(
  envelope: ApiV2Envelope<MarketTickerData> | null | undefined,
  expectedSymbol: string,
): TickerData | null {
  if (!envelopeMatchesSymbol(envelope, expectedSymbol)) return null;
  return envelope.data;
}

function streamCandlesForSymbol(
  envelope: ApiV2Envelope<MarketCandlesData> | null | undefined,
  expectedSymbol: string,
  expectedTimeframe: string,
): CandleRow[] {
  if (!envelopeMatchesSymbol(envelope, expectedSymbol)) return [];
  if (envelope?.data?.timeframe !== expectedTimeframe) return [];
  return (envelope.data.candles ?? [])
    .map((row): CandleRow | null => {
      const time = finite(row.open_time_ms) ?? finite(row.time);
      const open = finite(row.open);
      const high = finite(row.high);
      const low = finite(row.low);
      const close = finite(row.close);
      if (time === null || open === null || high === null || low === null || close === null) return null;
      return {
        time,
        open,
        high,
        low,
        close,
        volume: finite(row.volume) ?? undefined,
      };
    })
    .filter((row): row is CandleRow => row !== null);
}

function tickerForSymbol(data: MarketTickerData | null | undefined, expectedSymbol: string): TickerData | null {
  if (!data?.symbol || data.symbol.toUpperCase() !== expectedSymbol.toUpperCase()) return null;
  return data;
}

function resourceForSymbol<T extends { symbol?: string | null }>(
  data: T | null | undefined,
  expectedSymbol: string,
): T | null {
  if (!data?.symbol || data.symbol.toUpperCase() !== expectedSymbol.toUpperCase()) return null;
  return data;
}

function candleRowsForSymbol(
  data: MarketCandlesData | null | undefined,
  expectedSymbol: string,
  expectedTimeframe: string,
): CandleRow[] {
  if (!data?.symbol || data.symbol.toUpperCase() !== expectedSymbol.toUpperCase()) return [];
  if (data.timeframe !== expectedTimeframe) return [];
  return (data.candles ?? [])
    .map((row): CandleRow | null => {
      const time = finite(row.open_time_ms) ?? finite(row.time);
      const open = finite(row.open);
      const high = finite(row.high);
      const low = finite(row.low);
      const close = finite(row.close);
      if (time === null || open === null || high === null || low === null || close === null) return null;
      return {
        time,
        open,
        high,
        low,
        close,
        volume: finite(row.volume) ?? undefined,
      };
    })
    .filter((row): row is CandleRow => row !== null);
}

interface CurrentUser {
  id: string;
  role: string;
}

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'] as const;
type Timeframe = (typeof TIMEFRAMES)[number];

// ---------------------------------------------------------------------------
// Inline formatters (self-contained — no external formatter dependency)
// ---------------------------------------------------------------------------

function finite(v: unknown): number | null {
  return typeof v === 'number' && Number.isFinite(v) ? v : null;
}

function fmtPrice(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  const dec = Math.abs(n) >= 1000 ? 2 : Math.abs(n) >= 1 ? 4 : 8;
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: Math.min(2, dec), maximumFractionDigits: dec })}`;
}

/** Liquidation-level price sentinel: the 1m levels engine emits 0.0 when a
 *  side has no usable level (raw evidence: v2:liquidations:levels:BTCUSDT:1m
 *  nearest_liquidation_level_below=0.0 while sweep_target_long=null) — render
 *  honest '—' instead of a fabricated "$0.00" price. */
function posPriceOrNull(v: number | null | undefined): number | null {
  const n = finite(v);
  return n !== null && n > 0 ? n : null;
}

function fmtPct(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct >= 0 ? '+' : ''}${pct.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}%`;
}

function fmtBps(v: unknown): string {
  const n = finite(v);
  return n === null ? '—' : `${(n / 100).toLocaleString('en-US', { maximumFractionDigits: 4 })}%`;
}

function fmtCompact(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toLocaleString('en-US', { maximumFractionDigits: 4 });
}

function fmtVolume(v: number | null, ticker: string): string {
  if (v === null) return '—';
  const base = v >= 1e9 ? `${(v / 1e9).toFixed(2)}B`
    : v >= 1e6 ? `${(v / 1e6).toFixed(2)}M`
    : v >= 1e3 ? `${(v / 1e3).toFixed(1)}K`
    : v.toLocaleString('en-US', { maximumFractionDigits: 2 });
  return ticker ? `${base} ${ticker}` : base;
}

function fmtTurnover(v: number | null): string {
  if (v === null) return '—';
  if (v >= 1e9) return `$${(v / 1e9).toFixed(2)}B`;
  if (v >= 1e6) return `$${(v / 1e6).toFixed(2)}M`;
  return `$${v.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
}

function fmtFunding(rate: number | null): string {
  if (rate === null) return '—';
  // Backend funding_rate is always a Binance fraction (lastFundingRate, e.g. 0.012 = 1.2%),
  // so always scale to percent — matches /markets and /symbols. The prior |rate|<0.01
  // guard understated high-funding symbols 100x.
  const pct = rate * 100;
  return `${pct >= 0 ? '+' : ''}${pct.toLocaleString('en-US', { minimumFractionDigits: 4, maximumFractionDigits: 6 })}%`;
}

function fmtNextFunding(iso: string | null): string {
  if (!iso) return '—';
  const ms = Date.parse(iso) - Date.now();
  if (!Number.isFinite(ms) || ms < 0) return iso;
  const h = Math.floor(ms / 3_600_000);
  const m = Math.floor((ms % 3_600_000) / 60_000);
  return `${h}h ${m.toString().padStart(2, '0')}m`;
}

function changeClass(v: number | null): string {
  if (v === null) return '';
  return v > 0 ? 'mdc-pos' : v < 0 ? 'mdc-neg' : '';
}

/** Honest liquidation-stream freshness: consult `stale`/`staleness_ms` before
 *  claiming Live — a stream_active flag with a stale payload is not "Live". */
function fmtLiquidationStream(status: {
  stream_active: boolean;
  stale?: boolean;
  staleness_ms?: number | null;
} | null): { value: string; tone?: string } {
  if (!status) return { value: 'Connecting' };
  if (status.stale) {
    const ms = status.staleness_ms;
    const age = ms != null && Number.isFinite(ms)
      ? ms < 90_000 ? `${Math.round(ms / 1000)}s` : ms < 5_400_000 ? `${Math.round(ms / 60_000)}m` : `${(ms / 3_600_000).toFixed(1)}h`
      : 'age unknown';
    return { value: `Stale ${age}`, tone: 'mdc-warn' };
  }
  if (status.stream_active) return { value: 'Live', tone: 'mdc-pos' };
  return { value: 'Inactive', tone: 'mdc-warn' };
}

// ── Enrichment formatters ──

/** Raw basis-point distances (e.g. 29.85 → "29.9 bps"). ≥9990 bps is the
 *  backend "no level on this side" sentinel → honest '—'. */
function fmtBpsDist(v: unknown): string {
  const n = finite(v);
  if (n === null || n >= 9990) return '—';
  return `${n.toLocaleString('en-US', { maximumFractionDigits: 1 })} bps`;
}

/** 0..1 fraction as percent, e.g. 0.94 → "94.0%". */
function fmtProbPct(v: unknown): string {
  const n = finite(v);
  return n === null ? '—' : `${(n * 100).toFixed(1)}%`;
}

function fmtScore(v: unknown): string {
  const n = finite(v);
  return n === null ? '—' : n.toFixed(3);
}

function fmtUsdCompact(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  const a = Math.abs(n);
  const s = n < 0 ? '-' : '';
  if (a >= 1e12) return `${s}$${(a / 1e12).toFixed(2)}T`;
  if (a >= 1e9) return `${s}$${(a / 1e9).toFixed(2)}B`;
  if (a >= 1e6) return `${s}$${(a / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${s}$${(a / 1e3).toFixed(1)}K`;
  return `${s}$${a.toFixed(2)}`;
}

/** Liquidation direction bias −1..1 → "92% shorts" / "60% longs". */
function fmtBias(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  if (n === 0) return 'balanced';
  return n > 0 ? `${(n * 100).toFixed(0)}% longs` : `${(-n * 100).toFixed(0)}% shorts`;
}

/** Honest upstream freshness: ISO string or epoch-ms → "5h 12m ago". */
function fmtAgo(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === '') return '—';
  const ts = typeof v === 'number' ? v : Date.parse(v);
  if (!Number.isFinite(ts)) return '—';
  const ms = Date.now() - ts;
  if (!Number.isFinite(ms)) return '—';
  if (ms < 0) return 'now';
  const m = Math.floor(ms / 60_000);
  if (m < 1) return '<1m ago';
  if (m < 60) return `${m}m ago`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h ${m % 60}m ago`;
  return `${Math.floor(h / 24)}d ago`;
}

function trendTone(v: string | null | undefined): string {
  if (!v) return '';
  const u = v.toUpperCase();
  if (u === 'UP' || u === 'BULLISH') return 'mdc-pos';
  if (u === 'DOWN' || u === 'BEARISH') return 'mdc-neg';
  if (u === 'MIXED') return 'mdc-warn';
  return '';
}

function cascadeTone(v: number | null): string {
  if (v === null) return '';
  return v >= 0.7 ? 'mdc-neg' : v >= 0.4 ? 'mdc-warn' : 'mdc-pos';
}

function takerTone(v: number | null): string {
  if (v === null) return '';
  return v > 0.55 ? 'mdc-pos' : v < 0.45 ? 'mdc-neg' : '';
}

function mergeTicker(base: TickerData | null, patch: TickerData): TickerData {
  return {
    symbol: patch.symbol ?? base?.symbol ?? 'BTCUSDT',
    last_price: patch.last_price ?? base?.last_price ?? null,
    mark_price: patch.mark_price ?? base?.mark_price ?? null,
    index_price: patch.index_price ?? base?.index_price ?? null,
    change_1h: patch.change_1h ?? base?.change_1h ?? null,
    change_4h: patch.change_4h ?? base?.change_4h ?? null,
    change_24h: patch.change_24h ?? base?.change_24h ?? null,
    high_24h: patch.high_24h ?? base?.high_24h ?? null,
    low_24h: patch.low_24h ?? base?.low_24h ?? null,
    volume_24h: patch.volume_24h ?? base?.volume_24h ?? null,
    turnover_24h: patch.turnover_24h ?? base?.turnover_24h ?? null,
    funding_rate: patch.funding_rate ?? base?.funding_rate ?? null,
    next_funding: patch.next_funding ?? base?.next_funding ?? null,
    open_interest: patch.open_interest ?? base?.open_interest ?? null,
    bid: patch.bid ?? base?.bid ?? null,
    ask: patch.ask ?? base?.ask ?? null,
    spread_bps: patch.spread_bps ?? base?.spread_bps ?? null,
  };
}

// ---------------------------------------------------------------------------
// Chart data normalisation
// ---------------------------------------------------------------------------

function toUtcTimestamp(v: number): UTCTimestamp | null {
  const n = v > 1_000_000_000_000 ? Math.floor(v / 1000) : v;
  return n > 0 ? (n as UTCTimestamp) : null;
}

function validOhlc(o: number, h: number, l: number, c: number): boolean {
  return o > 0 && h > 0 && l > 0 && c > 0 && l <= o && l <= c && h >= o && h >= c;
}

function normalizeCandles(rows: CandleRow[]): CandlestickData<UTCTimestamp>[] {
  const seen = new Set<number>();
  return rows
    .map((r): CandlestickData<UTCTimestamp> | null => {
      const t = toUtcTimestamp(r.time);
      const o = finite(r.open);
      const h = finite(r.high);
      const l = finite(r.low);
      const c = finite(r.close);
      if (t === null || o === null || h === null || l === null || c === null) return null;
      if (!validOhlc(o, h, l, c)) return null;
      if (seen.has(Number(t))) return null;
      seen.add(Number(t));
      return { time: t, open: o, high: h, low: l, close: c };
    })
    .filter((r): r is CandlestickData<UTCTimestamp> => r !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function normalizeVolume(rows: CandleRow[]): HistogramData<UTCTimestamp>[] {
  const seen = new Set<number>();
  return rows
    .map((r): HistogramData<UTCTimestamp> | null => {
      const t = toUtcTimestamp(r.time);
      const vol = finite(r.volume);
      if (t === null || vol === null) return null;
      if (seen.has(Number(t))) return null;
      seen.add(Number(t));
      const isUp = (finite(r.close) ?? 0) >= (finite(r.open) ?? 0);
      return { time: t, value: vol, color: isUp ? 'rgba(18,184,134,0.36)' : 'rgba(255,107,107,0.36)' };
    })
    .filter((r): r is HistogramData<UTCTimestamp> => r !== null)
    .sort((a, b) => Number(a.time) - Number(b.time));
}

function candleRowIdentity(row: CandleRow): number | null {
  const value = finite(row.open_time_ms) ?? finite(row.time);
  if (value === null) return null;
  return value > 1_000_000_000_000 ? value : value * 1000;
}

function mergeCandleRows(current: CandleRow[], incoming: CandleRow[], limit = 240): CandleRow[] {
  const byTime = new Map<number, CandleRow>();
  for (const row of current) {
    const identity = candleRowIdentity(row);
    if (identity === null) continue;
    byTime.set(identity, row);
  }
  for (const row of incoming) {
    const identity = candleRowIdentity(row);
    if (identity === null) continue;
    byTime.set(identity, row);
  }
  return [...byTime.entries()]
    .sort(([left], [right]) => left - right)
    .map(([, row]) => row)
    .slice(-limit);
}

// ---------------------------------------------------------------------------
// Auth: lightweight fetch-based hook (avoids external auth dep)
// ---------------------------------------------------------------------------

function useCurrentUser(): { user: CurrentUser | null; loading: boolean } {
  const [user, setUser] = useState<CurrentUser | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    async function check(): Promise<void> {
      try {
        const res = await fetch('/api/auth/me', { credentials: 'include' });
        if (!res.ok) { if (active) { setUser(null); setLoading(false); } return; }
        const json = (await res.json()) as { user?: unknown; data?: unknown };
        const raw = json?.user ?? json?.data ?? json;
        if (active) {
          setUser(raw && typeof raw === 'object' && 'id' in raw ? raw as CurrentUser : null);
          setLoading(false);
        }
      } catch {
        if (active) { setUser(null); setLoading(false); }
      }
    }
    void check();
    return () => { active = false; };
  }, []);

  return { user, loading };
}

// ---------------------------------------------------------------------------
// CandlestickChart
// ---------------------------------------------------------------------------

interface CandlestickChartProps {
  candles: CandleRow[];
  loading: boolean;
  error: string | null;
}

function CandlestickChart({ candles, loading, error }: CandlestickChartProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const fittedRef = useRef(false);

  // Create chart once
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return undefined;

    const chart = createChart(el, {
      width: el.clientWidth,
      height: 420,
      layout: {
        background: { type: ColorType.Solid, color: '#050e18' },
        textColor: '#8fa7ba',
      },
      grid: {
        vertLines: { color: 'rgba(130,150,179,0.13)' },
        horzLines: { color: 'rgba(130,150,179,0.13)' },
      },
      crosshair: {
        vertLine: { color: 'rgba(220,164,62,0.55)' },
        horzLine: { color: 'rgba(220,164,62,0.55)' },
      },
      rightPriceScale: {
        borderColor: 'rgba(130,150,179,0.2)',
        scaleMargins: { top: 0.08, bottom: 0.24 },
      },
      timeScale: {
        borderColor: 'rgba(130,150,179,0.2)',
        timeVisible: true,
        secondsVisible: false,
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
      priceScaleId: 'vol',
      priceLineVisible: false,
      lastValueVisible: false,
    });
    volumeSeries.priceScale().applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });

    chartRef.current = chart;
    candleSeriesRef.current = candleSeries;
    volumeSeriesRef.current = volumeSeries;
    fittedRef.current = false;

    const observer = new ResizeObserver(() => {
      chart.resize(el.clientWidth, 420);
    });
    observer.observe(el);

    return () => {
      observer.disconnect();
      chart.remove();
      chartRef.current = null;
      candleSeriesRef.current = null;
      volumeSeriesRef.current = null;
    };
  }, []);

  // Push new candle data
  useEffect(() => {
    if (!candles.length) return;
    const normalized = normalizeCandles(candles);
    const volume = normalizeVolume(candles);
    candleSeriesRef.current?.setData(normalized);
    volumeSeriesRef.current?.setData(volume);
    if (!fittedRef.current && normalized.length) {
      chartRef.current?.timeScale().fitContent();
      fittedRef.current = true;
    }
  }, [candles]);

  return (
    <div className="mdc-chart-wrap">
      <div ref={containerRef} className="mdc-chart-canvas" />
      {loading && !candles.length && (
        <div className="mdc-chart-overlay">
          <span className="mdc-spinner" />
          <span>Connecting chart stream</span>
        </div>
      )}
      {!loading && error && !candles.length && (
        <div className="mdc-chart-overlay mdc-chart-overlay--sync">
          <span className="mdc-spinner" />
          <span>Candle stream syncing</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat chip
// ---------------------------------------------------------------------------

function Stat({ label, value, tone }: { label: string; value: ReactNode; tone?: string }): JSX.Element {
  return (
    <div className="mdc-stat">
      <span className="mdc-stat__label">{label}</span>
      <strong className={`mdc-stat__value${tone ? ` ${tone}` : ''}`}>{value}</strong>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Long/short positioning bar (honest '—' when upstream ratios missing)
// ---------------------------------------------------------------------------

function LongShortBar({ long, short }: { long: number | null; short: number | null }): JSX.Element {
  if (long === null || short === null || long + short <= 0) {
    return (
      <div className="mdc-ls-legend mdc-ls-legend--empty">
        <span>Long / short accounts</span>
        <span>—</span>
      </div>
    );
  }
  const longPct = (long / (long + short)) * 100;
  const shortPct = 100 - longPct;
  return (
    <div className="mdc-ls-wrap">
      <div className="mdc-ls-legend">
        <span className="mdc-pos">Longs {longPct.toFixed(1)}%</span>
        <span className="mdc-neg">Shorts {shortPct.toFixed(1)}%</span>
      </div>
      <div
        className="mdc-ls-bar"
        role="img"
        aria-label={`Long accounts ${longPct.toFixed(1)} percent versus short accounts ${shortPct.toFixed(1)} percent`}
      >
        <span className="mdc-ls-bar__long" style={{ width: `${longPct}%` }} />
        <span className="mdc-ls-bar__short" style={{ width: `${shortPct}%` }} />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Signal panel
// ---------------------------------------------------------------------------

function signalAgeSeconds(signal: SignalData): number | null {
  const direct = finite(signal.market_age_seconds);
  if (direct !== null) return Math.max(0, Math.round(direct));
  if (typeof signal.generated_at === 'string' && signal.generated_at.trim()) {
    const generatedMs = Date.parse(signal.generated_at);
    if (Number.isFinite(generatedMs)) return Math.max(0, Math.round((Date.now() - generatedMs) / 1000));
  }
  return null;
}

function fmtSignalAge(seconds: number): string {
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

/** Confidence is a probability, not a signed change — render without '+'. */
function fmtConfidence(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}%`;
}

const SIGNAL_STALE_AGE_SECONDS = 600;

function SignalPanel({ signal, loading }: { signal: SignalData | null; loading: boolean }): JSX.Element {
  if (loading) {
    return (
      <div className="mdc-signal-panel mdc-signal-panel--loading">
        <span className="mdc-spinner" />
      </div>
    );
  }
  if (!signal?.selected_action) {
    return (
      <div className="mdc-signal-panel mdc-signal-panel--empty">
        <Sparkles size={16} />
        <span>AI signal stream connecting for this symbol</span>
      </div>
    );
  }
  const action = signal.selected_action;
  const isBuy = /long|buy/i.test(action);
  const isSell = /short|sell/i.test(action);
  // Surface the trainer-declared freshness: a days-old HOLD must never read as
  // a live "Active Prediction". source_freshness comes straight from the API;
  // market_age_seconds/generated_at back it up if the flag is absent.
  const ageSeconds = signalAgeSeconds(signal);
  const declaredStale = (signal.source_freshness ?? '').trim().toUpperCase() === 'STALE';
  const isStale = declaredStale || (ageSeconds !== null && ageSeconds > SIGNAL_STALE_AGE_SECONDS);
  return (
    <div className="mdc-signal-panel">
      <div className="mdc-signal-panel__head">
        {isBuy ? <TrendingUp size={15} /> : isSell ? <TrendingDown size={15} /> : <Sparkles size={15} />}
        <span className={isBuy ? 'mdc-pos' : isSell ? 'mdc-neg' : ''}>{action}</span>
        {isStale && (
          <span
            className="mdc-signal-panel__stale-chip"
            title={signal.generated_at ? `Generated ${signal.generated_at}` : 'Prediction is stale'}
          >
            Stale{ageSeconds !== null ? ` · ${fmtSignalAge(ageSeconds)} old` : ''}
          </span>
        )}
      </div>
      <div className="mdc-signal-panel__grid">
        <Stat label="Confidence" value={fmtConfidence(signal.confidence)} />
        <Stat label="Entry" value={fmtPrice(signal.entry)} />
        <Stat label="Target" value={fmtPrice(signal.target_1)} />
        <Stat label="Stop" value={fmtPrice(signal.stop)} />
        <Stat label="R/R" value={signal.risk_reward != null ? `${signal.risk_reward.toFixed(2)}x` : '—'} />
      </div>
      {(ageSeconds !== null || signal.generated_at) && (
        <div className="mdc-signal-panel__meta">
          {ageSeconds !== null ? `Generated ${fmtSignalAge(ageSeconds)} ago` : `Generated ${signal.generated_at}`}
          {isStale ? ' · not a live prediction' : ''}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Auth overlay (over chart when session expires mid-use)
// ---------------------------------------------------------------------------

function AuthOverlay({ symbol, onSignIn }: { symbol: string; onSignIn: () => void }): JSX.Element {
  return (
    <div className="mdc-auth-overlay" aria-label="Sign in required to view chart">
      <div className="mdc-auth-overlay__card">
        <ShieldCheck size={32} className="mdc-auth-overlay__icon" />
        <h3>Sign in to view {symbol}</h3>
        <p>A free account gives you access to live candlestick charts, AI signals, and derivatives analytics.</p>
        <button type="button" className="mdc-auth-overlay__btn" onClick={onSignIn}>
          Sign In
        </button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function MarketPage(): JSX.Element {
  const params = useParams();
  const navigate = useNavigate();
  const traderSnapshot = useTraderSnapshot();
  const requestedSymbol = (params.symbol ?? 'BTCUSDT').toUpperCase().trim();
  const safeSymbol = safeV2MarketSymbol(requestedSymbol);
  const symbol = safeSymbol ?? 'Invalid market symbol';
  const querySymbol = safeSymbol ?? '';

  const { user, loading: authLoading } = useCurrentUser();

  const [timeframe, setTimeframe] = useState<Timeframe>('1h');

  const marketStream = useMarketDataStream(querySymbol, 2_000, timeframe);
  const tickerResource = useRealtimeResource<MarketTickerData>({
    url: safeSymbol ? `/api/v2/market/${safeSymbol}` : '/api/v2/market/{symbol}',
    source: safeSymbol ? `/api/v2/market/${safeSymbol}` : '/api/v2/market/{symbol}',
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 12_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
  });
  const candleResource = useRealtimeResource<MarketCandlesData>({
    url: safeSymbol ? `/api/v2/market/${safeSymbol}/candles?timeframe=${timeframe}&limit=200` : '/api/v2/market/{symbol}/candles',
    source: safeSymbol ? `/api/v2/market/${safeSymbol}/candles` : '/api/v2/market/{symbol}/candles',
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 12_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
  });
  const depthResource = useRealtimeResource<MarketDepthData>({
    url: safeSymbol ? `/api/v2/market/${safeSymbol}/depth` : '/api/v2/market/{symbol}/depth',
    source: safeSymbol ? `/api/v2/market/${safeSymbol}/depth` : '/api/v2/market/{symbol}/depth',
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 12_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
  });
  const tradesResource = useRealtimeResource<RecentTradesData>({
    url: safeSymbol ? `/api/v2/market/${safeSymbol}/trades` : '/api/v2/market/{symbol}/trades',
    source: safeSymbol ? `/api/v2/market/${safeSymbol}/trades` : '/api/v2/market/{symbol}/trades',
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 12_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
  });
  const derivativesResource = useRealtimeResource<MarketDerivativesData>({
    url: safeSymbol ? `/api/v2/market/${safeSymbol}/derivatives?timeframe=${timeframe}` : '/api/v2/market/{symbol}/derivatives',
    source: safeSymbol ? `/api/v2/market/${safeSymbol}/derivatives` : '/api/v2/market/{symbol}/derivatives',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
  });
  const indicatorsResource = useRealtimeResource<MarketIndicatorsData>({
    url: safeSymbol ? `/api/v2/market/${safeSymbol}/indicators?timeframe=${timeframe}` : '/api/v2/market/{symbol}/indicators',
    source: safeSymbol ? `/api/v2/market/${safeSymbol}/indicators` : '/api/v2/market/{symbol}/indicators',
    source_type: 'websocket',
    pollIntervalMs: 4_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
  });
  const signalResource = useRealtimeResource<{ active_signal?: unknown }>({
    url: safeSymbol ? `/api/v2/signals?symbol=${safeSymbol}` : '/api/v2/signals?symbol={symbol}',
    source: `${symbol} signal stream`,
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
    enabled: Boolean(user && safeSymbol),
  });

  const streamTicker = useMemo(
    () => streamTickerForSymbol(marketStream.ticker, querySymbol),
    [marketStream.ticker, querySymbol],
  );
  const streamCandles = useMemo(
    () => streamCandlesForSymbol(marketStream.candles, querySymbol, timeframe),
    [marketStream.candles, querySymbol, timeframe],
  );
  const resourceTicker = useMemo(
    () => tickerForSymbol(tickerResource.envelope.data, querySymbol),
    [tickerResource.envelope.data, querySymbol],
  );
  const resourceCandles = useMemo(
    () => candleRowsForSymbol(candleResource.envelope.data, querySymbol, timeframe),
    [candleResource.envelope.data, querySymbol, timeframe],
  );
  const depth = useMemo(
    () => (marketStream.depth && envelopeMatchesSymbol(marketStream.depth, querySymbol) ? marketStream.depth.data : resourceForSymbol(depthResource.envelope.data, querySymbol)),
    [depthResource.envelope.data, marketStream.depth, querySymbol],
  );
  const trades = useMemo(
    () => (marketStream.trades && envelopeMatchesSymbol(marketStream.trades, querySymbol) ? marketStream.trades.data : resourceForSymbol(tradesResource.envelope.data, querySymbol)),
    [marketStream.trades, querySymbol, tradesResource.envelope.data],
  );
  const derivatives = useMemo(
    () => resourceForSymbol(derivativesResource.envelope.data, querySymbol),
    [derivativesResource.envelope.data, querySymbol],
  );
  const indicators = useMemo(
    () => resourceForSymbol(indicatorsResource.envelope.data, querySymbol),
    [indicatorsResource.envelope.data, querySymbol],
  );
  const ticker = useMemo(
    () => (streamTicker ? mergeTicker(resourceTicker, streamTicker) : resourceTicker),
    [resourceTicker, streamTicker],
  );
  const candles = useMemo(
    () => (streamCandles.length ? mergeCandleRows(resourceCandles, streamCandles) : resourceCandles),
    [resourceCandles, streamCandles],
  );
  const tickerError = tickerResource.error ?? tickerResource.envelope.errors[0] ?? null;
  const candleError = candleResource.error ?? candleResource.envelope.errors[0] ?? null;
  const tickerLoading = Boolean(safeSymbol) && tickerResource.loading && !streamTicker && !resourceTicker;
  const candleLoading = Boolean(safeSymbol) && candleResource.loading && streamCandles.length === 0 && resourceCandles.length === 0;

  const signInUrl = `/login?returnTo=${encodeURIComponent(`/market/${safeSymbol ?? 'BTCUSDT'}`)}`;
  function goSignIn(): void { navigate(signInUrl); }

  // ---------------------------------------------------------------------------
  // Derived values
  // ---------------------------------------------------------------------------

  const signal = user && safeSymbol ? (signalResource.envelope.data?.active_signal ?? null) as SignalData | null : null;
  const signalLoading = Boolean(user) && signalResource.loading && !signalResource.envelope.data;
  const canonicalMarket = safeSymbol ? selectMarketBySymbol(traderSnapshot, safeSymbol) ?? {} : {};
  const canonicalMarketMetric = (fieldId: string) => selectMarketMetric(traderSnapshot, canonicalMarket, fieldId);
  // The authenticated trader snapshot is 401-gated; for logged-out visitors fall
  // back to the public /api/v2/market/{symbol} ticker so the canonical LAST /
  // MARK / INDEX price cards render real, fresh values instead of "Source
  // offline" (same pattern as the /markets BTC canonical cards).
  const marketPriceMetric = (
    fieldId: string,
    publicKey: 'last_price' | 'mark_price' | 'index_price',
  ): CanonicalMetric => {
    const authed = canonicalMarketMetric(fieldId);
    if (authed.value != null) return authed;
    const publicValue = ticker?.[publicKey] ?? null;
    if (publicValue == null) return authed;
    const publicEnvelope = tickerResource.envelope;
    return {
      ...authed,
      value: publicValue,
      source: publicEnvelope.source ?? (safeSymbol ? `/api/v2/market/${safeSymbol}` : '/api/v2/market/{symbol}'),
      sourceType: publicEnvelope.source_type ?? 'api',
      timestamp: publicEnvelope.timestamp != null ? new Date(publicEnvelope.timestamp).toISOString() : null,
      ageMs: publicEnvelope.lag_ms ?? null,
      quality: 'valid',
    };
  };
  const change = ticker?.change_24h ?? null;
  const changeDisplay = useMemo(() => {
    if (change === null) return null;
    const pct = Math.abs(change) <= 1 ? change * 100 : change;
    return { pct, label: `${Math.abs(pct).toFixed(2)}%`, positive: pct >= 0 };
  }, [change]);

  const fundingRate = ticker?.funding_rate ?? null;
  const fundingTone = fundingRate === null ? '' : fundingRate >= 0 ? 'mdc-pos' : 'mdc-neg';

  // Auth overlay is shown mid-session only (TraderShell handles full redirect before mount)
  const showAuthOverlay = !authLoading && !user;
  const baseTicker = safeSymbol ? safeSymbol.replace('USDT', '') : 'MARKET';
  const latestTrade = trades?.trades?.[0] ?? null;
  const liquidationLevels = derivatives?.liquidation_levels ?? null;
  const liquidationStatus = derivatives?.liquidation_stream_status ?? null;
  const liquidationStream = fmtLiquidationStream(liquidationStatus);

  // ── Symbol enrichment (Redis blocks on /api/v2/market/{symbol}) ──
  // Read from the raw resource envelope: mergeTicker() strips extra fields.
  const enrichment = useMemo(
    () => resourceForSymbol(
      tickerResource.envelope.data as EnrichedTickerData | null | undefined,
      querySymbol,
    ),
    [tickerResource.envelope.data, querySymbol],
  );
  const longShort = enrichment?.long_short ?? null;
  const fundingDetail = enrichment?.funding_detail ?? null;
  const coinglass = enrichment?.coinglass ?? null;
  const regime1m = enrichment?.regime_1m ?? null;
  const ta1m = enrichment?.ta_1m ?? null;
  const liqLevels = enrichment?.liquidation_levels ?? null;
  const liqEnhanced = enrichment?.liquidation_enhanced ?? null;
  const liqFlow = enrichment?.liquidation_flow ?? null;
  // Sides with zero ladder levels report sentinel distances — render honest '—'.
  const liqDistLong = (liqLevels?.levels_count_long ?? null) === 0
    ? null
    : finite(liqLevels?.distance_to_long_liq_bps ?? enrichment?.distance_to_long_liq_bps);
  const liqDistShort = (liqLevels?.levels_count_short ?? null) === 0
    ? null
    : finite(liqLevels?.distance_to_short_liq_bps ?? enrichment?.distance_to_short_liq_bps);
  const cascadeRisk = finite(liqLevels?.liquidation_cascade_risk ?? enrichment?.liquidation_cascade_risk);
  const takerBuyRatio = finite(enrichment?.taker_buy_ratio);
  const altScore = finite(enrichment?.altdata_symbol_score);
  const altRank = finite(enrichment?.altdata_symbol_rank);
  const htfTrendValue = regime1m?.htf_trend ?? enrichment?.htf_trend ?? null;
  const rsiZoneValue = regime1m?.rsi_zone ?? enrichment?.rsi_zone ?? null;
  const macdDirValue = regime1m?.macd_direction ?? enrichment?.macd_direction ?? null;
  const regimeConfidence = finite(regime1m?.confidence);

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <main className="mdc-page" data-testid="page-market-detail">
      <div className="mdc-bg" aria-hidden="true" />

      {/* ── Symbol header ── */}
      <header className="mdc-header" data-testid="market-symbol-header">
        <div className="mdc-header__title">
          <span className="mdc-kicker">Perpetual Futures · Live Market</span>
          <h1>
            {symbol}
            {safeSymbol && <span className="mdc-header__price"><CanonicalMetricValue metric={marketPriceMetric('market.last_price', 'last_price')} /></span>}
            {changeDisplay && (
              <span className={`mdc-header__change ${changeDisplay.positive ? 'mdc-pos' : 'mdc-neg'}`}>
                {changeDisplay.positive ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
                {changeDisplay.label}
              </span>
            )}
          </h1>
        </div>

        <div className="mdc-header__strip">
          <div className="mdc-hstat">
            <span>Last Price</span>
            <strong><CanonicalMetricValue metric={marketPriceMetric('market.last_price', 'last_price')} /></strong>
          </div>
          <div className="mdc-hstat">
            <span>Mark Price</span>
            <strong><CanonicalMetricValue metric={marketPriceMetric('market.mark_price', 'mark_price')} /></strong>
          </div>
          <div className="mdc-hstat">
            <span>Index Price</span>
            <strong><CanonicalMetricValue metric={marketPriceMetric('market.index_price', 'index_price')} /></strong>
          </div>
          {ticker ? (
            <>
              <div className="mdc-hstat">
                <span>24h High</span>
                <strong className="mdc-pos">{fmtPrice(ticker.high_24h)}</strong>
              </div>
              <div className="mdc-hstat">
                <span>24h Low</span>
                <strong className="mdc-neg">{fmtPrice(ticker.low_24h)}</strong>
              </div>
              <div className="mdc-hstat">
                <span>Volume</span>
                <strong>{fmtVolume(ticker.volume_24h, baseTicker)}</strong>
              </div>
              <div className="mdc-hstat">
                <span>Turnover</span>
                <strong>{fmtTurnover(ticker.turnover_24h)}</strong>
              </div>
            </>
          ) : tickerLoading ? (
            <span className="mdc-header__loading">Connecting market stream…</span>
          ) : (
            <span className="mdc-header__error">Live market stream syncing</span>
          )}
        </div>
      </header>

      {!safeSymbol && (
        <section className="mdc-panel mdc-invalid-panel" role="status" aria-label="Invalid market symbol">
          <div className="mdc-stats-error">
            <AlertTriangle size={16} />
            <span>Enter a valid market symbol to connect the realtime market stream.</span>
          </div>
        </section>
      )}

      {/* ── Chart + Stats row (70/30 split) ── */}
      <div className="mdc-chart-section" data-testid="market-chart-section">
        {/* Chart — hero element */}
        <div className="mdc-chart-col">
          <div className="mdc-panel mdc-chart-panel" data-testid="chart-panel">
            {/* Timeframe toolbar */}
            <div className="mdc-toolbar">
              <div className="mdc-toolbar__tf" role="group" aria-label="Chart timeframe">
                {TIMEFRAMES.map((tf) => (
                  <button
                    key={tf}
                    type="button"
                    className={`mdc-tf-btn${timeframe === tf ? ' mdc-tf-btn--active' : ''}`}
                    onClick={() => setTimeframe(tf)}
                    aria-pressed={timeframe === tf}
                  >
                    {tf}
                  </button>
                ))}
              </div>
              <span className="mdc-toolbar__symbol">{symbol} · {timeframe}</span>
            </div>

            {/* Chart canvas + optional auth overlay */}
            <div className="mdc-chart-container">
              <CandlestickChart candles={candles} loading={candleLoading} error={candleError} />
              {showAuthOverlay && <AuthOverlay symbol={symbol} onSignIn={goSignIn} />}
            </div>

            {/* Funding / OI / Mark / Next Funding strip */}
            <div className="mdc-bottom-strip">
              <div>
                <span>Funding Rate</span>
                <strong className={fundingTone}>{fmtFunding(fundingRate)}</strong>
              </div>
              <div>
                <span>Open Interest</span>
                <strong>{fmtCompact(ticker?.open_interest ?? null)}</strong>
              </div>
              <div>
                <span>Mark Price</span>
                <strong>{fmtPrice(ticker?.mark_price ?? null)}</strong>
              </div>
              <div>
                <span>Next Funding</span>
                <strong>{fmtNextFunding(ticker?.next_funding ?? null)}</strong>
              </div>
            </div>
          </div>
        </div>

        {/* Stats sidebar */}
        <aside className="mdc-stats-col">
          <div className="mdc-panel mdc-stats-panel">
            <div className="mdc-panel__head">
              <span className="mdc-panel__eyebrow">Instrument</span>
              <h2>Market Stats</h2>
            </div>

            {tickerLoading && !ticker && (
              <div className="mdc-stats-loading"><span className="mdc-spinner" /></div>
            )}

            {!tickerLoading && tickerError && !ticker && (
              <div className="mdc-stats-error">
                <AlertTriangle size={14} />
                <span>Live market stream syncing</span>
              </div>
            )}

            {ticker && (
              <div className="mdc-stats-grid">
                <Stat label="Last price" value={<CanonicalMetricValue metric={marketPriceMetric('market.last_price', 'last_price')} />} />
                <Stat label="Mark Price" value={<CanonicalMetricValue metric={marketPriceMetric('market.mark_price', 'mark_price')} />} />
                <Stat label="Index Price" value={<CanonicalMetricValue metric={marketPriceMetric('market.index_price', 'index_price')} />} />
                <Stat label="1h Change" value={fmtPct(ticker.change_1h ?? null)} tone={changeClass(ticker.change_1h ?? null)} />
                <Stat label="4h Change" value={fmtPct(ticker.change_4h ?? null)} tone={changeClass(ticker.change_4h ?? null)} />
                <Stat label="24h High" value={fmtPrice(ticker.high_24h)} tone="mdc-pos" />
                <Stat label="24h Low" value={fmtPrice(ticker.low_24h)} tone="mdc-neg" />
                <Stat label="24h Change" value={fmtPct(ticker.change_24h)} tone={changeClass(ticker.change_24h)} />
                <Stat label="Volume" value={fmtVolume(ticker.volume_24h, baseTicker)} />
                <Stat label="Turnover" value={fmtTurnover(ticker.turnover_24h)} />
                <Stat label="Funding Rate" value={fmtFunding(ticker.funding_rate)} tone={fundingTone} />
                <Stat label="Next Funding" value={fmtNextFunding(ticker.next_funding ?? null)} />
                <Stat label="Open Interest" value={fmtCompact(ticker.open_interest)} />
              </div>
            )}
          </div>
        </aside>
      </div>

      {/* ── Symbol enrichment: positioning, TA, liquidation proximity, scores ── */}
      {safeSymbol && (
        <div className="mdc-enrich-grid" data-testid="market-enrichment-section">
          {/* Funding · OI · Long/Short positioning */}
          <div className="mdc-panel" data-testid="enrich-positioning-panel">
            <div className="mdc-panel__head">
              <span className="mdc-panel__eyebrow">Positioning</span>
              <h2>Funding · OI · Long/Short</h2>
            </div>
            <LongShortBar
              long={finite(longShort?.long_account_ratio)}
              short={finite(longShort?.short_account_ratio)}
            />
            <div className="mdc-stats-grid">
              <Stat
                label="L/S Ratio"
                value={finite(longShort?.long_short_ratio) !== null ? `${(longShort?.long_short_ratio as number).toFixed(2)}x` : '—'}
              />
              <Stat
                label="Basis"
                value={fmtBpsDist(fundingDetail?.basis_bps ?? enrichment?.basis_bps ?? null)}
                tone={changeClass(finite(fundingDetail?.basis_bps ?? enrichment?.basis_bps))}
              />
              <Stat
                label="OI Δ 1h"
                value={fmtUsdCompact(coinglass?.open_interest_delta_1h_usd ?? enrichment?.open_interest_delta_1h_usd ?? null)}
                tone={changeClass(finite(coinglass?.open_interest_delta_1h_usd ?? enrichment?.open_interest_delta_1h_usd))}
              />
              <Stat
                label="Coinglass OI"
                value={fmtUsdCompact(coinglass?.open_interest_usd ?? enrichment?.coinglass_open_interest_usd ?? null)}
              />
              <Stat label="Funding z-score" value={fmtScore(coinglass?.funding_rate_zscore)} />
              <Stat label="Est. Settle" value={fmtPrice(fundingDetail?.estimated_settle_price ?? null)} />
            </div>
            <p className="mdc-foot">
              L/S accounts {longShort?.period ?? '—'} · upstream fetched {fmtAgo(longShort?.fetched_utc)}
            </p>
          </div>

          {/* TA summary — 1m closed candles */}
          <div className="mdc-panel" data-testid="enrich-ta-panel">
            <div className="mdc-panel__head">
              <span className="mdc-panel__eyebrow">Technicals · 1m</span>
              <h2>TA Summary</h2>
            </div>
            <div className="mdc-stats-grid">
              <Stat
                label="RSI (14)"
                value={finite(enrichment?.rsi_1m) !== null ? (enrichment?.rsi_1m as number).toFixed(1) : '—'}
                tone={trendTone(rsiZoneValue)}
              />
              <Stat label="ATR" value={fmtPrice(enrichment?.atr_1m ?? null)} />
              <Stat
                label="ADX"
                value={finite(enrichment?.adx_1m) !== null ? (enrichment?.adx_1m as number).toFixed(1) : '—'}
              />
              <Stat label="HTF Trend" value={htfTrendValue ?? '—'} tone={trendTone(htfTrendValue)} />
              <Stat label="RSI Zone" value={rsiZoneValue ?? '—'} tone={trendTone(rsiZoneValue)} />
              <Stat label="MACD" value={macdDirValue ?? '—'} tone={trendTone(macdDirValue)} />
              <Stat
                label="Regime"
                value={regime1m?.regime
                  ? `${regime1m.regime}${regimeConfidence !== null ? ` · ${(regimeConfidence * 100).toFixed(0)}%` : ''}`
                  : '—'}
              />
              <Stat label="Risk State" value={regime1m?.market_risk_state ?? '—'} />
            </div>
            <p className="mdc-foot">
              {finite(ta1m?.indicator_count) !== null ? `${ta1m?.indicator_count} indicators` : 'Indicator set —'}
              {ta1m?.closed_candles_only ? ' · closed candles only' : ''}
              {' · computed '}
              {fmtAgo(ta1m?.generated_utc)}
            </p>
          </div>

          {/* Liquidation proximity */}
          <div className="mdc-panel" data-testid="enrich-liquidation-panel">
            <div className="mdc-panel__head">
              <span className="mdc-panel__eyebrow">Liquidations</span>
              <h2>Level Proximity</h2>
            </div>
            <div className="mdc-stats-grid">
              <Stat label="Cascade Risk" value={fmtProbPct(cascadeRisk)} tone={cascadeTone(cascadeRisk)} />
              <Stat
                label="Market Stress"
                value={fmtProbPct(liqEnhanced?.market_stress_indicator)}
                tone={cascadeTone(finite(liqEnhanced?.market_stress_indicator))}
              />
              <Stat label="To Long Liq" value={fmtBpsDist(liqDistLong)} />
              <Stat label="To Short Liq" value={fmtBpsDist(liqDistShort)} />
              <Stat label="Level Above" value={fmtPrice(posPriceOrNull(liqLevels?.nearest_level_above))} />
              <Stat label="Level Below" value={fmtPrice(posPriceOrNull(liqLevels?.nearest_level_below))} />
              <Stat label="Sweep ↑" value={fmtPrice(posPriceOrNull(liqLevels?.sweep_target_short))} />
              <Stat label="Sweep ↓" value={fmtPrice(posPriceOrNull(liqLevels?.sweep_target_long))} />
              <Stat
                label="1h Liq Flow"
                value={fmtUsdCompact(liqFlow?.notional_1h ?? enrichment?.liq_notional_1h ?? null)}
              />
              <Stat
                label="1h Prints"
                value={finite(liqFlow?.count_1h ?? enrichment?.liq_count_1h) !== null
                  ? `${liqFlow?.count_1h ?? enrichment?.liq_count_1h} · ${fmtBias(liqFlow?.direction_bias_1h ?? enrichment?.liq_direction_bias_1h)}`
                  : '—'}
              />
            </div>
            <p className="mdc-foot">
              Ladder {finite(liqLevels?.levels_count_long) !== null ? `${liqLevels?.levels_count_long}L / ${liqLevels?.levels_count_short ?? '—'}S levels` : '—'}
              {' · updated '}
              {fmtAgo(liqLevels?.updated_ts_ms ?? null)}
            </p>
          </div>

          {/* Alt-data, CoinAnk, taker flow, smart money */}
          <div className="mdc-panel" data-testid="enrich-scores-panel">
            <div className="mdc-panel__head">
              <span className="mdc-panel__eyebrow">Alt-Data &amp; Flow</span>
              <h2>Symbol Scores</h2>
            </div>
            <div className="mdc-stats-grid">
              <Stat
                label="Symbol Score"
                value={altScore !== null ? `${altScore.toFixed(3)}${altRank !== null ? ` · #${altRank}` : ''}` : '—'}
              />
              <Stat label="CoinAnk Deriv" value={fmtScore(enrichment?.coinank_derivatives_score)} />
              <Stat
                label="Mkt Cap Rank"
                value={finite(enrichment?.market_cap_rank) !== null ? `#${enrichment?.market_cap_rank}` : '—'}
              />
              <Stat label="Market Cap" value={fmtUsdCompact(enrichment?.market_cap_usd ?? null)} />
              <Stat
                label="7d Change"
                value={fmtPct(enrichment?.change_7d ?? null)}
                tone={changeClass(finite(enrichment?.change_7d))}
              />
              <Stat
                label="Taker Buys"
                value={takerBuyRatio !== null ? `${(takerBuyRatio * 100).toFixed(1)}%` : '—'}
                tone={takerTone(takerBuyRatio)}
              />
              <Stat
                label="Flow Prints"
                value={finite(enrichment?.taker_flow_trade_count) !== null ? `${enrichment?.taker_flow_trade_count} trades` : '—'}
              />
              <Stat label="Smart Money" value="—" />
            </div>
            <p className="mdc-foot">
              Smart-money flag: no verified per-symbol source yet — shown only when evidence exists
            </p>
          </div>
        </div>
      )}

      {/* ── Lower grid: AI Signal + Derivatives + Source ── */}
      <div className="mdc-lower-grid">
        {/* Microstructure */}
        <div className="mdc-panel" data-testid="market-microstructure-section">
          <div className="mdc-panel__head">
            <span className="mdc-panel__eyebrow">Microstructure</span>
            <h2>Order book &amp; tape</h2>
          </div>
          <div className="mdc-stats-grid">
            <Stat label="Order book" value={depth ? `${depth.bids.length} bid / ${depth.asks.length} ask` : 'Connecting'} />
            <Stat label="Spread" value={fmtBps(depth?.spread_bps ?? ticker?.spread_bps ?? null)} />
            <Stat label="Bid" value={fmtPrice(ticker?.bid ?? depth?.bids?.[0]?.[0] ?? null)} />
            <Stat label="Ask" value={fmtPrice(ticker?.ask ?? depth?.asks?.[0]?.[0] ?? null)} />
            <Stat label="Recent trades" value={trades?.trades?.length ? `${trades.trades.length} prints` : 'Connecting'} />
            <Stat label="Last tape" value={latestTrade ? `${latestTrade.side.toUpperCase()} ${fmtPrice(latestTrade.price)}` : 'Connecting'} />
          </div>
        </div>

        {/* AI Signal */}
        <div className="mdc-panel" data-testid="market-signal-section">
          <div className="mdc-panel__head">
            <span className="mdc-panel__eyebrow">AI / Signals</span>
            <h2>Active Prediction</h2>
          </div>
          {showAuthOverlay ? (
            <div className="mdc-signal-panel mdc-signal-panel--auth">
              <ShieldCheck size={16} />
              <span>
                Sign in to see AI signals.{' '}
                <button type="button" className="mdc-inline-link" onClick={goSignIn}>
                  Sign In <ChevronRight size={12} aria-hidden="true" />
                </button>
              </span>
            </div>
          ) : (
            <SignalPanel signal={signal} loading={signalLoading} />
          )}
        </div>

        {/* Derivatives */}
        <div className="mdc-panel" data-testid="market-derivatives-section">
          <div className="mdc-panel__head">
            <span className="mdc-panel__eyebrow">Derivatives</span>
            <h2>Funding &amp; OI</h2>
          </div>
          <div className="mdc-stats-grid">
            <Stat label="Funding Rate" value={fmtFunding(derivatives?.funding_rate ?? fundingRate)} tone={fundingTone} />
            <Stat label="Next Funding" value={fmtNextFunding(derivatives?.next_funding ?? ticker?.next_funding ?? null)} />
            <Stat label="Open Interest" value={fmtCompact(derivatives?.open_interest ?? ticker?.open_interest ?? null)} />
            <Stat label="Mark Price" value={fmtPrice(ticker?.mark_price ?? null)} />
            <Stat label="Index Price" value={fmtPrice(ticker?.index_price ?? null)} />
            <Stat label="Long / Short" value={fmtCompact(derivatives?.long_short_ratio ?? null)} />
            <Stat label="Liquidation stream" value={liquidationStream.value} tone={liquidationStream.tone} />
            <Stat
              label="Liquidation levels"
              value={liquidationLevels
                ? `${fmtPrice(liquidationLevels.long_level)} / ${fmtPrice(liquidationLevels.short_level)}`
                : 'Connecting'}
            />
            <Stat label="Funding history" value={`${derivatives?.funding_history?.length ?? 0} rows`} />
            <Stat label="Open interest history" value={`${derivatives?.open_interest_history?.length ?? 0} rows`} />
          </div>
        </div>

        {/* Symbol intelligence: microstructure, whale walls, alt-data, HTF, cross-venue */}
        {safeSymbol && <SymbolIntelSection symbol={safeSymbol} />}

        {/* Source / Evidence */}
        <div className="mdc-panel" data-testid="market-evidence-section">
          <div className="mdc-panel__head">
            <span className="mdc-panel__eyebrow">Evidence</span>
            <h2>Data Sources</h2>
          </div>
          <div className="mdc-meta-grid" data-testid="market-evidence-drawer">
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Market stream</span>
              <strong className={tickerError ? 'mdc-neg' : ticker ? 'mdc-pos' : ''}>
                {tickerError ? 'Connecting stream fallback…' : streamTicker ? 'Realtime stream' : ticker ? 'Fallback connected' : 'Connecting stream…'}
              </strong>
            </div>
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Candle source</span>
              <strong className={candleError && !candles.length ? 'mdc-neg' : candles.length ? 'mdc-pos' : ''}>
                {candleError && !candles.length
                  ? 'Connecting stream fallback…'
                  : candles.length
                    ? `${candles.length} bars · ${timeframe}`
                    : 'Connecting stream…'}
              </strong>
            </div>
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Mode</span>
              <strong>Live market view</strong>
            </div>
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Indicators</span>
              <strong className={indicators?.indicator_count ? 'mdc-pos' : ''}>
                {indicators?.indicator_count ? `${indicators.indicator_count} current indicator source` : 'Current indicator source connecting'}
              </strong>
            </div>
            <div className="mdc-meta-row">
              <ShieldCheck size={14} aria-hidden="true" />
              <span>Source validation</span>
              <strong className={derivatives?.production_source_validation?.valid ? 'mdc-pos' : ''}>
                {derivatives?.production_source_validation?.valid ? 'Source evidence verified' : 'Source evidence pending'}
              </strong>
            </div>
            <div className="mdc-meta-row">
              <ShieldCheck size={14} aria-hidden="true" />
              <span>Execution routing</span>
              <strong className="mdc-pos">GUARDED</strong>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
