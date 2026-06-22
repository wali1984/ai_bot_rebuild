import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types (matched to actual /api/v2/orchestrator/status response) ─────────

interface OrchestratorHeartbeat {
  worker_id?: string;
  started_at?: string;
  finished_at?: string;
  predictions_seen?: number;
  proposals_arbitrated?: number;
  classification?: string;
  live_gate?: string;
  approves_live?: boolean;
  cannot_bypass_risk_gateway?: boolean;
}

interface Proposal {
  proposal_id?: string;
  symbol?: string;
  side?: string;
  confidence_calibrated?: number;
  expected_move_after_cost_bps?: number;
  freshness_seconds?: number;
  model_version?: string;
  source?: string;
  generated_utc?: string;
}

interface BucketWinner {
  symbol?: string;
  side?: string;
  winner_proposal_id?: string;
  winner_confidence_calibrated?: number;
  winner_expected_move_after_cost_bps?: number;
  winner_freshness_seconds?: number;
  winner_model_version?: string;
  considered_proposal_ids?: string[];
  score?: number;
}

interface OrchestratorDecision {
  schema_version?: string;
  generated_utc?: string;
  considered_count?: number;
  bucket_winners?: BucketWinner[];
  deconflict_reason?: string;
  deconflict_selected_side?: string;
  deconflict_selected_signal_id?: string;
  held_by_paper_fill_gate?: boolean;
  held_by_paper_fill_gate_count?: number;
  skipped_malformed_prediction_count?: number;
  stale_proposal_ids?: string[];
}

interface OrchestratorStatus {
  heartbeat?: OrchestratorHeartbeat;
  last_proposals?: Proposal[];
  last_decisions?: OrchestratorDecision[];
}

// ─── Helpers ─────────────────────────────────────────────────────────────────

function sideColor(s: string | null | undefined): string {
  const l = (s ?? '').toLowerCase();
  if (l === 'long' || l === 'buy') return '#26c281';
  if (l === 'short' || l === 'sell') return '#ef5350';
  return 'var(--text-muted)';
}

function confColor(c: number | null | undefined): string {
  if (c == null) return 'var(--text-muted)';
  if (c >= 0.7) return '#26c281';
  if (c >= 0.66) return '#f59e0b';
  return '#ef5350';
}

function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  return (Math.abs(n) <= 1 ? n * 100 : n).toFixed(1) + '%';
}

function fmtBps(n: number | null | undefined): string {
  if (n == null) return '—';
  return (n >= 0 ? '+' : '') + n.toFixed(0) + ' bps';
}

function fmtAge(iso: string | null | undefined): string {
  if (!iso) return '—';
  const d = new Date(iso);
  if (isNaN(d.getTime())) return '—';
  const sec = (Date.now() - d.getTime()) / 1000;
  if (sec < 60) return `${Math.round(sec)}s ago`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m ago`;
  return `${(sec / 3600).toFixed(1)}h ago`;
}

function Chip({ label, tone }: { label: string; tone: 'ok' | 'warn' | 'block' | 'neutral' }): JSX.Element {
  const map = {
    ok: { bg: 'rgba(38,194,129,0.12)', color: '#26c281', border: 'rgba(38,194,129,0.3)' },
    warn: { bg: 'rgba(245,158,11,0.12)', color: '#f59e0b', border: 'rgba(245,158,11,0.3)' },
    block: { bg: 'rgba(239,83,80,0.12)', color: '#ef5350', border: 'rgba(239,83,80,0.3)' },
    neutral: { bg: 'rgba(255,255,255,0.05)', color: 'var(--text-muted)', border: 'rgba(255,255,255,0.1)' },
  }[tone];
  return (
    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 10, fontWeight: 700, color: map.color, background: map.bg, border: `1px solid ${map.border}`, fontFamily: 'var(--font-mono)', display: 'inline-block' }}>
      {label.replace(/_/g, ' ')}
    </span>
  );
}

function KV({ label, value, valueColor }: { label: string; value: React.ReactNode; valueColor?: string }): JSX.Element {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
      <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      <span style={{ fontSize: 12, fontWeight: 700, fontFamily: 'var(--font-mono)', color: valueColor ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

function SectionHead({ title }: { title: string }): JSX.Element {
  return (
    <div style={{ fontSize: 10, fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 8 }}>{title}</div>
  );
}

function Card({ children, accent }: { children: React.ReactNode; accent?: string }): JSX.Element {
  return (
    <div style={{ background: 'rgba(0,0,0,0.2)', borderRadius: 8, padding: '12px 14px', border: `1px solid ${accent ?? 'rgba(255,255,255,0.06)'}`, marginBottom: 14 }}>
      {children}
    </div>
  );
}

// ─── Proposals feed ───────────────────────────────────────────────────────────

function ProposalsFeed({ proposals }: { proposals: Proposal[] }): JSX.Element {
  if (!proposals.length) {
    return <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '8px 0' }}>No proposals in current window.</div>;
  }
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 280, overflowY: 'auto' }}>
      {proposals.slice(0, 15).map((p, i) => (
        <div key={p.proposal_id ?? i} style={{ display: 'grid', gridTemplateColumns: '90px 48px 56px 72px 80px 1fr', gap: 6, alignItems: 'center', padding: '6px 10px', background: 'rgba(255,255,255,0.02)', borderRadius: 6, border: '1px solid rgba(255,255,255,0.04)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
          <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{p.symbol ?? '—'}</span>
          <span style={{ fontWeight: 700, color: sideColor(p.side) }}>{(p.side ?? '—').toUpperCase()}</span>
          <span style={{ color: confColor(p.confidence_calibrated) }}>{fmtPct(p.confidence_calibrated)}</span>
          <span style={{ color: (p.expected_move_after_cost_bps ?? 0) < 0 ? '#ef5350' : '#26c281' }}>{fmtBps(p.expected_move_after_cost_bps)}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>{p.freshness_seconds != null ? p.freshness_seconds.toFixed(0) + 's fresh' : '—'}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 9, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{(p.model_version ?? '').slice(0, 28)}</span>
        </div>
      ))}
    </div>
  );
}

// ─── Bucket winners table ─────────────────────────────────────────────────────

function BucketWinnersTable({ winners }: { winners: BucketWinner[] }): JSX.Element {
  if (!winners.length) return <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>No bucket winners.</div>;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 4, maxHeight: 260, overflowY: 'auto' }}>
      {winners.map((w, i) => (
        <div key={w.winner_proposal_id ?? i} style={{ display: 'grid', gridTemplateColumns: '90px 52px 60px 80px 56px 1fr', gap: 6, alignItems: 'center', padding: '6px 10px', background: 'rgba(38,194,129,0.04)', borderRadius: 6, border: '1px solid rgba(38,194,129,0.1)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
          <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{w.symbol ?? '—'}</span>
          <span style={{ fontWeight: 700, color: sideColor(w.side) }}>{(w.side ?? '—').toUpperCase()}</span>
          <span style={{ color: confColor(w.winner_confidence_calibrated) }}>{fmtPct(w.winner_confidence_calibrated)}</span>
          <span style={{ color: (w.winner_expected_move_after_cost_bps ?? 0) < 0 ? '#ef5350' : '#26c281' }}>{fmtBps(w.winner_expected_move_after_cost_bps)}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 10 }}>Score: {w.score?.toFixed(3) ?? '—'}</span>
          <span style={{ color: 'var(--text-muted)', fontSize: 9 }}>{(w.considered_proposal_ids ?? []).length} considered</span>
        </div>
      ))}
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────────

export default function OrchestratorAdminPage(): JSX.Element {
  const { envelope, loading, refetch } = useRealtimeResource<OrchestratorStatus>({
    url: '/api/v2/orchestrator/status',
    source: '/api/v2/orchestrator/status',
    pollIntervalMs: 5_000,
    staleThresholdMs: 15_000,
    mode: 'read_only',
  });

  const d = envelope.data;
  const hb = d?.heartbeat;
  const proposals = d?.last_proposals ?? [];
  const decisions = d?.last_decisions ?? [];
  const latestDecision = decisions[0];
  const bucketWinners = latestDecision?.bucket_winners ?? [];

  const classOk = (hb?.classification ?? '').toLowerCase().includes('ok');

  return (
    <div
      data-testid="page-orchestrator-admin"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh' }}
    >
      {/* Header */}
      <div style={{ padding: '16px 20px 12px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4 }}>
              <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700 }}>Orchestrator</h1>
              <Chip label="LIVE PLATFORM" tone="ok" />
              {hb && <Chip label={classOk ? 'LIVE' : 'DEGRADED'} tone={classOk ? 'ok' : 'warn'} />}
            </div>
            <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
              Proposes → Risk Gateway validates → Execution engine acts · Auto-refresh 5s · LIVE GATE: {hb?.live_gate ?? '—'}
            </p>
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <button onClick={refetch} style={{ padding: '5px 12px', borderRadius: 6, border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 11, cursor: 'pointer' }}>↺ Refresh</button>
          </div>
        </div>

        {/* Pipeline flow */}
        <div style={{ marginTop: 12, padding: '8px 12px', background: 'rgba(0,0,0,0.2)', borderRadius: 6, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-muted)', display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
          <span style={{ color: '#6366f1' }}>Trainer</span><span>→</span>
          <span style={{ color: '#6366f1' }}>v2:prediction:*</span><span>→</span>
          <span style={{ color: '#f59e0b', fontWeight: 700 }}>Orchestrator (proposes)</span><span>→</span>
          <span style={{ color: '#ef5350' }}>Risk Gateway (blocks/allows)</span><span>→</span>
          <span style={{ color: '#3b82f6' }}>Execution Engine</span><span>→</span>
          <span style={{ color: '#26c281' }}>v2:signals:runtime:*</span>
          <span style={{ marginLeft: 'auto', color: 'rgba(239,83,80,0.8)', fontWeight: 700 }}>OPERATOR GATED</span>
        </div>
      </div>

      <div style={{ padding: '16px 20px', display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, alignItems: 'start' }}>
        {/* Left column: Heartbeat + latest decision */}
        <div>
          {/* Heartbeat */}
          <SectionHead title="Orchestrator Heartbeat" />
          <Card accent={classOk ? 'rgba(38,194,129,0.2)' : undefined}>
            {loading && !d ? (
              <div style={{ height: 60, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12 }}>Loading…</div>
            ) : hb ? (
              <>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
                  <KV label="Classification" value={<Chip label={hb.classification?.replace('V2_ORCHESTRATOR_', '').replace('_OK', '') ?? '—'} tone={classOk ? 'ok' : 'warn'} />} />
                  <KV label="Live Gate" value={hb.live_gate ?? '—'} valueColor={hb.live_gate?.includes('blocked') ? '#ef5350' : '#26c281'} />
                  <KV label="Approves Live" value={hb.approves_live ? 'YES' : 'NO'} valueColor={hb.approves_live ? '#ef5350' : '#26c281'} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
                  <KV label="Predictions Seen" value={(hb.predictions_seen ?? 0).toLocaleString()} />
                  <KV label="Proposals Arbitrated" value={(hb.proposals_arbitrated ?? 0).toLocaleString()} />
                  <KV label="Cannot Bypass Risk GW" value={hb.cannot_bypass_risk_gateway ? 'YES (correct)' : 'NO'} valueColor={hb.cannot_bypass_risk_gateway ? '#26c281' : '#f59e0b'} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 12 }}>
                  <KV label="Worker" value={(hb.worker_id ?? '—').replace('v2_orchestrator_', '')} />
                  <KV label="Last Run" value={fmtAge(hb.finished_at)} valueColor="var(--text-muted)" />
                </div>
              </>
            ) : (
              <div style={{ color: 'var(--text-muted)', fontSize: 12 }}>No heartbeat data. Check Redis v2:orchestrator:* keys.</div>
            )}
          </Card>

          {/* Latest decision */}
          {latestDecision && (
            <>
              <SectionHead title="Latest Arbitration Decision" />
              <Card>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
                  <KV label="Considered" value={(latestDecision.considered_count ?? 0).toLocaleString()} />
                  <KV label="Winners" value={(latestDecision.bucket_winners?.length ?? 0).toLocaleString()} />
                  <KV label="Stale Rejected" value={(latestDecision.stale_proposal_ids?.length ?? 0).toLocaleString()} valueColor={latestDecision.stale_proposal_ids?.length ? '#f59e0b' : undefined} />
                </div>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 12, marginBottom: 12 }}>
                  <KV label="Execution Fill Gate Hold" value={latestDecision.held_by_paper_fill_gate ? `YES (${latestDecision.held_by_paper_fill_gate_count ?? 0})` : 'NO'} valueColor={latestDecision.held_by_paper_fill_gate ? '#f59e0b' : undefined} />
                  <KV label="Malformed Skipped" value={(latestDecision.skipped_malformed_prediction_count ?? 0).toLocaleString()} valueColor={latestDecision.skipped_malformed_prediction_count ? '#f59e0b' : undefined} />
                  <KV label="Age" value={fmtAge(latestDecision.generated_utc)} valueColor="var(--text-muted)" />
                </div>
                {latestDecision.deconflict_reason && (
                  <div style={{ marginTop: 8, padding: '6px 10px', background: 'rgba(245,158,11,0.08)', borderRadius: 6, border: '1px solid rgba(245,158,11,0.2)', fontSize: 11, fontFamily: 'var(--font-mono)', color: '#f59e0b' }}>
                    Deconflict: {latestDecision.deconflict_reason} → {latestDecision.deconflict_selected_side ?? '—'}
                  </div>
                )}
              </Card>
            </>
          )}

          {/* Bucket winners */}
          {bucketWinners.length > 0 && (
            <>
              <SectionHead title={`Bucket Winners — ${bucketWinners.length} selected`} />
              <Card accent="rgba(38,194,129,0.15)">
                <div style={{ fontSize: 9, display: 'grid', gridTemplateColumns: '90px 52px 60px 80px 56px 1fr', gap: 6, padding: '0 10px 6px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'var(--font-mono)' }}>
                  <span>Symbol</span><span>Side</span><span>Conf</span><span>Exp Move</span><span>Score</span><span>Considered</span>
                </div>
                <BucketWinnersTable winners={bucketWinners} />
              </Card>
            </>
          )}
        </div>

        {/* Right column: Proposals feed */}
        <div>
          <SectionHead title={`Live Proposals — ${proposals.length} in window`} />
          <Card>
            <div style={{ fontSize: 9, display: 'grid', gridTemplateColumns: '90px 48px 56px 72px 80px 1fr', gap: 6, padding: '0 10px 8px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'var(--font-mono)', borderBottom: '1px solid rgba(255,255,255,0.05)', marginBottom: 8 }}>
              <span>Symbol</span><span>Side</span><span>Conf</span><span>Exp Move</span><span>Freshness</span><span>Model</span>
            </div>
            <ProposalsFeed proposals={proposals} />
            {proposals.length > 15 && (
              <div style={{ marginTop: 8, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                Showing 15 of {proposals.length} proposals
              </div>
            )}
          </Card>

          {/* Stats */}
          {proposals.length > 0 && (
            <>
              <SectionHead title="Proposal Statistics" />
              <Card>
                {(() => {
                  const confs = proposals.map(p => p.confidence_calibrated).filter((c): c is number => c != null);
                  const moves = proposals.map(p => p.expected_move_after_cost_bps).filter((m): m is number => m != null);
                  const shorts = proposals.filter(p => (p.side ?? '').toLowerCase() === 'short').length;
                  const longs = proposals.filter(p => (p.side ?? '').toLowerCase() === 'long').length;
                  const avgConf = confs.length ? confs.reduce((a, b) => a + b, 0) / confs.length : null;
                  const avgMove = moves.length ? moves.reduce((a, b) => a + b, 0) / moves.length : null;
                  const minConf = confs.length ? Math.min(...confs) : null;
                  const maxConf = confs.length ? Math.max(...confs) : null;
                  const symbols = new Set(proposals.map(p => p.symbol).filter(Boolean)).size;
                  return (
                    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, 1fr)', gap: 10 }}>
                      <KV label="Total Proposals" value={proposals.length} />
                      <KV label="Unique Symbols" value={symbols} />
                      <KV label="SHORT / LONG" value={`${shorts} / ${longs}`} />
                      <KV label="Avg Confidence" value={fmtPct(avgConf)} valueColor={confColor(avgConf)} />
                      <KV label="Conf Range" value={minConf != null ? `${fmtPct(minConf)} – ${fmtPct(maxConf)}` : '—'} />
                      <KV label="Avg Exp Move" value={fmtBps(avgMove)} valueColor={(avgMove ?? 0) < 0 ? '#ef5350' : '#26c281'} />
                    </div>
                  );
                })()}
              </Card>
            </>
          )}

          {/* Source */}
          <div style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', padding: '6px 0' }}>
            Source: {envelope.source ?? '/api/v2/orchestrator/status'} · {envelope.source_type ?? 'redis_live'} · Poll: 5s
          </div>
        </div>
      </div>

      {/* Safety footer */}
      <div style={{ margin: '0 20px 20px', padding: '10px 16px', background: 'rgba(239,83,80,0.05)', border: '1px solid rgba(239,83,80,0.15)', borderRadius: 8 }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          SAFETY: Orchestrator proposes only. Risk Gateway is the sole allow/deny authority. Orchestrator cannot override Risk Gateway.
        </p>
      </div>
    </div>
  );
}
