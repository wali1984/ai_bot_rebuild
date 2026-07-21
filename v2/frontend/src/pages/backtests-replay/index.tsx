import { useState, useRef, useEffect, useMemo } from 'react';
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
import type { MarketCandlesData } from '../../types/apiV2';
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
  cursor: number;
  playing: boolean;
  speed: 1 | 2 | 5 | 10;
}

interface ReplayStatus {
  last_run: string | null;
  idempotent_hash: string | null;
  bounded_events_count: number | null;
}

interface BacktestResults {
  available: boolean;
  generated_utc: string | null;
  effective_trainer_mode: string | null;
  replay_examples_built: number | null;
  backtest_is_a_plus_evidence: boolean;
  continuous_replay_active: boolean | null;
  policy_backtest: {
    win_rate: number | null;
    profit_factor_proxy: number | null;
    expectancy_after_cost_bps: number | null;
    rows_evaluated: number | null;
    status: string | null;
    evidence_class: string | null;
  } | null;
  generalization: {
    validation_supervised_loss: number | null;
    validation_rows_evaluated: number | null;
    train_val_generalization_gap: number | null;
    overfit_gap_warning: boolean | null;
    loss_before: number | null;
    loss_after: number | null;
  } | null;
  replay_feedback: {
    existing_counterfactual_rows: number | null;
    new_matured_rows: number | null;
    pending_rows: number | null;
    trainer_loader_consumes: boolean | null;
  } | null;
  edge_factory_replay_status?: {
    status: string | null;
    generated_utc: string | null;
    replay_windows_processed: number | null;
    snapshots_scanned: number | null;
  } | null;
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
  const [state, setState] = useState<ReplayState>({ cursor: 0, playing: false, speed: 1 });
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const candleUrl = `/api/v2/market/${symbol}/candles?timeframe=${encodeURIComponent(timeframe)}&limit=500`;

  const { envelope: replayEnv } = useRealtimeResource<ReplayStatus>({
    url: '/api/v2/replay/status',
    source: '/api/v2/replay/status',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });

  const { envelope: backtestEnv } = useRealtimeResource<BacktestResults>({
    url: '/api/v2/replay/backtest',
    source: '/api/v2/replay/backtest',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 120_000,
    mode: 'read_only',
  });

  const {
    envelope: candleEnv,
    loading: candleLoading,
    error: candleError,
    refetch: syncCandles,
  } = useRealtimeResource<MarketCandlesData>({
    url: candleUrl,
    source: `/api/v2/market/${symbol}/candles`,
    source_type: 'websocket',
    pollIntervalMs: 5_000,
    staleThresholdMs: 20_000,
    mode: 'read_only',
  });

  const bars = useMemo<CandleBar[]>(() => {
    const candles = candleEnv.data?.candles ?? [];
    return candles
      .filter((c) => c.open_time_ms && c.open != null && c.high != null && c.low != null && c.close != null)
      .map((c) => ({
        time: Math.floor(c.open_time_ms! / 1000) as UTCTimestamp,
        open: c.open!,
        high: c.high!,
        low: c.low!,
        close: c.close!,
        volume: c.volume ?? 0,
      }))
      .sort((a, b) => (a.time as number) - (b.time as number));
  }, [candleEnv.data?.candles]);

  const volumes = useMemo(() => bars.map((b) => ({
    time: b.time,
    value: b.volume ?? 0,
    color: b.close >= b.open ? 'rgba(38,194,129,0.35)' : 'rgba(239,83,80,0.35)',
  })), [bars]);

  useEffect(() => {
    setState((s) => ({
      ...s,
      cursor: bars.length ? Math.min(s.cursor, bars.length - 1) : 0,
      playing: bars.length ? s.playing : false,
    }));
  }, [bars.length]);

  // Playback ticker
  useEffect(() => {
    if (state.playing) {
      intervalRef.current = setInterval(() => {
        setState((s) => {
          if (s.cursor >= bars.length - 1) {
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
  }, [bars.length, state.playing, state.speed]);

  const currentBar = bars[state.cursor];
  const progress = bars.length > 1 ? (state.cursor / (bars.length - 1)) * 100 : 0;
  const change = currentBar && bars[0] ? ((currentBar.close - bars[0].open) / bars[0].open) * 100 : null;
  const isUp = currentBar && state.cursor > 0 ? currentBar.close >= bars[state.cursor - 1].close : null;

  return (
    <div
      data-testid="page-backtests-replay"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), #0d1117', minHeight: '100vh', display: 'flex', flexDirection: 'column' }}
    >
      {/* ── Header ── */}
      <div style={{ padding: '14px 20px', background: 'color-mix(in oklch, #131720 82%, transparent)', backdropFilter: 'blur(8px)', borderBottom: '1px solid #1e2435', display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap', flexShrink: 0 }}>
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

        <button onClick={() => {
          setState((s) => ({ ...s, playing: false }));
          syncCandles();
        }} disabled={candleLoading} style={{
          padding: '5px 14px', borderRadius: 6, fontSize: 12, fontWeight: 600,
          border: '1px solid #1e2435', background: 'transparent', color: candleLoading ? '#4b5563' : '#9ca3af', cursor: candleLoading ? 'not-allowed' : 'pointer',
        }}>
          {candleLoading ? 'Syncing…' : 'Sync'}
        </button>

        <div style={{ flex: 1 }} />
        <FreshnessBadge status={candleEnv.freshness_status} lagMs={candleEnv.lag_ms} />
      </div>

      {/* ── Main layout ── */}
      <div style={{ flex: 1, display: 'grid', gridTemplateColumns: '1fr 260px', gridTemplateRows: '1fr auto', minHeight: 0 }}>

        {/* Chart */}
        <div style={{ gridColumn: 1, gridRow: 1, minHeight: 0, position: 'relative' }}>
          {candleLoading && bars.length === 0 && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', background: 'rgba(13,17,23,0.8)', zIndex: 10 }}>
              <div style={{ fontSize: 13, color: '#6b7280' }}>Syncing {symbol} {timeframe} candles…</div>
            </div>
          )}
          {candleError && bars.length === 0 && (
            <div style={{ position: 'absolute', inset: 0, display: 'flex', alignItems: 'center', justifyContent: 'center', flexDirection: 'column', gap: 10 }}>
              <div style={{ fontSize: 20 }}>⚠</div>
              <p style={{ color: '#ef5350', fontSize: 13, margin: 0 }}>{candleError}</p>
              <button onClick={syncCandles} style={{ padding: '6px 16px', borderRadius: 6, border: '1px solid #ef535040', background: 'rgba(239,83,80,0.08)', color: '#ef5350', fontSize: 12, cursor: 'pointer' }}>Retry</button>
            </div>
          )}
          {bars.length > 0 && (
            <ReplayChart bars={bars} volumes={volumes} cursor={state.cursor} />
          )}
        </div>

        {/* Right panel */}
        <div style={{ gridColumn: 2, gridRow: '1 / 3', background: '#131720', borderLeft: '1px solid #1e2435', padding: 16, overflow: 'auto' }}>
          {/* Current bar info */}
          <div className="glass" style={{ marginBottom: 16, padding: '12px 14px' }}>
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
          <div className="glass" style={{ marginBottom: 16, padding: '12px 14px' }}>
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
                <div style={{ fontSize: 12, fontFamily: 'monospace', color: '#9ca3af' }}>{state.cursor + 1} / {bars.length}</div>
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
          <div className="glass" style={{ padding: '12px 14px', marginBottom: 16 }}>
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

          {/* Backtest results + out-of-sample generalization */}
          <div data-testid="backtest-results-card" className="glass" style={{ padding: '12px 14px', marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Backtest &amp; Generalization</div>
            {backtestEnv.data?.available && backtestEnv.data.policy_backtest ? (
              <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
                <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: 'monospace', fontSize: 11 }}>
                  <span style={{ color: '#26c281' }}>Win {backtestEnv.data.policy_backtest.win_rate != null ? `${(backtestEnv.data.policy_backtest.win_rate * 100).toFixed(1)}%` : '—'}</span>
                  <span style={{ color: '#9ca3af' }}>PF {backtestEnv.data.policy_backtest.profit_factor_proxy != null ? backtestEnv.data.policy_backtest.profit_factor_proxy.toFixed(2) : '—'}</span>
                  <span style={{ color: '#9ca3af' }}>Exp {backtestEnv.data.policy_backtest.expectancy_after_cost_bps != null ? `${backtestEnv.data.policy_backtest.expectancy_after_cost_bps.toFixed(1)}bps` : '—'}</span>
                  <span style={{ color: '#4b5563' }}>rows {backtestEnv.data.policy_backtest.rows_evaluated ?? '—'}</span>
                </div>
                {backtestEnv.data.generalization && (
                  <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', fontFamily: 'monospace', fontSize: 11 }}>
                    <span style={{ color: '#9ca3af' }}>train {backtestEnv.data.generalization.loss_after != null ? backtestEnv.data.generalization.loss_after.toFixed(2) : '—'}</span>
                    <span style={{ color: '#9ca3af' }}>val {backtestEnv.data.generalization.validation_supervised_loss != null ? backtestEnv.data.generalization.validation_supervised_loss.toFixed(2) : '—'}</span>
                    <span style={{ color: backtestEnv.data.generalization.overfit_gap_warning ? '#ef5350' : '#26c281' }}>
                      gap {backtestEnv.data.generalization.train_val_generalization_gap != null ? backtestEnv.data.generalization.train_val_generalization_gap.toFixed(2) : '—'}
                      {backtestEnv.data.generalization.overfit_gap_warning ? ' ⚠ overfit' : ''}
                    </span>
                  </div>
                )}
                <div style={{ fontSize: 9, color: '#f59e0b', fontStyle: 'italic' }}>
                  {backtestEnv.data.policy_backtest.evidence_class || 'BACKTEST_ONLY'} — not A+/live evidence
                </div>
              </div>
            ) : (
              <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>
                No completed backtest cycle reported (available={String(backtestEnv.data?.available ?? false)}).
              </div>
            )}
            {/* Replay-feedback + edge-factory truth is real data even when no
                backtest cycle has completed (available=false) — never hide it
                behind the policy_backtest gate. */}
            {backtestEnv.data?.replay_feedback && (
              <div style={{ marginTop: 6, display: 'flex', flexDirection: 'column', gap: 3, fontFamily: 'monospace' }}>
                <div style={{ fontSize: 10, color: '#9ca3af' }}>
                  replay→trainer: {(backtestEnv.data.replay_feedback.existing_counterfactual_rows ?? 0).toLocaleString()} counterfactual rows
                  {backtestEnv.data.replay_feedback.trainer_loader_consumes ? ' · trainer loader consumes ✓' : ''}
                  {backtestEnv.data.continuous_replay_active ? ' · continuous ✓' : ''}
                </div>
                {(backtestEnv.data.replay_feedback.new_matured_rows != null || backtestEnv.data.replay_feedback.pending_rows != null) && (
                  <div style={{ fontSize: 10, color: '#4b5563' }}>
                    matured {backtestEnv.data.replay_feedback.new_matured_rows ?? '—'} · pending {backtestEnv.data.replay_feedback.pending_rows ?? '—'}
                  </div>
                )}
              </div>
            )}
            {backtestEnv.data?.edge_factory_replay_status?.generated_utc && (
              <div style={{ marginTop: 4, fontSize: 10, color: '#4b5563', fontFamily: 'monospace' }}>
                edge-factory replay: {backtestEnv.data.edge_factory_replay_status.status ?? 'reported'}
                {backtestEnv.data.edge_factory_replay_status.replay_windows_processed != null ? ` · windows ${backtestEnv.data.edge_factory_replay_status.replay_windows_processed}` : ''}
                {backtestEnv.data.edge_factory_replay_status.snapshots_scanned != null ? ` · snapshots ${backtestEnv.data.edge_factory_replay_status.snapshots_scanned}` : ''}
                {' · '}{backtestEnv.data.edge_factory_replay_status.generated_utc}
              </div>
            )}
          </div>

          {/* Candle resource status */}
          <div className="glass" style={{ padding: '12px 14px' }}>
            <div style={{ fontSize: 10, color: '#4b5563', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Candle Stream</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
              <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>
                Source: {candleEnv.source_type}
              </div>
              <div style={{ fontSize: 11, color: '#9ca3af', fontFamily: 'monospace' }}>
                Candles: {bars.length.toLocaleString()}
              </div>
              {candleEnv.warnings.length > 0 && (
                <div style={{ fontSize: 10, color: '#f59e0b', lineHeight: 1.4 }}>
                  {candleEnv.warnings[0]}
                </div>
              )}
            </div>
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
            disabled={bars.length === 0}
            title={state.playing ? 'Pause' : 'Play'}
            style={{
              width: 40, height: 40, borderRadius: 10,
              border: `1px solid ${state.playing ? '#3b82f640' : '#3b82f6'}`,
              background: state.playing ? 'rgba(59,130,246,0.2)' : 'rgba(59,130,246,0.1)',
              color: '#60a5fa', cursor: bars.length === 0 ? 'not-allowed' : 'pointer',
              fontSize: 16, display: 'flex', alignItems: 'center', justifyContent: 'center', fontWeight: 700,
            }}
          >
            {state.playing ? '⏸' : '▶'}
          </button>

          {/* Step forward */}
          <button
            onClick={() => setState((s) => ({ ...s, cursor: Math.min(bars.length - 1, s.cursor + 1), playing: false }))}
            title="Step forward one bar"
            disabled={state.cursor >= bars.length - 1}
            style={{ width: 32, height: 32, borderRadius: 8, border: '1px solid #1e2435', background: 'transparent', color: state.cursor >= bars.length - 1 ? '#2d3748' : '#6b7280', cursor: state.cursor >= bars.length - 1 ? 'not-allowed' : 'pointer', fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
          >⏵</button>

          {/* Fast forward */}
          <button
            onClick={() => setState((s) => ({ ...s, cursor: bars.length - 1, playing: false }))}
            title="Jump to end"
            disabled={bars.length === 0}
            style={{ width: 32, height: 32, borderRadius: 8, border: '1px solid #1e2435', background: 'transparent', color: bars.length === 0 ? '#2d3748' : '#6b7280', cursor: bars.length === 0 ? 'not-allowed' : 'pointer', fontSize: 14, display: 'flex', alignItems: 'center', justifyContent: 'center' }}
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
              {state.cursor + 1}/{bars.length}
            </span>
            <input
              type="range"
              min={0}
              max={Math.max(0, bars.length - 1)}
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
