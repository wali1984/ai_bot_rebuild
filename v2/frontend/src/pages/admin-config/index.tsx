import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';
import { DangerousControlPanel } from '../../components/controls/DangerousControlPanel';
import meta from './meta';

const CONFIG_ENDPOINT = '/api/v2/config/current';
const PIPELINE_ENDPOINT = '/api/v2/pipeline/status';
const TABS = ['Current', 'Pipeline', 'Locks'] as const;
type Tab = typeof TABS[number];
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

interface ConfigPayload { version?: string; environment?: string; last_changed_at?: string; last_changed_by?: string; config?: Record<string, unknown>; }
interface PipelinePayload { live_gate?: string; schema_version?: string; generated_utc?: string; symbols?: string[]; allowed_run_types?: string[]; live_gate_runtime_source?: string; trader_execution_enabled?: boolean; exchange_action_taken?: boolean; }

const LOCK_CONTROLS = [
  { label: 'Enable Live Trading', level: 'L5' },
  { label: 'Enable ADJUST_LEVERAGE', level: 'L4' },
  { label: 'Switch Paper → Live', level: 'L5' },
  { label: 'Enable CROSS Margin', level: 'L5' },
];

export default function AdminConfigPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Current');
  const { envelope: ce, loading: cLoading } = useRealtimeResource<ConfigPayload>({ url: CONFIG_ENDPOINT, source: 'admin-config', pollIntervalMs: 60_000 });
  const { envelope: pe } = useRealtimeResource<PipelinePayload>({ url: PIPELINE_ENDPOINT, source: 'admin-config-pipeline', pollIntervalMs: 30_000 });
  const cfg = ce.data;
  const pipeline = pe.data;

  return (
    <div data-testid="admin-config-page" style={{ display: 'flex', flexDirection: 'column', gap: 18, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Configuration</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>System config, pipeline settings, and dangerous-control locks</p>
        </div>
        <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
          <FreshnessBadge status={ce.freshness_status} lagMs={ce.lag_ms} />
        </div>
      </div>

      {/* Config header chips */}
      {(cfg || pipeline) && (
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap' }}>
          {cfg?.version && <span style={{ padding: '3px 10px', borderRadius: 5, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>v{cfg.version}</span>}
          {(cfg?.environment || 'paper') && <span style={{ padding: '3px 10px', borderRadius: 5, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 11, fontFamily: 'var(--font-mono)', color: SC.info }}>{cfg?.environment || 'paper'}</span>}
          {pipeline?.live_gate && <span style={{ padding: '3px 10px', borderRadius: 5, background: `${SC.error}15`, border: `1px solid ${SC.error}33`, fontSize: 11, fontFamily: 'var(--font-mono)', color: SC.error, fontWeight: 700 }}>gate: {pipeline.live_gate}</span>}
          {cfg?.last_changed_by && <span style={{ padding: '3px 10px', borderRadius: 5, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 11, color: 'var(--text-muted)' }}>by: {cfg.last_changed_by}</span>}
          {cfg?.last_changed_at && <span style={{ padding: '3px 10px', borderRadius: 5, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 11, color: 'var(--text-muted)' }}>{relativeAge(cfg.last_changed_at)}</span>}
        </div>
      )}

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

      {tab === 'Current' && (
        cLoading && !cfg ? (
          <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading config…</div>
        ) : cfg?.config ? (
          <pre data-testid="config-json" style={{ margin: 0, padding: 14, borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', fontSize: 11, fontFamily: 'var(--font-mono)', overflow: 'auto', maxHeight: 480, color: 'var(--text-primary)' }}>
            {JSON.stringify(cfg.config, null, 2)}
          </pre>
        ) : (
          <div style={{ padding: '14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-muted)', marginBottom: 4 }}>Config endpoint not wired</div>
            <div style={{ fontSize: 11, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>{CONFIG_ENDPOINT}</div>
            <div style={{ marginTop: 8, fontSize: 11, color: 'var(--text-muted)' }}>Pipeline gate + schema data available in Pipeline tab.</div>
          </div>
        )
      )}

      {tab === 'Pipeline' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Pipeline Config</div>
            {pipeline ? (
              [
                ['Schema Version', pipeline.schema_version || '—'],
                ['Generated', pipeline.generated_utc || '—'],
                ['Live Gate', pipeline.live_gate || '—'],
                ['Gate Source', pipeline.live_gate_runtime_source || '—'],
                ['Execution Enabled', pipeline.trader_execution_enabled ? 'YES' : 'NO'],
                ['Exchange Action', pipeline.exchange_action_taken ? 'YES' : 'NO'],
                ['Symbol Count', String(pipeline.symbols?.length ?? 0)],
              ].map(([l, v]) => (
                <div key={l} style={{ display: 'flex', justifyContent: 'space-between', padding: '5px 0', borderBottom: '1px solid var(--line-soft)', gap: 8 }}>
                  <span style={{ fontSize: 11, color: 'var(--text-muted)', flexShrink: 0 }}>{l}</span>
                  <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', textAlign: 'right' }}>{v}</span>
                </div>
              ))
            ) : <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>Loading pipeline config…</div>}
          </div>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Allowed Run Types</div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
              {(pipeline?.allowed_run_types || []).map(rt => (
                <div key={rt} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '6px 10px', borderRadius: 5, background: `${SC.info}10`, border: `1px solid ${SC.info}33` }}>
                  <span style={{ width: 5, height: 5, borderRadius: '50%', background: SC.info, display: 'inline-block' }} />
                  <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: SC.info }}>{rt.replace(/_/g, ' ')}</span>
                </div>
              ))}
              {!(pipeline?.allowed_run_types?.length) && <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No run types available</div>}
            </div>
          </div>
        </div>
      )}

      {tab === 'Locks' && (
        <div>
          <div style={{ padding: '10px 14px', marginBottom: 12, borderRadius: 6, background: `${SC.error}10`, border: `1px solid ${SC.error}33`, fontSize: 12, color: SC.error, fontFamily: 'var(--font-mono)' }}>
            DANGEROUS CONFIG LOCKS — All permanently disabled. Human approval + L4/L5 gate required.
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
