import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';
import { DANGEROUS_CONTROLS } from '../../constants/dangerousControls';

const RISK_ENDPOINT = '/api/v2/risk/status';
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

const LOCK_ACTIONS = [
  { id: 'enable_live_trading' as const, label: 'Enable Live Trading', level: 'L5' },
  { id: 'increase_leverage' as const, label: 'Increase Leverage', level: 'L4' },
  { id: 'disable_kill_switch' as const, label: 'Disable Kill Switch', level: 'L5' },
  { id: 'disable_mandatory_stop' as const, label: 'Disable Mandatory Stop', level: 'L4' },
];

function ActionRow({ id, label, level }: { id: string; label: string; level: string }) {
  const ctrl = DANGEROUS_CONTROLS[id as keyof typeof DANGEROUS_CONTROLS];
  const displayLabel = ctrl?.label ?? label;
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: `${SC.error}08`, border: `1px solid ${SC.error}22` }}>
      <span style={{ width: 6, height: 6, borderRadius: '50%', background: SC.error, display: 'inline-block', flexShrink: 0 }} />
      <span style={{ flex: 1, fontSize: 12, color: 'var(--text-primary)', fontWeight: 500 }}>{displayLabel}</span>
      <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: `${SC.error}22`, border: `1px solid ${SC.error}44`, color: SC.error, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{level}</span>
      <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: '#1a1a2a', border: '1px solid #333', color: SC.unknown, fontFamily: 'var(--font-mono)' }}>BLOCKED — requires approval</span>
    </div>
  );
}

export default function AdminRiskPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Decisions');
  const { envelope, loading } = useRealtimeResource<RiskPayload>({ url: RISK_ENDPOINT, source: 'admin-risk', pollIntervalMs: 10_000 });
  const raw = envelope.data;
  const data = raw?.data ?? raw;
  const decisions = raw?.recent_decisions || [];
  const heartbeat = (data as RiskPayload)?.heartbeat ?? raw?.heartbeat;
  const profile = (data as RiskPayload)?.active_profile ?? raw?.active_profile;
  const liveBlocked = raw?.live_blocked !== false;
  const decisionsTotal = heartbeat?.decisions_processed_total ?? 0;

  return (
    <div data-testid="admin-risk-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

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
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
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
          <div style={{ padding: '12px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-muted)', fontSize: 12 }}>
            No recent decisions in Redis. Risk gateway heartbeat: {heartbeat?.finished_at ? relativeAge(heartbeat.finished_at) : 'no data'}.
          </div>
        )
      )}

      {tab === 'Profile' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
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
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
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
            DANGEROUS CONTROLS — All permanently disabled. Human approval + L4/L5 gate required.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {LOCK_ACTIONS.map(a => <ActionRow key={a.id} {...a} />)}
          </div>
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
            <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
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
