import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  adaptiveStatusColor,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

interface TrainerAdminData {
  status: string | null;
  state?: string | null;
  last_train_at: string | null;
  current_epoch: number | null;
  total_epochs: number | null;
  loss: number | null;
  val_loss: number | null;
  checkpoint: string | null;
  dataset: string | null;
  model_version: string | null;
  symbols: string[];
  timeframes: string[];
  feature_count: number | null;
  train_samples: number | null;
  val_samples: number | null;
  predictions_emitted: number | null;
  predictions_blocked: number | null;
  calibration_score: number | null;
  input_dim?: number | null;
  feature_schema_status?: string | null;
  /** Canonical key on /api/v2/trainer/status (legacy alias: checkpoint). */
  checkpoint_id?: string | null;
  /** Canonical key on /api/v2/trainer/status (legacy alias: model_version). */
  model_id?: string | null;
  temporal_encoder?: string | null;
  temporal_encoder_enabled?: boolean | null;
  temporal_seq_len?: number | null;
  offline_pretrain_status?: {
    generated_utc?: string | null;
    phase?: string | null;
    promoted?: boolean | null;
    h2l_decision?: string | null;
    sortino_offline?: number | null;
    sortino_live?: number | null;
    cvar_offline?: number | null;
    cvar_live?: number | null;
  } | null;
  champion_challenger_status?: {
    status?: string | null;
    result_status?: string | null;
    best_challenger_id?: string | null;
    promotion_allowed?: boolean | null;
    promotion_reason?: string | null;
    paper_challenger_enabled?: boolean | null;
    replay_windows_processed?: number | null;
    replay_snapshots_scanned?: number | null;
    backtests_processed?: {
      train_rows?: number | null;
      validation_rows?: number | null;
      untouched_holdout_rows?: number | null;
      validation_trade_count?: number | null;
      untouched_holdout_trade_count?: number | null;
    } | null;
  } | null;
  active_jobs: Array<{ id: string; status: string; started_at: string | null; progress: number | null }>;
}

function statusColor(s: string | null): string {
  if (!s) return 'var(--text-muted)';
  const l = s.toLowerCase();
  if (l === 'running' || l === 'training') return 'var(--buy)';
  if (l === 'idle' || l === 'done' || l === 'complete') return 'var(--text-secondary)';
  if (l === 'error' || l === 'failed') return 'var(--sell)';
  return 'var(--warn)';
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div className="glass" style={{ padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', lineHeight: 1.25, overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word', display: 'block' }}>{value}</span>
    </div>
  );
}

export default function TrainerAdminPage(): JSX.Element {
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const { envelope, loading, error, refetch } = useRealtimeResource<TrainerAdminData>({
    url: '/api/v2/trainer/status',
    source: '/api/v2/trainer/status',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 120_000,
    mode: 'read_only',
  });

  const data = envelope.data;
  const challenger = data?.champion_challenger_status ?? null;
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status ?? null;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? capitalStatus?.signal_prediction_accuracy_status
    ?? null;
  const totalAccuracyCells = accuracyStatus?.symbol_timeframe_cell_count
    ?? accuracyStatus?.required_symbol_timeframe_cell_count;
  const missingAccuracyCells = missingAccuracyCellCount(accuracyStatus);

  return (
    <div
      data-testid="page-trainer-admin"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', paddingBottom: 64 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Trainer Admin</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Active jobs · Training metrics · Model registry · Predictions · Feature importance · Evidence
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button onClick={refetch} style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' }}>Refresh</button>
          </div>
        </div>
      </div>

      {loading && !data && <div style={{ padding: 24 }}><LoadingSkeleton rows={8} /></div>}
      {!loading && error && !data && (
        <div style={{ padding: '24px 24px 0' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Trainer admin stream reconnecting — {error}.</p>
        </div>
      )}

      {/* Status KPIs */}
      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
        <KV label="Status" value={loading ? '…' : (data?.status ?? data?.state ?? '—')} color={statusColor(data?.status ?? data?.state ?? null)} />
        <KV label="Challenger" value={loading ? '…' : (challenger?.status ?? 'MISSING_RUNTIME_EVIDENCE')} color={challenger?.promotion_allowed ? 'var(--buy)' : 'var(--warn)'} />
        <KV label="Best Challenger" value={loading ? '…' : (challenger?.best_challenger_id ?? 'none')} />
        <KV label="Promotion" value={loading ? '…' : (challenger?.promotion_allowed ? 'allowed' : 'blocked')} color={challenger?.promotion_allowed ? 'var(--buy)' : 'var(--sell)'} />
        <KV label="Promotion Reason" value={loading ? '…' : (challenger?.promotion_reason ?? 'runtime key missing')} color={challenger?.promotion_allowed ? 'var(--buy)' : 'var(--warn)'} />
        <KV label="Holdout Trades" value={loading ? '…' : String(challenger?.backtests_processed?.untouched_holdout_trade_count ?? '—')} color={(challenger?.backtests_processed?.untouched_holdout_trade_count ?? 0) >= 100 ? 'var(--buy)' : 'var(--warn)'} />
        <KV label="Replay Windows" value={loading ? '…' : String(challenger?.replay_windows_processed ?? '—')} />
        <KV label="Model Version" value={loading ? '…' : (data?.model_id ?? data?.model_version ?? '—')} />
        <KV label="Checkpoint" value={loading ? '…' : (data?.checkpoint_id ?? data?.checkpoint ?? '—')} />
        <KV label="Epoch" value={loading ? '…' : data?.current_epoch != null && data?.total_epochs != null ? `${data.current_epoch}/${data.total_epochs}` : '—'} />
        <KV label="Loss" value={loading ? '…' : (data?.loss?.toFixed(6) ?? '—')} />
        <KV label="Val Loss" value={loading ? '…' : (data?.val_loss?.toFixed(6) ?? '—')} />
        <KV label="Emitted" value={loading ? '…' : String(data?.predictions_emitted ?? '—')} color="var(--buy)" />
        <KV label="Blocked" value={loading ? '…' : String(data?.predictions_blocked ?? '—')} color="var(--sell)" />
        <KV label="Calibration" value={loading ? '…' : data?.calibration_score != null ? `${(data.calibration_score * 100).toFixed(1)}%` : '—'} />
        <KV label="Accuracy" value={formatAdaptivePercent(accuracyStatus?.overall_accuracy)} color={adaptiveStatusColor(accuracyStatus?.status)} />
        <KV label="TF Cells" value={`${accuracyStatus?.evaluated_symbol_timeframe_cell_count ?? 0}/${totalAccuracyCells ?? 0}`} />
        <KV label="Missing Cells" value={String(missingAccuracyCells ?? 0)} color={(missingAccuracyCells ?? 0) > 0 ? 'var(--sell)' : 'var(--buy)'} />
        <KV label="Capital Status" value={capitalStatus?.status ?? '—'} color={adaptiveStatusColor(capitalStatus?.status)} />
        <KV label="Features" value={loading ? '…' : String(data?.feature_count ?? '—')} />
        <KV label="Input Dim" value={loading ? '…' : String(data?.input_dim ?? '—')} />
        <KV label="Schema" value={loading ? '…' : (data?.feature_schema_status ?? '—')} color={data?.feature_schema_status === 'ALIGNED' ? 'var(--buy)' : 'var(--warn)'} />
        {/* Temporal encoder: null/absent = no evidence either way — honest dash, never assert single-frame. */}
        <KV
          label="Temporal Encoder"
          value={loading ? '…' : (
            data?.temporal_encoder_enabled == null
              ? '—'
              : data.temporal_encoder_enabled
                ? `${data.temporal_encoder ?? 'on'} × ${data.temporal_seq_len ?? '—'}`
                : 'single-frame'
          )}
          color={data?.temporal_encoder_enabled ? 'var(--buy)' : data?.temporal_encoder_enabled == null ? 'var(--text-muted)' : 'var(--text-secondary)'}
        />
        <KV
          label="Offline Pretrain"
          value={loading ? '…' : (data?.offline_pretrain_status?.h2l_decision ?? '—')}
          color={data?.offline_pretrain_status?.promoted ? 'var(--buy)' : 'var(--warn)'}
        />
        <KV
          label="H2L Risk Gate"
          value={loading ? '…' : (
            data?.offline_pretrain_status?.sortino_offline != null
              ? `S ${data.offline_pretrain_status.sortino_offline.toFixed(3)} / C ${data.offline_pretrain_status.cvar_offline?.toFixed(0) ?? '—'}`
              : '—'
          )}
        />
        <KV label="Last Train" value={loading ? '…' : (data?.last_train_at ? new Date(data.last_train_at).toLocaleString() : '—')} />
        <KV label="Dataset" value={loading ? '…' : (data?.dataset ?? '—')} />
      </div>

      <div style={{ padding: '20px 24px 0' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Trainer Prediction Accuracy + Capital Productivity"
          compact
          showMatrix
          maxMatrixHeight={240}
        />
      </div>

      {/* Active jobs */}
      <div style={{ padding: '20px 24px 0' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Active Jobs</h2>
        {!data?.active_jobs || data.active_jobs.length === 0 ? (
          <div className="glass" style={{ padding: '24px', textAlign: 'center' }}>
            <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>No active training jobs.</p>
          </div>
        ) : (
          <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
            {data.active_jobs.map((job) => (
              <div key={job.id} className="glass" style={{ padding: '14px 16px' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8 }}>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>{job.id}</span>
                  <span style={{ fontSize: 11, fontWeight: 700, color: statusColor(job.status) }}>{job.status.toUpperCase()}</span>
                </div>
                {job.progress != null && (
                  <div style={{ marginTop: 8, display: 'flex', alignItems: 'center', gap: 8 }}>
                    <div style={{ flex: 1, height: 4, background: 'var(--bg-elevated)', borderRadius: 2 }}>
                      <div style={{ height: '100%', borderRadius: 2, background: 'var(--accent)', width: `${Math.min(job.progress, 100)}%` }} />
                    </div>
                    <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{job.progress.toFixed(1)}%</span>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Admin controls note */}
      <div style={{ padding: '20px 24px', marginTop: 8 }}>
        <div style={{ padding: '14px 16px', background: 'color-mix(in oklch, var(--warn) 8%, transparent)', border: '1px solid color-mix(in oklch, var(--warn) 30%, transparent)', borderRadius: 'var(--radius)', fontSize: 12, color: 'var(--text-secondary)' }}>
          <strong style={{ color: 'var(--warn)' }}>Admin controls</strong> (start, pause, cancel, rerun, promote, rollback) require superadmin confirmation
          with reason, backend authorization, and audit logging before any trainer state is mutated. Controls not yet wired in this UI.
        </div>
      </div>
    </div>
  );
}
