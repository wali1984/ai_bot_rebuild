import { useState } from 'react';
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

interface OrchestratorStatus {
  heartbeat: {
    status: string | null;
    classification: string | null;
    live_gate: string | null;
    predictions_seen: number | null;
    decisions_emitted: number | null;
    deconflict_reason: string | null;
    timestamp: string | null;
    age_seconds: number | null;
  } | null;
  last_proposals: Array<{
    symbol?: string;
    timeframe?: string;
    action?: string;
    confidence?: number;
    risk_state?: string;
    orchestrator_state?: string;
    [key: string]: unknown;
  }>;
  last_decisions: Array<{
    symbol?: string;
    timeframe?: string;
    action?: string;
    decision?: string;
    reason?: string;
    [key: string]: unknown;
  }>;
  live_gate: string | null;
  classification: string | null;
  deconflict_reason: string | null;
  generated_at: string | null;
}

interface RiskStatus {
  active_profile: {
    profile_id?: string;
    max_leverage?: number;
    min_confidence_calibrated?: number;
    max_notional_per_trade?: number;
    max_spread_bps?: number;
    max_slippage_bps?: number;
    min_expected_move_after_cost_bps?: number;
    max_daily_loss?: number;
    kill_switch?: boolean;
    [key: string]: unknown;
  } | null;
  heartbeat: {
    status?: string;
    decisions_processed?: number;
    denials?: number;
    age_seconds?: number | null;
    [key: string]: unknown;
  } | null;
  latest_gateway_result: {
    decision?: string;
    symbol?: string;
    timeframe?: string;
    reason_code?: string;
    [key: string]: unknown;
  } | null;
  recent_decisions: Array<{
    symbol?: string;
    timeframe?: string;
    decision?: string;
    reason_code?: string;
    confidence?: number;
    action?: string;
    [key: string]: unknown;
  }>;
  denials_breakdown: Record<string, number>;
  generated_at: string | null;
}

// ─── Helpers ──────────────────────────────────────────────────────────────

function statusColor(s: string | null | undefined): string {
  if (!s) return 'var(--text-muted)';
  const l = s.toLowerCase();
  if (l.includes('ok') || l.includes('active') || l.includes('allow') || l.includes('open') || l.includes('pass')) return '#26c281';
  if (l.includes('block') || l.includes('denied') || l.includes('error') || l.includes('fail')) return '#ef5350';
  if (l.includes('warn') || l.includes('human_only') || l.includes('pending')) return '#f59e0b';
  return 'var(--text-secondary)';
}

function actionColor(a: string | null | undefined): string {
  if (!a) return 'var(--text-muted)';
  const l = (a ?? '').toLowerCase();
  if (l.includes('long') || l.includes('buy') || l.includes('allow')) return '#26c281';
  if (l.includes('short') || l.includes('sell') || l.includes('deny')) return '#ef5350';
  if (l.includes('hold')) return '#f59e0b';
  return 'var(--text-muted)';
}

function fmtAge(s: number | null | undefined): string {
  if (s == null) return '—';
  if (s < 60) return `${s}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

// ─── Status badge ─────────────────────────────────────────────────────────

function StatusBadge({ value, label }: { value: string | null | undefined; label?: string }): JSX.Element {
  const color = statusColor(value);
  if (!value) return <span style={{ color: 'var(--text-muted)', fontSize: 11 }}>—</span>;
  return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, color, background: `${color}12`, border: `1px solid ${color}30`, fontFamily: 'var(--font-mono)', display: 'inline-block' }}>
      {label ?? value.replace(/_/g, ' ')}
    </span>
  );
}

// ─── Orchestrator panel ───────────────────────────────────────────────────

function OrchestratorPanel(): JSX.Element {
  const { envelope, loading, refetch } = useRealtimeResource<OrchestratorStatus>({
    url: '/api/v2/orchestrator/status',
    source: '/api/v2/orchestrator/status',
    pollIntervalMs: 5_000,
    staleThresholdMs: 15_000,
    mode: 'read_only',
  });

  const d = envelope.data;
  const hb = d?.heartbeat;
  const isOk = (hb?.status ?? '').toLowerCase().includes('ok') || (hb?.classification ?? '').toLowerCase().includes('ok');

  return (
    <div style={{ flex: 1, minWidth: 320, background: 'var(--bg-panel)', border: `1px solid ${isOk ? 'rgba(38,194,129,0.2)' : 'var(--border)'}`, borderRadius: 12, overflow: 'hidden' }}>
      {/* Panel header */}
      <div style={{ padding: '14px 18px', background: isOk ? 'rgba(38,194,129,0.06)' : 'rgba(255,255,255,0.02)', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 18 }}>🎯</span>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>Orchestrator</h2>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>Proposes only · Risk gateway validates</p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
          <button onClick={refetch} style={{ padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', fontSize: 10, cursor: 'pointer' }}>↺</button>
        </div>
      </div>

      <div style={{ padding: '14px 18px' }}>
        {loading && !d && <LoadingSkeleton rows={4} />}

        {/* Heartbeat */}
        {hb && (
          <div style={{ marginBottom: 16, padding: '12px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 10 }}>Heartbeat</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
              {[
                { label: 'Status', value: <StatusBadge value={hb.status} /> },
                { label: 'Classification', value: <StatusBadge value={hb.classification} /> },
                { label: 'Live Gate', value: <StatusBadge value={hb.live_gate} /> },
                { label: 'Predictions Seen', value: <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{hb.predictions_seen?.toLocaleString() ?? '—'}</span> },
                { label: 'Decisions Emitted', value: <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)' }}>{hb.decisions_emitted?.toLocaleString() ?? '—'}</span> },
                { label: 'Age', value: <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: (hb.age_seconds ?? 0) < 60 ? '#26c281' : '#f59e0b' }}>{fmtAge(hb.age_seconds)}</span> },
              ].map(item => (
                <div key={item.label}>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 4 }}>{item.label}</div>
                  {item.value}
                </div>
              ))}
            </div>
            {hb.deconflict_reason && (
              <div style={{ marginTop: 10, padding: '6px 10px', background: 'rgba(245,158,11,0.08)', borderRadius: 6, border: '1px solid rgba(245,158,11,0.2)' }}>
                <span style={{ fontSize: 9, color: '#f59e0b', textTransform: 'uppercase', marginRight: 6 }}>Deconflict Reason</span>
                <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>{hb.deconflict_reason}</span>
              </div>
            )}
          </div>
        )}

        {/* Recent proposals */}
        {(d?.last_proposals?.length ?? 0) > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Recent Proposals</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
              {d!.last_proposals.slice(0, 10).map((p, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-primary)', minWidth: 70 }}>{p.symbol}</span>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', padding: '1px 5px', background: 'rgba(255,255,255,0.04)', borderRadius: 3 }}>{p.timeframe}</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: actionColor(p.action), fontFamily: 'var(--font-mono)' }}>{(p.action ?? '—').replace(/_/g, ' ').toUpperCase()}</span>
                  {p.confidence != null && <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{(p.confidence * 100).toFixed(1)}%</span>}
                  {p.risk_state && <StatusBadge value={p.risk_state} />}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Recent decisions */}
        {(d?.last_decisions?.length ?? 0) > 0 && (
          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Recent Decisions</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
              {d!.last_decisions.slice(0, 10).map((dec, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '6px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.05)', flexWrap: 'wrap' }}>
                  <span style={{ fontSize: 11, fontFamily: 'var(--font-mono)', fontWeight: 700, color: 'var(--text-primary)', minWidth: 70 }}>{dec.symbol ?? '?'}</span>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', padding: '1px 5px', background: 'rgba(255,255,255,0.04)', borderRadius: 3 }}>{dec.timeframe}</span>
                  <StatusBadge value={dec.decision} />
                  {dec.reason && <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{String(dec.reason).slice(0, 40)}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {!d && !loading && (
          <div style={{ padding: '20px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>No orchestrator data. Check Redis v2:orchestrator:* keys.</p>
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Risk panel ────────────────────────────────────────────────────────────

function RiskPanel(): JSX.Element {
  const { envelope, loading, refetch } = useRealtimeResource<RiskStatus>({
    url: '/api/v2/risk/status',
    source: '/api/v2/risk/status',
    pollIntervalMs: 5_000,
    staleThresholdMs: 15_000,
    mode: 'read_only',
  });

  const d = envelope.data;
  const profile = d?.active_profile;
  const hb = d?.heartbeat;
  const latest = d?.latest_gateway_result;

  return (
    <div style={{ flex: 1, minWidth: 320, background: 'var(--bg-panel)', border: '1px solid rgba(239,83,80,0.15)', borderRadius: 12, overflow: 'hidden' }}>
      {/* Panel header */}
      <div style={{ padding: '14px 18px', background: 'rgba(239,83,80,0.04)', borderBottom: '1px solid rgba(255,255,255,0.06)', display: 'flex', alignItems: 'center', gap: 10 }}>
        <span style={{ fontSize: 18 }}>🛡</span>
        <div style={{ flex: 1 }}>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 700 }}>Risk Gateway</h2>
          <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>Validates and blocks/allows · LIVE TRADING BLOCKED</p>
        </div>
        <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
          <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
          <button onClick={refetch} style={{ padding: '3px 8px', borderRadius: 4, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-muted)', fontSize: 10, cursor: 'pointer' }}>↺</button>
        </div>
      </div>

      <div style={{ padding: '14px 18px' }}>
        {loading && !d && <LoadingSkeleton rows={4} />}

        {/* Kill switch + live gate banner */}
        <div style={{ marginBottom: 14, padding: '10px 14px', borderRadius: 8, background: 'rgba(239,83,80,0.06)', border: '1px solid rgba(239,83,80,0.2)', display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <span style={{ fontSize: 16 }}>🔒</span>
            <div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Live Trading</div>
              <div style={{ fontSize: 13, fontWeight: 800, color: '#ef5350', fontFamily: 'var(--font-mono)' }}>BLOCKED</div>
            </div>
          </div>
          {profile?.kill_switch !== undefined && (
            <div>
              <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Kill Switch</div>
              <div style={{ fontSize: 13, fontWeight: 800, color: profile.kill_switch ? '#ef5350' : '#26c281', fontFamily: 'var(--font-mono)' }}>{profile.kill_switch ? 'ACTIVE' : 'OFF'}</div>
            </div>
          )}
        </div>

        {/* Active profile */}
        {profile && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 8 }}>
              <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>Active Risk Profile</div>
              <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(99,102,241,0.12)', color: '#6366f1', border: '1px solid rgba(99,102,241,0.3)', fontFamily: 'var(--font-mono)' }}>{profile.profile_id ?? '—'}</span>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8 }}>
              {[
                { label: 'Max Leverage', value: profile.max_leverage != null ? `${profile.max_leverage}×` : '—', color: (profile.max_leverage ?? 0) > 5 ? '#ef5350' : '#26c281' },
                { label: 'Min Confidence', value: profile.min_confidence_calibrated != null ? `${(profile.min_confidence_calibrated * 100).toFixed(0)}%` : '—', color: 'var(--text-secondary)' },
                { label: 'Max Notional', value: profile.max_notional_per_trade != null ? `$${profile.max_notional_per_trade.toFixed(2)}` : '—', color: 'var(--text-secondary)' },
                { label: 'Max Spread', value: profile.max_spread_bps != null ? `${profile.max_spread_bps}bps` : '—', color: 'var(--text-secondary)' },
                { label: 'Min Move', value: profile.min_expected_move_after_cost_bps != null ? `${profile.min_expected_move_after_cost_bps}bps` : '—', color: 'var(--text-secondary)' },
                { label: 'Max Daily Loss', value: profile.max_daily_loss != null ? `$${profile.max_daily_loss.toFixed(2)}` : '—', color: '#ef5350' },
              ].map(row => (
                <div key={row.label} style={{ padding: '8px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6 }}>
                  <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 2 }}>{row.label}</div>
                  <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: row.color }}>{row.value}</div>
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Heartbeat */}
        {hb && (
          <div style={{ marginBottom: 16, padding: '10px 14px', background: 'rgba(0,0,0,0.2)', borderRadius: 8, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', width: '100%', marginBottom: 4 }}>Gateway Heartbeat</div>
            {[
              { label: 'Status', value: <StatusBadge value={String(hb.status ?? '—')} /> },
              { label: 'Decisions', value: <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: 'var(--text-primary)' }}>{hb.decisions_processed ?? '—'}</span> },
              { label: 'Denials', value: <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700, color: '#ef5350' }}>{hb.denials ?? '—'}</span> },
              { label: 'Age', value: <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: (hb.age_seconds ?? 0) < 60 ? '#26c281' : '#f59e0b' }}>{fmtAge(hb.age_seconds as number | null)}</span> },
            ].map(item => (
              <div key={item.label}>
                <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', marginBottom: 3 }}>{item.label}</div>
                {item.value}
              </div>
            ))}
          </div>
        )}

        {/* Latest gateway result */}
        {latest && (
          <div style={{ marginBottom: 16, padding: '10px 14px', background: `${actionColor(latest.decision)}08`, borderRadius: 8, border: `1px solid ${actionColor(latest.decision)}20` }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Latest Gateway Decision</div>
            <div style={{ display: 'flex', gap: 10, alignItems: 'center', flexWrap: 'wrap' }}>
              {latest.symbol && <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 12 }}>{latest.symbol}</span>}
              {latest.timeframe && <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{latest.timeframe}</span>}
              <StatusBadge value={latest.decision} />
              {latest.reason_code && <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{latest.reason_code}</span>}
            </div>
          </div>
        )}

        {/* Recent decisions */}
        {(d?.recent_decisions?.length ?? 0) > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Recent Gateway Decisions</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 200, overflowY: 'auto' }}>
              {d!.recent_decisions.slice(0, 10).map((dec, i) => (
                <div key={i} style={{ display: 'flex', gap: 8, alignItems: 'center', padding: '5px 8px', background: 'rgba(255,255,255,0.02)', borderRadius: 5, flexWrap: 'wrap' }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700, minWidth: 70 }}>{dec.symbol ?? '?'}</span>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', padding: '1px 4px', background: 'rgba(255,255,255,0.04)', borderRadius: 3 }}>{dec.timeframe}</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: actionColor(dec.action), fontFamily: 'var(--font-mono)' }}>{(dec.action ?? '').replace(/_/g, ' ').toUpperCase()}</span>
                  <StatusBadge value={dec.decision} />
                  {dec.reason_code && <span style={{ fontSize: 9, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{dec.reason_code}</span>}
                </div>
              ))}
            </div>
          </div>
        )}

        {/* Denials breakdown */}
        {d?.denials_breakdown && Object.keys(d.denials_breakdown).length > 0 && (
          <div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>Denial Reasons</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
              {Object.entries(d.denials_breakdown).sort((a, b) => b[1] - a[1]).map(([reason, count]) => (
                <div key={reason} style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                  <div style={{ flex: 1, height: 6, background: 'rgba(255,255,255,0.06)', borderRadius: 3, overflow: 'hidden' }}>
                    <div style={{ height: '100%', width: `${Math.min(100, (count / Math.max(...Object.values(d.denials_breakdown))) * 100)}%`, background: '#ef5350', borderRadius: 3 }} />
                  </div>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', minWidth: 180 }}>{reason.replace(/_/g, ' ')}</span>
                  <span style={{ fontSize: 11, fontWeight: 700, fontFamily: 'var(--font-mono)', color: '#ef5350', minWidth: 24, textAlign: 'right' }}>{count}</span>
                </div>
              ))}
            </div>
          </div>
        )}

        {!d && !loading && (
          <div style={{ padding: '20px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>No risk gateway data. Check Redis v2:risk:* keys.</p>
          </div>
        )}

        <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
      </div>
    </div>
  );
}

// ─── Main page ────────────────────────────────────────────────────────────

export default function OrchestratorAdminPage(): JSX.Element {
  const [showArch, setShowArch] = useState(false);

  return (
    <div data-testid="page-orchestrator-admin" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}>

      {/* Header */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Orchestrator + Risk Gateway</h1>
              <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, background: 'rgba(239,83,80,0.1)', color: '#ef5350', border: '1px solid rgba(239,83,80,0.3)', fontFamily: 'var(--font-mono)' }}>READ-ONLY</span>
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              Orchestrator proposes → Risk gateway validates and blocks/allows → Execution engine acts (paper only) · Auto-refreshes every 5s
            </p>
          </div>
          <button onClick={() => setShowArch(!showArch)} style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>
            {showArch ? 'Hide' : 'Show'} Pipeline Architecture
          </button>
        </div>

        {/* Architecture flow */}
        {showArch && (
          <div style={{ marginTop: 14, padding: '12px 16px', background: 'rgba(0,0,0,0.2)', borderRadius: 8, border: '1px solid rgba(255,255,255,0.06)', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)' }}>
            <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
              <span style={{ color: '#6366f1' }}>Trainer</span>
              <span>→</span>
              <span style={{ color: '#6366f1' }}>v2:prediction:*</span>
              <span>→</span>
              <span style={{ color: '#f59e0b' }}>Orchestrator</span>
              <span>(proposes)</span>
              <span>→</span>
              <span style={{ color: '#ef5350' }}>Risk Gateway</span>
              <span>(blocks/allows)</span>
              <span>→</span>
              <span style={{ color: '#3b82f6' }}>Paper Engine</span>
              <span>→</span>
              <span style={{ color: '#26c281' }}>v2:signals:paper:*</span>
            </div>
            <div style={{ marginTop: 8, color: 'rgba(255,255,255,0.3)' }}>
              LIVE TRADING BLOCKED at all layers · Orchestrator cannot override Risk Gateway
            </div>
          </div>
        )}
      </div>

      {/* Two-column layout */}
      <div style={{ padding: 16, display: 'flex', gap: 16, flexWrap: 'wrap', alignItems: 'flex-start' }}>
        <OrchestratorPanel />
        <RiskPanel />
      </div>

      {/* Safety banner */}
      <div style={{ margin: '0 16px 16px', padding: '10px 16px', background: 'rgba(239,83,80,0.05)', border: '1px solid rgba(239,83,80,0.15)', borderRadius: 8 }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          SAFETY: This page is read-only. Orchestrator proposes only. Risk gateway is the sole allow/deny authority. LIVE TRADING BLOCKED. No exchange orders are placed from V2. V2_MODE=paper.
        </p>
      </div>
    </div>
  );
}
