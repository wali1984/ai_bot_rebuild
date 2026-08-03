import { useEffect, useMemo, useRef, useState, useCallback } from 'react';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useMarketDataStream } from '../../hooks/useMarketDataStream';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useAuth } from '../../hooks/useAuth';
import type { MarketCandlesData, MarketTickerData } from '../../types/apiV2';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { useAdaptiveCapitalDashboard } from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types ───────────────────────────────────────────────────────────────────

interface Position {
  symbol?: string;
  side?: string;
  quantity?: number;
  size?: number;
  entry_price?: number;
  mark_price?: number;
  unrealized_pnl?: number;
  unrealized_pnl_pct?: number;
  leverage?: number;
  liquidation_price?: number;
}

interface Order {
  id?: string;
  symbol?: string;
  side?: string;
  type?: string;
  quantity?: number;
  qty?: number;
  price?: number;
  status?: string;
  created_at?: string;
}

interface Execution {
  symbol?: string;
  side?: string;
  quantity?: number;
  qty?: number;
  price?: number;
  fee?: number;
  status?: string;
  created_at?: string;
}

interface AccountSnapshot {
  total_wallet_balance?: number;
  available_balance?: number;
  total_unrealized_profit?: number;
  total_margin_balance?: number;
  total_cross_un_pnl?: number;
  max_withdraw_amount?: number;
}

interface ExchangeAccountData {
  trader_id?: string;
  paper_account_id?: string;
  exchange?: string;
  account_type?: string;
  account_specific?: boolean;
  read_only?: boolean;
  live_trading_enabled?: boolean;
  account_snapshot?: AccountSnapshot | null;
  positions?: Position[];
  positions_count?: number;
  trade_permission_status?: string;
  margin_mode_evidence?: string | null;
  leverage_evidence?: string | null;
  credential_status?: { configured?: boolean; raw_credential_value_exposed?: boolean; live_trading_enabled?: boolean };
}

interface SignalRow {
  id: string;
  symbol: string;
  direction: string | null;
  status: string;
  confidence: number | null;
  entry: number | null;
  target1: number | null;
  stop: number | null;
  risk_reward: number | null;
  strategy: string | null;
  model_version: string | null;
  risk_decision: string | null;
  risk_reason: string | null;
  created_at: string | null;
}

interface SignalsData {
  active: SignalRow[];
  pending: SignalRow[];
  total: number;
}

interface PredictionsData {
  predictions: Array<{ action?: string | null; confidence?: number | null; model_version?: string | null; symbol?: string | null }>;
  count: number;
  trainer_status: string | null;
}

interface PortfolioData {
  equity?: number;
  realized_pnl?: number;
  unrealized_pnl?: number;
  positions?: Position[];
}

// ─── Symbol list ──────────────────────────────────────────────────────────────
// No hardcoded symbol list: options come from the trader's saved watchlist plus
// the live /api/v2/market/overview adaptive universe (operator policy).

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '4h', '1d'] as const;
type TF = (typeof TIMEFRAMES)[number];

const BOTTOM_TABS = ['Positions', 'Orders', 'Executions', 'Signals', 'AI'] as const;
type BottomTab = (typeof BOTTOM_TABS)[number];

// ─── Formatters ───────────────────────────────────────────────────────────────

function fmtPrice(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return n >= 1000
    ? n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
    : n < 0.001
    ? n.toFixed(8)
    : n.toFixed(4);
}

function fmtMoney(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const abs = Math.abs(n);
  const prefix = n < 0 ? '-' : '';
  if (abs >= 1_000_000) return `${prefix}$${(abs / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `${prefix}$${(abs / 1_000).toFixed(2)}K`;
  return `${prefix}$${abs.toFixed(2)}`;
}

function fmtPct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  const p = Math.abs(n) <= 1 ? n * 100 : n;
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;
}

/** Base-asset quantity (e.g. BTC units) — never a dollar amount, so no $ prefix. */
function fmtBaseVol(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(2)}K`;
  return n.toFixed(2);
}

function pnlColor(n: number | null | undefined): string {
  if (n == null) return 'var(--text-muted)';
  return n >= 0 ? 'var(--buy, #26a69a)' : 'var(--sell, #ef5350)';
}

function dirColor(d: string | null | undefined): string {
  if (!d) return 'var(--text-muted)';
  const l = d.toLowerCase();
  if (l === 'long' || l === 'buy') return 'var(--buy, #26a69a)';
  if (l === 'short' || l === 'sell') return 'var(--sell, #ef5350)';
  return 'var(--text-muted)';
}

// ─── Sub-components ───────────────────────────────────────────────────────────

function KV({ label, value, color, mono = true }: { label: string; value: string; color?: string; mono?: boolean }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)', color: color ?? 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  );
}

function ConnDot({ connected, label }: { connected: boolean; label: string }): JSX.Element {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 5, fontSize: 11, color: connected ? 'var(--buy, #26a69a)' : 'var(--text-muted)' }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: connected ? 'var(--buy, #26a69a)' : 'var(--text-muted)', boxShadow: connected ? '0 0 6px var(--buy, #26a69a)' : 'none' }} />
      {label}
    </span>
  );
}

function LiveBadge(): JSX.Element {
  return (
    <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, padding: '2px 8px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: 'color-mix(in oklch, var(--sell, #ef5350) 12%, transparent)', border: '1px solid color-mix(in oklch, var(--sell, #ef5350) 35%, transparent)', color: 'var(--sell, #ef5350)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
      ✕ Execution Blocked
    </span>
  );
}

// ─── Chart component ──────────────────────────────────────────────────────────

function BinanceChart({ symbol, timeframe, streamCandle }: { symbol: string; timeframe: TF; streamCandle: unknown | null }): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const [chartError, setChartError] = useState<string | null>(null);
  const [lastCount, setLastCount] = useState(0);
  const candleUrl = `/api/v2/market/${symbol}/candles?timeframe=${encodeURIComponent(timeframe)}&limit=500`;
  const {
    envelope: candleEnv,
    loading: candleLoading,
    error: candleError,
  } = useRealtimeResource<MarketCandlesData>({
    url: candleUrl,
    source: `/api/v2/market/${symbol}/candles`,
    source_type: 'websocket',
    pollIntervalMs: 5_000,
    staleThresholdMs: 20_000,
    mode: 'read_only',
  });

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      width: container.clientWidth,
      height: container.clientHeight,
      layout: { background: { type: ColorType.Solid, color: 'transparent' }, textColor: 'rgba(255,255,255,0.6)' },
      grid: { vertLines: { color: 'rgba(255,255,255,0.04)' }, horzLines: { color: 'rgba(255,255,255,0.04)' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: 'rgba(255,255,255,0.08)' },
      timeScale: { borderColor: 'rgba(255,255,255,0.08)', timeVisible: true, secondsVisible: false },
    });
    chartRef.current = chart;
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderUpColor: '#26a69a', borderDownColor: '#ef5350', wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    candleSeriesRef.current = candleSeries;
    const volumeSeries = chart.addSeries(HistogramSeries, {
      color: 'rgba(38, 166, 154, 0.3)', priceFormat: { type: 'volume' }, priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    volumeSeriesRef.current = volumeSeries;
    const ro = new ResizeObserver(() => {
      if (container) chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    });
    ro.observe(container);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; candleSeriesRef.current = null; volumeSeriesRef.current = null; };
  }, []);

  useEffect(() => {
    const candles = candleEnv.data?.candles ?? [];
    if (!candles.length || !candleSeriesRef.current || !volumeSeriesRef.current) return;
    try {
      const bars = candles
        .filter((c) => c.open_time_ms && c.open != null && c.high != null && c.low != null && c.close != null)
        .map((c) => ({
          time: Math.floor(c.open_time_ms! / 1000) as UTCTimestamp,
          open: c.open!,
          high: c.high!,
          low: c.low!,
          close: c.close!,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));
      const vols = candles
        .filter((c) => c.open_time_ms && c.volume != null)
        .map((c) => ({
          time: Math.floor(c.open_time_ms! / 1000) as UTCTimestamp,
          value: c.volume ?? 0,
          color: (c.close ?? 0) >= (c.open ?? 0) ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)',
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));
      candleSeriesRef.current.setData(bars);
      volumeSeriesRef.current.setData(vols);
      setLastCount(bars.length);
      setChartError(null);
      chartRef.current?.timeScale().fitContent();
    } catch (e) {
      setChartError(String(e));
    }
  }, [candleEnv.data?.candles]);

  useEffect(() => {
    if (!streamCandle || !candleSeriesRef.current) return;
    const c = streamCandle as Record<string, unknown>;
    const openTimeMs = typeof c.open_time_ms === 'number' ? c.open_time_ms : null;
    if (!openTimeMs) return;
    const time = Math.floor(openTimeMs / 1000) as UTCTimestamp;
    const open = Number(c.open); const high = Number(c.high); const low = Number(c.low); const close = Number(c.close);
    if (!Number.isFinite(open) || !Number.isFinite(close)) return;
    try { candleSeriesRef.current.update({ time, open, high, low, close }); } catch { /* ignore out-of-order */ }
    if (volumeSeriesRef.current) {
      try { volumeSeriesRef.current.update({ time, value: Number(c.volume) || 0, color: close >= open ? 'rgba(38,166,154,0.35)' : 'rgba(239,83,80,0.35)' }); } catch { /* ignore */ }
    }
  }, [streamCandle]);

  return (
    <div style={{ position: 'relative', width: '100%', height: '100%' }}>
      <div ref={containerRef} style={{ width: '100%', height: '100%' }} />
      {candleLoading && lastCount === 0 && (
        <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(0,0,0,0.3)', borderRadius: 4 }}>
          <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>Syncing candles…</span>
        </div>
      )}
      {(chartError || candleError) && !candleLoading && lastCount === 0 && (
        <div style={{ position: 'absolute', bottom: 8, left: 8, fontSize: 11, color: 'var(--warn, #f59e0b)' }}>Chart stream reconnecting: {chartError ?? candleError}</div>
      )}
    </div>
  );
}

// ─── Order Book ───────────────────────────────────────────────────────────────

function OrderBook({ bids, asks, lastPrice }: { bids: Array<[number | null, number | null]>; asks: Array<[number | null, number | null]>; lastPrice: number | null }): JSX.Element {
  const maxSize = Math.max(...bids.map((r) => Number(r[1] ?? 0)), ...asks.map((r) => Number(r[1] ?? 0)), 1);
  const askRows = [...asks].filter((r) => r[0] != null).sort((a, b) => Number(b[0]) - Number(a[0])).slice(0, 12);
  const bidRows = [...bids].filter((r) => r[0] != null).sort((a, b) => Number(b[0]) - Number(a[0])).slice(0, 12);

  function Row({ price, size, side }: { price: number | null; size: number | null; side: 'bid' | 'ask' }): JSX.Element {
    const pct = Math.min(100, (Number(size ?? 0) / maxSize) * 100);
    const color = side === 'bid' ? 'var(--buy, #26a69a)' : 'var(--sell, #ef5350)';
    const bgColor = side === 'bid' ? 'rgba(38,166,154,0.07)' : 'rgba(239,83,80,0.07)';
    return (
      <div style={{ position: 'relative', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, padding: '2px 8px', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
        <div style={{ position: 'absolute', inset: 0, background: bgColor, width: `${pct}%`, right: 0, left: 'auto' }} />
        <span style={{ color, zIndex: 1, position: 'relative' }}>{fmtPrice(price)}</span>
        <span style={{ color: 'var(--text-secondary)', zIndex: 1, position: 'relative', textAlign: 'right' }}>{size != null ? Number(size).toFixed(3) : '—'}</span>
      </div>
    );
  }

  const spread = (askRows[askRows.length - 1]?.[0] ?? 0) - (bidRows[0]?.[0] ?? 0);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%', overflow: 'hidden' }}>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 4, padding: '4px 8px 2px', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid var(--border)' }}>
        <span>Price (USDT)</span><span style={{ textAlign: 'right' }}>Size</span>
      </div>
      <div style={{ flex: 1, overflowY: 'auto', display: 'flex', flexDirection: 'column' }}>
        {askRows.map((r, i) => <Row key={`ask-${i}`} price={r[0]} size={r[1]} side="ask" />)}
        <div style={{ padding: '4px 8px', display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderTop: '1px solid var(--border)', borderBottom: '1px solid var(--border)', background: 'var(--bg-elevated)' }}>
          <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{fmtPrice(lastPrice)}</span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>Spread: {fmtPrice(spread)}</span>
        </div>
        {bidRows.map((r, i) => <Row key={`bid-${i}`} price={r[0]} size={r[1]} side="bid" />)}
      </div>
    </div>
  );
}

// ─── Order ticket ──────────────────────────────────────────────────────────────

const ORDER_TYPES = ['Market', 'Limit', 'Stop'] as const;
type OT = (typeof ORDER_TYPES)[number];

function OrderTicket({ symbol, lastPrice, equity, onSubmit }: { symbol: string; lastPrice: number | null; equity: number | null; onSubmit: (msg: string) => void }): JSX.Element {
  const [side, setSide] = useState<'Buy' | 'Sell'>('Buy');
  const [ot, setOt] = useState<OT>('Limit');
  const [qty, setQty] = useState('');
  const [price, setPrice] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [result, setResult] = useState<string | null>(null);

  const numQty = Number(qty);
  const numPrice = Number(price || lastPrice || 0);
  const notional = Number.isFinite(numQty) && Number.isFinite(numPrice) ? numQty * numPrice : 0;
  const pctOfEquity = equity && notional ? Math.min(100, (notional / equity) * 100).toFixed(1) : null;

  function fill(pct: number): void {
    if (!equity || !numPrice) return;
    const notionalTarget = equity * (pct / 100);
    const qtyTarget = notionalTarget / numPrice;
    setQty(qtyTarget.toFixed(6));
  }

  async function submit(): Promise<void> {
    if (!qty || !numQty || numQty <= 0) return;
    setSubmitting(true);
    setResult(null);
    try {
      const body = { symbol, side: side.toLowerCase(), order_type: ot.toLowerCase(), quantity: numQty, price: ot !== 'Market' ? numPrice : undefined };
      const res = await fetch('/api/v2/orders/paper', { method: 'POST', credentials: 'include', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
      const json = await res.json() as Record<string, unknown>;
      const status = json.data ? (json.data as Record<string, unknown>).status ?? 'submitted' : json.detail ?? 'error';
      setResult(`Order ${status}: ${side} ${qty} ${symbol} @ ${ot === 'Market' ? 'Market' : fmtPrice(numPrice)}`);
      onSubmit(String(status));
    } catch (e) {
      setResult(`Submit error: ${String(e)}`);
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 10, padding: '12px 14px' }}>
      <div style={{ display: 'flex', gap: 4 }}>
        {(['Buy', 'Sell'] as const).map((s) => (
          <button key={s} onClick={() => setSide(s)} style={{ flex: 1, padding: '8px 0', border: 'none', borderRadius: 'var(--radius-sm)', fontWeight: 700, fontSize: 13, cursor: 'pointer', transition: 'all 0.1s', background: side === s ? (s === 'Buy' ? 'var(--buy, #26a69a)' : 'var(--sell, #ef5350)') : 'var(--bg-elevated)', color: side === s ? '#fff' : 'var(--text-muted)' }}>
            {s}
          </button>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 4 }}>
        {ORDER_TYPES.map((t) => (
          <button key={t} onClick={() => setOt(t)} style={{ flex: 1, padding: '5px 0', border: `1px solid ${ot === t ? 'var(--accent)' : 'var(--border)'}`, borderRadius: 'var(--radius-sm)', fontSize: 11, cursor: 'pointer', background: ot === t ? 'color-mix(in oklch, var(--accent) 12%, transparent)' : 'transparent', color: ot === t ? 'var(--accent)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {t}
          </button>
        ))}
      </div>

      {ot !== 'Market' && (
        <div>
          <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Price (USDT)</label>
          <input
            type="number"
            value={price}
            onChange={(e) => setPrice(e.target.value)}
            placeholder={fmtPrice(lastPrice)}
            style={{ width: '100%', padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontSize: 13, fontFamily: 'var(--font-mono)', outline: 'none', boxSizing: 'border-box' }}
          />
        </div>
      )}

      <div>
        <label style={{ fontSize: 11, color: 'var(--text-muted)', display: 'block', marginBottom: 4 }}>Quantity</label>
        <input
          type="number"
          value={qty}
          onChange={(e) => setQty(e.target.value)}
          placeholder="0.000"
          style={{ width: '100%', padding: '8px 10px', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontSize: 13, fontFamily: 'var(--font-mono)', outline: 'none', boxSizing: 'border-box' }}
        />
        <div style={{ display: 'flex', gap: 4, marginTop: 6 }}>
          {[25, 50, 75, 100].map((p) => (
            <button key={p} onClick={() => fill(p)} style={{ flex: 1, padding: '4px 0', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', fontSize: 11, cursor: 'pointer', background: 'transparent', color: 'var(--text-muted)' }}>
              {p}%
            </button>
          ))}
        </div>
      </div>

      {notional > 0 && (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
          <KV label="Notional" value={fmtMoney(notional)} />
          {pctOfEquity && <KV label="% of Equity" value={`${pctOfEquity}%`} />}
        </div>
      )}

      <button
        onClick={() => void submit()}
        disabled={submitting || !qty || numQty <= 0}
        style={{ padding: '10px 0', border: 'none', borderRadius: 'var(--radius-sm)', background: side === 'Buy' ? 'var(--buy, #26a69a)' : 'var(--sell, #ef5350)', color: '#fff', fontWeight: 700, fontSize: 13, cursor: submitting ? 'wait' : 'pointer', opacity: (!qty || numQty <= 0) ? 0.5 : 1, fontFamily: 'var(--font-sans)' }}
      >
        {submitting ? 'Submitting…' : `${side} ${symbol}`}
      </button>

      {result && (
        <div style={{ padding: '8px 10px', borderRadius: 'var(--radius-sm)', background: 'var(--bg-elevated)', border: '1px solid var(--border)', fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
          {result}
        </div>
      )}

      <div style={{ padding: '6px 8px', background: 'color-mix(in oklch, var(--sell, #ef5350) 8%, transparent)', border: '1px solid color-mix(in oklch, var(--sell, #ef5350) 20%, transparent)', borderRadius: 'var(--radius-sm)', fontSize: 10, color: 'var(--sell, #ef5350)', fontFamily: 'var(--font-mono)', textAlign: 'center' }}>
        LIVE ORDER SUBMISSION BLOCKED · OPERATOR GATED
      </div>
    </div>
  );
}

// ─── Positions table ──────────────────────────────────────────────────────────

function PositionsTable({ positions }: { positions: Position[] }): JSX.Element {
  if (positions.length === 0) {
    return <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>No open positions</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, fontFamily: 'var(--font-mono)' }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Side', 'Size', 'Entry Price', 'Mark Price', 'Liq. Price', 'Unrealized PnL', 'PnL %', 'Leverage'].map((h) => (
              <th key={h} style={{ padding: '8px 12px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {positions.map((pos, i) => {
            const side = pos.side ?? '—';
            return (
              <tr key={`pos-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
                <td style={{ padding: '8px 12px', fontWeight: 700, color: 'var(--text-primary)' }}>{pos.symbol ?? '—'}</td>
                <td style={{ padding: '8px 12px', fontWeight: 700, color: dirColor(side) }}>{side.toUpperCase()}</td>
                <td style={{ padding: '8px 12px' }}>{pos.quantity ?? pos.size ?? '—'}</td>
                <td style={{ padding: '8px 12px' }}>{fmtPrice(pos.entry_price)}</td>
                <td style={{ padding: '8px 12px' }}>{fmtPrice(pos.mark_price)}</td>
                <td style={{ padding: '8px 12px', color: 'var(--warn, #f59e0b)' }}>{fmtPrice(pos.liquidation_price)}</td>
                <td style={{ padding: '8px 12px', fontWeight: 700, color: pnlColor(pos.unrealized_pnl) }}>{fmtMoney(pos.unrealized_pnl)}</td>
                <td style={{ padding: '8px 12px', color: pnlColor(pos.unrealized_pnl_pct) }}>{fmtPct(pos.unrealized_pnl_pct)}</td>
                <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{pos.leverage != null ? `${pos.leverage}×` : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

// ─── Orders table ──────────────────────────────────────────────────────────────

function OrdersTable({ orders }: { orders: Order[] }): JSX.Element {
  if (orders.length === 0) {
    return <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>No open orders</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, fontFamily: 'var(--font-mono)' }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Side', 'Type', 'Qty', 'Price', 'Status', 'Time'].map((h) => (
              <th key={h} style={{ padding: '8px 12px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {orders.map((o, i) => (
            <tr key={`ord-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '8px 12px', fontWeight: 700 }}>{o.symbol ?? '—'}</td>
              <td style={{ padding: '8px 12px', fontWeight: 700, color: dirColor(o.side) }}>{(o.side ?? '—').toUpperCase()}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{o.type ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{o.quantity ?? o.qty ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{fmtPrice(o.price)}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-secondary)', fontSize: 11 }}>{o.status ?? '—'}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{o.created_at ? new Date(o.created_at).toLocaleTimeString() : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Executions table ─────────────────────────────────────────────────────────

function ExecutionsTable({ executions }: { executions: Execution[] }): JSX.Element {
  if (executions.length === 0) {
    return <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>No executions</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, fontFamily: 'var(--font-mono)' }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Side', 'Qty', 'Price', 'Fee', 'Status', 'Time'].map((h) => (
              <th key={h} style={{ padding: '8px 12px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {executions.map((ex, i) => (
            <tr key={`ex-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '8px 12px', fontWeight: 700 }}>{ex.symbol ?? '—'}</td>
              <td style={{ padding: '8px 12px', fontWeight: 700, color: dirColor(ex.side) }}>{(ex.side ?? '—').toUpperCase()}</td>
              <td style={{ padding: '8px 12px' }}>{ex.quantity ?? ex.qty ?? '—'}</td>
              <td style={{ padding: '8px 12px' }}>{fmtPrice(ex.price)}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{ex.fee != null ? `$${ex.fee.toFixed(4)}` : '—'}</td>
              <td style={{ padding: '8px 12px', fontSize: 11 }}>{ex.status ?? '—'}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{ex.created_at ? new Date(ex.created_at).toLocaleTimeString() : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── Signals panel ────────────────────────────────────────────────────────────

function SignalsPanel({ active, pending }: { active: SignalRow[]; pending: SignalRow[] }): JSX.Element {
  const rows = [...active, ...pending];
  if (rows.length === 0) {
    return <div style={{ padding: '24px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>No active signals from orchestrator</div>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5, fontFamily: 'var(--font-mono)' }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Direction', 'Status', 'Confidence', 'Entry', 'Target', 'Stop', 'R:R', 'Strategy', 'Risk', 'Created'].map((h) => (
              <th key={h} style={{ padding: '8px 12px', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((sig, i) => (
            <tr key={`sig-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
              <td style={{ padding: '8px 12px', fontWeight: 700, color: 'var(--text-primary)' }}>{sig.symbol}</td>
              <td style={{ padding: '8px 12px', fontWeight: 700, color: dirColor(sig.direction) }}>{(sig.direction ?? '—').toUpperCase()}</td>
              <td style={{ padding: '8px 12px' }}>
                <span style={{ padding: '2px 6px', borderRadius: 999, fontSize: 10, fontWeight: 700, background: sig.status === 'active' ? 'var(--buy-bg)' : 'var(--bg-elevated)', color: sig.status === 'active' ? 'var(--buy)' : 'var(--text-muted)' }}>
                  {sig.status.toUpperCase()}
                </span>
              </td>
              <td style={{ padding: '8px 12px' }}>{sig.confidence != null ? `${(sig.confidence * 100).toFixed(1)}%` : '—'}</td>
              <td style={{ padding: '8px 12px' }}>{fmtPrice(sig.entry)}</td>
              <td style={{ padding: '8px 12px', color: 'var(--buy, #26a69a)' }}>{fmtPrice(sig.target1)}</td>
              <td style={{ padding: '8px 12px', color: 'var(--sell, #ef5350)' }}>{fmtPrice(sig.stop)}</td>
              <td style={{ padding: '8px 12px' }}>{sig.risk_reward != null ? `${sig.risk_reward.toFixed(2)}R` : '—'}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{sig.strategy ?? '—'}</td>
              <td style={{ padding: '8px 12px', color: sig.risk_decision === 'allow' ? 'var(--buy)' : sig.risk_decision === 'block' ? 'var(--sell)' : 'var(--text-muted)', fontSize: 11 }}>{(sig.risk_decision ?? '—').toUpperCase()}</td>
              <td style={{ padding: '8px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{sig.created_at ? new Date(sig.created_at).toLocaleTimeString() : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ─── AI panel ─────────────────────────────────────────────────────────────────

function AiPanel({ predictions, trainerStatus }: { predictions: PredictionsData['predictions']; trainerStatus: string | null }): JSX.Element {
  return (
    <div style={{ padding: 16, display: 'flex', flexDirection: 'column', gap: 12 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Trainer status:</span>
        <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', fontWeight: 700, color: (trainerStatus ?? '').toLowerCase().includes('active') || (trainerStatus ?? '').toLowerCase().includes('running') ? 'var(--buy)' : 'var(--warn, #f59e0b)' }}>
          {trainerStatus ?? 'Unknown'}
        </span>
      </div>
      {predictions.length === 0 ? (
        <div style={{ textAlign: 'center', color: 'var(--text-muted)', fontSize: 13, padding: '16px 0' }}>No active AI predictions · Trainer pipeline must be running</div>
      ) : predictions.map((pred, i) => (
        <div key={`pred-${i}`} className="glass" style={{ padding: '12px 14px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10 }}>
          <KV label="Symbol" value={pred.symbol ?? '—'} />
          <KV label="Action" value={(pred.action ?? '—').toUpperCase()} color={dirColor(pred.action)} />
          <KV label="Confidence" value={pred.confidence != null ? `${(pred.confidence * 100).toFixed(1)}%` : '—'} color={pred.confidence != null && pred.confidence >= 0.7 ? 'var(--buy)' : 'var(--warn)'} />
          <KV label="Model" value={pred.model_version ?? '—'} />
        </div>
      ))}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────────

export default function BinancePage(): JSX.Element {
  const { user } = useAuth();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState<TF>('15m');
  const [activeTab, setActiveTab] = useState<BottomTab>('Positions');
  const [orderLog, setOrderLog] = useState<string[]>([]);

  const stream = useMarketDataStream(symbol, 1000, timeframe);
  const ticker = stream.ticker?.data;
  const bids = stream.depth?.data?.bids ?? [];
  const asks = stream.depth?.data?.asks ?? [];

  // REST/API fallback for the header ticker strip. The native combined WSS can
  // deliver bookTicker/depth/trade frames while @ticker/@markPrice frames never
  // arrive (observed live), which left the price strip permanently '—' under a
  // green Live dot. /api/v2/market/{symbol} carries the same 24h fields, so
  // each field falls back to it independently.
  const { envelope: tickerFallbackEnv } = useRealtimeResource<MarketTickerData>({
    url: `/api/v2/market/${symbol}`,
    source: `/api/v2/market/${symbol}`,
    source_type: 'websocket',
    pollIntervalMs: 5_000,
    staleThresholdMs: 20_000,
    mode: 'read_only',
  });
  const restTicker = tickerFallbackEnv.data;
  const lastPrice = ticker?.last_price ?? restTicker?.last_price ?? null;
  const change24h = ticker?.change_24h ?? restTicker?.change_24h ?? null;
  const high24h = ticker?.high_24h ?? restTicker?.high_24h ?? null;
  const low24h = ticker?.low_24h ?? restTicker?.low_24h ?? null;
  const volume24h = ticker?.volume_24h ?? restTicker?.volume_24h ?? null;
  // volume_24h is in base-asset units (e.g. BTC); turnover_24h is the USD value.
  const turnover24h = ticker?.turnover_24h ?? restTicker?.turnover_24h ?? null;

  const { envelope: accountEnv } = useRealtimeResource<ExchangeAccountData>({
    url: '/api/v2/account/exchange-readonly',
    source: '/api/v2/account/exchange-readonly',
    source_type: 'websocket',
    pollIntervalMs: 15_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });

  const { envelope: portfolioEnv, refetch: refetchPortfolio } = useRealtimeResource<PortfolioData>({
    url: '/api/v2/portfolio?scope=current_session',
    source: '/api/v2/portfolio?scope=current_session',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });

  const { envelope: positionsEnv } = useRealtimeResource<{ positions: Position[] }>({
    url: '/api/v2/account/positions',
    source: '/api/v2/account/positions',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });

  const { envelope: ordersEnv } = useRealtimeResource<{ orders: Order[] }>({
    url: '/api/v2/execution/orders',
    source: '/api/v2/execution/orders',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });

  const { envelope: executionsEnv } = useRealtimeResource<{ executions: Execution[] }>({
    url: '/api/v2/execution/executions',
    source: '/api/v2/execution/executions',
    source_type: 'websocket',
    pollIntervalMs: 15_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
  });

  const { envelope: signalsEnv } = useRealtimeResource<SignalsData>({
    url: '/api/v2/signals',
    source: '/api/v2/signals',
    source_type: 'websocket',
    pollIntervalMs: 8_000,
    staleThresholdMs: 20_000,
    mode: 'read_only',
  });

  const { envelope: predictionsEnv } = useRealtimeResource<PredictionsData>({
    url: '/api/v2/ai/predictions',
    source: '/api/v2/ai/predictions',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });

  // Adaptive symbol universe for the selector: trader's saved watchlist first,
  // then every symbol from the live market overview (no hardcoded lists).
  const { envelope: overviewEnv } = useRealtimeResource<{ symbols?: string[] }>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const userWatchlist = user?.watchlist;
  const overviewSymbols = overviewEnv.data?.symbols;
  const symbolOptions = useMemo(() => {
    const normalize = (value: unknown): string | null => {
      if (typeof value !== 'string') return null;
      const sym = value.trim().toUpperCase();
      return /^[A-Z0-9]+$/.test(sym) ? sym : null;
    };
    const watchlist = (userWatchlist ?? []).map(normalize).filter((s): s is string => s !== null);
    const universe = (overviewSymbols ?? []).map(normalize).filter((s): s is string => s !== null).sort();
    return [...new Set([...watchlist, symbol, ...universe])];
  }, [userWatchlist, overviewSymbols, symbol]);

  const exchangeAccount = accountEnv.data;
  const accountSnapshot = exchangeAccount?.account_snapshot;
  const portfolio = portfolioEnv.data;
  const positions = positionsEnv.data?.positions ?? portfolio?.positions ?? exchangeAccount?.positions ?? [];
  const orders = ordersEnv.data?.orders ?? [];
  const executions = executionsEnv.data?.executions ?? [];
  const signals = signalsEnv.data;
  const predictions = predictionsEnv.data;
  const equity = portfolio?.equity ?? accountSnapshot?.total_margin_balance ?? null;
  const available = accountSnapshot?.available_balance ?? null;
  const unrealizedPnl = portfolio?.unrealized_pnl ?? accountSnapshot?.total_unrealized_profit ?? null;

  const onOrderSubmit = useCallback((msg: string) => {
    setOrderLog((prev) => [`${new Date().toLocaleTimeString()}: ${msg}`, ...prev.slice(0, 19)]);
    void refetchPortfolio();
  }, [refetchPortfolio]);

  const bottomTabCounts: Record<BottomTab, number> = {
    Positions: positions.length,
    Orders: orders.length,
    Executions: executions.length,
    Signals: (signals?.active?.length ?? 0) + (signals?.pending?.length ?? 0),
    AI: predictions?.count ?? 0,
  };

  return (
    <div
      data-testid="page-binance"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ display: 'flex', flexDirection: 'column', height: 'calc(100vh - 56px)', background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), #0b0e11', color: 'var(--text-primary)', overflow: 'hidden' }}
    >
      {/* ── Top bar: Symbol + ticker stats ── */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '8px 16px', background: '#131722', borderBottom: '1px solid #2a2d3a', flexShrink: 0, flexWrap: 'wrap' }}>
        {/* Symbol selector */}
        <select
          value={symbol}
          onChange={(e) => setSymbol(e.target.value)}
          style={{ padding: '4px 8px', background: '#1e2230', border: '1px solid #2a2d3a', borderRadius: 4, color: '#fff', fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', cursor: 'pointer' }}
          aria-label="Select trading symbol"
        >
          {symbolOptions.map((s) => <option key={s} value={s}>{s}</option>)}
        </select>

        {/* Price */}
        <span style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-mono)', color: (change24h ?? 0) >= 0 ? '#26a69a' : '#ef5350' }}>{fmtPrice(lastPrice)}</span>
        <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: (change24h ?? 0) >= 0 ? '#26a69a' : '#ef5350' }}>{fmtPct(change24h)}</span>

        {/* Stats */}
        <div style={{ display: 'flex', gap: 16, flexWrap: 'wrap' }}>
          {[['24h High', fmtPrice(high24h)], ['24h Low', fmtPrice(low24h)], ['24h Vol', turnover24h != null ? fmtMoney(turnover24h) : fmtBaseVol(volume24h)]].map(([label, value]) => (
            <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 1 }}>
              <span style={{ fontSize: 10, color: '#7b7f8a', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{label}</span>
              <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: '#c9cad4' }}>{value}</span>
            </div>
          ))}
        </div>

        <div style={{ flex: 1 }} />

        {/* WS status */}
        <ConnDot connected={stream.connected} label={stream.connected ? 'Live' : 'Connecting'} />
        <LiveBadge />

        {/* Timeframe selector */}
        <div style={{ display: 'flex', gap: 2 }}>
          {TIMEFRAMES.map((tf) => (
            <button key={tf} onClick={() => setTimeframe(tf)} style={{ padding: '3px 8px', fontSize: 11, border: `1px solid ${timeframe === tf ? '#3b82f6' : '#2a2d3a'}`, borderRadius: 3, background: timeframe === tf ? 'rgba(59,130,246,0.15)' : 'transparent', color: timeframe === tf ? '#3b82f6' : '#7b7f8a', cursor: 'pointer', fontFamily: 'var(--font-mono)' }}>
              {tf}
            </button>
          ))}
        </div>
      </div>

      <div style={{ flexShrink: 0, maxHeight: 260, overflowY: 'auto', padding: '8px 12px', background: '#0b0e11', borderBottom: '1px solid #1e2230' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Capital Productivity + PnL + Accuracy"
          compact
          showCapital
          showMatrix
          maxMatrixHeight={150}
        />
      </div>

      {/* ── Main workspace ── */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 220px 260px', minHeight: 0, overflow: 'hidden' }}>

        {/* ── Chart + book column ── */}
        <div style={{ display: 'flex', flexDirection: 'column', borderRight: '1px solid #1e2230', minHeight: 0 }}>
          <div style={{ flex: 1, minHeight: 0, padding: 4 }}>
            <BinanceChart symbol={symbol} timeframe={timeframe} streamCandle={stream.liveCandle} />
          </div>
        </div>

        {/* ── Order book ── */}
        <div style={{ borderRight: '1px solid #1e2230', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
          <div style={{ padding: '8px 10px', fontSize: 12, fontWeight: 600, color: '#c9cad4', borderBottom: '1px solid #1e2230', background: '#131722' }}>Order Book</div>
          <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
            <OrderBook bids={bids as Array<[number | null, number | null]>} asks={asks as Array<[number | null, number | null]>} lastPrice={lastPrice} />
          </div>
          {/* Recent trades */}
          <div style={{ height: '35%', borderTop: '1px solid #1e2230', overflow: 'hidden', display: 'flex', flexDirection: 'column' }}>
            <div style={{ padding: '6px 10px', fontSize: 11, fontWeight: 600, color: '#7b7f8a', background: '#131722', borderBottom: '1px solid #1e2230' }}>Recent Trades</div>
            <div style={{ flex: 1, overflow: 'auto' }}>
              {(stream.trades?.data?.trades ?? []).slice(0, 30).map((t, i) => (
                <div key={`trade-${i}`} style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', padding: '2px 10px', fontSize: 11.5, fontFamily: 'var(--font-mono)' }}>
                  <span style={{ color: t.side === 'buy' ? '#26a69a' : '#ef5350' }}>{fmtPrice(t.price)}</span>
                  <span style={{ color: '#7b7f8a', textAlign: 'center' }}>{Number(t.size).toFixed(3)}</span>
                  <span style={{ color: '#5a5e6e', textAlign: 'right' }}>{t.time ? new Date(t.time).toLocaleTimeString('en', { hour12: false }) : ''}</span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* ── Right panel: Account + Order ticket ── */}
        <div style={{ display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>
          {/* Account summary */}
          <div style={{ padding: '10px 14px', background: '#131722', borderBottom: '1px solid #1e2230', flexShrink: 0 }}>
            <div style={{ fontSize: 11, fontWeight: 600, color: '#7b7f8a', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 8 }}>Account · {user?.username || user?.email || '—'}</div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
              <KV label="Equity" value={fmtMoney(equity)} color={equity != null && equity > 0 ? '#c9cad4' : '#7b7f8a'} />
              <KV label="Available" value={fmtMoney(available)} />
              <KV label="Unrealized PnL" value={fmtMoney(unrealizedPnl)} color={pnlColor(unrealizedPnl)} />
              <KV label="Open Positions" value={String(positions.length)} />
            </div>
            {exchangeAccount?.credential_status && (
              <div style={{ marginTop: 8, fontSize: 10, color: '#7b7f8a' }}>
                Exchange: {exchangeAccount.exchange ?? 'Binance'} ·
                Credentials: {exchangeAccount.credential_status.configured ? '✓ Configured' : '✗ Not configured'} ·
                Live: {exchangeAccount.live_trading_enabled ? '⚠ Enabled' : '✓ Blocked'}
              </div>
            )}
          </div>

          {/* Order ticket */}
          <div style={{ flex: 1, overflow: 'auto', background: '#0b0e11' }}>
            <div style={{ padding: '8px 14px', fontSize: 11, fontWeight: 600, color: '#7b7f8a', textTransform: 'uppercase', letterSpacing: '0.05em', borderBottom: '1px solid #1e2230', background: '#131722' }}>
              New Order · {symbol}
            </div>
            <OrderTicket symbol={symbol} lastPrice={lastPrice} equity={equity} onSubmit={onOrderSubmit} />

            {/* Signal for this symbol */}
            {signals?.active?.filter((s) => s.symbol === symbol).map((sig, i) => (
              <div key={`sig-card-${i}`} style={{ margin: '0 14px 12px', padding: '10px 12px', background: '#131722', border: `1px solid ${sig.direction?.toLowerCase() === 'long' ? 'rgba(38,166,154,0.3)' : 'rgba(239,83,80,0.3)'}`, borderRadius: 6 }}>
                <div style={{ fontSize: 11, color: '#7b7f8a', marginBottom: 4 }}>Active signal from orchestrator</div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 6 }}>
                  <KV label="Direction" value={(sig.direction ?? '—').toUpperCase()} color={dirColor(sig.direction)} />
                  <KV label="Confidence" value={sig.confidence != null ? `${(sig.confidence * 100).toFixed(1)}%` : '—'} />
                  <KV label="Entry" value={fmtPrice(sig.entry)} />
                  <KV label="Target" value={fmtPrice(sig.target1)} color="#26a69a" />
                  <KV label="Stop" value={fmtPrice(sig.stop)} color="#ef5350" />
                  <KV label="R:R" value={sig.risk_reward != null ? `${sig.risk_reward.toFixed(2)}R` : '—'} />
                </div>
              </div>
            ))}

            {/* Order log */}
            {orderLog.length > 0 && (
              <div style={{ margin: '0 14px 12px' }}>
                <div style={{ fontSize: 10, color: '#7b7f8a', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Order Log</div>
                {orderLog.slice(0, 5).map((msg, i) => (
                  <div key={`log-${i}`} style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: '#5a5e6e', marginBottom: 2 }}>{msg}</div>
                ))}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* ── Bottom tabs ── */}
      <div style={{ borderTop: '1px solid #1e2230', flexShrink: 0, background: '#131722' }}>
        {/* Tab strip */}
        <div style={{ display: 'flex', borderBottom: '1px solid #1e2230' }}>
          {BOTTOM_TABS.map((tab) => (
            <button
              key={tab}
              onClick={() => setActiveTab(tab)}
              style={{ padding: '7px 16px', border: 'none', borderBottom: `2px solid ${activeTab === tab ? '#3b82f6' : 'transparent'}`, background: 'transparent', color: activeTab === tab ? '#3b82f6' : '#7b7f8a', fontSize: 12, fontWeight: activeTab === tab ? 600 : 400, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 5, whiteSpace: 'nowrap' }}
            >
              {tab}
              {bottomTabCounts[tab] > 0 && (
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: activeTab === tab ? '#3b82f6' : '#5a5e6e' }}>
                  {bottomTabCounts[tab]}
                </span>
              )}
            </button>
          ))}
        </div>

        {/* Tab content */}
        <div style={{ maxHeight: 240, overflowY: 'auto', background: '#0b0e11' }}>
          {activeTab === 'Positions' && <PositionsTable positions={positions} />}
          {activeTab === 'Orders' && <OrdersTable orders={orders} />}
          {activeTab === 'Executions' && <ExecutionsTable executions={executions} />}
          {activeTab === 'Signals' && <SignalsPanel active={signals?.active ?? []} pending={signals?.pending ?? []} />}
          {activeTab === 'AI' && <AiPanel predictions={predictions?.predictions ?? []} trainerStatus={predictions?.trainer_status ?? null} />}
        </div>
      </div>
    </div>
  );
}
