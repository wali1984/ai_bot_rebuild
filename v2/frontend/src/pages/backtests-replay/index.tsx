import { useState, useRef, useEffect, useCallback } from 'react';
import { Link } from 'react-router-dom';
import {
  CandlestickSeries,
  ColorType,
  HistogramSeries,
  createChart,
  type IChartApi,
  type ISeriesApi,
  type UTCTimestamp,
} from 'lightweight-charts';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { getV2MarketCandles } from '../../api/v2Market';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types ────────────────────────────────────────────────────────────────

interface CandleBar {
  time: UTCTimestamp;
  open: number;
  high: number;
  low: number;
  close: number;
  volume?: number;
}

interface ReplayState {
  bars: CandleBar[];
  volumes: Array<{ time: UTCTimestamp; value: number; color: string }>;
  cursor: number;
  playing: boolean;
  speed: 1 | 2 | 5 | 10;
}

interface ReplayStatus {
  last_run: string | null;
  idempotent_hash: string | null;
  bounded_events_count: number | null;
}

const HOT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT'];
const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h', '1d'];
const SPEEDS = [1, 2, 5, 10] as const;

// ─── Helpers ──────────────────────────────────────────────────────────────

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 10000) return `$${n.toLocaleString('en-US', { minimumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
  return `$${n.toFixed(6)}`;
}
function fmtVol(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1e9) return `${(n / 1e9).toFixed(2)}B`;
  if (n >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (n >= 1e3) return `${(n / 1e3).toFixed(1)}K`;
  return n.toFixed(2);
}

// ─── Replay chart ─────────────────────────────────────────────────────────

function ReplayChart({ bars, volumes, cursor }: {
  bars: CandleBar[];
  volumes: Array<{ time: UTCTimestamp; value: number; color: string }>;
  cursor: number;
}): JSX.Element {
  const containerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candleRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volRef = useRef<ISeriesApi<'Histogram'> | null>(null);
  const cursorLineRef = useRef<ISeriesApi<'Candlestick'> | null>(null);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const chart = createChart(container, {
      layout: { background: { type: ColorType.Solid, color: '#0d1117' }, textColor: '#9ca3af' },
      grid: { vertLines: { color: '#1e2435' }, horzLines: { color: '#1e2435' } },
      crosshair: { mode: 1 },
      rightPriceScale: { borderColor: '#1e2435' },
      timeScale: { borderColor: '#1e2435', timeVisible: true },
      width: container.clientWidth,
      height: container.clientHeight,
    });
    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#26c281', downColor: '#ef5350',
      borderUpColor: '#26c281', borderDownColor: '#ef5350',
      wickUpColor: '#26c28180', wickDownColor: '#ef535080',
    });
    const volSeries = chart.addSeries(HistogramSeries, {
      color: 'rgba(38,194,129,0.3)',
      priceFormat: { type: 'volume' },
      priceScaleId: 'vol',
    });
    chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.8, bottom: 0 } });
    chartRef.current = chart;
    candleRef.current = candleSeries;
    volRef.current = volSeries;
    const ro = new ResizeObserver(() => {
      chart.applyOptions({ width: container.clientWidth, height: container.clientHeight });
    });
    ro.observe(container);
    return () => { ro.disconnect(); chart.remove(); chartRef.current = null; candleRef.current = null; volRef.current = null; };
  }, []);

  useEffect(() => {
    if (!candleRef.current || !volRef.current || bars.length === 0) return;
    const visibleBars = bars.slice(0, cursor + 1);
    const visibleVols = volumes.slice(0, cursor + 1);
    candleRef.current.setData(visibleBars);
    volRef.current.setData(visibleVols);
  }, [bars, volumes, cursor]);

  return <div ref={containerRef} style={{ width: '100%', height: '100%' }} />;
}

// ─── Main page ─────────────────────────────────────────────────────────────

export default function BacktestsReplayPage(): JSX.Element {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [timeframe, setTimeframe] = useState('1h');
  const [state, setState] = useState<ReplayState>({ bars: [], volumes: [], cursor: 0, playing: false, speed: 1 });
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const { envelope: replayEnv } = useRealtimeResource<ReplayStatus>({
    url: '/api/v2/replay/status',
    source: '/api/v2/replay/status',
    source_type: 'api',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });

  // Load candles from backend
  const loadData = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    setState((s) => ({ ...s, playing: false, cursor: 0 }));
    if (intervalRef.current) clearInterval(intervalRef.current);
    try {
      const env = await getV2MarketCandles(symbol, timeframe);
      const candles = env?.data?.candles ?? [];
      const bars: CandleBar[] = candles
        .filter((c) => c.open_time_ms && c.open != null && c.high != null && c.low != null && c.close != null)
        .map((c) => ({
          time: Math.floor(c.open_time_ms! / 1000) as UTCTimestamp,
          open: c.open!, high: c.high!, low: c.low!, close: c.close!,
          volume: c.volume ?? 0,
        }))
        .sort((a, b) => (a.time as number) - (b.time as number));
      const volumes = bars.map((b) => ({
        time: b.time,
        value: b.volume ?? 0,
        color: b.close >= b.open ? 'rgba(38,194,129,0.35)' : 'rgba(239,83,80,0.35)',
      }));
      setState((s) => ({ ...s, bars, volumes, cursor: Math.min(50, bars.length - 1) }));
    } catch (e) {
      setLoadError(String(e));
    } finally {
      setLoading(false);
    }
  }, [symbol, timeframe]);

  // Load initial data
  useEffect(() => {
    void loadData();
  }, [loadData]);

  // Playback ticker
  useEffect(() => {
    if (state.playing) {
      intervalRef.current = setInterval(() => {
        setState((s) => {
          if (s.cursor >= s.bars.length - 1) {
            clearInterval(intervalRef.current!);
            return { ...s, playing: false };
          }
          return { ...s, cursor: s.cursor + 1 };
        });
      }, Math.max(50, 500 / state.speed));
    } else {
      if (intervalRef.current) clearInterval(intervalRef.current);
    }
    return () => { if (intervalRef.current) clearInterval(intervalRef.current); };
  }, [state.playing, state.speed]);

  const currentBar = state.bars[state.cursor];
  const progress = state.bars.length > 1 ? (state.cursor / (state.bars.length - 1)) * 100 : 0;
  const change = currentBar && state.bars[0] ? ((currentBar.close - state.bars[0].open) / state.bars[0].open) * 100 : null;
  const isUp = currentBar && state.cursor > 0 ? currentBar.close >= state.bars[state.cursor - 1].close : null;

  return (
    <div
      data-testid="page-backtests-replay"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: '#0d1117', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}
    >
      {/* ── Header ── */}
      <div style={{ padding: '14px 20px', background: '#131720', borderBottom: '1px solid #1e2435', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', flexShrink: 0 }}>
        <Link to="/backtests" style={{ fontSize: 12, color: '#4b5563', textDecoration: 'none', display: 'flex', alignItems: 'center', gap: 4 }}>
          ← Backtests
        </Link>
        <div style={{ width: 1, height: 16, background: '#1e2435' }} />
        <span style={{ fontSize: 14, fontWeight: 700, color: '#e5e7eb' }}>Replay</span>

        {/* Symbol selector */}
        <div style={{ display: 'flex', gap: 4 }}>
          {HOT_SYMBOLS.map((s) => (
            <button key={s} onClick={() => setSymbol(s)} style={{
              padding: '4px 10px', borderRadius: 6, fontSize: 11.5, fontFamily: 'monospace',
              border: `1px solid ${symbol === s ? '#3b82f6' : '#1e2435'}`,
              background: symbol === s ? 'rgba(59,130,246,0.1)' : 'transparent',
              color: symbol === s ? '#60a5fa' : '#6b7280', cursor: 'pointer',
            }}>
              {s.replace('USDT', '')}
            </button>
          ))}
        </div>

        <div style={{ display: 'flex', gap: 4 }}>
          {TIMEFRAMES.map((tf) => (
            <button key={tf} onClick={() => setTimeframe(tf)} style={{
              padding: '4px 10px', borderRadius: 6, fontSize: 11.5, fontFamily: 'monospace',
              border: `1px solid ${timeframe === tf ? '#3b82f6' : '#1e2435'}`,
              background: timeframe === tf ? 'rgba(59,130,246,0.1)' : 'transparent',
              color: timeframe === tf ? '#60a5fa' : '#6b7280', cursor: 'pointer',
            }}>
              {tf}
            </button>
          ))}
        </div>

        <button onClick={() => void loadData()} disabled={loading} style={{
          padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
          border: '1px solid #1e2435', background: 'transparent', color: loading ? '#4b5563' : '#9ca3af', cursor: loading ? 'not-allowed' : 'pointer',
        }}>
          {loading ? 'Loading…' : 'Load'}
        </button>

        <div style={{ flex: 1 }} />
        <FreshnessBadge status={replayEnv.freshness_status} lagMs={replayEnv.lag_ms} />
      </div>

      {/* ── Main layout ── */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 260px', gridTemplateRows: '1fr auto', minHeight: 0 }}>

        {/* Chart */}
        <div style={{ gridColumn: 1, gridRow: 1, minHeight: 0, position: 'relative' }}>
          {loading && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(13,17,23,0.8)', zIndex: 10 }}>
              <div style={{ fontSize: 13, color: '#6b7280' }}>Loading {symbol} {timeframe} candles…</div>
            </div>
          )}
          {loadError && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 20 }}>⚠</div>
              <p style={{ color: '#ef5350', fontSize: 13, margin: 0 }}>{loadError}</p>
              <button onClick={() => void loadData()} style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #ef535040', background: 'rgba(239,83,80,0.08)', color: '#ef5350', fontSize: 12, cursor: 'pointer' }}>Retry</button>
            </div>
          )}
          {state.bars.length > 0 && (
            <ReplayChart bars={state.bars} volumes={state.volumes} cursor={state.cursor} />
          )}
        </div>

        {/* Right panel */}
        <div style={{ gridColumn: 2, gridRow: '1 / 3', background: '#131720', borderLeft: '1px solid #1e2435', padding: 16, overflow: 'auto' }}>
          {/* Current bar info */}
          <div style={{ marginBottom: 16, padding: '12px 14px', background: '#0d1117', borderRadius: 8, border: '1px solid #1e2435' }}>
            <div style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Current Bar</div>
            {currentBar ? (
              <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8 }}>
                {[
                  { label: 'Open', value: fmtPrice(currentBar.open), color: '#9ca3af' },
                  { label: 'High', value: fmtPrice(currentBar.high), color: '#26c281' },
                  { label: 'Low', value: fmtPrice(currentBar.low), color: '#ef5350' },
                  { label: 'Close', value: fmtPrice(currentBar.close), color: isUp ? '#26c281' : '#ef5350' },
                ].map(({ label, value, color }) => (
                  <div key={label}>
                    <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</div>
                    <div style={{ fontSize: 13, fontFamily: 'monospace', fontWeight: 700, color }}>{value}</div>
                  </div>
                ))}
              </div>
            ) : (
              <div style={{ fontSize: 12, color: '#4b5563' }}>No bar selected</div>
            )}
            {currentBar && (
              <div style={{ marginTop: 8, paddingTop: 8, borderTop: '1px solid #1e2435' }}>
                <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Volume</div>
                <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#9ca3af' }}>{fmtVol(currentBar.volume)}</div>
              </div>
            )}
          </div>

          {/* Session stats */}
          <div style={{ marginBottom: 16, padding: '12px 14px', background: '#0d1117', borderRadius: 8, border: '1px solid #1e2435' }}>
            <div style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Session Stats</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              <div>
                <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Total Move</div>
                <div style={{ fontSize: 14, fontFamily: 'monospace', fontWeight: 700, color: change != null ? (change >= 0 ? '#26c281' : '#ef5350') : '#4b5563' }}>
                  {change != null ? `${change >= 0 ? '+' : ''}${change.toFixed(2)}%` : '—'}
                </div>
              </div>
              <div>
                <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Bars Replayed</div>
                <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#9ca3af' }}>{state.cursor + 1} / {state.bars.length}</div>
              </div>
              <div>
                <div style={{ fontSize: 9, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Progress</div>
                <div style={{ height: 4, background: '#1e2435', borderRadius: 2, marginTop: 4, overflow: 'hidden' }}>
                  <div style={{ height: '100%', width: `${progress}%`, background: '#3b82f6', borderRadius: 2 }} />
                </div>
              </div>
            </div>
          </div>

          {/* Replay engine status */}
          <div style={{ padding: '12px 14px', background: '#0d1117', borderRadius: 8, border: '1px solid #1e2435', marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Replay Engine</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 11, color: replayEnv.data?.last_run ? '#26c281' : '#f59e0b', fontFamily: 'monospace' }}>
                {replayEnv.data?.last_run ? `Last run: ${replayEnv.data.last_run}` : 'No run recorded'}
              </div>
              {replayEnv.data?.bounded_events_count != null && (
                <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>
                  Events: {replayEnv.data.bounded_events_count.toLocaleString()}
                </div>
              )}
              {replayEnv.data?.idempotent_hash && (
                <div style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace', wordBreak: 'break-all' }}>
                  Hash: {replayEnv.data.idempotent_hash.slice(0, 16)}…
                </div>
              )}
            </div>
          </div>

          {/* Pending features */}
          <div style={{ padding: '12px 14px', background: '#0d1117', borderRadius: 8, border: '1px solid #1e2435' }}>
            <div style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Pending Features</div>
            {['Signal overlays', 'Risk decision replay', 'Equity curve', 'Feature snapshots', 'Scenario comparison'].map((f) => (
              <div key={f} style={{ fontSize: 11, color: '#4b5563', padding: '3px 0', borderBottom: '1px solid #1e2435', display: 'flex', alignItems: 'center', gap: 6 }}>
                <span style={{ color: '#f59e0b' }}>○</span> {f}
              </div>
            ))}
          </div>
        </div>

        {/* Controls bar */}
        <div style={{ gridColumn: 1, gridRow: 2, background: '#131720', borderTop: '1px solid #1e2435', padding: '12px 20px', display: 'flex', alignItems: 'center', gap: 12, flexShrink: 0, flexWrap: 'wrap' }}>
          {/* Rewind */}
          <button
            onClick={() => setState((s) => ({ ...s, cursor: 0, playing: false }))}
            title="Rewind to start"
            style={{ width: 32, height: 32, borderRadius: 8, border: '1px solid #1e2435', background: 'transparent', color: '#6b7280', cursor: 'pointer', fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >⏮</button>

          {/* Step back */}
          <button
            onClick={() => setState((s) => ({ ...s, cursor: Math.max(0, s.cursor - 1), playing: false }))}
            title="Step back one bar"
            disabled={state.cursor === 0}
            style={{ width: 32, height: 32, borderRadius: 8, border: '1px solid #1e2435', background: 'transparent', color: state.cursor === 0 ? '#2d3748' : '#6b7280', cursor: state.cursor === 0 ? 'not-allowed' : 'pointer', fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >⏴</button>

          {/* Play/Pause */}
          <button
            onClick={() => setState((s) => ({ ...s, playing: !s.playing }))}
            disabled={state.bars.length === 0}
            title={state.playing ? 'Pause' : 'Play'}
            style={{
              width: 40, height: 40, borderRadius: 10,
              border: `1px solid ${state.playing ? '#3b82f640' : '#3b82f6'}`,
              background: state.playing ? 'rgba(59,130,246,0.2)' : 'rgba(59,130,246,0.1)',
              color: '#60a5fa', cursor: state.bars.length === 0 ? 'not-allowed' : 'pointer',
              fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700,
            }}
          >
            {state.playing ? '⏸' : '▶'}
          </button>

          {/* Step forward */}
          <button
            onClick={() => setState((s) => ({ ...s, cursor: Math.min(s.bars.length - 1, s.cursor + 1), playing: false }))}
            title="Step forward one bar"
            disabled={state.cursor >= state.bars.length - 1}
            style={{ width: 32, height: 32, borderRadius: 8, border: '1px solid #1e2435', background: 'transparent', color: state.cursor >= state.bars.length - 1 ? '#2d3748' : '#6b7280', cursor: state.cursor >= state.bars.length - 1 ? 'not-allowed' : 'pointer', fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >⏵</button>

          {/* Fast forward */}
          <button
            onClick={() => setState((s) => ({ ...s, cursor: s.bars.length - 1, playing: false }))}
            title="Jump to end"
            style={{ width: 32, height: 32, borderRadius: 8, border: '1px solid #1e2435', background: 'transparent', color: '#6b7280', cursor: 'pointer', fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >⏭</button>

          {/* Divider */}
          <div style={{ width: 1, height: 24, background: '#1e2435' }} />

          {/* Speed selector */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
            <span style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Speed</span>
            {SPEEDS.map((s) => (
              <button
                key={s}
                onClick={() => setState((prev) => ({ ...prev, speed: s }))}
                style={{
                  padding: '4px 9px', borderRadius: 6, fontSize: 11, fontFamily: 'monospace',
                  border: `1px solid ${state.speed === s ? '#3b82f6' : '#1e2435'}`,
                  background: state.speed === s ? 'rgba(59,130,246,0.1)' : 'transparent',
                  color: state.speed === s ? '#60a5fa' : '#4b5563', cursor: 'pointer',
                }}
              >
                {s}×
              </button>
            ))}
          </div>

          {/* Divider */}
          <div style={{ width: 1, height: 24, background: '#1e2435' }} />

          {/* Timeline scrubber */}
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 200 }}>
            <span style={{ fontSize: 10, color: '#4b5563', whiteSpace: 'nowrap', fontFamily: 'monospace' }}>
              {state.cursor + 1}/{state.bars.length}
            </span>
            <input
              type="range"
              min={0}
              max={Math.max(0, state.bars.length - 1)}
              value={state.cursor}
              onChange={(e) => setState((s) => ({ ...s, cursor: Number(e.target.value), playing: false }))}
              style={{ flex: 1, accentColor: '#3b82f6' }}
            />
            <span style={{ fontSize: 10, color: '#4b5563', fontFamily: 'monospace', whiteSpace: 'nowrap' }}>
              {progress.toFixed(0)}%
            </span>
          </div>

          <div style={{ flex: 1 }} />

          {/* Bar timestamp */}
          {currentBar && (
            <span style={{ fontSize: 11, fontFamily: 'monospace', color: '#4b5563', whiteSpace: 'nowrap' }}>
              {new Date((currentBar.time as number) * 1000).toUTCString().replace(' GMT', 'Z').split('T')[0]}
            </span>
          )}
        </div>
      </div>
    </div>
  );
}
