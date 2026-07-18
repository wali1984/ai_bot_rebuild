import { useState, useMemo } from 'react';
import { usePaperActivityStream } from '../../hooks/usePaperActivityStream';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  pnlWindow,
  type CapitalProductivityRuntimeStatus,
  type PnlHistoryStatus,
  type SignalPredictionAccuracyStatus,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ── Types ────────────────────────────────────────────────────────────────────

interface PaperPosition {
  position_id: string | null;
  symbol: string;
  side: string;
  net_quantity: number | null;
  avg_entry_price: number | null;
  entry_price_source?: string | null;
  mark_price?: number | null;
  last_mark_price: number | null;
  notional_usd: number | null;
  leverage: number;
  unrealized_pnl: number | null;
  unrealized_pnl_bps: number | null;
  mark_price_age_seconds?: number | null;
  mark_price_source?: string | null;
  mark_price_stale?: boolean | null;
  timeframe: string | null;
  strategy_id: string | null;
  market_regime_at_entry: string | null;
  position_age_seconds: number | null;
  opened_est: string | null;
  paper_fill_allowed: boolean | null;
  places_real_order: boolean | null;
  hedge_state: string | null;
  signal_id?: string | null;
  prediction_id?: string | null;
  decision_reasoning?: Record<string, unknown> | null;
}

interface ClosedTrade {
  close_id: string | null;
  symbol: string;
  side: string;
  entry_price: number | null;
  entry_price_source?: string | null;
  exit_price: number | null;
  exit_price_source?: string | null;
  realized_pnl_usd: number | null;
  realized_pnl_bps: number | null;
  close_reason: string | null;
  hold_time_seconds: number | null;
  fees: number | null;
  winner: boolean | null;
  strategy_id: string | null;
  market_regime_at_entry: string | null;
  timeframe: string | null;
  exit_price_utc: string | null;
  signal_id?: string | null;
  prediction_id?: string | null;
  decision_reasoning?: Record<string, unknown> | null;
}

interface EquityPoint { t: string | null; pnl: number; winner: boolean | null }

interface RiskProfile {
  profile_id: string | null;
  max_leverage: number;
  max_notional_per_trade: number | null;
  max_open_positions: number | null;
  min_confidence_calibrated: number | null;
  max_daily_loss: number | null;
  max_drawdown: number | null;
  max_spread_bps: number | null;
  min_expected_move_after_cost_bps: number | null;
  cooldown_seconds: number | null;
}

interface Summary {
  open_position_count: number;
  closed_trade_count: number;
  realized_pnl_usd: number | null;
  realized_net_pnl_usd?: number | null;
  unrealized_pnl_usd: number | null;
  total_pnl_usd?: number | null;
  total_open_notional: number | null;
  paper_signals_seen: number | null;
  intents_accepted: number | null;
  intents_blocked: number | null;
  persistent_accepted_fill_count: number | null;
  worker_id: string | null;
  started_at: string | null;
  finished_at: string | null;
}

interface RealTraderReadiness {
  exact_no_live_reason?: string | null;
  readiness_blockers?: string[] | null;
  live_ready?: boolean | null;
  live_submit_allowed?: boolean | null;
}

interface PaperStatus {
  positions: PaperPosition[];
  closed_trades: ClosedTrade[];
  equity_curve: EquityPoint[];
  reason_breakdown: Record<string, number>;
  risk_profile: RiskProfile;
  summary: Summary;
  exact_no_live_reason?: string | null;
  top_blockers?: string[] | null;
  real_trader_readiness?: RealTraderReadiness | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

const fmt = {
  usd: (v: number | null | undefined, fallback = '—') => {
    if (v == null || !Number.isFinite(v)) return fallback;
    return (v < 0 ? '-' : '+') + '$' + Math.abs(v).toFixed(2);
  },
  usdRaw: (v: number | null | undefined, fallback = '—') => {
    if (v == null || !Number.isFinite(v)) return fallback;
    return '$' + v.toFixed(2);
  },
  price: (v: number | null | undefined) => {
    if (v == null || !Number.isFinite(v) || v <= 0) return '—';
    return v >= 100 ? '$' + v.toFixed(2) : v >= 1 ? '$' + v.toFixed(4) : '$' + v.toFixed(6);
  },
  bpsAsPct: (v: number | null | undefined) => {
    if (v == null || !Number.isFinite(v)) return '—';
    const pct = v / 100;
    return (pct >= 0 ? '+' : '') + pct.toFixed(2) + '%';
  },
  pct: (v: number | null | undefined) => {
    if (v == null || !Number.isFinite(v)) return '—';
    return (v >= 0 ? '+' : '') + (v * 100).toFixed(2) + '%';
  },
  age: (sec: number | null | undefined) => {
    if (sec == null) return '—';
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = Math.floor(sec % 60);
    if (h > 0) return `${h}h ${m}m`;
    if (m > 0) return `${m}m ${s}s`;
    return `${s}s`;
  },
  holdTime: (sec: number | null | undefined) => {
    if (sec == null) return '—';
    const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60);
    if (h > 0) return `${h}h ${m}m`;
    return `${m}m`;
  },
  ts: (v: string | null | undefined) => {
    if (!v) return '—';
    try { return new Date(v).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }); }
    catch { return v; }
  },
};

function normalizeBlockerLabel(value: string): string {
  return value
    .replace(/_/g, ' ')
    .replace(/\b\w/g, c => c.toUpperCase());
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const value of values) {
    const item = String(value ?? '').trim();
    if (!item || seen.has(item)) continue;
    seen.add(item);
    out.push(item);
  }
  return out;
}

function runtimeText(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return '—';
  return value
    .replace(/paper fill/gi, 'execution decision')
    .replace(/paper/gi, 'runtime')
    .replace(/_/g, ' ')
    .trim();
}

function decisionBasis(row: { decision_reasoning?: Record<string, unknown> | null; signal_id?: string | null; prediction_id?: string | null; close_reason?: string | null }): { primary: string; secondary: string } {
  const reasoning = row.decision_reasoning && typeof row.decision_reasoning === 'object' ? row.decision_reasoning : null;
  const primary = runtimeText(reasoning?.reason ?? reasoning?.risk_state ?? row.close_reason ?? '—');
  const signal = runtimeText(reasoning?.signal_id ?? row.signal_id);
  const prediction = runtimeText(reasoning?.prediction_id ?? row.prediction_id);
  return {
    primary,
    secondary: signal !== '—' ? `Signal ${signal}` : prediction !== '—' ? `Prediction ${prediction}` : 'Evidence unavailable',
  };
}

function pnlColor(v: number | null | undefined): string {
  if (v == null) return 'var(--text-muted)';
  return v >= 0 ? 'var(--buy, #22c55e)' : 'var(--sell, #ef4444)';
}

function EvidenceMetric({
  label,
  value,
  color,
  title,
}: {
  label: string;
  value: string;
  color?: string;
  title?: string;
}) {
  return (
    <div style={{
      minWidth: 0,
      background: 'color-mix(in oklch, var(--bg-elevated) 78%, transparent)',
      border: '1px solid color-mix(in oklch, var(--border) 76%, transparent)',
      borderRadius: 6,
      padding: '8px 10px',
    }}>
      <div style={{
        marginBottom: 3,
        color: 'var(--text-muted)',
        fontSize: 10,
        letterSpacing: '0.05em',
        textTransform: 'uppercase',
      }}>
        {label}
      </div>
      <div
        title={title}
        style={{
          color: color ?? 'var(--text-primary)',
          fontSize: 13,
          fontWeight: 700,
          fontFamily: 'var(--font-mono)',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </div>
    </div>
  );
}

function DecisionBasisPanel({
  row,
}: {
  row: {
    decision_reasoning?: Record<string, unknown> | null;
    signal_id?: string | null;
    prediction_id?: string | null;
    close_reason?: string | null;
  };
}) {
  const basis = decisionBasis(row);
  const reasoning = row.decision_reasoning && typeof row.decision_reasoning === 'object' ? row.decision_reasoning : null;
  const confidence = typeof reasoning?.confidence === 'number' ? `${Math.round(reasoning.confidence * 100)}%` : '—';
  return (
    <div style={{
      display: 'grid',
      gap: 8,
      borderTop: '1px solid var(--border)',
      paddingTop: 10,
      marginTop: 10,
    }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12 }}>
        <span style={{ color: 'var(--text-muted)', fontSize: 10, letterSpacing: '0.05em', textTransform: 'uppercase' }}>
          AI Basis
        </span>
        <span style={{ color: 'var(--text-muted)', fontSize: 10, fontFamily: 'var(--font-mono)' }}>
          {basis.secondary}
        </span>
      </div>
      <div style={{ color: 'var(--text-primary)', fontSize: 12, lineHeight: 1.45 }}>
        {basis.primary}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        <EvidenceMetric label="Action" value={runtimeText(reasoning?.action)} />
        <EvidenceMetric label="Confidence" value={confidence} />
        <EvidenceMetric label="Source" value={runtimeText(reasoning?.source)} />
      </div>
    </div>
  );
}

// ── Side Badge ───────────────────────────────────────────────────────────────

function SideBadge({ side }: { side: string }) {
  const isLong = side.toUpperCase().includes('LONG') || side.toUpperCase() === 'BUY';
  return (
    <span style={{
      display: 'inline-block',
      padding: '2px 8px',
      borderRadius: 4,
      fontSize: 11,
      fontWeight: 700,
      letterSpacing: '0.05em',
      background: isLong ? 'rgba(34,197,94,0.15)' : 'rgba(239,68,68,0.15)',
      color: isLong ? 'var(--buy, #22c55e)' : 'var(--sell, #ef4444)',
      border: `1px solid ${isLong ? 'rgba(34,197,94,0.3)' : 'rgba(239,68,68,0.3)'}`,
    }}>
      {isLong ? '▲ LONG' : '▼ SHORT'}
    </span>
  );
}

// ── Regime Badge ─────────────────────────────────────────────────────────────

function RegimeBadge({ regime }: { regime: string | null }) {
  if (!regime) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const colors: Record<string, string> = {
    TREND: '#60a5fa', VOLATILE: '#f59e0b', RANGING: '#a78bfa',
    BREAKOUT: '#34d399', REVERSAL: '#fb923c',
  };
  const color = colors[regime.toUpperCase()] ?? 'var(--text-secondary)';
  return (
    <span style={{ fontSize: 11, color, fontWeight: 600 }}>
      {regime}
    </span>
  );
}

// ── Equity Curve SVG ─────────────────────────────────────────────────────────

function EquityCurve({ points }: { points: EquityPoint[] }) {
  if (points.length < 2) {
    return (
      <div style={{ height: 160, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        Not enough trade history
      </div>
    );
  }

  const pnls = points.map(p => p.pnl);
  const minPnl = Math.min(...pnls);
  const maxPnl = Math.max(...pnls);
  const range = maxPnl - minPnl || 1;
  const W = 800, H = 160, PAD = 8;

  const xScale = (i: number) => PAD + (i / (points.length - 1)) * (W - PAD * 2);
  const yScale = (v: number) => H - PAD - ((v - minPnl) / range) * (H - PAD * 2);

  const pathData = points
    .map((p, i) => `${i === 0 ? 'M' : 'L'}${xScale(i).toFixed(1)},${yScale(p.pnl).toFixed(1)}`)
    .join(' ');

  const areaPath = pathData + ` L${xScale(points.length - 1)},${H} L${PAD},${H} Z`;
  const lastPnl = pnls[pnls.length - 1];
  const lineColor = lastPnl >= 0 ? '#22c55e' : '#ef4444';
  const fillId = `ec-fill-${Math.random().toString(36).slice(2)}`;
  const zeroY = yScale(0);

  return (
    <svg viewBox={`0 0 ${W} ${H}`} style={{ width: '100%', height: 160 }} preserveAspectRatio="none">
      <defs>
        <linearGradient id={fillId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={lineColor} stopOpacity="0.25" />
          <stop offset="100%" stopColor={lineColor} stopOpacity="0.02" />
        </linearGradient>
      </defs>
      {zeroY > PAD && zeroY < H - PAD && (
        <line x1={PAD} y1={zeroY} x2={W - PAD} y2={zeroY}
          stroke="rgba(255,255,255,0.12)" strokeWidth="1" strokeDasharray="4 4" />
      )}
      <path d={areaPath} fill={`url(#${fillId})`} />
      <path d={pathData} fill="none" stroke={lineColor} strokeWidth="1.5" strokeLinejoin="round" />
      <circle cx={xScale(points.length - 1)} cy={yScale(lastPnl)} r="3" fill={lineColor} />
      <text x={W - PAD - 2} y={yScale(lastPnl) - 6} textAnchor="end" fill={lineColor}
        fontSize="11" fontFamily="monospace">
        {lastPnl >= 0 ? '+' : ''}{lastPnl.toFixed(2)} USD
      </text>
    </svg>
  );
}

// ── KPI Strip ────────────────────────────────────────────────────────────────

function KpiStrip({
  summary,
  riskProfile,
  pnlHistory,
  accuracyStatus,
  capitalStatus,
}: {
  summary: Summary;
  riskProfile: RiskProfile;
  pnlHistory: PnlHistoryStatus | null | undefined;
  accuracyStatus: SignalPredictionAccuracyStatus | null | undefined;
  capitalStatus: CapitalProductivityRuntimeStatus | null | undefined;
}) {
  const oneDay = pnlWindow(pnlHistory, '1d');
  const sevenDay = pnlWindow(pnlHistory, '7d');
  const thirtyDay = pnlWindow(pnlHistory, '30d');
  const kpis = [
    {
      label: 'Open Notional',
      value: fmt.usdRaw(summary.total_open_notional),
      color: 'var(--text-primary)',
    },
    {
      label: 'Realized PnL',
      value: fmt.usd(summary.realized_pnl_usd),
      color: pnlColor(summary.realized_pnl_usd),
    },
    {
      label: '1D PnL',
      value: formatAdaptiveMoney(oneDay?.realized_pnl_usd),
      color: pnlColor(oneDay?.realized_pnl_usd),
    },
    {
      label: '1W PnL',
      value: formatAdaptiveMoney(sevenDay?.realized_pnl_usd),
      color: pnlColor(sevenDay?.realized_pnl_usd),
    },
    {
      label: '30D PnL',
      value: formatAdaptiveMoney(thirtyDay?.realized_pnl_usd),
      color: pnlColor(thirtyDay?.realized_pnl_usd),
    },
    {
      label: 'Unrealized PnL',
      value: fmt.usd(summary.unrealized_pnl_usd),
      color: pnlColor(summary.unrealized_pnl_usd),
    },
    {
      label: 'Open Positions',
      value: String(summary.open_position_count),
      color: 'var(--text-primary)',
    },
    {
      label: 'Closed Trades',
      value: String(summary.closed_trade_count),
      color: 'var(--text-primary)',
    },
    {
      label: 'Signals Seen',
      value: summary.paper_signals_seen != null ? String(summary.paper_signals_seen) : '—',
      color: 'var(--text-secondary)',
    },
    {
      label: 'Accuracy',
      value: formatAdaptivePercent(accuracyStatus?.overall_accuracy),
      color: adaptiveStatusColor(accuracyStatus?.status),
    },
    {
      label: 'Capital Status',
      value: capitalStatus?.status ?? '—',
      color: adaptiveStatusColor(capitalStatus?.status),
    },
    {
      label: 'Max Leverage',
      value: `${riskProfile.max_leverage ?? 1}x`,
      color: 'var(--text-secondary)',
    },
    {
      label: 'Max Trade Size',
      value: fmt.usdRaw(riskProfile.max_notional_per_trade),
      color: 'var(--text-secondary)',
    },
  ];

  return (
    <div style={{
      display: 'grid',
      gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))',
      gap: 8,
      marginBottom: 16,
    }}>
      {kpis.map(({ label, value, color }) => (
        <div key={label} className="glass" style={{
          padding: '10px 14px',
        }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            {label}
          </div>
          <div style={{ fontSize: 18, fontWeight: 700, color, fontFamily: 'var(--font-mono)', letterSpacing: '-0.01em' }}>
            {value}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── Position Cards ────────────────────────────────────────────────────────────

function PositionsTab({ positions }: { positions: PaperPosition[] }) {
  const [sortKey, setSortKey] = useState<'symbol' | 'notional' | 'pnl' | 'age'>('notional');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);
  const [filter, setFilter] = useState('');

  const sorted = useMemo(() => {
    let rows = [...positions];
    if (filter) rows = rows.filter(p => p.symbol.toLowerCase().includes(filter.toLowerCase()));
    rows.sort((a, b) => {
      const getVal = (p: PaperPosition): number => {
        if (sortKey === 'symbol') return a.symbol.localeCompare(b.symbol);
        if (sortKey === 'notional') return (p.notional_usd ?? 0);
        if (sortKey === 'pnl') return (p.unrealized_pnl ?? 0);
        if (sortKey === 'age') return (p.position_age_seconds ?? 0);
        return 0;
      };
      if (sortKey === 'symbol') return sortDir * a.symbol.localeCompare(b.symbol);
      return sortDir * ((getVal(b) as number) - (getVal(a) as number));
    });
    return rows;
  }, [positions, sortKey, sortDir, filter]);

  function toggleSort(key: typeof sortKey) {
    if (sortKey === key) setSortDir(d => (d === 1 ? -1 : 1));
    else { setSortKey(key); setSortDir(-1); }
  }

  function SortBtn({ col, label }: { col: typeof sortKey; label: string }) {
    const active = sortKey === col;
    return (
      <button
        type="button"
        onClick={() => toggleSort(col)}
        style={{
          background: 'none', border: 'none', cursor: 'pointer', padding: 0,
          color: active ? 'var(--accent)' : 'var(--text-muted)',
          fontWeight: active ? 700 : 400, fontSize: 11, letterSpacing: '0.05em',
          display: 'flex', alignItems: 'center', gap: 3,
          textTransform: 'uppercase',
        }}
      >
        {label}
        {active ? (sortDir === -1 ? ' ▼' : ' ▲') : ''}
      </button>
    );
  }

  if (!positions.length) {
    return (
      <div style={{ textAlign: 'center', padding: '40px 0', color: 'var(--text-muted)' }}>
        No open positions
      </div>
    );
  }

  return (
    <div>
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <input
          placeholder="Filter symbol…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 6, padding: '6px 10px', color: 'var(--text-primary)',
            fontSize: 13, width: 180,
          }}
        />
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          {sorted.length} position{sorted.length !== 1 ? 's' : ''}
        </span>
      </div>

      <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
        <SortBtn col="symbol" label="Symbol" />
        <SortBtn col="notional" label="Trade Size" />
        <SortBtn col="pnl" label="Net PnL" />
        <SortBtn col="age" label="Age" />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
        {sorted.map((pos, i) => (
          <article key={pos.position_id ?? i} className="glass" style={{
            minWidth: 0,
            padding: '14px 16px',
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ color: 'var(--text-primary)', fontSize: 16, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
                  {pos.symbol}
                </div>
                <div style={{ marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap', color: 'var(--text-muted)', fontSize: 11 }}>
                  <span>{pos.timeframe ?? 'TF unavailable'}</span>
                  <span>{runtimeText(pos.strategy_id)}</span>
                  <RegimeBadge regime={pos.market_regime_at_entry} />
                </div>
              </div>
              <SideBadge side={pos.side} />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
              <EvidenceMetric label="Trade Size" value={fmt.usdRaw(pos.notional_usd)} />
              <EvidenceMetric label="Leverage" value={`${pos.leverage}x`} />
              <EvidenceMetric label="Entry" value={fmt.price(pos.avg_entry_price)} title={pos.entry_price_source ?? undefined} />
              <EvidenceMetric
                label="Mark"
                value={fmt.price(pos.mark_price ?? pos.last_mark_price)}
                color={pos.mark_price_stale ? 'var(--warn)' : undefined}
                title={pos.mark_price_source ?? undefined}
              />
              <EvidenceMetric label="Net PnL" value={fmt.usd(pos.unrealized_pnl)} color={pnlColor(pos.unrealized_pnl)} />
              <EvidenceMetric label="PnL %" value={fmt.bpsAsPct(pos.unrealized_pnl_bps)} color={pnlColor(pos.unrealized_pnl_bps)} />
              <EvidenceMetric label="Age" value={fmt.age(pos.position_age_seconds)} />
              <EvidenceMetric
                label="Mark Age"
                value={fmt.age(pos.mark_price_age_seconds)}
                color={pos.mark_price_stale ? 'var(--warn)' : undefined}
              />
            </div>
            <DecisionBasisPanel row={pos} />
          </article>
        ))}
      </div>

      <div style={{
        marginTop: 10, padding: '6px 10px',
        background: 'rgba(34,197,94,0.05)', borderRadius: 6,
        border: '1px solid rgba(34,197,94,0.15)',
        fontSize: 11, color: 'var(--text-muted)',
        display: 'flex', gap: 16, flexWrap: 'wrap',
      }}>
        <span>Realtime position stream</span>
        <span>Execution fills synchronized</span>
        <span>Risk-governed workflow</span>
      </div>
    </div>
  );
}

// ── History Tab ───────────────────────────────────────────────────────────────

function HistoryTab({
  trades,
  equityCurve,
  reasonBreakdown,
}: {
  trades: ClosedTrade[];
  equityCurve: EquityPoint[];
  reasonBreakdown: Record<string, number>;
}) {
  const [filter, setFilter] = useState('');
  const [winnerFilter, setWinnerFilter] = useState<'all' | 'win' | 'loss'>('all');

  const filtered = useMemo(() => {
    return trades.filter(t => {
      if (filter && !t.symbol.toLowerCase().includes(filter.toLowerCase())) return false;
      if (winnerFilter === 'win' && !t.winner) return false;
      if (winnerFilter === 'loss' && t.winner) return false;
      return true;
    });
  }, [trades, filter, winnerFilter]);

  const winCount = trades.filter(t => t.winner).length;
  const winRate = trades.length ? ((winCount / trades.length) * 100).toFixed(1) : '—';

  const totalReasons = Object.values(reasonBreakdown).reduce((a, b) => a + b, 0);
  const sortedReasons = Object.entries(reasonBreakdown).sort((a, b) => b[1] - a[1]);

  return (
    <div>
      {/* Equity curve */}
      <div className="glass" style={{
        padding: '12px 16px', marginBottom: 16,
      }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 8 }}>
          <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)' }}>
            Cumulative Realized PnL
          </span>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Win rate: <strong style={{ color: Number(winRate) >= 50 ? 'var(--buy, #22c55e)' : 'var(--sell, #ef4444)' }}>{winRate}%</strong>
            &nbsp;({winCount}/{trades.length})
          </span>
        </div>
        <EquityCurve points={equityCurve} />
      </div>

      {/* Close reason breakdown */}
      {sortedReasons.length > 0 && (
        <div className="glass" style={{
          padding: '12px 16px', marginBottom: 16,
        }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 10, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Exit Reason Breakdown
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {sortedReasons.map(([reason, count]) => {
              const pct = totalReasons ? (count / totalReasons) * 100 : 0;
              const isPositive = reason.includes('TAKE_PROFIT') || reason.includes('TP');
              const isNegative = reason.includes('STOP_LOSS') || reason.includes('SL');
              const barColor = isPositive ? '#22c55e' : isNegative ? '#ef4444' : '#60a5fa';
              return (
                <div key={reason}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 3, fontSize: 11 }}>
                    <span style={{ color: 'var(--text-secondary)' }}>{reason.replace(/_/g, ' ')}</span>
                    <span style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{count} ({pct.toFixed(1)}%)</span>
                  </div>
                  <div style={{ background: 'var(--bg-elevated)', borderRadius: 2, height: 4 }}>
                    <div style={{ width: `${pct}%`, height: '100%', borderRadius: 2, background: barColor, transition: 'width 0.3s ease' }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}

      {/* Filter controls */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12, alignItems: 'center' }}>
        <input
          placeholder="Filter symbol…"
          value={filter}
          onChange={e => setFilter(e.target.value)}
          style={{
            background: 'var(--bg-elevated)', border: '1px solid var(--border)',
            borderRadius: 6, padding: '6px 10px', color: 'var(--text-primary)',
            fontSize: 13, width: 160,
          }}
        />
        {(['all', 'win', 'loss'] as const).map(f => (
          <button
            key={f}
            type="button"
            onClick={() => setWinnerFilter(f)}
            style={{
              padding: '5px 12px', borderRadius: 6, fontSize: 12, fontWeight: 600,
              cursor: 'pointer', border: '1px solid var(--border)',
              background: winnerFilter === f ? 'var(--accent)' : 'var(--bg-elevated)',
              color: winnerFilter === f ? '#fff' : 'var(--text-secondary)',
            }}
          >
            {f === 'all' ? 'All' : f === 'win' ? '✓ Winners' : '✗ Losers'}
          </button>
        ))}
        <span style={{ color: 'var(--text-muted)', fontSize: 12 }}>
          {filtered.length} trades
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(320px, 1fr))', gap: 12 }}>
        {filtered.map((t, i) => (
          <article key={t.close_id ?? i} className="glass" style={{
            minWidth: 0,
            padding: '14px 16px',
            boxShadow: t.winner ? 'inset 3px 0 0 rgba(34,197,94,0.75)' : 'inset 3px 0 0 rgba(239,68,68,0.75)',
          }}>
            <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, marginBottom: 12 }}>
              <div style={{ minWidth: 0 }}>
                <div style={{ color: 'var(--text-primary)', fontSize: 16, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
                  {t.symbol}
                </div>
                <div style={{ marginTop: 4, display: 'flex', gap: 8, flexWrap: 'wrap', color: 'var(--text-muted)', fontSize: 11 }}>
                  <span>{t.timeframe ?? 'TF unavailable'}</span>
                  <RegimeBadge regime={t.market_regime_at_entry} />
                  <span>{fmt.ts(t.exit_price_utc)}</span>
                </div>
              </div>
              <div style={{ display: 'grid', justifyItems: 'end', gap: 6 }}>
                <SideBadge side={t.side} />
                <span style={{
                  color: t.winner ? 'var(--buy, #22c55e)' : 'var(--sell, #ef4444)',
                  fontSize: 10,
                  fontWeight: 800,
                  letterSpacing: '0.05em',
                  textTransform: 'uppercase',
                }}>
                  {t.winner ? 'Winner' : 'Loss'}
                </span>
              </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8 }}>
              <EvidenceMetric label="Entry" value={fmt.price(t.entry_price)} title={t.entry_price_source ?? undefined} />
              <EvidenceMetric label="Exit" value={fmt.price(t.exit_price)} title={t.exit_price_source ?? undefined} />
              <EvidenceMetric label="Realized PnL" value={fmt.usd(t.realized_pnl_usd)} color={pnlColor(t.realized_pnl_usd)} />
              <EvidenceMetric label="PnL %" value={fmt.bpsAsPct(t.realized_pnl_bps)} color={pnlColor(t.realized_pnl_bps)} />
              <EvidenceMetric label="Hold" value={fmt.holdTime(t.hold_time_seconds)} />
              <EvidenceMetric label="Close Reason" value={runtimeText(t.close_reason)} />
            </div>
            <DecisionBasisPanel row={t} />
          </article>
        ))}
      </div>
    </div>
  );
}

// ── Risk Gate Tab ─────────────────────────────────────────────────────────────

function RiskGateTab({ riskProfile, summary }: { riskProfile: RiskProfile; summary: Summary }) {
  const fields = [
    ['Profile', riskProfile.profile_id ?? '—'],
    ['Max Leverage', `${riskProfile.max_leverage ?? 1}x`],
    ['Max Trade Size', fmt.usdRaw(riskProfile.max_notional_per_trade)],
    ['Max Open Positions', riskProfile.max_open_positions != null ? String(riskProfile.max_open_positions) : '—'],
    ['Min Confidence', riskProfile.min_confidence_calibrated != null ? `${(riskProfile.min_confidence_calibrated * 100).toFixed(0)}%` : '—'],
    ['Max Daily Loss', fmt.usdRaw(riskProfile.max_daily_loss)],
    ['Max Drawdown', riskProfile.max_drawdown != null ? `${riskProfile.max_drawdown}%` : '—'],
    ['Max Spread', riskProfile.max_spread_bps != null ? fmt.bpsAsPct(riskProfile.max_spread_bps) : '—'],
    ['Min Expected Move', riskProfile.min_expected_move_after_cost_bps != null ? fmt.bpsAsPct(riskProfile.min_expected_move_after_cost_bps) : '—'],
    ['Cooldown', riskProfile.cooldown_seconds != null ? fmt.age(riskProfile.cooldown_seconds) : '—'],
  ];

  const intentsAccepted = summary.intents_accepted ?? 0;
  const intentsBlocked = summary.intents_blocked ?? 0;
  const totalIntents = intentsAccepted + intentsBlocked;
  const blockRate = totalIntents ? ((intentsBlocked / totalIntents) * 100).toFixed(1) : '—';

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div className="glass" style={{ padding: '16px' }}>
        <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
          Risk Profile — {riskProfile.profile_id ?? 'Unknown'}
        </div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 0 }}>
          {fields.map(([label, value]) => (
            <div key={label} style={{
              display: 'flex', justifyContent: 'space-between', alignItems: 'center',
              padding: '8px 0', borderBottom: '1px solid rgba(255,255,255,0.04)',
            }}>
              <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{label}</span>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
            </div>
          ))}
        </div>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        {/* Intent Gate stats */}
        <div className="glass" style={{ padding: '16px' }}>
          <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 12, textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Intent Gate Statistics
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {[
              { label: 'Signals Processed', value: summary.paper_signals_seen },
              { label: 'Intents Accepted', value: intentsAccepted, color: 'var(--buy, #22c55e)' },
              { label: 'Intents Blocked', value: intentsBlocked, color: 'var(--sell, #ef4444)' },
              { label: 'Block Rate', value: `${blockRate}%` },
              { label: 'Fill Count', value: summary.persistent_accepted_fill_count },
            ].map(({ label, value, color }) => (
              <div key={label} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>{label}</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: color ?? 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                  {value != null ? String(value) : '—'}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Safety status */}
        <div style={{
          background: 'rgba(239,68,68,0.06)',
          border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 8,
          padding: '14px 16px',
        }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#ef4444', marginBottom: 8 }}>
            Operator-gated execution workflow
          </div>
          {[
            'LIVE_GATE=blocked_human_only',
            'places_real_order: false',
            'V2_MODE=runtime',
            'exchange_mutation_enabled: false',
            'Execution guard active',
          ].map(s => (
            <div key={s} style={{ fontSize: 11, color: 'rgba(239,68,68,0.7)', marginTop: 4 }}>
              ✓ {s}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}

// ── Freshness Badge ───────────────────────────────────────────────────────────

function FreshnessBadge({ fetchedAt }: { fetchedAt: number | null }) {
  if (!fetchedAt) return null;
  const ageSec = Math.round((Date.now() - fetchedAt) / 1000);
  const color = ageSec < 15 ? 'var(--buy, #22c55e)' : ageSec < 30 ? '#f59e0b' : 'var(--sell, #ef4444)';
  return (
    <span style={{ fontSize: 11, color, fontFamily: 'var(--font-mono)' }}>
      {ageSec}s ago
    </span>
  );
}

function AGradeBlockerStrip({ status }: { status: PaperStatus | null }) {
  const readiness = status?.real_trader_readiness ?? null;
  const blockers = uniqueStrings([
    ...(status?.top_blockers ?? []),
    ...(readiness?.readiness_blockers ?? []),
  ]).slice(0, 8);
  const exact = status?.exact_no_live_reason ?? readiness?.exact_no_live_reason ?? blockers[0] ?? 'LIVE_GATE_BLOCKED_HUMAN_ONLY';
  const liveReady = Boolean(readiness?.live_ready);
  const submitAllowed = Boolean(readiness?.live_submit_allowed);
  const hardTrainerBlock = blockers.some(b => b === 'VALIDATION_LOSS_REGRESSED' || b === 'BLOCKED_NO_DURABLE_WEIGHT_UPDATE');

  return (
    <section
      aria-label="A-grade blocker truth"
      style={{
        marginBottom: 16,
        border: '1px solid color-mix(in oklch, var(--sell, #ef4444) 35%, var(--border))',
        background: 'color-mix(in oklch, var(--sell, #ef4444) 8%, var(--bg-panel))',
        borderRadius: 8,
        padding: 12,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap' }}>
        <div style={{ minWidth: 220, flex: '1 1 320px' }}>
          <div style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0, marginBottom: 4 }}>
            A-grade gate
          </div>
          <div style={{ fontSize: 15, fontWeight: 700, color: 'var(--sell, #ef4444)', lineHeight: 1.35 }}>
            {normalizeBlockerLabel(exact)}
          </div>
          <div style={{ marginTop: 6, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.45 }}>
            Live ready: {liveReady ? 'true' : 'false'} · Submit allowed: {submitAllowed ? 'true' : 'false'}
            {hardTrainerBlock ? ' · Durable checkpoint blocked' : ''}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', justifyContent: 'flex-end', flex: '1 1 360px' }}>
          {blockers.map(blocker => (
            <span
              key={blocker}
              title={blocker}
              style={{
                maxWidth: 260,
                overflowWrap: 'anywhere',
                padding: '4px 8px',
                borderRadius: 6,
                border: '1px solid color-mix(in oklch, var(--sell, #ef4444) 30%, var(--border))',
                background: blocker === 'A_GRADE_SUPPLY_ZERO'
                  ? 'color-mix(in oklch, var(--sell, #ef4444) 14%, transparent)'
                  : 'color-mix(in oklch, var(--warn, #f59e0b) 10%, transparent)',
                color: blocker === 'A_GRADE_SUPPLY_ZERO' ? 'var(--sell, #ef4444)' : 'var(--warn, #f59e0b)',
                fontSize: 11,
                fontWeight: 700,
                lineHeight: 1.25,
              }}
            >
              {normalizeBlockerLabel(blocker)}
            </span>
          ))}
        </div>
      </div>
    </section>
  );
}

// ── Main Page ─────────────────────────────────────────────────────────────────

type Tab = 'positions' | 'history' | 'risk';

export default function PaperTradingPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('positions');
  const paperActivity = usePaperActivityStream(1000);
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);

  const { envelope, loading, error, refetch } = useRealtimeResource<PaperStatus>({
    url: '/api/v2/paper/status',
    source: '/api/v2/paper/status',
    pollIntervalMs: 8_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
  });

  const data: PaperStatus | null = envelope.data ?? null;
  const rawFetchedAt = paperActivity.envelope?.received_at ?? envelope.received_at ?? null;
  const fetchedAt = typeof rawFetchedAt === 'string' ? Date.parse(rawFetchedAt) : null;
  const streamPositions = paperActivity.data.positions as unknown as PaperPosition[];
  const positions = streamPositions.length ? streamPositions : data?.positions ?? [];
  const closedTrades = data?.closed_trades ?? [];
  const equityCurve = data?.equity_curve ?? [];
  const reasonBreakdown = data?.reason_breakdown ?? {};
  const riskProfile = data?.risk_profile ?? {} as RiskProfile;
  const apiSummary = (data?.summary ?? {}) as Summary;
  const streamSummary = paperActivity.data.summary as unknown as Partial<Summary>;
  const summary = {
    ...apiSummary,
    ...streamSummary,
    realized_pnl_usd: apiSummary.realized_net_pnl_usd ?? apiSummary.realized_pnl_usd ?? streamSummary.realized_pnl_usd ?? null,
    unrealized_pnl_usd: apiSummary.unrealized_pnl_usd ?? streamSummary.unrealized_pnl_usd ?? null,
    total_pnl_usd: apiSummary.total_pnl_usd ?? streamSummary.total_pnl_usd ?? null,
    open_position_count: streamSummary.open_position_count ?? data?.summary?.open_position_count ?? positions.length,
  } as Summary;
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status ?? null;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status ?? capitalStatus?.signal_prediction_accuracy_status ?? null;

  const TABS: { key: Tab; label: string }[] = [
    { key: 'positions', label: `Positions (${summary.open_position_count ?? positions.length})` },
    { key: 'history', label: `History (${summary.closed_trade_count ?? closedTrades.length})` },
    { key: 'risk', label: 'Risk Gate' },
  ];

  return (
    <div style={{
      background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)',
      minHeight: '100vh',
      padding: '16px 20px',
      color: 'var(--text-primary)',
      fontFamily: 'var(--font-mono)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
            Execution Runtime
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            Trainer-driven telemetry and approval-gated execution workflow
          </p>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <FreshnessBadge fetchedAt={fetchedAt} />
          <button
            type="button"
            onClick={refetch}
            style={{
              padding: '4px 10px', borderRadius: 6, fontSize: 11, cursor: 'pointer',
              background: 'var(--bg-elevated)', border: '1px solid var(--border)',
              color: 'var(--text-secondary)',
            }}
          >
            ↻ Refresh
          </button>
          <span style={{
            padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700,
            background: 'rgba(34,197,94,0.12)', color: '#22c55e',
            border: '1px solid rgba(34,197,94,0.3)',
          }}>
            ● MARKET DATA LIVE
          </span>
          <span style={{
            padding: '4px 10px', borderRadius: 6, fontSize: 11, fontWeight: 700,
            background: 'rgba(245,158,11,0.10)', color: '#f59e0b',
            border: '1px solid rgba(245,158,11,0.28)',
          }}>
            EXECUTION RESTRICTED
          </span>
          <span style={{ fontSize: 11, color: paperActivity.connected ? 'var(--buy)' : 'var(--text-muted)' }}>
            {paperActivity.connected ? 'Position stream connected' : paperActivity.source === 'http_fallback' ? 'API fallback' : 'Connecting…'}
          </span>
          {(loading || paperActivity.loading) && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Connecting…</span>
          )}
        </div>
      </div>

      {/* Error banner */}
      {error && (
        <div style={{
          background: 'rgba(239,68,68,0.08)', border: '1px solid rgba(239,68,68,0.25)',
          borderRadius: 8, padding: '8px 14px', marginBottom: 12, fontSize: 13,
          color: '#ef4444',
        }}>
          {error}
        </div>
      )}

      <AGradeBlockerStrip status={data} />

      {/* KPI strip */}
      <KpiStrip
        summary={summary}
        riskProfile={riskProfile}
        pnlHistory={pnlHistory}
        accuracyStatus={accuracyStatus}
        capitalStatus={capitalStatus}
      />

      <div style={{ marginBottom: 16 }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Capital Productivity + PnL + Accuracy"
          compact
          showMatrix
          maxMatrixHeight={220}
        />
      </div>

      {/* Worker status */}
      {summary.worker_id && (
        <div style={{
          fontSize: 11, color: 'var(--text-muted)', marginBottom: 12,
          display: 'flex', gap: 16,
        }}>
          <span>Worker: <strong style={{ color: 'var(--text-secondary)' }}>{summary.worker_id}</strong></span>
          {summary.finished_at && (
            <span>Last run: <strong style={{ color: 'var(--text-secondary)' }}>{fmt.ts(summary.finished_at)}</strong></span>
          )}
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, borderBottom: '1px solid var(--border)', marginBottom: 16 }}>
        {TABS.map(t => (
          <button
            key={t.key}
            type="button"
            onClick={() => setTab(t.key)}
            style={{
              padding: '9px 18px',
              background: 'none',
              border: 'none',
              borderBottom: `2px solid ${tab === t.key ? 'var(--accent)' : 'transparent'}`,
              color: tab === t.key ? 'var(--text-primary)' : 'var(--text-muted)',
              fontWeight: tab === t.key ? 700 : 400,
              fontSize: 13,
              cursor: 'pointer',
              marginBottom: -1,
              transition: 'color 0.15s, border-color 0.15s',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Tab content */}
      <div style={{
        minWidth: 0,
      }}>
        {tab === 'positions' && <PositionsTab positions={positions} />}
        {tab === 'history' && (
          <HistoryTab
            trades={closedTrades}
            equityCurve={equityCurve}
            reasonBreakdown={reasonBreakdown}
          />
        )}
        {tab === 'risk' && <RiskGateTab riskProfile={riskProfile} summary={summary} />}
      </div>
    </div>
  );
}
