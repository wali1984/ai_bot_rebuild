import { useState, useCallback, useEffect } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types ─────────────────────────────────────────────────────────────────

interface BacktestResult {
  run_id: string;
  symbol: string;
  timeframe: string;
  strategy: string;
  started_at: string | null;
  completed_at: string | null;
  status: string;
  total_trades: number | null;
  wins: number | null;
  losses: number | null;
  win_rate: number | null;
  total_pnl: number | null;
  sharpe_ratio: number | null;
  max_drawdown: number | null;
  candle_count: number | null;
  equity_curve: number[] | null;
  trade_count: number | null;
  trades: Array<{
    entry_time?: string;
    action?: string;
    entry_price?: number;
    exit_price?: number;
    pnl?: number;
    exit_reason?: string;
  }> | null;
}

interface BacktestResultsData {
  results: BacktestResult[];
  count: number;
}

interface RunStatus {
  run_id: string;
  status: string;
  result?: Partial<BacktestResult>;
}

// ─── Constants ─────────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'] as const;
type TF = typeof TIMEFRAMES[number];
const SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT', 'ADAUSDT', 'LTCUSDT', 'DOTUSDT'];

// ─── Helpers ──────────────────────────────────────────────────────────────

function fmtPct(v: number | null | undefined): string {
  if (v == null) return '—';
  return `${(v * 100).toFixed(2)}%`;
}
function pnlColor(v: number | null | undefined): string {
  if (v == null) return 'var(--text-muted)';
  return v > 0 ? '#26c281' : v < 0 ? '#ef5350' : '#f59e0b';
}
function winColor(wr: number | null | undefined): string {
  if (wr == null) return 'var(--text-muted)';
  if (wr >= 0.6) return '#26c281';
  if (wr >= 0.45) return '#f59e0b';
  return '#ef5350';
}

// ─── Mini equity curve ────────────────────────────────────────────────────

function MiniEquityCurve({ curve }: { curve: number[] | null }): JSX.Element {
  if (!curve || curve.length < 2) return <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>—</span>;
  const min = Math.min(...curve);
  const max = Math.max(...curve);
  const range = max - min || 1;
  const w = 120, h = 32;
  const step = w / (curve.length - 1);
  const pts = curve.map((v, i) => `${i * step},${h - ((v - min) / range) * h}`).join(' ');
  const lastVal = curve[curve.length - 1];
  const color = lastVal > 0 ? '#26c281' : lastVal < 0 ? '#ef5350' : '#f59e0b';
  return (
    <svg width={w} height={h} style={{ display: 'block' }}>
      <polyline points={pts} fill="none" stroke={color} strokeWidth="1.5" />
    </svg>
  );
}

// ─── Result card ─────────────────────────────────────────────────────────

function ResultCard({ r, onSelect }: { r: BacktestResult; onSelect: () => void }): JSX.Element {
  const wr = r.win_rate;
  return (
    <div onClick={onSelect} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px', cursor: 'pointer', transition: 'border-color 0.15s' }}
      onMouseEnter={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'rgba(59,130,246,0.4)'}
      onMouseLeave={e => (e.currentTarget as HTMLDivElement).style.borderColor = 'var(--border)'}>
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 10 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{r.symbol.replace('USDT', '')} <span style={{ fontSize: 11, color: '#3b82f6', background: 'rgba(59,130,246,0.08)', padding: '1px 5px', borderRadius: 3 }}>{r.timeframe}</span></div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', marginTop: 2 }}>{r.run_id.slice(0, 12)}… · {r.strategy}</div>
        </div>
        <div style={{ textAlign: 'right' }}>
          <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: pnlColor(r.total_pnl) }}>{fmtPct(r.total_pnl)}</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>total PnL</div>
        </div>
      </div>
      <div style={{ display: 'flex', gap: 12, marginBottom: 10, flexWrap: 'wrap' }}>
        {[
          { label: 'Win Rate', value: wr != null ? `${(wr * 100).toFixed(1)}%` : '—', color: winColor(wr) },
          { label: 'Trades', value: r.total_trades ?? '—', color: 'var(--text-secondary)' },
          { label: 'Sharpe', value: r.sharpe_ratio != null ? r.sharpe_ratio.toFixed(2) : '—', color: (r.sharpe_ratio ?? 0) >= 0 ? '#26c281' : '#ef5350' },
          { label: 'Max DD', value: r.max_drawdown != null ? fmtPct(r.max_drawdown) : '—', color: '#ef5350' },
          { label: 'Candles', value: r.candle_count ?? '—', color: 'var(--text-muted)' },
        ].map(kpi => (
          <div key={kpi.label}>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{kpi.label}</div>
            <div style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: String(kpi.color) }}>{kpi.value}</div>
          </div>
        ))}
      </div>
      <MiniEquityCurve curve={r.equity_curve} />
    </div>
  );
}

// ─── Result detail ────────────────────────────────────────────────────────

function ResultDetail({ result, onClose }: { result: BacktestResult; onClose: () => void }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--accent)', borderRadius: 12, padding: '20px 24px', marginBottom: 20 }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 16 }}>
        <h3 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>{result.symbol} {result.timeframe} — Backtest Detail</h3>
        <button onClick={onClose} style={{ marginLeft: 'auto', padding: '4px 10px', borderRadius: 5, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>Close</button>
      </div>
      {/* Equity curve */}
      {result.equity_curve && result.equity_curve.length >= 2 && (
        <div style={{ marginBottom: 20 }}>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Equity Curve</div>
          {(() => {
            const curve = result.equity_curve!;
            const min = Math.min(...curve);
            const max = Math.max(...curve);
            const range = max - min || 1;
            const w = 600, h = 80;
            const step = w / (curve.length - 1);
            const pts = curve.map((v, i) => `${i * step},${h - ((v - min) / range) * h}`).join(' ');
            const lastVal = curve[curve.length - 1];
            const color = lastVal > 0 ? '#26c281' : '#ef5350';
            return (
              <svg width="100%" viewBox={`0 0 ${w} ${h}`} style={{ display: 'block', maxWidth: 600 }}>
                <line x1="0" y1={h - ((0 - min) / range) * h} x2={w} y2={h - ((0 - min) / range) * h} stroke="rgba(255,255,255,0.08)" strokeWidth="1" />
                <polyline points={pts} fill="none" stroke={color} strokeWidth="2" />
              </svg>
            );
          })()}
        </div>
      )}
      {/* Trade journal */}
      {result.trades && result.trades.length > 0 && (
        <div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Trade Journal ({result.trades.length} trades)</div>
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
              <thead>
                <tr>
                  {['Time', 'Action', 'Entry', 'Exit', 'PnL', 'Reason'].map(col => (
                    <th key={col} style={{ padding: '6px 10px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 9, textTransform: 'uppercase', letterSpacing: '0.05em', whiteSpace: 'nowrap', fontWeight: 600 }}>{col}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {result.trades.slice(0, 50).map((t, i) => (
                  <tr key={i} style={{ borderBottom: '1px solid rgba(255,255,255,0.03)' }}>
                    <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{t.entry_time ? new Date(t.entry_time).toLocaleString() : '—'}</td>
                    <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: t.action?.includes('long') ? '#26c281' : '#ef5350' }}>{(t.action ?? '').replace(/_/g, ' ').toUpperCase()}</td>
                    <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: 11 }}>${t.entry_price?.toFixed(2) ?? '—'}</td>
                    <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontSize: 11 }}>${t.exit_price?.toFixed(2) ?? '—'}</td>
                    <td style={{ padding: '5px 10px', fontFamily: 'var(--font-mono)', fontWeight: 700, color: pnlColor(t.pnl) }}>{t.pnl != null ? fmtPct(t.pnl) : '—'}</td>
                    <td style={{ padding: '5px 10px', fontSize: 10, color: 'var(--text-muted)' }}>{t.exit_reason ?? '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
            {(result.trades?.length ?? 0) > 50 && <div style={{ padding: '8px 10px', fontSize: 11, color: 'var(--text-muted)' }}>…showing first 50 of {result.trades!.length} trades</div>}
          </div>
        </div>
      )}
    </div>
  );
}

// ─── Manual run form ──────────────────────────────────────────────────────

function RunForm({ onRunStarted }: { onRunStarted: (runId: string) => void }): JSX.Element {
  const [symbol, setSymbol] = useState('BTCUSDT');
  const [tf, setTf] = useState<TF>('1h');
  const [lookback, setLookback] = useState(100);
  const [holdCandles, setHoldCandles] = useState(1);
  const [tpBps, setTpBps] = useState(100);
  const [slBps, setSlBps] = useState(80);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = useCallback(async () => {
    setRunning(true);
    setError(null);
    try {
      const resp = await fetch('/api/v2/backtest/run', {
        method: 'POST',
        credentials: 'include',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ symbol, timeframe: tf, lookback_candles: lookback, hold_candles: holdCandles, tp_bps: tpBps, sl_bps: slBps }),
      });
      if (!resp.ok) {
        const txt = await resp.text();
        throw new Error(`HTTP ${resp.status}: ${txt}`);
      }
      const data = await resp.json();
      const runId = data?.data?.run_id ?? data?.run_id;
      if (runId) onRunStarted(runId);
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  }, [symbol, tf, lookback, holdCandles, tpBps, slBps, onRunStarted]);

  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, padding: '18px 20px', marginBottom: 20 }}>
      <h3 style={{ margin: '0 0 14px', fontSize: 14, fontWeight: 700 }}>Manual Backtest Run</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12, marginBottom: 14 }}>
        <div>
          <label style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 4 }}>Symbol</label>
          <select value={symbol} onChange={e => setSymbol(e.target.value)} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, outline: 'none' }}>
            {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 4 }}>Timeframe</label>
          <select value={tf} onChange={e => setTf(e.target.value as TF)} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, outline: 'none' }}>
            {TIMEFRAMES.map(t => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <div>
          <label style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 4 }}>Lookback Candles</label>
          <input type="number" value={lookback} onChange={e => setLookback(Number(e.target.value))} min={20} max={500} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
        </div>
        <div>
          <label style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 4 }}>Hold Candles</label>
          <input type="number" value={holdCandles} onChange={e => setHoldCandles(Number(e.target.value))} min={1} max={20} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
        </div>
        <div>
          <label style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 4 }}>TP (%)</label>
          <input type="number" value={tpBps / 100} onChange={e => setTpBps(Number(e.target.value) * 100)} min={0.1} max={10} step={0.01} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
        </div>
        <div>
          <label style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', display: 'block', marginBottom: 4 }}>SL (%)</label>
          <input type="number" value={slBps / 100} onChange={e => setSlBps(Number(e.target.value) * 100)} min={0.1} max={10} step={0.01} style={{ width: '100%', padding: '6px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 12, outline: 'none', boxSizing: 'border-box' }} />
        </div>
      </div>
      {error && <div style={{ padding: '8px 12px', borderRadius: 6, background: 'rgba(239,83,80,0.1)', border: '1px solid rgba(239,83,80,0.3)', color: '#ef5350', fontSize: 12, marginBottom: 12 }}>{error}</div>}
      <button onClick={handleRun} disabled={running} style={{
        padding: '8px 20px', borderRadius: 8, fontSize: 13, fontWeight: 700, cursor: running ? 'not-allowed' : 'pointer',
        border: `1px solid ${running ? 'var(--border)' : 'var(--accent)'}`,
        background: running ? 'transparent' : 'rgba(59,130,246,0.1)',
        color: running ? 'var(--text-muted)' : 'var(--accent)',
        display: 'flex', alignItems: 'center', gap: 8,
      }}>
        {running ? '⏳ Running…' : '▶ Run Backtest'}
      </button>
    </div>
  );
}

// ─── Run status poller ────────────────────────────────────────────────────

function RunStatusPoller({ runId, onComplete }: { runId: string; onComplete: () => void }): JSX.Element {
  const [status, setStatus] = useState<RunStatus | null>(null);
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (done) return;
    let mounted = true;
    const poll = async () => {
      try {
        const resp = await fetch(`/api/v2/backtest/status/${runId}`);
        if (!resp.ok) return;
        const data = await resp.json();
        const s: RunStatus = data?.data ?? data;
        if (mounted) {
          setStatus(s);
          if (s.status === 'completed' || s.status === 'error') {
            setDone(true);
            onComplete();
          }
        }
      } catch { /* ignore */ }
    };
    const id = setInterval(poll, 2000);
    poll();
    return () => { mounted = false; clearInterval(id); };
  }, [runId, done, onComplete]);

  if (!status) return (
    <div style={{ padding: '10px 14px', background: 'var(--bg-panel)', borderRadius: 8, border: '1px solid var(--border)', marginBottom: 12, display: 'flex', gap: 10, alignItems: 'center' }}>
      <span style={{ fontSize: 13 }}>⏳</span>
      <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Waiting for run {runId.slice(0, 12)}…</span>
    </div>
  );

  const isComplete = status.status === 'completed';
  const isError = status.status === 'error';
  const color = isComplete ? '#26c281' : isError ? '#ef5350' : '#f59e0b';

  return (
    <div style={{ padding: '10px 14px', background: 'var(--bg-panel)', borderRadius: 8, border: `1px solid ${color}30`, marginBottom: 12, display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
      <span style={{ fontSize: 13 }}>{isComplete ? '✅' : isError ? '❌' : '⏳'}</span>
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>{runId.slice(0, 12)}…</span>
      <span style={{ fontSize: 12, fontWeight: 700, color, fontFamily: 'var(--font-mono)' }}>{status.status.toUpperCase()}</span>
      {isComplete && status.result && <>
        <span style={{ fontSize: 12, color: pnlColor(status.result.total_pnl as number | null) }}>PnL: {fmtPct(status.result.total_pnl as number | null)}</span>
        <span style={{ fontSize: 12, color: winColor(status.result.win_rate as number | null) }}>Win: {status.result.win_rate != null ? `${((status.result.win_rate as number) * 100).toFixed(1)}%` : '—'}</span>
      </>}
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────

export default function BacktestsPage(): JSX.Element {
  const [pendingRunIds, setPendingRunIds] = useState<string[]>([]);
  const [selectedResult, setSelectedResult] = useState<BacktestResult | null>(null);
  const [filterSymbol, setFilterSymbol] = useState('');
  const [filterTF, setFilterTF] = useState('');
  const [resultsVersion, setResultsVersion] = useState(0);

  const { envelope, loading, refetch } = useRealtimeResource<BacktestResultsData>({
    url: `/api/v2/backtest/results${filterSymbol ? `?symbol=${filterSymbol}` : ''}${filterTF ? `${filterSymbol ? '&' : '?'}timeframe=${filterTF}` : ''}`,
    source: '/api/v2/backtest/results',
    pollIntervalMs: 30_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
    initialFetchWhenStreaming: true,
  });

  const results = envelope.data?.results ?? [];
  const backtestSourceUnavailable = !envelope.data || envelope.source_type === 'unavailable';

  const handleRunStarted = useCallback((runId: string) => {
    setPendingRunIds(prev => [runId, ...prev]);
  }, []);

  const handleRunComplete = useCallback(() => {
    setResultsVersion(v => v + 1);
    setTimeout(refetch, 3000);
  }, [refetch]);

  return (
    <div data-testid="page-strategy-backtesting" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh', paddingBottom: 64 }}>

      {/* Header */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <span style={{ fontSize: 18 }}>📈</span>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Backtest Engine</h1>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              Historical replay of AI signals against real OHLCV data · Equity curves · Trade journal · Execution-restricted research
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>
      </div>

      <div style={{ padding: '16px 20px' }}>
        {/* Manual run form */}
        <RunForm onRunStarted={handleRunStarted} />

        {/* Pending run status */}
        {pendingRunIds.map(runId => (
          <RunStatusPoller key={runId} runId={runId} onComplete={handleRunComplete} />
        ))}

        {/* Selected result detail */}
        {selectedResult && <ResultDetail result={selectedResult} onClose={() => setSelectedResult(null)} />}

        {/* Results header */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 14, flexWrap: 'wrap' }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700 }}>All Results</h2>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>{results.length} runs in Redis</span>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginLeft: 'auto', flexWrap: 'wrap' }}>
            <select value={filterSymbol} onChange={e => setFilterSymbol(e.target.value)} style={{ padding: '4px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 11, outline: 'none' }}>
              <option value="">All Symbols</option>
              {SYMBOLS.map(s => <option key={s} value={s}>{s}</option>)}
            </select>
            <select value={filterTF} onChange={e => setFilterTF(e.target.value)} style={{ padding: '4px 8px', borderRadius: 5, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 11, outline: 'none' }}>
              <option value="">All TFs</option>
              {TIMEFRAMES.map(t => <option key={t} value={t}>{t}</option>)}
            </select>
          </div>
        </div>

        {loading && results.length === 0 && <LoadingSkeleton rows={3} />}

        {!loading && results.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', background: 'var(--bg-panel)', borderRadius: 12, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>📊</div>
            <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700 }}>
              {backtestSourceUnavailable ? 'Backtest engine unavailable' : 'Backtest engine unavailable or empty'}
            </h3>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
              {backtestSourceUnavailable
                ? 'Read-only account context only. No sourced backtest rows are available from the read-only endpoint; this is a source availability state, not backtest results.'
                : 'Read-only account context only. The sourced result set is empty; this is an empty source state, not backtest results. Use the Run form above to start a backtest. Results are stored in Redis for 7 days.'}
            </p>
          </div>
        )}

        {results.length > 0 && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 14 }}>
            {results.map(r => (
              <ResultCard key={r.run_id} r={r} onSelect={() => setSelectedResult(r)} />
            ))}
          </div>
        )}

        <div style={{ marginTop: 20, padding: '10px 14px', background: 'var(--bg-panel)', borderRadius: 8, border: '1px solid var(--border)' }}>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
            Source: {envelope.source || '/api/v2/backtest/results'} ·
            {' '}Freshness: {envelope.freshness_status || 'unknown'} ·
            {' '}Backtest reads: Redis OHLCV + signal direction · Fees: 0.05% per side · No exchange orders placed · Results TTL 7 days
          </p>
        </div>
      </div>
    </div>
  );
}
