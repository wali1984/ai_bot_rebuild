import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';
import { DangerousControlPanel } from '../../components/controls/DangerousControlPanel';
import meta from './meta';

const FILLS_ENDPOINT = '/api/v2/admin/execution/fills';
const RISK_ENDPOINT = '/api/v2/risk/status';
const TABS = ['Fills', 'Gate', 'Controls'] as const;
type Tab = typeof TABS[number];
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

interface Fill {
  fill_id?: string; symbol?: string; side?: string; qty?: number;
  price?: number; mode?: string; filled_at?: string; source?: string;
}
interface FillsPayload {
  mode?: string; live_gate?: string; fills?: Fill[];
  fill_count?: number; paper_mode?: boolean; generated_at?: string;
}
interface RiskPayload {
  live_blocked?: boolean; live_gate?: string;
  data?: { latest_gateway_result?: { risk_action?: string; risk_reason_code?: string; generated_at?: string; }; heartbeat?: { decisions_processed_total?: number } };
}

const LOCK_CONTROLS = [
  { label: 'Switch Paper → Live', level: 'L5' },
  { label: 'Increase Max Position Size', level: 'L4' },
  { label: 'Add Live API Keys', level: 'L5' },
];

export default function AdminExecutionPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Fills');
  const { envelope: fe, loading } = useRealtimeResource<FillsPayload>({ url: FILLS_ENDPOINT, source: 'admin-execution', pollIntervalMs: 15_000 });
  const { envelope: re } = useRealtimeResource<RiskPayload>({ url: RISK_ENDPOINT, source: 'admin-exec-risk', pollIntervalMs: 20_000 });
  const f = fe.data;
  const r = re.data;
  const fills = f?.fills || [];
  const gateBlocked = r?.live_blocked !== false || f?.live_gate?.includes('blocked');

  return (
    <div data-testid="admin-execution-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Execution</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Paper fills, execution gate, and mode controls</p>
        </div>
        <FreshnessBadge status={fe.freshness_status} lagMs={fe.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {[
          { label: 'MODE', value: (f?.mode || 'PAPER').toUpperCase(), accent: f?.mode === 'live' ? SC.error : SC.info },
          { label: 'GATE', value: (f?.live_gate || r?.live_gate || '—').replace(/_/g, ' '), accent: gateBlocked ? SC.error : SC.ok },
          { label: 'FILLS', value: String(fills.length || f?.fill_count || 0) },
          { label: 'PAPER MODE', value: f?.paper_mode !== false ? 'YES' : 'NO', accent: f?.paper_mode !== false ? SC.ok : SC.error },
        ].map(({ label, value, accent }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 15, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Mode banner */}
      <div data-testid="execution-mode-banner" style={{
        padding: '10px 14px', borderRadius: 6,
        background: gateBlocked ? `${SC.error}10` : `${SC.ok}10`,
        border: `1px solid ${gateBlocked ? SC.error : SC.ok}44`,
        display: 'flex', alignItems: 'center', gap: 12, fontFamily: 'var(--font-mono)', fontSize: 12, flexWrap: 'wrap',
      }}>
        <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>Mode: {(f?.mode || 'paper').toUpperCase()}</span>
        <span style={{ color: 'var(--text-muted)' }}>|</span>
        <span style={{ color: gateBlocked ? SC.error : SC.ok }}>Gate: {(f?.live_gate || r?.live_gate || 'blocked_human_only').toUpperCase()}</span>
        {r?.data?.heartbeat?.decisions_processed_total != null && (
          <span style={{ marginLeft: 'auto', color: 'var(--text-muted)', fontSize: 11 }}>{r.data.heartbeat.decisions_processed_total.toLocaleString()} risk decisions</span>
        )}
      </div>

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

      {tab === 'Fills' && (
        loading && !f ? <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading fills…</div> :
        fills.length > 0 ? (
          <div style={{ overflowX: 'auto' }}>
            <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
              <thead>
                <tr style={{ borderBottom: '1px solid var(--admin-border)' }}>
                  {['Fill ID', 'Symbol', 'Side', 'Qty', 'Price', 'Mode', 'Filled At'].map(h => (
                    <th key={h} style={{ padding: '7px 10px', textAlign: 'left', fontSize: 10, color: 'var(--text-muted)', fontWeight: 600, fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em', whiteSpace: 'nowrap' }}>{h}</th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {fills.slice(0, 30).map((fill, i) => (
                  <tr key={fill.fill_id ?? i} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                    <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-muted)' }}>{fill.fill_id ? `…${fill.fill_id.slice(-8)}` : '—'}</td>
                    <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', fontWeight: 600 }}>{fill.symbol ?? '—'}</td>
                    <td style={{ padding: '7px 10px' }}>
                      <span style={{ padding: '2px 7px', borderRadius: 4, background: fill.side === 'buy' ? `${SC.ok}20` : `${SC.error}20`, color: fill.side === 'buy' ? SC.ok : SC.error, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)' }}>
                        {(fill.side ?? '—').toUpperCase()}
                      </span>
                    </td>
                    <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)' }}>{fill.qty ?? '—'}</td>
                    <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)' }}>{fill.price?.toFixed(4) ?? '—'}</td>
                    <td style={{ padding: '7px 10px', fontSize: 10, color: SC.info, fontFamily: 'var(--font-mono)' }}>{(fill.mode ?? 'paper').toUpperCase()}</td>
                    <td style={{ padding: '7px 10px', color: 'var(--text-muted)', fontSize: 11 }}>{fill.filled_at ? relativeAge(fill.filled_at) : '—'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div style={{ padding: '12px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-muted)', fontSize: 12 }}>
            No fills recorded. Paper mode active — fills appear here after risk gateway allows paper executions.
          </div>
        )
      )}

      {tab === 'Gate' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Execution Gate State</div>
            {[
              ['Mode', (f?.mode || 'paper').toUpperCase()],
              ['Gate', f?.live_gate || r?.live_gate || '—'],
              ['Live Blocked', r?.live_blocked !== false ? 'YES' : 'NO'],
              ['Paper Mode', f?.paper_mode !== false ? 'YES' : 'NO'],
              ['Generated', f?.generated_at ? relativeAge(f.generated_at) : '—'],
            ].map(([l, v]) => (
              <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--line-soft)', gap: 8 }}>
                <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{l}</span>
                <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{v}</span>
              </div>
            ))}
          </div>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Latest Risk Decision</div>
            {r?.data?.latest_gateway_result ? (
              [
                ['Action', r.data.latest_gateway_result.risk_action?.toUpperCase() || '—'],
                ['Reason', r.data.latest_gateway_result.risk_reason_code || '—'],
                ['At', relativeAge(r.data.latest_gateway_result.generated_at)],
              ].map(([l, v]) => (
                <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--line-soft)', gap: 8 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{l}</span>
                  <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{v}</span>
                </div>
              ))
            ) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No risk decision data</div>}
          </div>
        </div>
      )}

      {tab === 'Controls' && (
        <div>
          <div style={{ padding: '10px 14px', marginBottom: 12, borderRadius: 6, background: `${SC.error}10`, border: `1px solid ${SC.error}33`, fontSize: 12, color: SC.error, fontFamily: 'var(--font-mono)' }}>
            DANGEROUS CONTROLS — Disabled. Human approval gate required.
          </div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
            {LOCK_CONTROLS.map(({ label, level }) => (
              <div key={label} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: `${SC.error}08`, border: `1px solid ${SC.error}22` }}>
                <span style={{ width: 6, height: 6, borderRadius: '50%', background: SC.error, display: 'inline-block', flexShrink: 0 }} />
                <span style={{ flex: 1, fontSize: 12, color: 'var(--text-primary)', fontWeight: 500 }}>{label}</span>
                <span style={{ fontSize: 10, padding: '2px 6px', borderRadius: 4, background: `${SC.error}22`, border: `1px solid ${SC.error}44`, color: SC.error, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{level}</span>
                <span style={{ fontSize: 10, padding: '2px 8px', borderRadius: 4, background: '#1a1a2a', border: '1px solid #333', color: SC.unknown, fontFamily: 'var(--font-mono)' }}>BLOCKED</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
