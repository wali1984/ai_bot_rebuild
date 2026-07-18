import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';
import { DANGEROUS_CONTROLS } from '../../constants/dangerousControls';
import { DangerousControlPanel } from '../../components/controls/DangerousControlPanel';
import { ControlActionDialog, type ControlSpec } from '../../components/admin';
import meta from './meta';

const RISK_ENDPOINT = '/api/v2/risk/status';
const MOBILE_RISK_ENDPOINT = '/api/v2/mobile/risk-status';
const TABS = ['Decisions', 'Profile', 'Controls', 'Readiness'] as const;
type Tab = typeof TABS[number];
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

interface RiskDecision { risk_decision_id?: string; symbol?: string; risk_action?: string; risk_reason_code?: string; live_blocked?: boolean; }
interface RiskPayload {
  live_gate?: string; live_blocked?: boolean; fail_closed?: boolean;
  active_profile?: { profile_id?: string; profile_name?: string };
  recent_decisions?: RiskDecision[];
  heartbeat?: { decisions_processed_total?: number; finished_at?: string };
  data?: {
    latest_gateway_result?: { symbol?: string; side?: string; risk_action?: string; risk_reason_code?: string; generated_at?: string };
    active_profile?: { profile_name?: string; profile_id?: string };
    heartbeat?: { decisions_processed_total?: number; finished_at?: string };
  };
}

interface MobileRiskPayload {
  risk_state?: string | null;
  risk_classification?: string | null;
  kill_switch_active?: boolean | null;
  fail_closed?: boolean | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
  live_gate?: string | { gate?: string | null; label?: string | null; places_real_order?: boolean | null; live_trading_enabled?: boolean | null } | null;
  real_trader_readiness?: {
    live_gate?: string | null;
    operator_flip_required?: boolean | null;
    live_ready?: boolean | null;
    order_submitted?: boolean | null;
    test_order_submitted?: boolean | null;
  } | null;
  adaptive_hedge_cross_margin?: {
    hedge_state?: string | null;
    hedge_rows?: number | null;
    portfolio_liquidation_buffer_usd?: number | null;
    cross_margin_available_buffer_usd?: number | null;
    worst_case_portfolio_loss_usd?: number | null;
    maintenance_margin_estimate_usd?: number | null;
    margin_call_risk?: string | null;
    cross_margin_state?: string | null;
  } | null;
  provider_readiness?: {
    altdata_trade_block_score?: number | null;
    altdata_reduce_size_score?: number | null;
    altdata_hedge_required_score?: number | null;
  } | null;
  preemptive_edge_control?: {
    advanced_indicator_status?: string | null;
    advanced_indicators?: {
      sweep_risk_can_block_or_reduce?: boolean | null;
      status?: string | null;
    } | null;
  } | null;
}

const LOCK_ACTIONS = [
  { id: 'enable_live_trading' as const, label: 'Enable Live Trading', level: 'L5' },
  { id: 'increase_leverage' as const, label: 'Increase Leverage', level: 'L4' },
  { id: 'disable_kill_switch' as const, label: 'Disable Kill Switch', level: 'L5' },
  { id: 'disable_mandatory_stop' as const, label: 'Disable Mandatory Stop', level: 'L4' },
];

const CONTROL_SPECS: ControlSpec[] = LOCK_ACTIONS.map(a => {
  const ctrl = DANGEROUS_CONTROLS[a.id as keyof typeof DANGEROUS_CONTROLS];
  return {
    action_id: a.id,
    label: ctrl?.label ?? a.label,
    description: ctrl?.rationale ?? `Requires ${a.level} approval. Cannot be automatically reversed.`,
    danger: true,
    requires_reason: true,
    execute_endpoint: `/api/v2/admin/controls/${a.id}`,
  };
});

function usd(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return 'not reported';
  return value.toLocaleString('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 2 });
}

function statusText(value: string | null | undefined): string {
  return value ? value.replace(/_/g, ' ') : 'not reported';
}

function liveGateText(value: MobileRiskPayload['live_gate']): string {
  if (!value) return 'blocked_human_only';
  if (typeof value === 'string') return value;
  return value.gate ?? value.label ?? 'blocked_human_only';
}

function RiskRuntimeTruthPanel(): JSX.Element {
  const { envelope } = useRealtimeResource<MobileRiskPayload>({
    url: MOBILE_RISK_ENDPOINT,
    source: MOBILE_RISK_ENDPOINT,
    pollIntervalMs: 10_000,
    staleThresholdMs: 45_000,
    mode: 'read_only',
  });
  const risk = envelope.data;
  const hedge = risk?.adaptive_hedge_cross_margin;
  const preemptive = risk?.preemptive_edge_control;
  const provider = risk?.provider_readiness;
  const squeezeCanBlock = preemptive?.advanced_indicators?.sweep_risk_can_block_or_reduce === true;
  const liveBlocked = risk?.routes_to_live !== true && risk?.places_real_order !== true;
  const rows = [
    { label: 'Liquidation buffer', value: usd(hedge?.portfolio_liquidation_buffer_usd), tone: 'ok' },
    { label: 'Hedge state', value: statusText(hedge?.hedge_state), tone: hedge?.hedge_state && hedge.hedge_state !== 'NO_HEDGE' ? 'warn' : 'info' },
    { label: 'Squeeze risk', value: squeezeCanBlock ? 'sweep risk can block or reduce' : statusText(preemptive?.advanced_indicator_status), tone: squeezeCanBlock ? 'warn' : 'info' },
    { label: 'Kill switch', value: risk?.kill_switch_active ? 'active' : 'not active', tone: risk?.kill_switch_active ? 'warn' : 'ok' },
    { label: 'Maintenance margin', value: usd(hedge?.maintenance_margin_estimate_usd), tone: 'info' },
    { label: 'ADL risk', value: statusText(hedge?.margin_call_risk), tone: hedge?.margin_call_risk === 'LOW' ? 'ok' : 'warn' },
    { label: 'Hedge required score', value: provider?.altdata_hedge_required_score != null ? provider.altdata_hedge_required_score.toFixed(2) : 'not reported', tone: (provider?.altdata_hedge_required_score ?? 0) > 0.5 ? 'warn' : 'info' },
    { label: 'Approval state', value: liveBlocked ? `blocked: ${liveGateText(risk?.live_gate)}` : 'live route reported', tone: liveBlocked ? 'warn' : 'error' },
  ];
  const toneColor = (tone: string): string => tone === 'ok' ? SC.ok : tone === 'warn' ? SC.warn : tone === 'error' ? SC.error : SC.info;

  return (
    <section data-testid="risk-runtime-truth-panel" className="glass" style={{ padding: '12px 14px' }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 14, fontWeight: 800, color: 'var(--text-primary)' }}>Risk Runtime Truth</h2>
          <p style={{ margin: '3px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
            Liquidation, hedge, squeeze, kill switch, and operator approval state from the shared web/iOS risk contract.
          </p>
        </div>
        <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: liveBlocked ? SC.warn : SC.error }}>
          {MOBILE_RISK_ENDPOINT}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(170px, 1fr))', gap: 8 }}>
        {rows.map((row) => (
          <div key={row.label} style={{ padding: '8px 10px', borderRadius: 7, border: `1px solid ${toneColor(row.tone)}44`, background: 'var(--bg-base)' }}>
            <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 3 }}>{row.label}</div>
            <div style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: toneColor(row.tone), overflowWrap: 'anywhere' }}>{row.value}</div>
          </div>
        ))}
      </div>
      <p style={{ margin: '10px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
        No order, test-order, leverage, or margin mutation is available from this panel. Operator approval remains required.
      </p>
    </section>
  );
}

export default function AdminRiskPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Decisions');
  const [openControlId, setOpenControlId] = useState<string | null>(null);
  const { envelope, loading } = useRealtimeResource<RiskPayload>({ url: RISK_ENDPOINT, source: 'admin-risk', pollIntervalMs: 10_000 });
  const raw = envelope.data;
  const data = raw?.data ?? raw;
  const decisions = raw?.recent_decisions || [];
  const heartbeat = (data as RiskPayload)?.heartbeat ?? raw?.heartbeat;
  const profile = (data as RiskPayload)?.active_profile ?? raw?.active_profile;
  const liveBlocked = raw?.live_blocked !== false;
  const decisionsTotal = heartbeat?.decisions_processed_total ?? 0;

  return (
    <div data-testid="admin-risk-page" style={{ display: 'flex', flexDirection: 'column', gap: 18, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Risk</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Risk gateway, execution gating, and dangerous control locks</p>
        </div>
        <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {[
          { label: 'LIVE EXECUTION', value: liveBlocked ? 'BLOCKED' : 'ENABLED', accent: liveBlocked ? SC.error : SC.ok },
          { label: 'GATE', value: (raw?.live_gate || '—').replace(/_/g, ' '), accent: raw?.live_gate?.includes('blocked') ? SC.error : SC.ok },
          { label: 'PROFILE', value: profile?.profile_name || profile?.profile_id || '—' },
          { label: 'DECISIONS TOTAL', value: decisionsTotal.toLocaleString() },
          { label: 'FAIL CLOSED', value: raw?.fail_closed ? 'YES' : 'NO', accent: raw?.fail_closed ? SC.warn : SC.ok },
        ].map(({ label, value, accent }) => (
          <div key={label} className="glass" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Gate banner */}
      <div data-testid="live-execution-status" style={{
        padding: '10px 14px', borderRadius: 6,
        background: liveBlocked ? `${SC.error}12` : `${SC.ok}12`,
        border: `1px solid ${liveBlocked ? SC.error : SC.ok}44`,
        display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap',
      }}>
        <span style={{ fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 13, color: liveBlocked ? SC.error : SC.ok }}>
          LIVE EXECUTION: {liveBlocked ? 'BLOCKED' : 'ENABLED'}
        </span>
        {raw?.live_gate && <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>gate: {raw.live_gate}</span>}
        {raw?.fail_closed && <span style={{ fontSize: 11, color: SC.warn, fontFamily: 'var(--font-mono)' }}>FAIL-CLOSED</span>}
        {profile?.profile_name && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>profile: {profile.profile_name}</span>}
        {heartbeat?.finished_at && <span style={{ fontSize: 11, color: 'var(--text-muted)', marginLeft: 'auto' }}>heartbeat {relativeAge(heartbeat.finished_at)}</span>}
      </div>

      <RiskRuntimeTruthPanel />

      <DangerousControlPanel controlIds={meta.dangerousControlIds} />

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map(t => (
          <button key={t} type="button" onClick={() => setTab(t)} style={{
            padding: '7px 16px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t ? 700 : 400, color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)',
            borderBottom: tab === t ? '2px solid var(--admin-accent)' : '2px solid transparent',
          }}>{t}</button>
        ))}
      </div>

      {tab === 'Decisions' && (
        loading && !raw ? <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading risk decisions…</div> :
        decisions.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table data-testid="risk-decisions-table" style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--admin-border)' }}>
                  {['ID', 'Symbol', 'Action', 'Reason Code', 'Live Blocked'].map(h => (
                    <th key={h} style={{ padding: '7px 10px', textAlign: 'left', fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {decisions.slice(0, 20).map((d, i) => (
                  <tr key={d.risk_decision_id ?? i} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                    <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)', maxWidth: 140, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{d.risk_decision_id ?? '—'}</td>
                    <td style={{ padding: '7px 10px', fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{d.symbol ?? '—'}</td>
                    <td style={{ padding: '7px 10px' }}>
                      <span style={{ padding: '2px 7px', borderRadius: 4, background: d.risk_action === 'allow' ? `${SC.ok}20` : `${SC.error}20`, color: d.risk_action === 'allow' ? SC.ok : SC.error, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                        {(d.risk_action ?? 'unknown').toUpperCase()}
                      </span>
                    </td>
                    <td style={{ padding: '7px 10px', fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{d.risk_reason_code ?? '—'}</td>
                    <td style={{ padding: '7px 10px', color: d.live_blocked ? SC.ok : SC.error, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 700 }}>{d.live_blocked ? 'YES' : 'NO'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="glass" style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: 12 }}>
            No recent decisions in Redis. Risk gateway heartbeat: {heartbeat?.finished_at ? relativeAge(heartbeat.finished_at) : 'no data'}.
          </div>
        )
      )}

      {tab === 'Profile' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          <div className="glass" style={{ padding: '16px' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Active Risk Profile</div>
            {profile ? (
              <>
                {[['Profile Name', profile.profile_name || '—'], ['Profile ID', profile.profile_id || '—']].map(([l, v]) => (
                  <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--line-soft)', gap: 8 }}>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{l}</span>
                    <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{v}</span>
                  </div>
                ))}
              </>
            ) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No active profile data</div>}
          </div>
          <div className="glass" style={{ padding: '16px' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Heartbeat</div>
            {[['Decisions Total', decisionsTotal.toLocaleString()], ['Last At', heartbeat?.finished_at ? relativeAge(heartbeat.finished_at) : '—']].map(([l, v]) => (
              <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--line-soft)', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{l}</span>
                <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{v}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {tab === 'Controls' && (
        <div>
          <div style={{ padding: '10px 14px', marginBottom: 12, borderRadius: 6, background: `${SC.error}10`, border: `1px solid ${SC.error}33`, fontSize: 12, color: SC.error, fontFamily: 'var(--font-mono)' }}>
            DANGEROUS CONTROLS — Human approval + mandatory reason + audit chain required. All actions are logged.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {LOCK_ACTIONS.map(a => {
              const spec = CONTROL_SPECS.find(s => s.action_id === a.id);
              const displayLabel = spec?.label ?? a.label;
              return (
                <div key={a.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: `${SC.error}08`, border: `1px solid ${SC.error}22` }}>
                  <span style={{ width: 6, height: 6, borderRadius: '50%', background: SC.error, display: 'inline-block', flexShrink: 0 }} />
                  <span style={{ flex: 1, fontSize: 12, color: 'var(--text-primary)', fontWeight: 500 }}>{displayLabel}</span>
                  <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: `${SC.error}22`, border: `1px solid ${SC.error}44`, color: SC.error, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{a.level}</span>
                  <button
                    type="button"
                    data-testid={`control-btn-${a.id}`}
                    onClick={() => setOpenControlId(a.id)}
                    style={{ fontSize: 10, padding: '3px 10px', borderRadius: 4, background: 'var(--bg-elevated)', border: `1px solid ${SC.error}55`, color: SC.error, cursor: 'pointer', fontFamily: 'var(--font-mono)', fontWeight: 600 }}
                  >
                    Request
                  </button>
                </div>
              );
            })}
          </div>
          {openControlId && (() => {
            const spec = CONTROL_SPECS.find(s => s.action_id === openControlId);
            return spec ? (
              <ControlActionDialog
                spec={spec}
                onClose={() => setOpenControlId(null)}
              />
            ) : null;
          })()}
        </div>
      )}

      {tab === 'Readiness' && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
          {[
            { label: 'Live gate blocked', done: liveBlocked },
            { label: 'Fail-closed active', done: !!raw?.fail_closed },
            { label: 'Risk profile loaded', done: !!profile?.profile_name },
            { label: 'Heartbeat received', done: !!heartbeat?.finished_at },
            { label: 'No decisions with allow+live_blocked=false', done: decisions.filter(d => d.risk_action === 'allow' && !d.live_blocked).length === 0 },
          ].map(({ label, done }) => (
            <div key={label} className="glass" style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px' }}>
              <span style={{ fontSize: 13, color: done ? SC.ok : SC.warn, fontWeight: 700 }}>{done ? '✓' : '○'}</span>
              <span style={{ fontSize: 12, color: done ? 'var(--text-primary)' : 'var(--text-muted)' }}>{label}</span>
              <span style={{ marginLeft: 'auto', fontSize: 10, fontFamily: 'var(--font-mono)', color: done ? SC.ok : SC.warn }}>{done ? 'PASS' : 'PENDING'}</span>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
