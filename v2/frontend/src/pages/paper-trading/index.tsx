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
  last_mark_price: number | null;
  notional_usd: number | null;
  leverage: number;
  unrealized_pnl: number | null;
  unrealized_pnl_bps: number | null;
  mark_price_age_seconds?: number | null;
  mark_price_source?: string | null;
  timeframe: string | null;
  strategy_id: string | null;
  market_regime_at_entry: string | null;
  position_age_seconds: number | null;
  opened_est: string | null;
  paper_fill_allowed: boolean | null;
  places_real_order: boolean | null;
  hedge_state: string | null;
}

interface ClosedTrade {
  close_id: string | null;
  symbol: string;
  side: string;
  entry_price: number | null;
  exit_price: number | null;
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
  unrealized_pnl_usd: number | null;
  total_open_notional: number | null;
  paper_signals_seen: number | null;
  intents_accepted: number | null;
  intents_blocked: number | null;
  persistent_accepted_fill_count: number | null;
  worker_id: string | null;
  started_at: string | null;
  finished_at: string | null;
}

interface PaperStatus {
  positions: PaperPosition[];
  closed_trades: ClosedTrade[];
  equity_curve: EquityPoint[];
  reason_breakdown: Record<string, number>;
  risk_profile: RiskProfile;
  summary: Summary;
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
    if (v == null || !Number.isFinite(v)) return '—';
    return v >= 100 ? '$' + v.toFixed(2) : v >= 1 ? '$' + v.toFixed(4) : '$' + v.toFixed(6);
  },
  bps: (v: number | null | undefined) => {
    if (v == null || !Number.isFinite(v)) return '—';
    return (v >= 0 ? '+' : '') + v.toFixed(1) + ' bps';
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

function pnlColor(v: number | null | undefined): string {
  if (v == null) return 'var(--text-muted)';
  return v >= 0 ? 'var(--buy, #22c55e)' : 'var(--sell, #ef4444)';
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
        <div key={label} style={{
          background: 'var(--bg-panel)',
          border: '1px solid var(--border)',
          borderRadius: 8,
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

// ── Positions Table ───────────────────────────────────────────────────────────

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

      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {(['Symbol', 'Side', 'Trade Size', 'Leverage', 'TF', 'Entry', 'Mark', 'Net PnL', 'PnL bps', 'Strategy', 'Regime', 'Age'] as const).map(h => (
                <th key={h} style={{
                  padding: '8px 10px', textAlign: 'left', color: 'var(--text-muted)',
                  fontWeight: 500, fontSize: 11, letterSpacing: '0.06em', textTransform: 'uppercase',
                  whiteSpace: 'nowrap',
                }}>
                  {h === 'Trade Size' ? <SortBtn col="notional" label={h} />
                    : h === 'Net PnL' ? <SortBtn col="pnl" label={h} />
                    : h === 'Symbol' ? <SortBtn col="symbol" label={h} />
                    : h === 'Age' ? <SortBtn col="age" label={h} />
                    : h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((pos, i) => (
              <tr key={pos.position_id ?? i} style={{
                borderBottom: '1px solid var(--border)',
                background: i % 2 === 0 ? 'transparent' : 'rgba(255,255,255,0.01)',
              }}>
                <td style={{ padding: '8px 10px', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {pos.symbol}
                </td>
                <td style={{ padding: '8px 10px' }}>
                  <SideBadge side={pos.side} />
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-primary)', fontWeight: 600 }}>
                  {fmt.usdRaw(pos.notional_usd)}
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                  {pos.leverage}x
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                  {pos.timeframe ?? '—'}
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }}>
                  {fmt.price(pos.avg_entry_price)}
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-secondary)' }} title={pos.mark_price_source ?? undefined}>
                  {fmt.price(pos.last_mark_price)}
                </td>
                <td style={{ padding: '8px 10px', fontWeight: 600, color: pnlColor(pos.unrealized_pnl) }}>
                  {fmt.usd(pos.unrealized_pnl)}
                </td>
                <td style={{ padding: '8px 10px', color: pnlColor(pos.unrealized_pnl_bps), fontSize: 11 }}>
                  {fmt.bps(pos.unrealized_pnl_bps)}
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
                  {pos.strategy_id ?? '—'}
                </td>
                <td style={{ padding: '8px 10px' }}>
                  <RegimeBadge regime={pos.market_regime_at_entry} />
                </td>
                <td style={{ padding: '8px 10px', color: 'var(--text-muted)', fontSize: 11 }}>
                  {fmt.age(pos.position_age_seconds)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div style={{
        marginTop: 10, padding: '6px 10px',
        background: 'rgba(34,197,94,0.05)', borderRadius: 6,
        border: '1px solid rgba(34,197,94,0.15)',
        fontSize: 11, color: 'var(--text-muted)',
        display: 'flex', gap: 16,
      }}>
        <span>✓ Real-time platform telemetry</span>
        <span>✓ Execution fills synchronized</span>
        <span>✓ Risk-governed workflow</span>
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
      <div style={{
        background: 'var(--bg-panel)', border: '1px solid var(--border)',
        borderRadius: 8, padding: '12px 16px', marginBottom: 16,
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
        <div style={{
          background: 'var(--bg-panel)', border: '1px solid var(--border)',
          borderRadius: 8, padding: '12px 16px', marginBottom: 16,
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

      {/* Trade history table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12, fontFamily: 'var(--font-mono)' }}>
          <thead>
            <tr style={{ borderBottom: '1px solid var(--border)' }}>
              {['Symbol', 'Side', 'TF', 'Entry', 'Exit', 'Realized PnL', 'bps', 'Hold', 'Close Reason', 'Regime', 'Time'].map(h => (
                <th key={h} style={{
                  padding: '7px 8px', textAlign: 'left', color: 'var(--text-muted)',
                  fontWeight: 500, fontSize: 10, letterSpacing: '0.06em', textTransform: 'uppercase',
                  whiteSpace: 'nowrap',
                }}>
                  {h}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.map((t, i) => (
              <tr key={t.close_id ?? i} style={{
                borderBottom: '1px solid rgba(255,255,255,0.04)',
                background: t.winner ? 'rgba(34,197,94,0.02)' : 'rgba(239,68,68,0.02)',
              }}>
                <td style={{ padding: '6px 8px', fontWeight: 700, color: 'var(--text-primary)' }}>
                  {t.symbol}
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <SideBadge side={t.side} />
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-muted)' }}>
                  {t.timeframe ?? '—'}
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                  {fmt.price(t.entry_price)}
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-secondary)' }}>
                  {fmt.price(t.exit_price)}
                </td>
                <td style={{ padding: '6px 8px', fontWeight: 600, color: pnlColor(t.realized_pnl_usd) }}>
                  {fmt.usd(t.realized_pnl_usd)}
                </td>
                <td style={{ padding: '6px 8px', color: pnlColor(t.realized_pnl_bps), fontSize: 10 }}>
                  {fmt.bps(t.realized_pnl_bps)}
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-muted)' }}>
                  {fmt.holdTime(t.hold_time_seconds)}
                </td>
                <td style={{ padding: '6px 8px', fontSize: 10, color: 'var(--text-secondary)' }}>
                  {(t.close_reason ?? '—').replace(/_/g, ' ')}
                </td>
                <td style={{ padding: '6px 8px' }}>
                  <RegimeBadge regime={t.market_regime_at_entry} />
                </td>
                <td style={{ padding: '6px 8px', color: 'var(--text-muted)', fontSize: 10 }}>
                  {fmt.ts(t.exit_price_utc)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
    ['Max Spread', riskProfile.max_spread_bps != null ? `${riskProfile.max_spread_bps} bps` : '—'],
    ['Min Expected Move', riskProfile.min_expected_move_after_cost_bps != null ? `${riskProfile.min_expected_move_after_cost_bps} bps` : '—'],
    ['Cooldown', riskProfile.cooldown_seconds != null ? fmt.age(riskProfile.cooldown_seconds) : '—'],
  ];

  const intentsAccepted = summary.intents_accepted ?? 0;
  const intentsBlocked = summary.intents_blocked ?? 0;
  const totalIntents = intentsAccepted + intentsBlocked;
  const blockRate = totalIntents ? ((intentsBlocked / totalIntents) * 100).toFixed(1) : '—';

  return (
    <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
      <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 8, padding: '16px' }}>
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
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 8, padding: '16px' }}>
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
  const streamSummary = paperActivity.data.summary as unknown as Partial<Summary>;
  const summary = {
    ...((data?.summary ?? {}) as Summary),
    ...streamSummary,
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
      background: 'var(--bg-base)',
      minHeight: '100vh',
      padding: '16px 20px',
      color: 'var(--text-primary)',
      fontFamily: 'var(--font-mono)',
    }}>
      {/* Header */}
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 16 }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
            Live Trading
          </h1>
          <p style={{ margin: '4px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            Trainer-driven execution telemetry and live trading workflow
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
            ● LIVE MODE
          </span>
          <span style={{ fontSize: 11, color: paperActivity.connected ? 'var(--buy)' : 'var(--text-muted)' }}>
            {paperActivity.connected ? 'WebSocket live' : paperActivity.source === 'http_fallback' ? 'HTTP fallback' : 'Connecting…'}
          </span>
          {(loading || paperActivity.loading) && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>Loading…</span>
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
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 8,
        padding: '16px',
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
