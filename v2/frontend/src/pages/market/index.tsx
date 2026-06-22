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
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
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
import './marketDetail.css';

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface TickerData {
  symbol: string;
  last_price: number | null;
  mark_price: number | null;
  index_price: number | null;
  change_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  turnover_24h: number | null;
  funding_rate: number | null;
  next_funding: string | null;
  open_interest: number | null;
}

interface CandleRow {
  time: number;
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

function fmtPct(v: unknown): string {
  const n = finite(v);
  if (n === null) return '—';
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct >= 0 ? '+' : ''}${pct.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}%`;
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
  const pct = Math.abs(rate) < 0.01 ? rate * 100 : rate;
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
          <span>Loading chart data…</span>
        </div>
      )}
      {!loading && error && !candles.length && (
        <div className="mdc-chart-overlay mdc-chart-overlay--error">
          <AlertTriangle size={24} />
          <span>Market data unavailable — retrying…</span>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stat chip
// ---------------------------------------------------------------------------

function Stat({ label, value, tone }: { label: string; value: string; tone?: string }): JSX.Element {
  return (
    <div className="mdc-stat">
      <span className="mdc-stat__label">{label}</span>
      <strong className={`mdc-stat__value${tone ? ` ${tone}` : ''}`}>{value}</strong>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Signal panel
// ---------------------------------------------------------------------------

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
        <span>AI signal data unavailable for this symbol</span>
      </div>
    );
  }
  const action = signal.selected_action;
  const isBuy = /long|buy/i.test(action);
  const isSell = /short|sell/i.test(action);
  return (
    <div className="mdc-signal-panel">
      <div className="mdc-signal-panel__head">
        {isBuy ? <TrendingUp size={15} /> : isSell ? <TrendingDown size={15} /> : <Sparkles size={15} />}
        <span className={isBuy ? 'mdc-pos' : isSell ? 'mdc-neg' : ''}>{action}</span>
      </div>
      <div className="mdc-signal-panel__grid">
        <Stat label="Confidence" value={fmtPct(signal.confidence)} />
        <Stat label="Entry" value={fmtPrice(signal.entry)} />
        <Stat label="Target" value={fmtPrice(signal.target_1)} />
        <Stat label="Stop" value={fmtPrice(signal.stop)} />
        <Stat label="R/R" value={signal.risk_reward != null ? `${signal.risk_reward.toFixed(2)}x` : '—'} />
      </div>
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
  const symbol = (params.symbol ?? 'BTCUSDT').toUpperCase().trim();

  const { user, loading: authLoading } = useCurrentUser();

  const [ticker, setTicker] = useState<TickerData | null>(null);
  const [tickerError, setTickerError] = useState<string | null>(null);
  const [tickerLoading, setTickerLoading] = useState(true);

  const [candles, setCandles] = useState<CandleRow[]>([]);
  const [candleError, setCandleError] = useState<string | null>(null);
  const [candleLoading, setCandleLoading] = useState(true);

  const [timeframe, setTimeframe] = useState<Timeframe>('1h');

  const [signal, setSignal] = useState<SignalData | null>(null);
  const [signalLoading, setSignalLoading] = useState(true);

  const signInUrl = `/login?returnTo=${encodeURIComponent(`/market/${symbol}`)}`;
  function goSignIn(): void { navigate(signInUrl); }

  // ---------------------------------------------------------------------------
  // Ticker polling — 10s
  // ---------------------------------------------------------------------------

  const fetchTicker = useCallback(async () => {
    try {
      const res = await fetch(`/api/v2/market/${symbol}`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as { data?: unknown };
      if (!json?.data || typeof json.data !== 'object') throw new Error('Empty response');
      setTicker(json.data as TickerData);
      setTickerError(null);
    } catch (err) {
      setTickerError(err instanceof Error ? err.message : 'Unavailable');
    } finally {
      setTickerLoading(false);
    }
  }, [symbol]);

  useEffect(() => {
    setTickerLoading(true);
    setTicker(null);
    setTickerError(null);
    void fetchTicker();
    const id = window.setInterval(fetchTicker, 10_000);
    return () => window.clearInterval(id);
  }, [fetchTicker]);

  // ---------------------------------------------------------------------------
  // Candles — refresh on symbol/timeframe change
  // ---------------------------------------------------------------------------

  const fetchCandles = useCallback(async () => {
    setCandleLoading(true);
    try {
      const res = await fetch(`/api/v2/market/${symbol}/candles?interval=${timeframe}&limit=200`);
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const json = (await res.json()) as { data?: { candles?: unknown } };
      const rows = json?.data?.candles;
      if (!Array.isArray(rows) || rows.length === 0) throw new Error('No candle data');
      setCandles(rows as CandleRow[]);
      setCandleError(null);
    } catch (err) {
      setCandleError(err instanceof Error ? err.message : 'Unavailable');
    } finally {
      setCandleLoading(false);
    }
  }, [symbol, timeframe]);

  useEffect(() => {
    setCandles([]);
    setCandleError(null);
    void fetchCandles();
  }, [fetchCandles]);

  // ---------------------------------------------------------------------------
  // Signal — 30s poll, only when authenticated
  // ---------------------------------------------------------------------------

  useEffect(() => {
    if (!user) { setSignal(null); setSignalLoading(false); return undefined; }
    let active = true;
    setSignalLoading(true);

    async function load(): Promise<void> {
      try {
        const res = await fetch(`/api/v2/signals?symbol=${symbol}`);
        if (!res.ok) return;
        const json = (await res.json()) as { data?: { active_signal?: unknown } };
        if (active) setSignal((json?.data?.active_signal ?? null) as SignalData | null);
      } catch { /* best-effort */ } finally {
        if (active) setSignalLoading(false);
      }
    }

    void load();
    const id = window.setInterval(load, 30_000);
    return () => { active = false; window.clearInterval(id); };
  }, [symbol, user]);

  // ---------------------------------------------------------------------------
  // Derived values
  // ---------------------------------------------------------------------------

  const price = ticker?.last_price ?? null;
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
  const baseTicker = symbol.replace('USDT', '');

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
            {price !== null && <span className="mdc-header__price">{fmtPrice(price)}</span>}
            {changeDisplay && (
              <span className={`mdc-header__change ${changeDisplay.positive ? 'mdc-pos' : 'mdc-neg'}`}>
                {changeDisplay.positive ? <TrendingUp size={16} /> : <TrendingDown size={16} />}
                {changeDisplay.label}
              </span>
            )}
          </h1>
        </div>

        <div className="mdc-header__strip">
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
            <span className="mdc-header__loading">Loading market data…</span>
          ) : (
            <span className="mdc-header__error">Market data unavailable — retrying…</span>
          )}
        </div>
      </header>

      {/* ── Chart + Stats row (70/30 split) ── */}
      <div className="mdc-chart-section">
        {/* Chart — hero element */}
        <div className="mdc-chart-col">
          <div className="mdc-panel mdc-chart-panel">
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
                <span>Market data unavailable — retrying…</span>
              </div>
            )}

            {ticker && (
              <div className="mdc-stats-grid">
                <Stat label="Mark Price" value={fmtPrice(ticker.mark_price)} />
                <Stat label="Index Price" value={fmtPrice(ticker.index_price)} />
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

      {/* ── Lower grid: AI Signal + Derivatives + Source ── */}
      <div className="mdc-lower-grid">
        {/* AI Signal */}
        <div className="mdc-panel">
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
        <div className="mdc-panel">
          <div className="mdc-panel__head">
            <span className="mdc-panel__eyebrow">Derivatives</span>
            <h2>Funding &amp; OI</h2>
          </div>
          <div className="mdc-stats-grid">
            <Stat label="Funding Rate" value={fmtFunding(fundingRate)} tone={fundingTone} />
            <Stat label="Next Funding" value={fmtNextFunding(ticker?.next_funding ?? null)} />
            <Stat label="Open Interest" value={fmtCompact(ticker?.open_interest ?? null)} />
            <Stat label="Mark Price" value={fmtPrice(ticker?.mark_price ?? null)} />
            <Stat label="Index Price" value={fmtPrice(ticker?.index_price ?? null)} />
            <Stat label="24h Change" value={fmtPct(ticker?.change_24h ?? null)} tone={changeClass(ticker?.change_24h ?? null)} />
          </div>
        </div>

        {/* Source / Evidence */}
        <div className="mdc-panel">
          <div className="mdc-panel__head">
            <span className="mdc-panel__eyebrow">Evidence</span>
            <h2>Data Sources</h2>
          </div>
          <div className="mdc-meta-grid">
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Market API</span>
              <strong className={tickerError ? 'mdc-neg' : ticker ? 'mdc-pos' : ''}>
                {tickerError ? 'Unavailable — retrying…' : ticker ? 'Connected' : 'Connecting…'}
              </strong>
            </div>
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Candle source</span>
              <strong className={candleError && !candles.length ? 'mdc-neg' : candles.length ? 'mdc-pos' : ''}>
                {candleError && !candles.length
                  ? 'Unavailable — retrying…'
                  : candles.length
                    ? `${candles.length} bars · ${timeframe}`
                    : 'Loading…'}
              </strong>
            </div>
            <div className="mdc-meta-row">
              <Activity size={14} aria-hidden="true" />
              <span>Mode</span>
              <strong>Live market view</strong>
            </div>
            <div className="mdc-meta-row">
              <ShieldCheck size={14} aria-hidden="true" />
              <span>Live trading</span>
              <strong className="mdc-pos">GUARDED</strong>
            </div>
          </div>
        </div>
      </div>
    </main>
  );
}
