import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';
import { ServiceHealthGrid } from '../../components/admin';
import { SelfHealingPanel } from '../../components/admin/SelfHealingPanel';
import { SelfHealingBanner } from '../../components/banners/SelfHealingBanner';
import type { AdminService, ServiceStatus } from '../../types/adminData';

const VALID_STATUSES: ServiceStatus[] = ['ok', 'warn', 'error', 'unknown'];

const OVERVIEW_ENDPOINT = '/api/v2/admin/overview';
const STATUS_ENDPOINT = '/api/v2/status';

const SC = {
  ok: '#22c55e', warn: '#f59e0b', error: '#ef4444',
  unknown: '#6b7280', info: '#60a5fa',
};

function sColor(s?: string | null): string {
  switch ((s || '').toLowerCase()) {
    case 'ok': case 'active': case 'allow': case 'current': return SC.ok;
    case 'warn': case 'warning': case 'degraded': case 'rest_fallback': return SC.warn;
    case 'error': case 'block': case 'blocked': case 'failed': case 'stale': return SC.error;
    default: return SC.unknown;
  }
}

function Pill({ label, color }: { label: string; color: string }) {
  return (
    <span style={{
      display: 'inline-block', padding: '2px 7px', borderRadius: 4,
      background: `${color}22`, border: `1px solid ${color}55`,
      color, fontSize: 10, fontWeight: 700, fontFamily: 'var(--font-mono)', letterSpacing: '0.06em',
    }}>{label}</span>
  );
}

function Dot({ status }: { status: string }) {
  const c = sColor(status);
  return <span style={{ display: 'inline-block', width: 8, height: 8, borderRadius: '50%', background: c, flexShrink: 0 }} />;
}

function KV({ label, value, accent, mono }: { label: string; value: string; accent?: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12, padding: '3px 0', borderBottom: '1px solid var(--line-soft)' }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ fontSize: 12, color: accent || 'var(--text-primary)', fontFamily: mono ? 'var(--font-mono)' : undefined, textAlign: 'right' }}>{value}</span>
    </div>
  );
}

interface ServiceRow {
  id?: string; name: string; status: string; detail?: string; version?: string | null;
  // AdminService compat fields from API
  heartbeat_at?: string | null; last_checked_at?: string | null; owner?: string;
  // Extra per-service fields (not in AdminService)
  decisions_total?: number; symbol_count?: number; data_coverage?: number | null;
  cuda_active?: boolean; allowed_run_types?: string[];
}

function toAdminService(svc: ServiceRow): AdminService {
  return {
    id: svc.id ?? svc.name,
    name: svc.name,
    status: VALID_STATUSES.includes(svc.status as ServiceStatus) ? svc.status as ServiceStatus : 'unknown',
    heartbeat_at: svc.heartbeat_at ?? svc.last_checked_at ?? null,
    lag_ms: null,
    error_count: 0,
    warning_count: 0,
    owner: svc.owner ?? '—',
    version: svc.version ?? null,
  };
}
interface OverviewPayload {
  generated_at?: string; live_gate?: string; live_blocked?: boolean;
  services?: ServiceRow[]; active_incidents?: unknown[];
  intelligence_health?: string; orchestration_health?: string; risk_status?: string;
  trainer?: { state?: string; checkpoint_id?: string; cuda_active?: boolean; data_coverage?: number | null };
  risk?: { profile_name?: string; live_blocked?: boolean; decisions_total?: number; last_at?: string | null };
  pipeline?: { live_gate?: string; symbol_count?: number; allowed_run_types?: string[] };
}
interface StatusPayload {
  status_dimensions?: { market_data?: string; automation?: string; execution?: string };
  market_stream?: { status?: string; lag_ms?: number | null; last_frame_at?: string | null; source?: string };
  warnings?: string[]; live_trading_enabled?: boolean; paper_mode?: boolean;
}

export default function AdminOverviewPage(): JSX.Element {
  const { envelope: ov, loading } = useRealtimeResource<OverviewPayload>({ url: OVERVIEW_ENDPOINT, source: 'admin-overview', pollIntervalMs: 15_000 });
  const { envelope: sv } = useRealtimeResource<StatusPayload>({ url: STATUS_ENDPOINT, source: 'admin-status', pollIntervalMs: 20_000 });

  const d = ov.data;
  const sd = sv.data;
  const services = d?.services || [];
  const incidents = d?.active_incidents || [];
  const stream = sd?.market_stream;
  const warnings = sd?.warnings || [];
  const pipelineSvc = services.find(s => s.id === 'pipeline');
  const trainerSvc = services.find(s => s.id === 'trainer');
  const riskSvc = services.find(s => s.id === 'risk-gateway');

  return (
    <div data-testid="admin-overview-page" style={{ display: 'flex', flexDirection: 'column', gap: 18, background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>

      {/* Global red banner: a service down after auto-heal, or supervisor stale */}
      <SelfHealingBanner />

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Overview</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Global operational status — services, incidents, and system health</p>
        </div>
        <FreshnessBadge status={ov.freshness_status} lagMs={ov.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(min(150px, 100%), 1fr))', gap: 10 }}>
        {[
          { label: 'LIVE GATE', value: d?.live_gate?.replace(/_/g, ' ') || '—', accent: d?.live_blocked !== false ? SC.error : SC.ok },
          { label: 'SYMBOLS', value: String(pipelineSvc?.symbol_count ?? d?.pipeline?.symbol_count ?? '—') },
          { label: 'MARKET STREAM', value: stream?.status?.toUpperCase() || '—', accent: sColor(stream?.status) },
          { label: 'INCIDENTS', value: String(incidents.length), accent: incidents.length > 0 ? SC.error : SC.ok },
          { label: 'LIVE TRADING', value: sd?.live_trading_enabled ? 'ENABLED' : 'BLOCKED', accent: sd?.live_trading_enabled ? SC.error : SC.warn },
        ].map(({ label, value, accent }) => (
          <div key={label} className="glass" style={{ padding: '10px 14px', display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.1em' }}>{label}</span>
            <span style={{ fontSize: 16, fontWeight: 700, color: accent || 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{value}</span>
          </div>
        ))}
      </div>

      {/* Warnings */}
      {warnings.length > 0 && (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
          {warnings.map((w, i) => (
            <div key={i} style={{ padding: '7px 12px', borderRadius: 6, background: `${SC.warn}15`, border: `1px solid ${SC.warn}44`, color: SC.warn, fontSize: 12, fontFamily: 'var(--font-mono)' }}>
              ⚠ {w}
            </div>
          ))}
        </div>
      )}

      {/* Service Health — renders ServiceHealthGrid with testIds service-health-{name} */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>Service Health</div>
        <ServiceHealthGrid
          services={services.map(toAdminService)}
          loading={loading && !d}
        />
        {/* Market stream row from /api/v2/status — shown alongside service grid */}
        {services.length > 0 && stream && (
          <div className="glass" style={{ marginTop: 5, display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px' }}>
            <Dot status={stream.status === 'stale' ? 'warn' : stream.status || 'unknown'} />
            <div style={{ flex: 1 }}>
              <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Market Stream</span>
              <span style={{ marginLeft: 10, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{stream.source}</span>
            </div>
            {stream.lag_ms != null && <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{Math.round(stream.lag_ms / 1000)}s lag</span>}
            <Pill label={(stream.status || 'unknown').toUpperCase()} color={sColor(stream.status)} />
          </div>
        )}
      </div>

      {/* Self-healing supervisor: all non-ingestor services, auto-heal status */}
      <SelfHealingPanel />

      {/* Detail panels */}
      {d && (d.trainer || d.risk || d.pipeline) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          {d.trainer && (
            <div className="glass" style={{ padding: '14px 16px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>ML / Trainer</div>
              <KV label="State" value={d.trainer.state || '—'} accent={d.trainer.state?.includes('ACTIVE') ? SC.ok : SC.warn} mono />
              <KV label="Checkpoint" value={d.trainer.checkpoint_id ? `…${d.trainer.checkpoint_id.slice(-12)}` : '—'} mono />
              <KV label="Coverage" value={d.trainer.data_coverage != null ? `${d.trainer.data_coverage.toFixed(2)}%` : '—'} mono />
              <KV label="CUDA" value={d.trainer.cuda_active ? 'ACTIVE' : 'NO'} accent={d.trainer.cuda_active ? SC.ok : SC.warn} mono />
            </div>
          )}
          {d.risk && (
            <div className="glass" style={{ padding: '14px 16px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Risk Gateway</div>
              <KV label="Profile" value={d.risk.profile_name || '—'} />
              <KV label="Live Blocked" value={d.risk.live_blocked !== false ? 'YES' : 'NO'} accent={d.risk.live_blocked !== false ? SC.error : SC.ok} mono />
              <KV label="Decisions" value={(d.risk.decisions_total ?? 0).toLocaleString()} mono />
              <KV label="Heartbeat" value={relativeAge(d.risk.last_at)} />
            </div>
          )}
          {d.pipeline && (
            <div className="glass" style={{ padding: '14px 16px' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Pipeline</div>
              <KV label="Gate" value={d.pipeline.live_gate?.replace(/_/g, ' ') || '—'} accent={d.pipeline.live_gate?.includes('blocked') ? SC.error : SC.ok} mono />
              <KV label="Symbols" value={`${d.pipeline.symbol_count ?? 0} active`} mono />
              <div style={{ marginTop: 8, display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                {(d.pipeline.allowed_run_types || []).map(rt => <Pill key={rt} label={rt.replace(/_/g, ' ')} color={SC.info} />)}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Incidents */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>Incidents</div>
        {incidents.length === 0 ? (
          <div style={{ padding: '8px 14px', borderRadius: 6, background: `${SC.ok}11`, border: `1px solid ${SC.ok}33`, color: SC.ok, fontSize: 12, fontFamily: 'var(--font-mono)' }}>
            ✓ No active incidents
          </div>
        ) : incidents.map((_, i) => (
          <div key={i} style={{ padding: '8px 14px', borderRadius: 6, background: `${SC.error}11`, border: `1px solid ${SC.error}33`, color: SC.error, fontSize: 12 }}>Incident {i + 1}</div>
        ))}
      </div>
    </div>
  );
}
