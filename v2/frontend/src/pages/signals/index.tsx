import { useState, useMemo, useCallback, useEffect } from 'react';
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

interface SignalRow {
  symbol: string;
  timeframe: string;
  action: string | null;
  side: string | null;
  confidence: number | null;
  live_gate: string | null;
  actionable: boolean;
  risk_state: string | null;
  orchestrator_state: string | null;
  paper_fill_status: string | null;
  paper_fill_gate_status: string | null;
  data_coverage_percent: number | null;
  market_state_integrity_score: number | null;
  generated_at: string | null;
  age_seconds: number | null;
  signal_id: string | null;
  prediction_id: string | null;
  price_target: number | null;
  price_target_after_cost: number | null;
  expected_move_bps: number | null;
}

interface SignalMatrixData {
  rows: SignalRow[];
  count: number;
  symbols: string[];
  symbol_count: number;
  timeframes: string[];
  missing: string[];
}

interface SignalExplanation {
  summary: string;
  signal_strength: string;
  confidence_narrative: string;
  data_quality_narrative: string;
  market_integrity_narrative: string;
  technical_drivers: string;
  price_target_narrative: string;
  risk_gate_narrative: string;
  pipeline_state_narrative: string;
  full_text: string;
}

interface ExplainData {
  symbol: string;
  timeframe: string;
  generated_at: string | null;
  explanation: SignalExplanation;
  key_numbers: {
    action: string;
    confidence_calibrated: number;
    confidence_raw: number;
    dominant_prob: number;
    expected_move_bps: number;
    price_target: number | null;
    data_coverage_pct: number;
    integrity_score: number;
    masa_signal: number | null;
    policy_value: number | null;
    missing_feature_count: number;
  };
}

// ─── Constants ─────────────────────────────────────────────────────────────

const TIMEFRAMES = ['1m', '5m', '15m', '1h', '4h'] as const;
type TF = typeof TIMEFRAMES[number];
const DEFAULT_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'DOGEUSDT', 'AVAXUSDT', 'ADAUSDT'];

// ─── Helpers ──────────────────────────────────────────────────────────────

function actionColor(a: string | null | undefined): string {
  if (!a) return 'var(--text-muted)';
  const l = a.toLowerCase();
  if (l.includes('long') || l.includes('buy')) return '#26c281';
  if (l.includes('short') || l.includes('sell')) return '#ef5350';
  if (l.includes('hold')) return '#f59e0b';
  return 'var(--text-muted)';
}
function gateColor(g: string | null | undefined): string {
  if (!g) return 'var(--text-muted)';
  const l = g.toLowerCase();
  if (l.includes('allow') || l.includes('pass') || l.includes('open')) return '#26c281';
  if (l.includes('block') || l.includes('human_only')) return '#ef5350';
  return '#f59e0b';
}
function confColor(c: number | null | undefined): string {
  if (c == null) return 'var(--text-muted)';
  const v = Math.abs(c) <= 1 ? c : c / 100;
  if (v >= 0.75) return '#26c281';
  if (v >= 0.55) return '#f59e0b';
  return '#ef5350';
}
function fmtConf(c: number | null | undefined): string {
  if (c == null) return '—';
  const v = Math.abs(c) <= 1 ? c * 100 : c;
  return `${v.toFixed(1)}%`;
}
function fmtAge(s: number | null | undefined): string {
  if (s == null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}
function fmtPrice(p: number | null | undefined): string {
  if (p == null) return '—';
  return `$${p.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}
function fmtBps(bps: number | null | undefined): string {
  if (bps == null) return '—';
  const pct = bps / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

// ─── Routing badge ─────────────────────────────────────────────────────────

function RoutingBadge({ gateStatus, paperFill }: { gateStatus: string | null | undefined; paperFill: string | null | undefined }): JSX.Element {
  const isLive = (gateStatus ?? '').toLowerCase().includes('open') && !(gateStatus ?? '').toLowerCase().includes('blocked');
  const isPaper = (paperFill ?? '').toLowerCase().includes('paper') || (gateStatus ?? '').toLowerCase().includes('human_only');
  const isBlocked = (gateStatus ?? '').toLowerCase().includes('blocked');

  if (isLive) return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(38,194,129,0.15)', color: '#26c281', border: '1px solid #26c28130', fontFamily: 'var(--font-mono)' }}>
      ⚡ LIVE ROUTED
    </span>
  );
  if (isPaper) return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(59,130,246,0.12)', color: '#3b82f6', border: '1px solid #3b82f630', fontFamily: 'var(--font-mono)' }}>
      📋 PAPER ROUTED
    </span>
  );
  if (isBlocked) return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(239,83,80,0.1)', color: '#ef5350', border: '1px solid #ef535030', fontFamily: 'var(--font-mono)' }}>
      🔒 BLOCKED
    </span>
  );
  return <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, color: 'var(--text-muted)', border: '1px solid var(--border)', fontFamily: 'var(--font-mono)' }}>PENDING</span>;
}

// ─── Action badge ─────────────────────────────────────────────────────────

function ActionBadge({ action }: { action: string | null | undefined }): JSX.Element {
  const color = actionColor(action);
  if (!action) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  const label = action.replace(/_/g, ' ').toUpperCase();
  return (
    <span style={{ padding: '3px 10px', borderRadius: 5, fontSize: 12, fontWeight: 800, fontFamily: 'var(--font-mono)', color, background: `${color}15`, border: `1px solid ${color}30`, letterSpacing: '0.05em' }}>
      {label.includes('SHORT') ? '▼ ' : label.includes('LONG') ? '▲ ' : '● '}{label}
    </span>
  );
}

// ─── Confidence bar ────────────────────────────────────────────────────────

function ConfBar({ value, width = 64 }: { value: number | null | undefined; width?: number }): JSX.Element {
  const pct = value != null ? Math.min(100, Math.max(0, (Math.abs(value) <= 1 ? value : value / 100) * 100)) : 0;
  const color = confColor(value);
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${pct}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color, fontWeight: 700, minWidth: 40 }}>{fmtConf(value)}</span>
    </div>
  );
}

// ─── Price target cell ────────────────────────────────────────────────────

function PriceTargetCell({ target, moveBps, action }: { target: number | null | undefined; moveBps: number | null | undefined; action: string | null | undefined }): JSX.Element {
  if (!target) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  const color = actionColor(action);
  return (
    <div>
      <div style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12, color }}>{fmtPrice(target)}</div>
      {moveBps != null && <div style={{ fontSize: 9, color: 'var(--text-muted)', marginTop: 1 }}>{fmtBps(moveBps)}</div>}
    </div>
  );
}

// ─── AI Reasoning drawer ──────────────────────────────────────────────────

function AIReasoningPanel({ symbol, timeframe }: { symbol: string; timeframe: string }): JSX.Element {
  const { envelope, loading } = useRealtimeResource<ExplainData>({
    url: `/api/v2/predictions/explain?symbol=${symbol}&timeframe=${timeframe}`,
    source: 'ai_explain',
    pollIntervalMs: 120_000,
    mode: 'read_only',
  });

  const exp = envelope.data?.explanation;
  const nums = envelope.data?.key_numbers;

  if (loading && !exp) return (
    <div style={{ padding: '16px 20px', background: 'var(--bg-elevated)' }}>
      <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
        <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading AI reasoning…</span>
      </div>
    </div>
  );

  if (!exp) return (
    <div style={{ padding: '16px 20px', background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border)' }}>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
        AI reasoning not yet available for {symbol} {timeframe}. The explain endpoint may need the backend deployed.
      </p>
    </div>
  );

  return (
    <div style={{ background: 'var(--bg-elevated)', borderBottom: '1px solid var(--border)', padding: '20px 24px' }}>
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 16 }}>
        <span style={{ fontSize: 14 }}>🧠</span>
        <h4 style={{ margin: 0, fontSize: 13, fontWeight: 700, color: 'var(--text-primary)' }}>AI Signal Reasoning — {symbol} {timeframe}</h4>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', marginLeft: 'auto' }}>Based on real model data</span>
      </div>

      {/* Key numbers strip */}
      {nums && (
        <div style={{ display: 'flex', gap: 12, flexWrap: 'wrap', marginBottom: 16, padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
          {[
            { label: 'Action', value: nums.action, color: actionColor(nums.action) },
            { label: 'Confidence', value: fmtConf(nums.confidence_calibrated), color: confColor(nums.confidence_calibrated) },
            { label: 'Raw Confidence', value: fmtConf(nums.confidence_raw), color: 'var(--text-muted)' },
            { label: 'Dominant Prob', value: `${(nums.dominant_prob * 100).toFixed(1)}%`, color: nums.dominant_prob > 0.9 ? '#26c281' : '#f59e0b' },
            { label: 'MASA Signal', value: nums.masa_signal != null ? nums.masa_signal.toFixed(3) : '—', color: nums.masa_signal != null ? (nums.masa_signal < 0 ? '#ef5350' : '#26c281') : 'var(--text-muted)' },
            { label: 'Missing Features', value: String(nums.missing_feature_count), color: nums.missing_feature_count > 20 ? '#f59e0b' : '#26c281' },
            { label: 'Integrity', value: `${nums.integrity_score?.toFixed(1) ?? '—'}/100`, color: (nums.integrity_score ?? 0) >= 90 ? '#26c281' : '#f59e0b' },
          ].map(kpi => (
            <div key={kpi.label} style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
              <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{kpi.label}</span>
              <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: kpi.color }}>{kpi.value}</span>
            </div>
          ))}
        </div>
      )}

      {/* Explanation sections */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(340px, 1fr))', gap: 12 }}>
        {[
          { icon: '📊', title: 'Signal Summary', text: exp.summary },
          { icon: '💪', title: 'Signal Strength', text: exp.signal_strength },
          { icon: '🎯', title: 'Confidence Calibration', text: exp.confidence_narrative },
          { icon: '📉', title: 'Data Quality', text: exp.data_quality_narrative },
          { icon: '🏗️', title: 'Market Integrity', text: exp.market_integrity_narrative },
          { icon: '⚡', title: 'Technical Drivers', text: exp.technical_drivers },
          { icon: '💰', title: 'Price Target', text: exp.price_target_narrative },
          { icon: '🔒', title: 'Risk Gate', text: exp.risk_gate_narrative },
          { icon: '🔄', title: 'Pipeline State', text: exp.pipeline_state_narrative },
        ].filter(s => s.text).map(section => (
          <div key={section.title} style={{ padding: '12px 14px', background: 'rgba(255,255,255,0.03)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>
              {section.icon} {section.title}
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.6 }}>{section.text}</p>
          </div>
        ))}
      </div>
    </div>
  );
}

// ─── Signal card (expanded view) ───────────────────────────────────────────

function SignalCard({ row }: { row: SignalRow }): JSX.Element {
  const [showReasoning, setShowReasoning] = useState(false);
  const isShort = (row.action ?? '').toLowerCase().includes('short');
  const priceChange = row.expected_move_bps != null ? row.expected_move_bps / 100 : null;

  return (
    <tr>
      <td colSpan={9} style={{ padding: 0 }}>
        <div style={{ background: 'var(--bg-elevated)', borderBottom: '2px solid var(--border)' }}>
          {/* Top info grid */}
          <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 14 }}>
            {/* Price target card */}
            <div style={{ gridColumn: 'span 2', padding: '12px 16px', background: isShort ? 'rgba(239,83,80,0.07)' : 'rgba(38,194,129,0.07)', borderRadius: 8, border: `1px solid ${isShort ? '#ef535030' : '#26c28130'}` }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>Price Target</div>
              <div style={{ fontSize: 18, fontWeight: 800, fontFamily: 'var(--font-mono)', color: actionColor(row.action) }}>{fmtPrice(row.price_target_after_cost ?? row.price_target)}</div>
              <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 3 }}>
                after cost · expected move {priceChange != null ? `${priceChange >= 0 ? '+' : ''}${priceChange.toFixed(2)}%` : '—'}
              </div>
            </div>
            {[
              ['Confidence', fmtConf(row.confidence), confColor(row.confidence)],
              ['Data Coverage', row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(1)}%` : '—', row.data_coverage_percent != null && row.data_coverage_percent >= 80 ? '#26c281' : '#f59e0b'],
              ['Integrity Score', row.market_state_integrity_score != null ? `${row.market_state_integrity_score.toFixed(1)}/100` : '—', (row.market_state_integrity_score ?? 0) >= 90 ? '#26c281' : '#f59e0b'],
              ['Risk State', (row.risk_state ?? '—').replace(/_/g, ' '), gateColor(row.risk_state)],
              ['Orchestrator', (row.orchestrator_state ?? '—').split('_').slice(-2).join(' '), 'var(--text-muted)'],
              ['Paper Fill', (row.paper_fill_status ?? '—').replace(/_/g, ' '), '#3b82f6'],
              ['Signal Age', fmtAge(row.age_seconds), row.age_seconds != null && row.age_seconds < 3600 ? 'var(--text-secondary)' : '#ef5350'],
              ['Generated', row.generated_at ? new Date(row.generated_at).toLocaleString() : '—', 'var(--text-muted)'],
            ].map(([label, value, color]) => (
              <div key={String(label)}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{label}</div>
                <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: String(color) }}>{value}</div>
              </div>
            ))}
          </div>

          {/* IDs */}
          <div style={{ padding: '8px 20px', borderTop: '1px solid rgba(255,255,255,0.05)', display: 'flex', gap: 24, flexWrap: 'wrap' }}>
            {[['Signal ID', row.signal_id], ['Prediction ID', row.prediction_id]].map(([label, value]) => value ? (
              <div key={String(label)}>
                <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginRight: 6 }}>{label}</span>
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{value}</span>
              </div>
            ) : null)}
          </div>

          {/* AI Reasoning toggle */}
          <div style={{ padding: '8px 20px', borderTop: '1px solid rgba(255,255,255,0.05)' }}>
            <button
              onClick={() => setShowReasoning(!showReasoning)}
              style={{
                padding: '6px 14px', borderRadius: 6, border: `1px solid ${showReasoning ? 'var(--accent)' : 'rgba(255,255,255,0.1)'}`,
                background: showReasoning ? 'rgba(59,130,246,0.08)' : 'transparent',
                color: showReasoning ? 'var(--accent)' : 'var(--text-secondary)',
                fontSize: 11, fontWeight: 600, cursor: 'pointer', display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              🧠 {showReasoning ? 'Hide' : 'Show'} AI Reasoning & Evidence
            </button>
          </div>
          {showReasoning && <AIReasoningPanel symbol={row.symbol} timeframe={row.timeframe} />}
        </div>
      </td>
    </tr>
  );
}

// ─── Sort header ──────────────────────────────────────────────────────────

type SortKey = 'symbol' | 'timeframe' | 'action' | 'confidence' | 'age_seconds' | 'price_target';
type SortDir = 'asc' | 'desc';

function SortTh({ label, col, current, dir, onSort }: { label: string; col: SortKey; current: SortKey; dir: SortDir; onSort: (c: SortKey) => void }): JSX.Element {
  const active = current === col;
  return (
    <th onClick={() => onSort(col)} style={{ padding: '8px 12px', textAlign: 'left', cursor: 'pointer', userSelect: 'none', borderBottom: '1px solid var(--border)', color: active ? 'var(--accent)' : 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600, whiteSpace: 'nowrap', background: 'var(--bg-panel)' }}>
      {label}{active ? (dir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  );
}

// ─── Main Page ─────────────────────────────────────────────────────────────

export default function SignalsPage(): JSX.Element {
  const [selectedSymbols, setSelectedSymbols] = useState<Set<string>>(new Set(DEFAULT_SYMBOLS));
  const [selectedTFs, setSelectedTFs] = useState<Set<TF>>(new Set(TIMEFRAMES));
  const [sortKey, setSortKey] = useState<SortKey>('symbol');
  const [sortDir, setSortDir] = useState<SortDir>('asc');
  const [expandedRow, setExpandedRow] = useState<string | null>(null);
  const [showAllSymbols, setShowAllSymbols] = useState(false);
  const [symbolSearch, setSymbolSearch] = useState('');
  const [routeFilter, setRouteFilter] = useState<'all' | 'paper' | 'live' | 'blocked'>('all');

  const symbolsParam = Array.from(selectedSymbols).join(',');
  const tfsParam = Array.from(selectedTFs).join(',');
  const url = `/api/v2/signals/matrix?symbols=${symbolsParam}&timeframes=${tfsParam}`;

  const { envelope, loading, refetch } = useRealtimeResource<SignalMatrixData>({
    url, source: '/api/v2/signals/matrix', pollIntervalMs: 10_000, staleThresholdMs: 20_000, mode: 'read_only',
  });
  const { envelope: allEnv } = useRealtimeResource<SignalMatrixData>({
    url: '/api/v2/signals/matrix', source: '/api/v2/signals/matrix', pollIntervalMs: 60_000, mode: 'read_only',
  });

  const allSymbols = useMemo(() => allEnv.data?.symbols ?? [], [allEnv.data]);
  const rows = envelope.data?.rows ?? [];

  // Route filter
  const filteredRows = useMemo(() => {
    if (routeFilter === 'all') return rows;
    if (routeFilter === 'paper') return rows.filter(r => (r.paper_fill_gate_status ?? '').toLowerCase().includes('open') || (r.live_gate ?? '').toLowerCase().includes('human_only'));
    if (routeFilter === 'live') return rows.filter(r => (r.live_gate ?? '').toLowerCase().includes('open') && !(r.live_gate ?? '').toLowerCase().includes('blocked'));
    if (routeFilter === 'blocked') return rows.filter(r => (r.live_gate ?? '').toLowerCase().includes('blocked') && !(r.paper_fill_gate_status ?? '').toLowerCase().includes('open'));
    return rows;
  }, [rows, routeFilter]);

  const sorted = useMemo(() => {
    const copy = [...filteredRows];
    copy.sort((a, b) => {
      let av: string | number = 0, bv: string | number = 0;
      if (sortKey === 'symbol') { av = a.symbol; bv = b.symbol; }
      else if (sortKey === 'timeframe') { const o: Record<string, number> = { '1m': 0, '5m': 1, '15m': 2, '1h': 3, '4h': 4 }; av = o[a.timeframe] ?? 99; bv = o[b.timeframe] ?? 99; }
      else if (sortKey === 'action') { av = a.action ?? ''; bv = b.action ?? ''; }
      else if (sortKey === 'confidence') { av = a.confidence ?? -1; bv = b.confidence ?? -1; }
      else if (sortKey === 'age_seconds') { av = a.age_seconds ?? 999999; bv = b.age_seconds ?? 999999; }
      else if (sortKey === 'price_target') { av = a.price_target_after_cost ?? a.price_target ?? -1; bv = b.price_target_after_cost ?? b.price_target ?? -1; }
      if (typeof av === 'string' && typeof bv === 'string') return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
      if (typeof av === 'number' && typeof bv === 'number') return sortDir === 'asc' ? av - bv : bv - av;
      return 0;
    });
    return copy;
  }, [filteredRows, sortKey, sortDir]);

  const handleSort = useCallback((col: SortKey) => {
    if (col === sortKey) setSortDir(d => d === 'asc' ? 'desc' : 'asc'); else { setSortKey(col); setSortDir('asc'); }
  }, [sortKey]);

  const toggleSymbol = useCallback((s: string) => {
    setSelectedSymbols(prev => { const n = new Set(prev); if (n.has(s)) { if (n.size > 1) n.delete(s); } else n.add(s); return n; });
  }, []);

  const displayedSymbols = useMemo(() => {
    const filter = symbolSearch.trim().toUpperCase();
    const pool = showAllSymbols ? allSymbols : DEFAULT_SYMBOLS;
    return filter ? pool.filter(s => s.includes(filter)) : pool;
  }, [showAllSymbols, allSymbols, symbolSearch]);

  const paperCount = rows.filter(r => (r.paper_fill_gate_status ?? '').toLowerCase().includes('open')).length;
  const liveCount = rows.filter(r => (r.live_gate ?? '').toLowerCase() === 'open').length;
  const avgConf = rows.length > 0 ? rows.reduce((s, r) => s + (r.confidence ?? 0), 0) / rows.length : null;

  return (
    <div data-testid="page-signals" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Signals</h1>
            <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
              Published signal routing · Trainer → Risk Gate → Paper/Live Engine · {rows.length} signals · {allSymbols.length} symbols in scope
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '4px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>

        {/* KPI strip */}
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', marginBottom: 12 }}>
          {[
            { label: 'Total Signals', value: rows.length, color: 'var(--text-primary)' },
            { label: 'Paper Routed', value: paperCount, color: '#3b82f6' },
            { label: 'Live Routed', value: liveCount, color: liveCount > 0 ? '#26c281' : 'var(--text-muted)' },
            { label: 'Long', value: rows.filter(r => (r.action ?? '').toLowerCase().includes('long')).length, color: '#26c281' },
            { label: 'Short', value: rows.filter(r => (r.action ?? '').toLowerCase().includes('short')).length, color: '#ef5350' },
            { label: 'Avg Confidence', value: avgConf != null ? fmtConf(avgConf) : '—', color: confColor(avgConf) },
          ].map(k => (
            <div key={k.label} style={{ background: 'var(--bg-base)', border: '1px solid var(--border)', borderRadius: 6, padding: '6px 12px', display: 'flex', gap: 8, alignItems: 'center' }}>
              <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{k.label}</span>
              <span style={{ fontSize: 14, fontWeight: 700, fontFamily: 'var(--font-mono)', color: k.color }}>{k.value}</span>
            </div>
          ))}
        </div>

        {/* Route filter */}
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', alignSelf: 'center', marginRight: 4 }}>Filter by Routing</span>
          {(['all', 'paper', 'live', 'blocked'] as const).map(f => (
            <button key={f} onClick={() => setRouteFilter(f)} style={{
              padding: '4px 12px', borderRadius: 6, fontSize: 11, fontWeight: routeFilter === f ? 700 : 400, cursor: 'pointer',
              border: `1px solid ${routeFilter === f ? (f === 'paper' ? '#3b82f6' : f === 'live' ? '#26c281' : f === 'blocked' ? '#ef5350' : 'var(--accent)') : 'var(--border)'}`,
              background: routeFilter === f ? (f === 'paper' ? 'rgba(59,130,246,0.12)' : f === 'live' ? 'rgba(38,194,129,0.12)' : f === 'blocked' ? 'rgba(239,83,80,0.1)' : 'rgba(59,130,246,0.1)') : 'transparent',
              color: routeFilter === f ? (f === 'paper' ? '#3b82f6' : f === 'live' ? '#26c281' : f === 'blocked' ? '#ef5350' : 'var(--accent)') : 'var(--text-secondary)',
            }}>
              {f === 'all' ? 'All' : f === 'paper' ? '📋 Paper' : f === 'live' ? '⚡ Live' : '🔒 Blocked'}
            </button>
          ))}
          <span style={{ fontSize: 11, color: 'var(--text-muted)', alignSelf: 'center', marginLeft: 4 }}>{sorted.length} shown</span>
        </div>

        {/* Symbol selector */}
        <div style={{ marginBottom: 10 }}>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Symbols</span>
            <input value={symbolSearch} onChange={e => setSymbolSearch(e.target.value)} placeholder="Filter..." style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'var(--bg-base)', color: 'var(--text-primary)', fontSize: 11, width: 90, outline: 'none' }} />
            <button onClick={() => setShowAllSymbols(s => !s)} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>
              {showAllSymbols ? `Default (${DEFAULT_SYMBOLS.length})` : `All (${allSymbols.length})`}
            </button>
            <button onClick={() => setSelectedSymbols(new Set(['BTCUSDT', 'ETHUSDT', 'SOLUSDT']))} style={{ padding: '2px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 10, cursor: 'pointer' }}>BTC/ETH/SOL</button>
          </div>
          <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', maxHeight: 64, overflowY: 'auto' }}>
            {displayedSymbols.map(s => (
              <button key={s} onClick={() => toggleSymbol(s)} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 10, fontWeight: selectedSymbols.has(s) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedSymbols.has(s) ? 'var(--accent)' : 'var(--border)'}`, background: selectedSymbols.has(s) ? 'rgba(59,130,246,0.12)' : 'transparent', color: selectedSymbols.has(s) ? 'var(--accent)' : 'var(--text-secondary)' }}>
                {s.replace('USDT', '')}
              </button>
            ))}
          </div>
        </div>

        {/* TF filter */}
        <div style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginRight: 4 }}>Timeframes</span>
          {TIMEFRAMES.map(tf => (
            <button key={tf} onClick={() => {
              setSelectedTFs(prev => { const n = new Set(prev); if (n.has(tf)) { if (n.size > 1) n.delete(tf); } else n.add(tf); return n; });
            }} style={{ padding: '3px 9px', borderRadius: 5, fontSize: 11, fontWeight: selectedTFs.has(tf) ? 700 : 400, fontFamily: 'var(--font-mono)', cursor: 'pointer', border: `1px solid ${selectedTFs.has(tf) ? 'var(--accent)' : 'var(--border)'}`, background: selectedTFs.has(tf) ? 'rgba(59,130,246,0.12)' : 'transparent', color: selectedTFs.has(tf) ? 'var(--accent)' : 'var(--text-secondary)' }}>
              {tf}
            </button>
          ))}
        </div>
      </div>

      {/* Table */}
      <div style={{ padding: 16 }}>
        {loading && sorted.length === 0 && <LoadingSkeleton rows={8} />}
        {!loading && sorted.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', background: 'var(--bg-panel)', borderRadius: 12, border: '1px solid var(--border)' }}>
            <div style={{ fontSize: 32, marginBottom: 10 }}>📡</div>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>No signals match the current filter. Try changing the routing filter or selecting more symbols.</p>
          </div>
        )}
        {sorted.length > 0 && (
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
                <thead>
                  <tr>
                    <SortTh label="Symbol" col="symbol" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="TF" col="timeframe" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Direction" col="action" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Confidence" col="confidence" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <SortTh label="Price Target" col="price_target" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Routing</th>
                    <th style={{ padding: '8px 12px', textAlign: 'left', borderBottom: '1px solid var(--border)', color: 'var(--text-muted)', fontSize: 10, textTransform: 'uppercase', letterSpacing: '0.06em', background: 'var(--bg-panel)', whiteSpace: 'nowrap' }}>Coverage</th>
                    <SortTh label="Age" col="age_seconds" current={sortKey} dir={sortDir} onSort={handleSort} />
                    <th style={{ padding: '8px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}></th>
                  </tr>
                </thead>
                <tbody>
                  {sorted.map(row => {
                    const rowKey = `${row.symbol}:${row.timeframe}`;
                    const expanded = expandedRow === rowKey;
                    return (
                      <>
                        <tr key={rowKey} onClick={() => setExpandedRow(expanded ? null : rowKey)}
                          style={{ cursor: 'pointer', borderBottom: '1px solid rgba(255,255,255,0.04)', background: expanded ? 'var(--bg-elevated)' : 'transparent', transition: 'background 0.1s' }}
                          onMouseEnter={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'; }}
                          onMouseLeave={e => { if (!expanded) (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>
                            {row.symbol.replace('USDT', '')}<span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 10, marginLeft: 2 }}>USDT</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}>
                            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-secondary)', padding: '2px 6px', background: 'var(--bg-base)', borderRadius: 4, border: '1px solid var(--border)' }}>{row.timeframe}</span>
                          </td>
                          <td style={{ padding: '10px 12px' }}><ActionBadge action={row.side ?? row.action} /></td>
                          <td style={{ padding: '10px 12px' }}><ConfBar value={row.confidence} /></td>
                          <td style={{ padding: '10px 12px' }}><PriceTargetCell target={row.price_target_after_cost ?? row.price_target} moveBps={row.expected_move_bps} action={row.action} /></td>
                          <td style={{ padding: '10px 12px' }}><RoutingBadge gateStatus={row.live_gate} paperFill={row.paper_fill_gate_status} /></td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: row.data_coverage_percent != null && row.data_coverage_percent >= 80 ? '#26c281' : '#f59e0b' }}>
                            {row.data_coverage_percent != null ? `${row.data_coverage_percent.toFixed(0)}%` : '—'}
                          </td>
                          <td style={{ padding: '10px 12px', fontFamily: 'var(--font-mono)', fontSize: 11, color: row.age_seconds != null && row.age_seconds < 3600 ? 'var(--text-secondary)' : '#ef5350' }}>
                            {fmtAge(row.age_seconds)}
                          </td>
                          <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{expanded ? '▲' : '▶'}</td>
                        </tr>
                        {expanded && <SignalCard key={`${rowKey}-card`} row={row} />}
                      </>
                    );
                  })}
                </tbody>
              </table>
            </div>
          </div>
        )}
        <div style={{ marginTop: 12, padding: '8px 0', borderTop: '1px solid rgba(255,255,255,0.04)' }}>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
            Signal routing: Trainer → Redis v2:signals:paper:* → Risk Gateway → Paper/Live Trader · {sorted.length} rows shown · LIVE TRADING BLOCKED
          </p>
        </div>
      </div>
    </div>
  );
}
