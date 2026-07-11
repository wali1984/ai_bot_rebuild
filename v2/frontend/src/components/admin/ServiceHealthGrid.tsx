import type { AdminService, ServiceStatus } from '../../types/adminData';

const STATUS_COLOR: Record<ServiceStatus, string> = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  error: 'var(--error)',
  unknown: 'var(--text-muted)',
};

const STATUS_BG: Record<ServiceStatus, string> = {
  ok: 'color-mix(in oklch, var(--ok) 8%, var(--bg-elevated))',
  warn: 'color-mix(in oklch, var(--warn) 8%, var(--bg-elevated))',
  error: 'color-mix(in oklch, var(--error) 10%, var(--bg-elevated))',
  unknown: 'var(--bg-elevated)',
};

function relativeAge(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.now() - Date.parse(iso);
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${Math.floor(sec / 3600)}h ago`;
}

interface Props {
  services: AdminService[];
  loading?: boolean;
}

export function ServiceHealthGrid({ services, loading = false }: Props): JSX.Element {
  if (loading) {
    return (
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(180px, 100%), 1fr))', gap: 10 }}>
        {Array.from({ length: 6 }).map((_, i) => (
          <div
            key={i}
            style={{
              height: 80,
              borderRadius: 8,
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
            }}
          />
        ))}
      </div>
    );
  }

  if (!services.length) {
    return (
      <div style={{ padding: '20px 0', color: 'var(--text-muted)', fontSize: 13, textAlign: 'center' }}>
        No service data available.
      </div>
    );
  }

  return (
    <div
      data-testid="service-health-grid"
      style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(180px, 100%), 1fr))', gap: 10 }}
    >
      {services.map((svc) => {
        const color = STATUS_COLOR[svc.status] ?? 'var(--text-muted)';
        const bg = STATUS_BG[svc.status] ?? 'var(--bg-elevated)';
        return (
          <div
            key={svc.id}
            data-testid={`service-health-${svc.name}`}
            style={{
              padding: '12px 14px',
              borderRadius: 8,
              background: bg,
              border: `1px solid ${color}44`,
              display: 'flex',
              flexDirection: 'column',
              gap: 6,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 6 }}>
              <span style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                {svc.name}
              </span>
              <span
                style={{
                  display: 'inline-block',
                  padding: '2px 7px',
                  borderRadius: 4,
                  background: color,
                  color: '#fff',
                  fontSize: 10,
                  fontFamily: 'var(--font-mono)',
                  fontWeight: 700,
                  flexShrink: 0,
                }}
              >
                {svc.status.toUpperCase()}
              </span>
            </div>
            <div style={{ fontSize: 11, color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              owner: {svc.owner}
            </div>
            <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {relativeAge(svc.heartbeat_at)}
              {svc.lag_ms != null && (
                <span style={{ marginLeft: 8 }}>{svc.lag_ms}ms lag</span>
              )}
              {svc.error_count > 0 && (
                <span style={{ marginLeft: 8, color: 'var(--error)' }}>{svc.error_count} err</span>
              )}
            </div>
          </div>
        );
      })}
    </div>
  );
}
