import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';

const SURFACES_ENDPOINT = '/api/v2/admin/monitoring/data-surfaces';
const PIPELINE_ENDPOINT = '/api/v2/pipeline/status';

const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', unknown: '#6b7280', info: '#60a5fa' };

function Chip({ label, color }: { label: string; color: string }) {
  return <span style={{ padding: '2px 7px', borderRadius: 4, background: `${color}20`, border: `1px solid ${color}44`, color, fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{label}</span>;
}

interface DataSurface {
  surface?: string; endpoint?: string; source_type?: string; owner?: string;
  status?: string; lag_ms?: number | null; last_record_at?: string | null;
}
interface SurfacesPayload { surfaces?: DataSurface[]; generated_at?: string; }
interface PipelinePayload { live_gate?: string; symbols?: string[]; allowed_run_types?: string[]; }

const TABS = ['Sources', 'Pipeline', 'Monitors'] as const;
type Tab = typeof TABS[number];

export default function AdminDataPage(): JSX.Element {
  const [tab, setTab] = useState<Tab>('Sources');
  const { envelope: se, loading } = useRealtimeResource<SurfacesPayload>({ url: SURFACES_ENDPOINT, source: 'admin-data', pollIntervalMs: 30_000 });
  const { envelope: pe } = useRealtimeResource<PipelinePayload>({ url: PIPELINE_ENDPOINT, source: 'admin-pipeline', pollIntervalMs: 30_000 });

  const surfaces = se.data?.surfaces || [];
  const pipeline = pe.data;

  return (
    <div data-testid="admin-data-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Data</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Pipeline health — data surfaces, ingestors, and monitors</p>
        </div>
        <FreshnessBadge status={se.freshness_status} lagMs={se.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
        {[
          { label: 'DATA SURFACES', value: String(surfaces.length) },
          { label: 'PIPELINE GATE', value: pipeline?.live_gate?.replace(/_/g, ' ') || '—', accent: pipeline?.live_gate?.includes('blocked') ? SC.error : SC.ok },
          { label: 'SYMBOLS', value: String(pipeline?.symbols?.length ?? '—') },
          { label: 'RUN TYPES', value: String(pipeline?.allowed_run_types?.length ?? '—') },
        ].map(({ label, value, accent }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      <div style={{ display: 'flex', gap: 2, borderBottom: '1px solid var(--line-soft)' }}>
        {TABS.map(t => (
          <button key={t} type="button" onClick={() => setTab(t)} style={{
            padding: '7px 16px', border: 'none', background: 'none', cursor: 'pointer', fontSize: 12,
            fontWeight: tab === t ? 700 : 400, color: tab === t ? 'var(--text-primary)' : 'var(--text-muted)',
            borderBottom: tab === t ? '2px solid var(--admin-accent)' : '2px solid transparent',
          }}>{t}</button>
        ))}
      </div>

      {tab === 'Sources' && (
        loading && !se.data ? <div style={{ color: 'var(--text-muted)', fontSize: 12, padding: '12px 0' }}>Loading data surfaces…</div> :
        surfaces.length > 0 ? (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {surfaces.map((s, i) => (
              <div key={s.surface || i} style={{ display: 'grid', gridTemplateColumns: '1fr auto auto auto', gap: 12, alignItems: 'center', padding: '10px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
                <div>
                  <div style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{s.surface || '—'}</div>
                  <div style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 2 }}>{s.endpoint || '—'}</div>
                </div>
                <Chip label={s.source_type || 'api'} color={SC.info} />
                <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{s.owner || '—'}</span>
                <Chip label={(s.status || 'pending').toUpperCase()} color={s.status === 'ok' ? SC.ok : s.status === 'error' ? SC.error : SC.warn} />
              </div>
            ))}
          </div>
        ) : (
          <div style={{ padding: '14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', color: 'var(--text-muted)', fontSize: 12 }}>
            No data surfaces returned from <span style={{ fontFamily: 'var(--font-mono)', color: SC.info }}>{SURFACES_ENDPOINT}</span>
          </div>
        )
      )}

      {tab === 'Pipeline' && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Gate & Control</div>
            <div style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: pipeline?.live_gate?.includes('blocked') ? SC.error : SC.ok, marginBottom: 8 }}>
              {pipeline?.live_gate?.toUpperCase() || '—'}
            </div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {(pipeline?.allowed_run_types || []).map(rt => <Chip key={rt} label={rt.replace(/_/g, ' ')} color={SC.info} />)}
            </div>
          </div>
          <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
            <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Symbol Universe ({pipeline?.symbols?.length ?? 0})</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, maxHeight: 200, overflowY: 'auto' }}>
              {(pipeline?.symbols || []).slice(0, 40).map(s => (
                <span key={s} style={{ padding: '2px 6px', borderRadius: 3, background: 'var(--bg-panel)', border: '1px solid var(--line-soft)', fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{s}</span>
              ))}
              {(pipeline?.symbols?.length ?? 0) > 40 && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>+{(pipeline?.symbols?.length ?? 0) - 40} more</span>}
            </div>
          </div>
        </div>
      )}

      {tab === 'Monitors' && (
        <div style={{ padding: '16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
          <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            Monitor registry available via <span style={{ fontFamily: 'var(--font-mono)', color: SC.info }}>/api/v2/admin/monitoring/routes</span>. Wire monitor heartbeats here to show active/broken/unused monitor scripts.
          </div>
        </div>
      )}
    </div>
  );
}
