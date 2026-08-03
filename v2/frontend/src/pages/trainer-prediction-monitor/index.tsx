import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import {
  accuracyCell as lookupAccuracyCell,
  adaptiveStatusColor,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  type SignalPredictionAccuracyCell,
  type SignalPredictionAccuracyStatus,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

interface FeatureImportanceEntry {
  feature: string;
  importance: number;
}

interface PredictionEntry {
  symbol: string;
  timeframe?: string | null;
  action: string | null;
  confidence: number | null;
  target_price?: number | null;
  current_price?: number | null;
  expected_move_pct?: number | null;
  horizon?: string | null;
  strategy?: string | null;
  model_version?: string | null;
  checkpoint_id?: string | null;
  feature_snapshot_id?: string | null;
  timestamp?: string | null;
  source?: string | null;
  emitted?: boolean;
  blocked?: boolean;
  block_reason?: string | null;
}

interface CalibrationBlock {
  calibration_source?: string | null;
  confidence_calibrated?: number | null;
  confidence_raw?: number | null;
  coverage_factor?: number | null;
  missing_penalty?: number | null;
  stale_penalty?: number | null;
  temperature?: number | null;
  used_calibration?: boolean | null;
}

interface OfflinePretrainStatus {
  phase?: string | null;
  promoted?: boolean | null;
  generated_utc?: string | null;
  h2l_decision?: string | null;
  duration_seconds?: number | null;
  sortino_offline?: number | null;
}

// Shape of /api/v2/ai/predictions `data` (verified against the live payload):
// checkpoint lives in `checkpoint_id`, calibration is a nested object, and the
// trainer state is a flat `trainer_status` string (e.g. STALE_REDIS_EVIDENCE).
interface AIPredictionsData {
  predictions: PredictionEntry[];
  count?: number | null;
  trainer_status?: string | null;
  model_version: string | null;
  checkpoint_id?: string | null;
  cuda_active?: boolean | null;
  data_coverage?: number | null;
  calibration_available?: boolean | null;
  calibration?: CalibrationBlock | null;
  feature_importance_available?: boolean | null;
  feature_importance?: FeatureImportanceEntry[] | null;
  offline_pretrain_status?: OfflinePretrainStatus | null;
}

// Flat payload of /api/v2/trainer/status — carries the honest evidence age
// (staleness_seconds) that /api/v2/ai/predictions re-emission hides.
interface TrainerStatusFlat {
  state?: string | null;
  staleness_seconds?: number | null;
  freshness_status?: string | null;
  checkpoint_id?: string | null;
  data_coverage?: number | null;
  cuda_active?: boolean | null;
  champion_challenger_status?: {
    best_challenger_id?: string | null;
    promotion_allowed?: boolean | null;
    blocker_reasons?: string[] | null;
    backtests_processed?: {
      train_rows?: number | null;
      validation_rows?: number | null;
      untouched_holdout_rows?: number | null;
    } | null;
  } | null;
  cuda_runtime?: {
    gpu_name?: string | null;
    cuda_available?: boolean | null;
    gpu_idle_data_starved?: boolean | null;
    memory_allocated_bytes?: number | null;
    memory_total_bytes?: number | null;
  } | null;
  inference_sidecar?: {
    predictions_count?: number | null;
    trust_gate_rejection_count?: number | null;
  } | null;
}

function fmt(n: number | null, d = 2): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function fmtPct(n: number | null): string {
  if (n == null) return '—';
  const p = Math.abs(n) <= 1 ? n * 100 : n;
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;
}
function fmtConf(n: number | null): string {
  if (n == null) return '—';
  return `${(n * 100).toFixed(1)}%`;
}

function dirColor(d: string | null): string {
  if (!d) return 'var(--text-muted)';
  const l = d.toLowerCase();
  if (l === 'long' || l === 'buy') return 'var(--buy)';
  if (l === 'short' || l === 'sell') return 'var(--sell)';
  return 'var(--text-secondary)';
}

function predictionTimeframe(prediction: PredictionEntry): string | null {
  return prediction.timeframe ?? prediction.horizon ?? null;
}

function AccuracyBadge({ cell }: { cell: SignalPredictionAccuracyCell | null }): JSX.Element {
  if (!cell || !cell.evaluated_count) {
    return (
      <div style={{ fontFamily: 'var(--font-mono)' }}>
        <span style={{ display: 'block', fontSize: 11, color: 'var(--text-muted)' }}>—</span>
        <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)' }}>no outcomes</span>
      </div>
    );
  }
  return (
    <div style={{ fontFamily: 'var(--font-mono)' }}>
      <span style={{ display: 'block', fontSize: 12, fontWeight: 800, color: adaptiveStatusColor(cell.status) }}>
        {formatAdaptivePercent(cell.accuracy)}
      </span>
      <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)' }}>
        {cell.correct_count ?? 0}/{cell.evaluated_count} hits
      </span>
      <span style={{ display: 'block', fontSize: 9, color: (cell.realized_pnl_usd ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
        {formatAdaptiveMoney(cell.realized_pnl_usd)} pnl
      </span>
    </div>
  );
}

function KPICard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }): JSX.Element {
  // Long mono identifiers (e.g. V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA) must wrap
  // inside the card instead of bleeding under the neighbouring KPI card.
  const isLongValue = value.length > 16;
  return (
    <div className="glass" style={{
      padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 4, minWidth: 0, overflow: 'hidden',
    }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span title={value} style={{ fontSize: isLongValue ? 13 : 20, lineHeight: 1.3, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', overflowWrap: 'anywhere', minWidth: 0 }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: 'var(--text-muted)', overflowWrap: 'anywhere' }}>{sub}</span>}
    </div>
  );
}

function isStaleTrainerState(state: string | null | undefined): boolean {
  return (state ?? '').toUpperCase().includes('STALE');
}

function trainerStateColor(state: string | null | undefined): string {
  if (!state) return 'var(--text-muted)';
  const u = state.toUpperCase();
  if (u.includes('STALE') || u.includes('ABORT') || u.includes('HELD')) return 'var(--warn)';
  if (u.includes('ERROR') || u.includes('FAILED') || u.includes('DOWN')) return 'var(--sell)';
  if (u.includes('RUNNING') || u.includes('TRAINING') || u.includes('ACTIVE')) return 'var(--buy)';
  return 'var(--text-secondary)';
}

function fmtAgeSeconds(s: number | null | undefined): string | null {
  if (s == null || !Number.isFinite(s) || s < 0) return null;
  if (s < 60) return `${Math.round(s)}s`;
  if (s < 3600) return `${Math.round(s / 60)}m`;
  return `${(s / 3600).toFixed(1)}h`;
}

function fmtCoveragePct(n: number | null | undefined): string {
  if (n == null || !Number.isFinite(n)) return '—';
  return `${n.toFixed(1)}%`;
}

function TrainerStatusPanel({
  data,
  evidenceAgeSeconds,
  challenger,
  cudaRuntime,
  inference,
}: {
  data: AIPredictionsData | null;
  evidenceAgeSeconds: number | null;
  challenger?: TrainerStatusFlat['champion_challenger_status'];
  cudaRuntime?: TrainerStatusFlat['cuda_runtime'];
  inference?: TrainerStatusFlat['inference_sidecar'];
}): JSX.Element {
  const state = data?.trainer_status ?? null;
  const offline = data?.offline_pretrain_status ?? null;
  const age = fmtAgeSeconds(evidenceAgeSeconds);
  return (
    <div className="glass" style={{ padding: '16px 18px' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Trainer Status</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
        {[
          { label: 'Status', value: state ? state.replace(/_/g, ' ') : '—', color: trainerStateColor(state) },
          { label: 'Evidence Age', value: age ?? '—', color: isStaleTrainerState(state) ? 'var(--warn)' : undefined },
          { label: 'Checkpoint', value: data?.checkpoint_id ?? '—' },
          { label: 'CUDA', value: data?.cuda_active == null ? '—' : data.cuda_active ? 'active' : 'inactive', color: data?.cuda_active ? 'var(--buy)' : undefined },
          { label: 'Train Rows', value: `${challenger?.backtests_processed?.train_rows ?? 0} / 1000`, color: (challenger?.backtests_processed?.train_rows ?? 0) >= 1000 ? 'var(--buy)' : 'var(--warn)' },
          { label: 'GPU', value: cudaRuntime?.gpu_name ?? (data?.cuda_active ? 'CUDA active' : '—'), color: cudaRuntime?.cuda_available ? 'var(--buy)' : undefined },
          { label: 'GPU State', value: cudaRuntime ? (cudaRuntime.gpu_idle_data_starved ? 'idle · data-starved' : `${((cudaRuntime.memory_allocated_bytes ?? 0) / 1e9).toFixed(1)} GB active`) : '—', color: cudaRuntime?.gpu_idle_data_starved ? 'var(--warn)' : undefined },
          { label: 'Sidecar predictions', value: String(inference?.predictions_count ?? '—') },
          { label: 'Trust-gate rejects', value: String(inference?.trust_gate_rejection_count ?? '—'), color: (inference?.trust_gate_rejection_count ?? 0) > 0 ? 'var(--warn)' : undefined },
          { label: 'Data Coverage', value: fmtCoveragePct(data?.data_coverage) },
          { label: 'Offline Pretrain', value: offline?.phase ? offline.phase.replace(/_/g, ' ') : '—', color: offline?.phase?.toUpperCase().includes('ABORT') ? 'var(--warn)' : undefined },
          { label: 'Last Pretrain Run', value: offline?.generated_utc ? new Date(offline.generated_utc).toLocaleString() : '—' },
        ].map((item) => (
          <div key={item.label} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</span>
            <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: item.color ?? 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={String(item.value)}>{item.value}</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function FeatureImportanceBar({ items }: { items: FeatureImportanceEntry[] }): JSX.Element {
  if (items.length === 0) {
    return <p style={{ color: 'var(--text-muted)', fontSize: 12, padding: '8px 0' }}>Feature importance not available from trainer.</p>;
  }
  const top = [...items].sort((a, b) => b.importance - a.importance).slice(0, 12);
  const max = top[0]?.importance ?? 1;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {top.map((f) => (
        <div key={f.feature} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span style={{ fontSize: 11, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', width: 160, flexShrink: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{f.feature}</span>
          <div style={{ flex: 1, height: 6, background: 'var(--bg-elevated)', borderRadius: 3 }}>
            <div style={{ height: '100%', borderRadius: 3, background: 'var(--accent)', width: `${(f.importance / max) * 100}%`, transition: 'width 0.3s' }} />
          </div>
          <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', width: 40, textAlign: 'right' }}>{(f.importance * 100).toFixed(1)}%</span>
        </div>
      ))}
    </div>
  );
}

function PredictionMatrix({
  predictions,
  accuracy,
}: {
  predictions: PredictionEntry[];
  accuracy: SignalPredictionAccuracyStatus | null;
}): JSX.Element {
  if (predictions.length === 0) {
    return <p style={{ color: 'var(--text-muted)', fontSize: 12, padding: '16px 0' }}>No predictions available from trainer endpoint.</p>;
  }
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'TF', 'Action', 'Confidence', 'Accuracy / PnL', 'Target', 'Current', 'Move', 'Horizon', 'Strategy', 'Emitted', 'Block Reason'].map((h) => (
              <th key={h} style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {predictions.map((p, i) => {
            const timeframe = predictionTimeframe(p);
            const accuracyCell = timeframe ? lookupAccuracyCell(accuracy, p.symbol, timeframe) : null;
            return (
              <tr key={`${p.symbol}-${timeframe ?? 'tf'}-${i}`} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 12px', fontWeight: 600 }}>{p.symbol}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{timeframe ?? '—'}</td>
                <td style={{ padding: '10px 12px', fontWeight: 700, color: dirColor(p.action) }}>{p.action?.toUpperCase() ?? '—'}</td>
                <td style={{ padding: '10px 12px' }}>{fmtConf(p.confidence)}</td>
                <td style={{ padding: '10px 12px' }}><AccuracyBadge cell={accuracyCell} /></td>
                <td style={{ padding: '10px 12px', color: 'var(--buy)' }}>{fmt(p.target_price ?? null)}</td>
                <td style={{ padding: '10px 12px' }}>{fmt(p.current_price ?? null)}</td>
                <td style={{ padding: '10px 12px', color: (p.expected_move_pct ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' }}>{fmtPct(p.expected_move_pct ?? null)}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text-muted)' }}>{p.horizon ?? '—'}</td>
                <td style={{ padding: '10px 12px', color: 'var(--text-muted)', fontSize: 11 }}>{p.strategy ?? '—'}</td>
                <td style={{ padding: '10px 12px' }}>
                  {p.emitted ? (
                    <span style={{ color: 'var(--buy)', fontWeight: 700 }}>✓</span>
                  ) : p.blocked ? (
                    <span style={{ color: 'var(--sell)', fontWeight: 700 }}>✗</span>
                  ) : (
                    <span style={{ color: 'var(--text-muted)' }}>—</span>
                  )}
                </td>
                <td style={{ padding: '10px 12px', color: 'var(--sell)', fontSize: 11 }}>{p.block_reason ?? (p.emitted ? '' : '—')}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function AIPredictionsPage(): JSX.Element {
  const { envelope, loading, error, refetch } = useRealtimeResource<AIPredictionsData>({
    url: '/api/v2/ai/predictions',
    source: '/api/v2/ai/predictions',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 120_000,
    mode: 'read_only',
  });
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  // /api/v2/ai/predictions re-emits the last Redis evidence with a fresh
  // timestamp, so the delivery envelope alone cannot show how old the trainer
  // brain actually is. /api/v2/trainer/status carries the honest
  // staleness_seconds for the same evidence.
  const trainerStatusRes = useRealtimeResource<TrainerStatusFlat>({
    url: '/api/v2/trainer/status',
    source: '/api/v2/trainer/status',
    source_type: 'api',
    pollIntervalMs: 60_000,
    staleThresholdMs: 300_000,
    mode: 'read_only',
  });

  const data = envelope.data;
  const trainerFlat = trainerStatusRes.envelope.data;
  const trainerState = data?.trainer_status ?? trainerFlat?.state ?? null;
  const trainerEvidenceAgeSeconds = typeof trainerFlat?.staleness_seconds === 'number' ? trainerFlat.staleness_seconds : null;
  const trainerStale = isStaleTrainerState(trainerState);
  const trainerAgeLabel = fmtAgeSeconds(trainerEvidenceAgeSeconds);
  const calibrated = data?.calibration?.confidence_calibrated ?? null;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.signal_prediction_accuracy_status
    ?? null;

  return (
    <div
      data-testid="page-trainer-prediction-monitor"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', paddingBottom: 48 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', backdropFilter: 'blur(8px)', borderBottom: '1px solid var(--border)', marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>AI Predictions</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Prediction matrix · Forecast bands · Calibration · Model performance · Trainer status · Execution restricted
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            {trainerState && (
              <span
                title="Trainer brain state from Redis evidence — independent of API delivery freshness"
                style={{
                  padding: '3px 9px',
                  borderRadius: 'var(--radius-sm)',
                  fontSize: 11,
                  fontWeight: 800,
                  fontFamily: 'var(--font-mono)',
                  color: trainerStateColor(trainerState),
                  border: `1px solid ${trainerStateColor(trainerState)}`,
                  background: 'transparent',
                }}
              >
                TRAINER: {trainerState.replace(/_/g, ' ')}{trainerAgeLabel ? ` · ${trainerAgeLabel}` : ''}
              </span>
            )}
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button
              onClick={refetch}
              style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' }}
            >
              Refresh
            </button>
          </div>
        </div>
      </div>

      {loading && !data && <div style={{ padding: 24 }}><LoadingSkeleton rows={8} /></div>}
      {!loading && error && !data && (
        <div style={{ padding: '24px 24px 0' }}>
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Predictions unavailable — {error}. No predictions are fabricated.</p>
        </div>
      )}

      {/* Trainer staleness banner — honest state when the brain is held */}
      {trainerStale && (
        <div style={{ margin: '16px 24px 0', padding: '10px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid color-mix(in oklch, var(--warn) 45%, transparent)', background: 'color-mix(in oklch, var(--warn) 10%, var(--bg-elevated))', fontSize: 12, color: 'var(--warn)', fontFamily: 'var(--font-mono)' }}>
          Trainer evidence is stale ({trainerState?.replace(/_/g, ' ')}{trainerAgeLabel ? ` · age ${trainerAgeLabel}` : ''}). The prediction below is re-emitted from the last Redis evidence — it is not fresh model output. Delivery freshness above refers to the API response only.
        </div>
      )}

      {/* KPI row */}
      <div style={{ padding: '16px 24px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
        <KPICard label="Model" value={loading ? '…' : (data?.model_version ?? '—')} sub="Active model version" />
        <KPICard
          label="Trainer Status"
          value={loading ? '…' : (trainerState ? trainerState.replace(/_/g, ' ') : '—')}
          color={trainerStateColor(trainerState)}
          sub={trainerAgeLabel ? `evidence age ${trainerAgeLabel}` : 'from Redis evidence'}
        />
        <KPICard
          label="Calibration"
          value={loading ? '…' : fmtConf(calibrated)}
          sub={data?.calibration ? `raw ${fmtConf(data.calibration.confidence_raw ?? null)} · T=${data.calibration.temperature ?? '—'}` : 'Confidence calibration'}
        />
        <KPICard label="Data Coverage" value={loading ? '…' : fmtCoveragePct(data?.data_coverage)} sub="Feature coverage into model" />
        <KPICard
          label="CUDA"
          value={loading ? '…' : data?.cuda_active == null ? '—' : data.cuda_active ? 'ACTIVE' : 'INACTIVE'}
          color={data?.cuda_active ? 'var(--buy)' : undefined}
          sub="GPU inference runtime"
        />
      </div>

      <div style={{ padding: '0 24px 16px' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Prediction Accuracy + Capital Productivity"
          compact
          showMatrix
          maxMatrixHeight={260}
        />
      </div>

      {/* Trainer status */}
      <div style={{ padding: '0 24px 16px' }}>
        <TrainerStatusPanel data={data} evidenceAgeSeconds={trainerEvidenceAgeSeconds} challenger={trainerFlat?.champion_challenger_status} cudaRuntime={trainerFlat?.cuda_runtime} inference={trainerFlat?.inference_sidecar} />
      </div>

      {/* Prediction matrix */}
      <div style={{ padding: '0 24px 24px' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Prediction Matrix</h2>
        {loading && !data ? <LoadingSkeleton rows={5} /> : <PredictionMatrix predictions={data?.predictions ?? []} accuracy={accuracyStatus} />}
      </div>

      {/* Feature importance */}
      <div style={{ padding: '0 24px 24px' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Feature Importance</h2>
        <div className="glass" style={{ padding: '16px 18px' }}>
          {loading && !data ? <LoadingSkeleton rows={4} /> : <FeatureImportanceBar items={data?.feature_importance ?? []} />}
        </div>
      </div>

      {/* Evidence panel */}
      {data && (
        <div style={{ padding: '0 24px 24px' }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Evidence</h2>
          <div className="glass" style={{ padding: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
              {[
                ['Source', envelope.source ?? '/api/v2/ai/predictions'],
                ['Endpoint', '/api/v2/ai/predictions'],
                ['Received At', envelope.received_at ? new Date(envelope.received_at).toISOString() : '—'],
                ['Delivery Freshness', envelope.freshness_status],
                ['Trainer Status', trainerState ? trainerState.replace(/_/g, ' ') : '—'],
                ['Trainer Evidence Age', trainerAgeLabel ?? '—'],
                ['Source Type', envelope.source_type],
                ['Model Version', data.model_version ?? '—'],
                ['Checkpoint', data.checkpoint_id ?? '—'],
                ['Calibration', fmtConf(calibrated)],
                ['Calibration Raw', fmtConf(data.calibration?.confidence_raw ?? null)],
                ['Missing Fields', String(envelope.missing_fields.length)],
              ].map(([label, value]) => (
                <div key={label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                  <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
                  <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {/* Warnings */}
      {envelope.warnings.length > 0 && (
        <div style={{ padding: '0 24px' }}>
          {envelope.warnings.map((w, i) => (
            <p key={i} style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>⚠ {w}</p>
          ))}
        </div>
      )}

      {/* Footer */}
      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--border)', marginTop: 8 }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Forecast source evidence for approval-gated execution workflows.
        </p>
      </div>
    </div>
  );
}
