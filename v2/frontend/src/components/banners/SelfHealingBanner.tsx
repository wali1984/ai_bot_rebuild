import { useRealtimeResource } from '../../hooks/useRealtimeResource';

/** One unhealthy service surfaced by the self-healing supervisor. */
export interface SelfHealingService {
  name: string | null;
  unit: string | null;
  category: string | null;
  criticality: string | null;
  action: string | null;
  active_state: string | null;
  reason: string | null;
  heartbeat_age_seconds: number | null;
}

export interface SelfHealingBannerPayload {
  show: boolean;
  severity: 'ok' | 'warn' | 'critical' | string;
  count: number;
  services: SelfHealingService[];
  message: string;
}

export interface SelfHealingStatusPayload {
  available: boolean;
  supervisor_stale?: boolean;
  banner: SelfHealingBannerPayload;
}

const ENDPOINT = '/api/v2/self-healing/status';

/**
 * Global red banner: renders ONLY when a service is still down after the
 * self-healing supervisor's auto-recovery attempts (rate-limited restarts
 * exhausted, alert-mode, not-active-while-enabled) or the supervisor itself is
 * stale. Names the affected services. Renders nothing when everything is healthy.
 */
export function SelfHealingBanner(): JSX.Element | null {
  const { envelope } = useRealtimeResource<SelfHealingStatusPayload>({
    url: ENDPOINT,
    source: ENDPOINT,
    source_type: 'websocket',
    pollIntervalMs: 20_000,
    staleThresholdMs: 90_000,
    initialFetch: true,
    initialFetchWhenStreaming: true,
    httpFallback: true,
    enabled: true,
    mode: 'read_only',
  });

  const data = envelope.data;
  const banner = data?.banner;
  if (!banner || !banner.show || banner.severity === 'ok') {
    return null;
  }

  const critical = banner.severity === 'critical';
  const accent = critical ? 'var(--sell, #ef4444)' : 'var(--warn, #f59e0b)';
  const bg = critical
    ? 'color-mix(in oklch, var(--sell, #ef4444) 14%, transparent)'
    : 'color-mix(in oklch, var(--warn, #f59e0b) 14%, transparent)';

  return (
    <section
      role="alert"
      aria-live="assertive"
      data-testid="self-healing-banner"
      data-severity={banner.severity}
      data-down-count={String(banner.count)}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: 8,
        padding: '10px 14px',
        margin: '0 0 12px 0',
        border: `1px solid ${accent}`,
        borderLeft: `4px solid ${accent}`,
        borderRadius: 'var(--radius, 8px)',
        background: bg,
        color: 'var(--text, inherit)',
        fontFamily: 'var(--font-mono, ui-monospace, monospace)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap' }}>
        <span
          data-testid="self-healing-banner-chip"
          style={{
            fontWeight: 700,
            fontSize: 12,
            letterSpacing: 0.5,
            color: accent,
            border: `1px solid ${accent}`,
            borderRadius: 999,
            padding: '2px 10px',
            textTransform: 'uppercase',
          }}
        >
          {critical ? 'SERVICE DOWN' : 'DEGRADED'}
        </span>
        <span data-testid="self-healing-banner-message" style={{ fontSize: 13 }}>
          {banner.message}
        </span>
      </div>
      {banner.services.length > 0 ? (
        <ul
          data-testid="self-healing-banner-services"
          style={{
            listStyle: 'none',
            margin: 0,
            padding: 0,
            display: 'flex',
            flexWrap: 'wrap',
            gap: 6,
          }}
        >
          {banner.services.map((svc) => (
            <li
              key={svc.unit ?? svc.name ?? Math.random().toString(36)}
              data-testid={`self-healing-down-${svc.name ?? 'unknown'}`}
              data-criticality={svc.criticality ?? 'normal'}
              title={svc.reason ?? undefined}
              style={{
                fontSize: 12,
                padding: '2px 8px',
                borderRadius: 6,
                border: `1px solid ${accent}`,
                background: 'transparent',
                whiteSpace: 'nowrap',
              }}
            >
              <strong>{svc.name}</strong>
              <span style={{ opacity: 0.7 }}>{` · ${svc.action ?? svc.active_state ?? ''}`}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </section>
  );
}
