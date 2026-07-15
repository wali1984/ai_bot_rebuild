import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface Decision {
  name: string | null;
  unit: string | null;
  category: string | null;
  criticality: string | null;
  action: string | null;
  active_state: string | null;
  reason: string | null;
  heartbeat_age_seconds: number | null;
  max_staleness_seconds: number | null;
}

interface SelfHealingStatus {
  available: boolean;
  generated_utc?: string;
  supervisor_stale?: boolean;
  supervisor_age_seconds?: number | null;
  component_count?: number;
  healthy_count?: number;
  unhealthy_count?: number;
  action_counts?: Record<string, number>;
  restarted_units?: string[];
  decisions: Decision[];
}

const ENDPOINT = '/api/v2/self-healing/status';

// Map a supervisor action -> a traffic-light tone.
function toneFor(action: string | null, activeState: string | null): 'ok' | 'warn' | 'error' {
  const a = (action ?? '').toUpperCase();
  if (a === 'OK') return 'ok';
  if (a.startsWith('SKIP_DELIBERATELY') || a === 'SKIP_NOT_ENABLED' || a === 'SKIP_NOT_INSTALLED' || a === 'SKIP_DENYLISTED') {
    return 'ok';
  }
  if (a === 'RESTART_DEAD' || a === 'RESTART_STALE' || a === 'STALE_PENDING') return 'warn';
  if (a === 'SKIP_RATE_LIMITED' || a.startsWith('ALERT')) return 'error';
  const s = (activeState ?? '').toLowerCase();
  if (s === 'active' || s === 'activating' || s === 'reloading') return 'ok';
  return 'error';
}

const TONE_COLOR: Record<'ok' | 'warn' | 'error', string> = {
  ok: 'var(--ok, #10b981)',
  warn: 'var(--warn, #f59e0b)',
  error: 'var(--error, #ef4444)',
};

/**
 * Self-healing monitor: every non-ingestor service the supervisor watches, with a
 * traffic-light status derived from its heal action. Green = healthy, amber =
 * auto-recovering, red = down after auto-heal / alerting.
 */
export function SelfHealingPanel(): JSX.Element {
  const { envelope, loading } = useRealtimeResource<SelfHealingStatus>({
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
  const decisions = data?.decisions ?? [];
  const sorted = [...decisions].sort((a, b) => {
    const ta = toneFor(a.action, a.active_state);
    const tb = toneFor(b.action, b.active_state);
    const rank = { error: 0, warn: 1, ok: 2 } as const;
    if (rank[ta] !== rank[tb]) return rank[ta] - rank[tb];
    return String(a.name).localeCompare(String(b.name));
  });

  const healthy = data?.healthy_count ?? decisions.filter((d) => toneFor(d.action, d.active_state) === 'ok').length;
  const total = data?.component_count ?? decisions.length;
  const down = data?.unhealthy_count ?? 0;

  return (
    <section
      data-testid="self-healing-panel"
      style={{
        border: '1px solid var(--border, #2a2a2a)',
        borderRadius: 'var(--radius, 8px)',
        background: 'var(--bg-panel, #131313)',
        padding: 14,
      }}
    >
      <header style={{ display: 'flex', alignItems: 'baseline', gap: 12, flexWrap: 'wrap', marginBottom: 10 }}>
        <h3 style={{ margin: 0, fontSize: 15 }}>Self-Healing Services</h3>
        <span data-testid="self-healing-counts" style={{ fontSize: 12, color: 'var(--text-muted, #999)' }}>
          {healthy}/{total} healthy
          {down > 0 ? (
            <span style={{ color: TONE_COLOR.error, fontWeight: 700 }}>{` · ${down} down`}</span>
          ) : null}
          {data?.supervisor_stale ? (
            <span style={{ color: TONE_COLOR.warn }}>{' · supervisor stale'}</span>
          ) : null}
        </span>
        {loading && !data ? <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>loading…</span> : null}
      </header>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))',
          gap: 8,
        }}
      >
        {sorted.map((d) => {
          const tone = toneFor(d.action, d.active_state);
          const color = TONE_COLOR[tone];
          return (
            <div
              key={d.unit ?? d.name ?? Math.random().toString(36)}
              data-testid={`self-healing-row-${d.name ?? 'unknown'}`}
              data-tone={tone}
              title={d.reason ?? undefined}
              style={{
                display: 'flex',
                flexDirection: 'column',
                gap: 3,
                padding: '8px 10px',
                borderRadius: 6,
                border: `1px solid ${color}`,
                background: `color-mix(in oklch, ${color} 8%, transparent)`,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                <span style={{ fontSize: 13, fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {d.name}
                </span>
                <span
                  style={{
                    fontSize: 10,
                    fontWeight: 700,
                    color,
                    border: `1px solid ${color}`,
                    borderRadius: 999,
                    padding: '1px 6px',
                    textTransform: 'uppercase',
                    whiteSpace: 'nowrap',
                  }}
                >
                  {tone === 'ok' ? 'OK' : tone === 'warn' ? 'HEALING' : 'DOWN'}
                </span>
              </div>
              <span style={{ fontSize: 11, color: 'var(--text-muted, #999)' }}>
                {d.category}
                {d.criticality === 'critical' ? ' · critical' : ''}
                {d.heartbeat_age_seconds != null ? ` · ${Math.round(d.heartbeat_age_seconds)}s` : ''}
              </span>
            </div>
          );
        })}
      </div>
    </section>
  );
}
