import meta from './meta';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { healthStatusTone } from '../../components/system/healthStatus';
import { SystemResourcesPanel } from '../../components/system/SystemResourcesPanel';

const AUTH_HEALTH_ENDPOINT = '/api/auth/health';
const DATA_HEALTH_ENDPOINT = '/api/v2/data-health';

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

interface IngestorRollup {
  schema_version?: string;
  overall_status?: string;
  stream_present?: Record<string, boolean>;
  all_core_streams_present?: boolean;
  provider_health?: Record<string, { status?: string | null; age_seconds?: number | null; freshness?: string | null }>;
  provider_count?: number;
  active_provider_count?: number;
  stale_provider_count?: number;
  stale_providers?: string[];
}

interface DataHealthPayload {
  overall?: string;
  surfaces?: HealthSurface[];
  count?: number;
  ingestors?: IngestorRollup;
}

interface AuthHealthPayload {
  schema_version?: string;
  status?: string;
  freshness_status?: string;
  data_quality_status?: string;
  auth_store_backend?: string | null;
  durable_user_store_configured?: boolean | null;
  production_ready?: boolean | null;
  login_endpoint_available?: boolean | null;
  live_gate?: string | null;
  places_real_order?: boolean | null;
  routes_to_live?: boolean | null;
  contains_secret_values?: boolean | null;
  raw_credential_value_exposed?: boolean | null;
  session_security?: {
    status?: string | null;
    cookie_httponly?: boolean | null;
    cookie_secure?: boolean | null;
    cookie_samesite?: string | null;
    revocation_store_kind?: string | null;
    auth_user_store?: {
      backend?: string | null;
      production_ready?: boolean | null;
      missing_fields?: string[];
    } | null;
    revocation_store?: {
      backend?: string | null;
      production_ready?: boolean | null;
      missing_fields?: string[];
    } | null;
  } | null;
  warnings?: string[];
}

function fmtLag(ms: number | null | undefined): string {
  if (ms == null || !Number.isFinite(ms)) return '—';
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`;
  return `${Math.round(ms / 60_000)}m`;
}

function yesNo(value: boolean | null | undefined): string {
  if (value == null) return 'not reported';
  return value ? 'yes' : 'no';
}

function statusLabel(value: string | null | undefined): string {
  return value ? value.replace(/_/g, ' ') : 'not reported';
}

function TruthCell({ label, value, tone = 'neutral' }: { label: string; value: string; tone?: 'ok' | 'warn' | 'error' | 'neutral' }): JSX.Element {
  const color = tone === 'ok'
    ? 'var(--buy,#10b981)'
    : tone === 'warn'
      ? '#f59e0b'
      : tone === 'error'
        ? 'var(--sell,#ef4444)'
        : 'var(--text-primary)';
  return (
    <div style={{ padding: '8px 10px', borderRadius: 7, background: 'var(--bg-base)', border: '1px solid var(--line-soft)' }}>
      <div style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: 12, color, fontFamily: 'var(--font-mono)', fontWeight: 700, overflowWrap: 'anywhere' }}>{value}</div>
    </div>
  );
}

function RuntimeAuthPanel(): JSX.Element {
  const auth = useRealtimeResource<AuthHealthPayload>({
    url: AUTH_HEALTH_ENDPOINT,
    source: AUTH_HEALTH_ENDPOINT,
    source_type: 'api',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });
  const data = auth.envelope.data;
  const tone = healthStatusTone(data?.status ?? auth.envelope.freshness_status);
  const authStore = data?.session_security?.auth_user_store;
  const revocationStore = data?.session_security?.revocation_store;
  const liveBlocked = data?.places_real_order !== true && data?.routes_to_live !== true;

  return (
    <section data-testid="system-auth-runtime-panel" style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-panel)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', borderBottom: '1px solid var(--line-soft)', flexWrap: 'wrap' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Auth, Backend, Redis</h2>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            Login reachability, session hardening, Redis-backed feed health, and live-gate safety from canonical read-only contracts.
          </p>
        </div>
        <span style={{ padding: '3px 9px', borderRadius: 5, background: tone.bg, color: tone.color, fontSize: 11, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
          {tone.label}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(175px, 1fr))', gap: 8, padding: 12 }}>
        <TruthCell label="Auth endpoint" value={AUTH_HEALTH_ENDPOINT} tone={data?.status === 'ok' ? 'ok' : 'warn'} />
        <TruthCell label="Backend session" value={data?.login_endpoint_available ? 'login endpoint online' : 'login endpoint unavailable'} tone={data?.login_endpoint_available ? 'ok' : 'error'} />
        <TruthCell label="Auth backend" value={statusLabel(data?.auth_store_backend ?? authStore?.backend)} tone={data?.durable_user_store_configured ? 'ok' : 'warn'} />
        <TruthCell label="Redis feed" value={`${DATA_HEALTH_ENDPOINT} · redis_live surfaces`} tone="ok" />
        <TruthCell label="Cookie security" value={`httpOnly ${yesNo(data?.session_security?.cookie_httponly)} · secure ${yesNo(data?.session_security?.cookie_secure)}`} tone={data?.session_security?.cookie_httponly && data.session_security.cookie_secure ? 'ok' : 'warn'} />
        <TruthCell label="Revocation store" value={statusLabel(data?.session_security?.revocation_store_kind ?? revocationStore?.backend)} tone={revocationStore?.production_ready ? 'ok' : 'warn'} />
        <TruthCell label="Live gate" value={statusLabel(data?.live_gate ?? 'blocked_human_only')} tone={liveBlocked ? 'ok' : 'error'} />
        <TruthCell label="Secrets exposed" value={data?.contains_secret_values || data?.raw_credential_value_exposed ? 'yes' : 'no'} tone={data?.contains_secret_values || data?.raw_credential_value_exposed ? 'error' : 'ok'} />
      </div>
      <div style={{ padding: '0 12px 12px', fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        Data health source: {DATA_HEALTH_ENDPOINT}. Production auth readiness: {data?.production_ready ? 'ready' : 'not ready'}.
        {data?.warnings?.length ? ` Missing: ${data.warnings.slice(0, 4).join(', ')}` : ''}
      </div>
    </section>
  );
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

const STREAM_LABELS: Record<string, string> = {
  candles: 'Candles / OHLCV',
  orderbook_features: 'Orderbook features',
  trade_tape: 'Trade tape',
  funding_oi: 'Funding / OI',
  liquidation_levels: 'Liquidation levels',
  ta_full: 'TA-Lib (full)',
  feature_snapshots: 'Feature snapshots',
};

function IngestorRollupPanel({ ingestors, loading }: { ingestors: IngestorRollup | undefined; loading: boolean }): JSX.Element {
  const overall = ingestors?.overall_status ?? (loading ? 'connecting' : 'unknown');
  const tone = healthStatusTone(
    overall === 'HEALTHY' ? 'ok'
      : overall === 'SOME_PROVIDERS_STALE' ? 'warn'
        : overall === 'DEGRADED_MISSING_CORE_STREAM' ? 'error'
          : overall,
  );
  const streams = ingestors?.stream_present ?? {};
  const streamKeys = Object.keys(STREAM_LABELS);
  // stale_provider_count only counts hard-STALE; derive an honest "not healthy" set
  // from provider_health so DEGRADED / unknown / null providers (e.g. moralis)
  // are not hidden behind "Stale providers: none".
  const providerHealth = ingestors?.provider_health ?? {};
  const providerEntries = Object.entries(providerHealth);
  const isHealthy = (v: { status?: string | null; freshness?: string | null }): boolean => {
    const st = (v.status ?? '').toUpperCase();
    const fr = (v.freshness ?? '').toLowerCase();
    if (!st) return false;
    if (['STALE', 'DEGRADED', 'OFFLINE', 'ERROR', 'DOWN', 'MISSING'].some((t) => st.includes(t))) return false;
    if (['stale', 'unknown', 'offline', 'degraded'].includes(fr)) return false;
    return ['ACTIVE', 'READY', 'GREEN', 'OK', 'HEALTHY'].some((t) => st.includes(t));
  };
  const unhealthy = providerEntries.filter(([, v]) => !isHealthy(v)).map(([name]) => name);
  const providerTone = (v: { status?: string | null; freshness?: string | null }): 'ok' | 'warn' | 'error' | 'neutral' => {
    if (isHealthy(v)) return 'ok';
    const st = (v.status ?? '').toUpperCase();
    if (!st || st.includes('OFFLINE') || st.includes('DOWN') || st.includes('ERROR') || st.includes('STALE')) return 'error';
    return 'warn';
  };
  return (
    <section style={{ border: '1px solid var(--border)', borderRadius: 8, background: 'var(--bg-panel)', overflow: 'hidden' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, padding: '12px 14px', borderBottom: '1px solid var(--line-soft)' }}>
        <div>
          <h2 style={{ margin: 0, fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Ingestors &amp; Providers</h2>
          <p style={{ margin: '2px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>
            Consolidated data-stream presence and provider freshness roll-up (read-only).
          </p>
        </div>
        <span style={{ padding: '3px 9px', borderRadius: 5, background: tone.bg, color: tone.color, fontSize: 11, fontWeight: 800, fontFamily: 'var(--font-mono)' }}>
          {String(overall).replace(/_/g, ' ')}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, padding: 12 }}>
        <TruthCell label="Core streams" value={ingestors?.all_core_streams_present ? 'all present' : 'missing core'} tone={ingestors?.all_core_streams_present ? 'ok' : 'error'} />
        <TruthCell label="Active providers" value={String(ingestors?.active_provider_count ?? '—')} tone={(ingestors?.active_provider_count ?? 0) > 0 ? 'ok' : 'warn'} />
        <TruthCell label="Providers tracked" value={String(ingestors?.provider_count ?? '—')} tone="neutral" />
        <TruthCell
          label="Unhealthy providers"
          value={unhealthy.length ? `${unhealthy.length}: ${unhealthy.slice(0, 4).join(', ')}` : 'none'}
          tone={unhealthy.length ? 'warn' : 'ok'}
        />
      </div>
      {providerEntries.length > 0 && (
        <div style={{ padding: '0 12px 8px' }}>
          <div style={{ fontSize: 11, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', margin: '4px 0 6px' }}>Per-provider health</div>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8 }}>
            {providerEntries.map(([name, v]) => {
              const age = v.age_seconds;
              const ageStr = age == null ? '' : age < 60 ? ` · ${Math.round(age)}s` : ` · ${Math.round(age / 60)}m`;
              return (
                <TruthCell
                  key={name}
                  label={name.replace(/_/g, ' ')}
                  value={`${(v.status ?? 'unknown').toString().toLowerCase()}${ageStr}`}
                  tone={providerTone(v)}
                />
              );
            })}
          </div>
        </div>
      )}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, padding: '0 12px 12px' }}>
        {streamKeys.map((key) => {
          const present = streams[key] === true;
          return (
            <TruthCell key={key} label={STREAM_LABELS[key]} value={present ? 'flowing' : 'absent'} tone={present ? 'ok' : 'error'} />
          );
        })}
      </div>
    </section>
  );
}

function DataFeedsPanel(): JSX.Element {
  const health = useRealtimeResource<DataHealthPayload>({
    url: DATA_HEALTH_ENDPOINT,
    source: DATA_HEALTH_ENDPOINT,
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
    <div style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>
    <IngestorRollupPanel ingestors={data?.ingestors} loading={health.loading} />
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
    </div>
  );
}

export default function SystemHealthPage(): JSX.Element {
  return (
    <div data-testid="system-health-page" style={{ padding: '20px 24px', display: 'flex', flexDirection: 'column', gap: 18 }}>
      <div>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 800, color: 'var(--text-primary)' }}>{meta.title}</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{meta.description}</p>
      </div>
      <RuntimeAuthPanel />
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
