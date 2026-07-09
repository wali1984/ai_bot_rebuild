import meta from './meta';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { healthStatusTone } from '../../components/system/healthStatus';
import { SystemResourcesPanel } from '../../components/system/SystemResourcesPanel';

interface HealthSurface {
  name: string;
  endpoint: string;
  status: string;
  description?: string;
  actual_payload_count?: number | null;
  source_type?: string | null;
  stale?: boolean | null;
  lag_ms?: number | null;
  last_success?: string | null;
  missing_fields?: string[];
}

interface DataHealthPayload {
  overall?: string;
  surfaces?: HealthSurface[];
  count?: number;
}

function fmtLag(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

function SurfaceRow({ surface }: { surface: HealthSurface }): JSX.Element {
  const tone = healthStatusTone(surface.status);
  const missing = surface.missing_fields ?? [];
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))',
        gap: 12,
        alignItems: 'center',
        padding: '10px 12px',
        borderBottom: '1px solid var(--line-soft)',
      }}
    >
      <div style={{ minWidth: 0 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <span style={{ width: 7, height: 7, borderRadius: '50%', background: tone.color, flexShrink: 0 }} />
          <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>{surface.name}</strong>
          <span style={{ padding: '2px 7px', borderRadius: 5, background: tone.bg, color: tone.color, fontSize: 10, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
            {tone.label}
          </span>
        </div>
        <div style={{ marginTop: 3, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis' }}>
          {surface.endpoint}
        </div>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 8 }}>
        <div>
          <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Payloads</span>
          <span style={{ fontSize: 12, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{surface.actual_payload_count ?? '—'}</span>
        </div>
        <div>
          <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Lag</span>
          <span style={{ fontSize: 12, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{fmtLag(surface.lag_ms)}</span>
        </div>
        <div>
          <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase' }}>Stale</span>
          <span style={{ fontSize: 12, color: surface.stale ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)', fontFamily: 'var(--font-mono)', fontWeight: 700 }}>{surface.stale ? 'YES' : 'NO'}</span>
        </div>
      </div>
      <div style={{ minWidth: 0 }}>
        <div style={{ fontSize: 12, color: 'var(--text-secondary)' }}>{surface.description || 'Read-only feed status'}</div>
        <div style={{ marginTop: 3, fontSize: 10, color: missing.length ? '#f59e0b' : 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          {missing.length ? `missing: ${missing.slice(0, 4).join(', ')}` : surface.source_type || 'source pending'}
        </div>
      </div>
    </div>
  );
}

function DataFeedsPanel(): JSX.Element {
  const health = useRealtimeResource<DataHealthPayload>({
    url: '/api/v2/data-health',
    source: '/api/v2/data-health',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 45_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });
  const data = health.envelope.data;
  const surfaces = data?.surfaces ?? [];
  const overallTone = healthStatusTone(data?.overall ?? (health.loading ? 'connecting' : 'unknown'));

  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-panel)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', borderBottom: '1px solid var(--line-soft)' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Data Feeds</h2>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Actual payload status from the shared web/iOS read-only feed contract.</p>
        </div>
        <span style={{ padding: '3px 9px', borderRadius: 5, background: overallTone.bg, color: overallTone.color, fontSize: 11, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
          {overallTone.label}
        </span>
      </div>
      {surfaces.length > 0 ? (
        <div>{surfaces.map((surface) => <SurfaceRow key={`${surface.name}:${surface.endpoint}`} surface={surface} />)}</div>
      ) : (
        <div style={{ padding: 14, fontSize: 13, color: 'var(--text-muted)' }}>
          {health.error || 'Connecting data-health feed…'}
        </div>
      )}
    </section>
  );
}

export default function SystemHealthPage(): JSX.Element {
  return (
    <div data-testid="system-health-page" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: 'var(--text-primary)' }}>{meta.title}</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{meta.description}</p>
      </div>
      <DataFeedsPanel />
      <section>
        <h2 style={{ margin: '0 0 10px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>
          System Resources
        </h2>
        <SystemResourcesPanel />
      </section>
    </div>
  );
}
