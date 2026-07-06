import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { SystemResourcesPanel } from '../../components/system/SystemResourcesPanel';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

interface RouteEntry { path: string; surface: string; owner: string; expected: boolean; }
interface DataSurface { surface: string; endpoint: string; source_type: string; owner: string; }
interface RealtimeStream { name: string; type: string; status: string; endpoint?: string; interval_ms?: number; }
interface RoutesData { routes: RouteEntry[]; total: number; timestamp: string; }
interface SurfacesData { surfaces: DataSurface[]; total: number; connected: number; unavailable: number; timestamp: string; }
interface StreamsData { streams: RealtimeStream[]; total: number; active: number; timestamp: string; }
interface BuildStatus { dist_exists: boolean; index_exists: boolean; status: string; timestamp: string; }

function statusColor(s: string): string {
  const l = s.toLowerCase();
  if (l === 'active' || l === 'built' || l === 'ok') return 'var(--buy)';
  if (l === 'check_required' || l === 'partial') return 'var(--warn)';
  return 'var(--sell)';
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

export default function MonitorCenterPage(): JSX.Element {
  const routes = useRealtimeResource<RoutesData>({ url: '/api/v2/admin/monitoring/routes', source: '/api/v2/admin/monitoring/routes', source_type: 'websocket', pollIntervalMs: 60_000, staleThresholdMs: 180_000, mode: 'read_only' });
  const surfaces = useRealtimeResource<SurfacesData>({ url: '/api/v2/admin/monitoring/data-surfaces', source: '/api/v2/admin/monitoring/data-surfaces', source_type: 'websocket', pollIntervalMs: 60_000, staleThresholdMs: 180_000, mode: 'read_only' });
  const streams = useRealtimeResource<StreamsData>({ url: '/api/v2/admin/monitoring/realtime-streams', source: '/api/v2/admin/monitoring/realtime-streams', source_type: 'websocket', pollIntervalMs: 30_000, staleThresholdMs: 90_000, mode: 'read_only' });
  const build = useRealtimeResource<BuildStatus>({ url: '/api/v2/admin/monitoring/build-status', source: '/api/v2/admin/monitoring/build-status', source_type: 'websocket', pollIntervalMs: 60_000, staleThresholdMs: 180_000, mode: 'read_only' });

  const rData = routes.envelope.data;
  const sData = surfaces.envelope.data;
  const stData = streams.envelope.data;
  const bData = build.envelope.data;

  return (
    <div
      data-testid="page-monitor-center"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 64 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Monitor Center</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
          Page coverage · Data coverage · Realtime stream health · Route health · Test &amp; build status
        </p>
      </div>

      {/* Summary KPIs */}
      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
        <KV label="Routes" value={routes.loading ? '…' : String(rData?.total ?? '—')} />
        <KV label="Data Surfaces" value={surfaces.loading ? '…' : String(sData?.total ?? '—')} />
        <KV label="Connected" value={surfaces.loading ? '…' : String(sData?.connected ?? '—')} color="var(--buy)" />
        <KV label="Unavailable" value={surfaces.loading ? '…' : String(sData?.unavailable ?? '—')} color={sData?.unavailable ? 'var(--sell)' : 'var(--text-muted)'} />
        <KV label="Active Streams" value={streams.loading ? '…' : String(stData?.active ?? '—')} color="var(--buy)" />
        <KV label="Build" value={build.loading ? '…' : (bData?.status ?? '—')} color={bData?.status === 'built' ? 'var(--buy)' : 'var(--sell)'} />
      </div>

      {/* System resources: host + GPU utilisation, realtime over WebSocket */}
      <div style={{ padding: '20px 24px 0' }}>
        <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>System Resources</h2>
        <SystemResourcesPanel />
      </div>

      {/* Page / Route coverage */}
      <div style={{ padding: '20px 24px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Page Coverage ({rData?.total ?? 0})</h2>
          <FreshnessBadge status={routes.envelope.freshness_status} lagMs={routes.envelope.lag_ms} />
        </div>
        {routes.loading && !rData ? <LoadingSkeleton rows={5} /> : (
          rData?.routes?.length ? (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-elevated)' }}>
                    {['Path', 'Surface', 'Owner', 'OK'].map((h) => (
                      <th key={h} style={{ padding: '8px 12px', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {rData.routes.map((r, i) => (
                    <tr key={r.path} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                      <td style={{ padding: '8px 12px', fontWeight: 600 }}>{r.path}</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{r.surface}</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{r.owner}</td>
                      <td style={{ padding: '8px 12px', color: r.expected ? 'var(--buy)' : 'var(--sell)', fontWeight: 700 }}>{r.expected ? '✓' : '✗'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: 0 }}>Route stream connecting.</p>
        )}
      </div>

      {/* Data surfaces */}
      <div style={{ padding: '20px 24px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Data Surfaces ({sData?.total ?? 0})</h2>
          <FreshnessBadge status={surfaces.envelope.freshness_status} lagMs={surfaces.envelope.lag_ms} />
        </div>
        {surfaces.loading && !sData ? <LoadingSkeleton rows={5} /> : (
          sData?.surfaces?.length ? (
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-elevated)' }}>
                    {['Surface', 'Endpoint', 'Source Type', 'Owner'].map((h) => (
                      <th key={h} style={{ padding: '8px 12px', fontSize: 10, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {sData.surfaces.map((s, i) => (
                    <tr key={s.surface} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                      <td style={{ padding: '8px 12px', fontWeight: 600 }}>{s.surface}</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-secondary)' }}>{s.endpoint}</td>
                      <td style={{ padding: '8px 12px', color: statusColor(s.source_type === 'unavailable' ? 'unavailable' : 'active'), fontWeight: s.source_type === 'unavailable' ? 700 : 400 }}>{s.source_type}</td>
                      <td style={{ padding: '8px 12px', color: 'var(--text-muted)' }}>{s.owner}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: 0 }}>Data surface stream connecting.</p>
        )}
      </div>

      {/* Realtime streams */}
      <div style={{ padding: '20px 24px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Realtime Streams ({stData?.total ?? 0})</h2>
          <FreshnessBadge status={streams.envelope.freshness_status} lagMs={streams.envelope.lag_ms} />
        </div>
        {streams.loading && !stData ? <LoadingSkeleton rows={3} /> : (
          stData?.streams?.length ? (
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(260px, 1fr))', gap: 10 }}>
              {stData.streams.map((s) => (
                <div key={s.name} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '12px 14px' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 4 }}>
                    <span style={{ fontWeight: 600, fontSize: 12, color: 'var(--text-primary)' }}>{s.name}</span>
                    <span style={{ fontSize: 10, fontWeight: 700, color: statusColor(s.status) }}>{s.status.toUpperCase()}</span>
                  </div>
                  <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>{s.type}{s.interval_ms ? ` · ${s.interval_ms}ms` : ''}</p>
                </div>
              ))}
            </div>
          ) : <p style={{ color: 'var(--text-muted)', fontSize: 13, margin: 0 }}>Realtime stream registry connecting.</p>
        )}
      </div>

      {/* Build status */}
      <div style={{ padding: '20px 24px 0' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10 }}>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Build Status</h2>
          <SourceBadge sourceType={build.envelope.source_type} source={build.envelope.source} endpoint={build.envelope.endpoint} />
        </div>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
          <KV label="Status" value={build.loading ? '…' : (bData?.status ?? '—')} color={bData?.status === 'built' ? 'var(--buy)' : 'var(--sell)'} />
          <KV label="Dist Exists" value={build.loading ? '…' : (bData?.dist_exists ? 'Yes' : 'No')} color={bData?.dist_exists ? 'var(--buy)' : 'var(--sell)'} />
          <KV label="Index.html" value={build.loading ? '…' : (bData?.index_exists ? 'Yes' : 'No')} color={bData?.index_exists ? 'var(--buy)' : 'var(--sell)'} />
        </div>
      </div>
    </div>
  );
}
