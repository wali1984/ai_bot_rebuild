import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { relativeAge } from '../../data/adminFieldRegistry';

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

interface ServiceRow { id: string; name: string; status: string; detail?: string; version?: string | null; decisions_total?: number; symbol_count?: number; data_coverage?: number | null; cuda_active?: boolean; allowed_run_types?: string[]; }
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
    <div data-testid="admin-overview-page" style={{ display: 'flex', flexDirection: 'column', gap: 18 }}>

      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: 8, flexWrap: 'wrap' }}>
        <div>
          <h1 style={{ margin: 0, fontSize: 18, fontWeight: 700 }}>Overview</h1>
          <p style={{ margin: '3px 0 0', fontSize: 12, color: 'var(--text-muted)' }}>Global operational status — services, incidents, and system health</p>
        </div>
        <FreshnessBadge status={ov.freshness_status} lagMs={ov.lag_ms} />
      </div>

      {/* Stat tiles */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 10 }}>
        {[
          { label: 'LIVE GATE', value: d?.live_gate?.replace(/_/g, ' ') || '—', accent: d?.live_blocked !== false ? SC.error : SC.ok },
          { label: 'SYMBOLS', value: String(pipelineSvc?.symbol_count ?? d?.pipeline?.symbol_count ?? '—') },
          { label: 'MARKET STREAM', value: stream?.status?.toUpperCase() || '—', accent: sColor(stream?.status) },
          { label: 'INCIDENTS', value: String(incidents.length), accent: incidents.length > 0 ? SC.error : SC.ok },
          { label: 'LIVE TRADING', value: sd?.live_trading_enabled ? 'ENABLED' : 'BLOCKED', accent: sd?.live_trading_enabled ? SC.error : SC.warn },
        ].map(({ label, value, accent }) => (
          <div key={label} style={{ padding: '10px 14px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)', display: 'flex', flexDirection: 'column', gap: 3 }}>
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

      {/* Service rows */}
      <div>
        <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 8 }}>Service Health</div>
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
          {loading && !d ? (
            <div style={{ padding: '12px 14px', color: 'var(--text-muted)', fontSize: 13 }}>Loading services…</div>
          ) : (
            <>
              {services.length > 0 ? services.map(svc => (
                <div key={svc.id} data-testid={`service-row-${svc.id}`} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
                  <Dot status={svc.status} />
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                      <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{svc.name}</span>
                      {svc.detail && <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{svc.detail}</span>}
                    </div>
                    <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 3 }}>
                      {svc.id === 'trainer' && svc.data_coverage != null && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>coverage {svc.data_coverage.toFixed(1)}%</span>}
                      {svc.id === 'trainer' && <span style={{ fontSize: 10, color: svc.cuda_active ? SC.ok : SC.warn }}>CUDA {svc.cuda_active ? 'ON' : 'OFF'}</span>}
                      {svc.id === 'risk-gateway' && svc.decisions_total != null && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{svc.decisions_total.toLocaleString()} decisions</span>}
                      {svc.id === 'pipeline' && svc.symbol_count != null && <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>{svc.symbol_count} symbols</span>}
                    </div>
                  </div>
                  {svc.version && <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', maxWidth: 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', flexShrink: 0 }}>{svc.version}</span>}
                  <Pill label={svc.status.toUpperCase()} color={sColor(svc.status)} />
                </div>
              )) : (
                /* Fallback using /api/v2/status dimensions */
                [
                  { id: 'market', name: 'Market Stream', status: stream?.status === 'stale' ? 'warn' : stream?.status === 'current' ? 'ok' : 'unknown', detail: stream?.source || '—' },
                  { id: 'auto', name: 'Automation', status: sd?.status_dimensions?.automation === 'DEGRADED' ? 'warn' : 'unknown', detail: sd?.status_dimensions?.automation || '—' },
                  { id: 'execution', name: 'Execution', status: sd?.status_dimensions?.execution === 'RESTRICTED' ? 'warn' : 'unknown', detail: sd?.status_dimensions?.execution || '—' },
                ].map(svc => (
                  <div key={svc.id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
                    <Dot status={svc.status} />
                    <span style={{ flex: 1, fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{svc.name}</span>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{svc.detail}</span>
                    <Pill label={svc.status.toUpperCase()} color={sColor(svc.status)} />
                  </div>
                ))
              )}
              {/* Market stream row from /status */}
              {services.length > 0 && stream && (
                <div style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '9px 14px', borderRadius: 6, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
                  <Dot status={stream.status === 'stale' ? 'warn' : stream.status || 'unknown'} />
                  <div style={{ flex: 1 }}>
                    <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>Market Stream</span>
                    <span style={{ marginLeft: 10, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{stream.source}</span>
                  </div>
                  {stream.lag_ms != null && <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{Math.round(stream.lag_ms / 1000)}s lag</span>}
                  <Pill label={(stream.status || 'unknown').toUpperCase()} color={sColor(stream.status)} />
                </div>
              )}
            </>
          )}
        </div>
      </div>

      {/* Detail panels */}
      {d && (d.trainer || d.risk || d.pipeline) && (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 12 }}>
          {d.trainer && (
            <div style={{ padding: '14px 16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>ML / Trainer</div>
              <KV label="State" value={d.trainer.state || '—'} accent={d.trainer.state?.includes('ACTIVE') ? SC.ok : SC.warn} mono />
              <KV label="Checkpoint" value={d.trainer.checkpoint_id ? `…${d.trainer.checkpoint_id.slice(-12)}` : '—'} mono />
              <KV label="Coverage" value={d.trainer.data_coverage != null ? `${d.trainer.data_coverage.toFixed(2)}%` : '—'} mono />
              <KV label="CUDA" value={d.trainer.cuda_active ? 'ACTIVE' : 'NO'} accent={d.trainer.cuda_active ? SC.ok : SC.warn} mono />
            </div>
          )}
          {d.risk && (
            <div style={{ padding: '14px 16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
              <div style={{ fontSize: 10, fontWeight: 700, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.1em', marginBottom: 10 }}>Risk Gateway</div>
              <KV label="Profile" value={d.risk.profile_name || '—'} />
              <KV label="Live Blocked" value={d.risk.live_blocked !== false ? 'YES' : 'NO'} accent={d.risk.live_blocked !== false ? SC.error : SC.ok} mono />
              <KV label="Decisions" value={(d.risk.decisions_total ?? 0).toLocaleString()} mono />
              <KV label="Heartbeat" value={relativeAge(d.risk.last_at)} />
            </div>
          )}
          {d.pipeline && (
            <div style={{ padding: '14px 16px', borderRadius: 8, background: 'var(--bg-elevated)', border: '1px solid var(--admin-border)' }}>
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
