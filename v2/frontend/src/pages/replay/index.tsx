import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { usePayloadFile } from '../../hooks/usePayloadFile';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

interface ReplayStatus {
  last_run: string | null;
  idempotent_hash: string | null;
  bounded_events_count: number | null;
}

interface ReplaySummary {
  generated_at?: string;
  historical_audit_status?: string;
  live_gate_status?: string;
  mode?: string;
  period_days?: number;
  scenario_count?: number;
  v2_block_count?: number;
  v2_paper_pnl_fixture_sum?: string;
  estimated_loss_avoided_by_v2?: string;
}

const REPLAY_SUMMARY_PATH = '/historical_30d_replay_and_paper_proof/latest/historical_30d_summary.json';

function StatCard({ label, value, color, sub }: { label: string; value: string; color?: string; sub?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 18px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 6 }}>{label}</span>
      <span style={{ display: 'block', fontSize: 18, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', marginBottom: sub ? 4 : 0 }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{sub}</span>}
    </div>
  );
}

const REPLAY_CAPABILITIES = [
  { label: 'Bar-by-bar replay', detail: 'Step through historical OHLCV with pause, rewind, fast-forward controls', status: 'planned' },
  { label: 'Signal overlays', detail: 'Show every signal decision on the chart as it happened in the replay window', status: 'planned' },
  { label: 'Risk gate replay', detail: 'Replay risk gateway allow/block decisions with feature snapshot context', status: 'planned' },
  { label: 'Equity curve', detail: 'Cumulative PnL including slippage and fees per replay window', status: 'planned' },
  { label: 'Drawdown chart', detail: 'Peak-to-trough drawdown with recovery analysis and duration', status: 'planned' },
  { label: 'Feature snapshot diff', detail: 'Compare feature values at any two replay timestamps', status: 'planned' },
  { label: 'Event audit trail', detail: 'Every Redis event replayed in order with source lineage', status: 'partial' },
  { label: 'Scenario comparison', detail: 'Compare replay outcomes across different strategy configurations', status: 'planned' },
];

export default function ReplayPage(): JSX.Element {
  const { envelope, loading, refetch } = useRealtimeResource<ReplayStatus>({
    url: '/api/v2/replay/status',
    source: '/api/v2/replay/status',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });

  const { data: summary } = usePayloadFile<ReplaySummary>(REPLAY_SUMMARY_PATH, 30_000);
  const status = envelope.data;
  const hasLastRun = status?.last_run != null;
  const hasEvents = status?.bounded_events_count != null;

  return (
    <div
      data-testid="page-replay"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 64 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Replay</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Historical event replay engine · Signal and risk decision re-simulation · Evidence-first audit trail
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' }}>
              Refresh
            </button>
          </div>
        </div>
      </div>

      <div style={{ padding: 24 }}>
        {loading && !status && <LoadingSkeleton rows={4} />}

        {/* Last run status */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Last Run Status</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(200px, 1fr))', gap: 12 }}>
            <StatCard
              label="Last Replay Run"
              value={status?.last_run ?? 'No record'}
              color={hasLastRun ? 'var(--buy)' : 'var(--text-muted)'}
              sub={hasLastRun ? 'From Redis replay:last_run key' : 'No replay has completed yet'}
            />
            <StatCard
              label="Idempotent Hash"
              value={status?.idempotent_hash ?? '—'}
              color={status?.idempotent_hash ? 'var(--text-primary)' : 'var(--text-muted)'}
              sub="Deterministic run identifier"
            />
            <StatCard
              label="Bounded Events"
              value={status?.bounded_events_count != null ? String(status.bounded_events_count) : '—'}
              color={hasEvents ? 'var(--buy)' : 'var(--text-muted)'}
              sub="Events replayed in last run"
            />
            <StatCard
              label="Replay Engine"
              value={hasLastRun ? 'Has run' : 'Awaiting first run'}
              color={hasLastRun ? 'var(--buy)' : 'var(--warn)'}
              sub="Based on Redis key evidence"
            />
          </div>
        </div>

        {/* Historical 30d proof summary */}
        {summary && (
          <div style={{ marginBottom: 24 }}>
            <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Historical 30-Day Proof</h2>
            <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '18px 20px' }}>
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 14 }}>
                {[
                  { label: 'Generated at', value: summary.generated_at ?? '—' },
                  { label: 'Mode', value: summary.mode ?? '—' },
                  { label: 'Period', value: summary.period_days ? `${summary.period_days}d` : '—' },
                  { label: 'Scenarios', value: summary.scenario_count != null ? String(summary.scenario_count) : '—' },
                  { label: 'V2 blocks', value: summary.v2_block_count != null ? String(summary.v2_block_count) : '—' },
                  { label: 'Runtime PnL', value: summary.v2_paper_pnl_fixture_sum ?? '—' },
                  { label: 'Loss avoided', value: summary.estimated_loss_avoided_by_v2 ?? '—' },
                  { label: 'Live gate', value: summary.live_gate_status ?? 'blocked' },
                  { label: 'Audit status', value: summary.historical_audit_status ?? '—' },
                ].map(({ label, value }) => (
                  <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                    <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
                    <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
                  </div>
                ))}
              </div>
              <p style={{ margin: '12px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
                Source: historical 30-day replay proof · Static proof fixture · Not a live runtime stream
              </p>
            </div>
          </div>
        )}

        {/* Capabilities roadmap */}
        <div style={{ marginBottom: 24 }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Replay Capabilities</h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 12 }}>
            {REPLAY_CAPABILITIES.map((cap) => (
              <div key={cap.label} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '14px 16px' }}>
                <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 6 }}>
                  <span style={{ fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>{cap.label}</span>
                  <span style={{
                    fontSize: 10, fontWeight: 700, padding: '2px 7px', borderRadius: 999, fontFamily: 'var(--font-mono)',
                    background: cap.status === 'partial' ? 'color-mix(in oklch, var(--warn) 12%, transparent)' : 'var(--bg-elevated)',
                    color: cap.status === 'partial' ? 'var(--warn)' : 'var(--text-muted)',
                    border: '1px solid var(--border)', textTransform: 'uppercase',
                  }}>
                    {cap.status}
                  </span>
                </div>
                <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>{cap.detail}</p>
              </div>
            ))}
          </div>
        </div>

        {/* Replay readiness gate */}
        <div style={{ padding: '18px 20px', borderRadius: 'var(--radius)', border: '1px solid var(--border)', background: 'var(--bg-panel)' }}>
          <h3 style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>Readiness Gate</h3>
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)', lineHeight: 1.6 }}>
            Interactive replay will be unblocked when: (1) The replay engine writes verified Redis keys with event counts and hashes,
            (2) Signal and risk decision lineage is confirmed traceable to raw feature snapshots,
            (3) Equity curve metrics pass correctness review against known historical data,
            and (4) The bar-by-bar controller is validated against deterministic scenario checksums.
            Until then, this page shows runtime status only — no historical results are generated on-demand.
          </p>
          <div style={{ marginTop: 12, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: hasLastRun ? 'color-mix(in oklch, var(--buy) 10%, transparent)' : 'var(--bg-elevated)', color: hasLastRun ? 'var(--buy)' : 'var(--text-muted)', border: '1px solid var(--border)' }}>
              {hasLastRun ? '✓' : '○'} Redis run evidence
            </span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: hasEvents ? 'color-mix(in oklch, var(--buy) 10%, transparent)' : 'var(--bg-elevated)', color: hasEvents ? 'var(--buy)' : 'var(--text-muted)', border: '1px solid var(--border)' }}>
              {hasEvents ? '✓' : '○'} Event count verified
            </span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
              ○ Bar-by-bar controller
            </span>
            <span style={{ padding: '4px 10px', borderRadius: 999, fontSize: 11, fontWeight: 600, background: 'var(--bg-elevated)', color: 'var(--text-muted)', border: '1px solid var(--border)' }}>
              ○ Equity curve validated
            </span>
          </div>
        </div>

        {/* Warnings */}
        {envelope.warnings.length > 0 && (
          <div style={{ marginTop: 20 }}>
            {envelope.warnings.map((w, i) => (
              <p key={i} style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>⚠ {w}</p>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
