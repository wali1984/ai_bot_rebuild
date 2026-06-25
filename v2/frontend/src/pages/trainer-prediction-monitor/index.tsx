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
  target_price: number | null;
  current_price: number | null;
  expected_move_pct: number | null;
  horizon: string | null;
  strategy: string | null;
  model_version: string | null;
  feature_snapshot_id: string | null;
  emitted: boolean;
  blocked: boolean;
  block_reason: string | null;
}

interface TrainerStatus {
  status: string | null;
  last_train_at: string | null;
  current_epoch: number | null;
  total_epochs: number | null;
  loss: number | null;
  val_loss: number | null;
  checkpoint: string | null;
  dataset: string | null;
}

interface AIPredictionsData {
  predictions: PredictionEntry[];
  trainer: TrainerStatus | null;
  feature_importance: FeatureImportanceEntry[];
  model_version: string | null;
  checkpoint: string | null;
  total_emitted: number | null;
  total_blocked: number | null;
  calibration_score: number | null;
  win_rate_realized: number | null;
  source: string | null;
  timestamp: string | null;
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
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span style={{ fontSize: 20, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{sub}</span>}
    </div>
  );
}

function TrainerStatusPanel({ trainer }: { trainer: TrainerStatus | null }): JSX.Element {
  const statusColor = (s: string | null): string => {
    if (!s) return 'var(--text-muted)';
    const l = s.toLowerCase();
    if (l === 'running' || l === 'training') return 'var(--buy)';
    if (l === 'idle' || l === 'done') return 'var(--text-secondary)';
    if (l === 'error' || l === 'failed') return 'var(--sell)';
    return 'var(--warn)';
  };
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 18px' }}>
      <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Trainer Status</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(150px, 1fr))', gap: 12 }}>
        {[
          { label: 'Status', value: trainer?.status ?? '—', color: statusColor(trainer?.status ?? null) },
          { label: 'Epoch', value: trainer?.current_epoch != null && trainer?.total_epochs != null ? `${trainer.current_epoch}/${trainer.total_epochs}` : '—' },
          { label: 'Loss', value: trainer?.loss?.toFixed(4) ?? '—' },
          { label: 'Val Loss', value: trainer?.val_loss?.toFixed(4) ?? '—' },
          { label: 'Checkpoint', value: trainer?.checkpoint ?? '—' },
          { label: 'Last Train', value: trainer?.last_train_at ? new Date(trainer.last_train_at).toLocaleTimeString() : '—' },
        ].map((item) => (
          <div key={item.label} style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{item.label}</span>
            <span style={{ fontSize: 13, fontWeight: 600, fontFamily: 'var(--font-mono)', color: item.color ?? 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{item.value}</span>
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
                <td style={{ padding: '10px 12px', color: 'var(--buy)' }}>{fmt(p.target_price)}</td>
                <td style={{ padding: '10px 12px' }}>{fmt(p.current_price)}</td>
                <td style={{ padding: '10px 12px', color: (p.expected_move_pct ?? 0) >= 0 ? 'var(--buy)' : 'var(--sell)' }}>{fmtPct(p.expected_move_pct)}</td>
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

  const data = envelope.data;
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? adaptiveCapital.data?.capital_productivity_runtime_status?.signal_prediction_accuracy_status
    ?? null;

  return (
    <div
      data-testid="page-trainer-prediction-monitor"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)', marginBottom: 0 }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>AI Predictions</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Prediction matrix · Forecast bands · Calibration · Model performance · Trainer status · Execution restricted
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
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

      {/* KPI row */}
      <div style={{ padding: '16px 24px', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 12 }}>
        <KPICard label="Model" value={loading ? '…' : (data?.model_version ?? '—')} sub="Active model version" />
        <KPICard label="Emitted" value={loading ? '…' : String(data?.total_emitted ?? '—')} color="var(--buy)" sub="Signals emitted" />
        <KPICard label="Blocked" value={loading ? '…' : String(data?.total_blocked ?? '—')} color="var(--sell)" sub="Signals blocked by risk" />
        <KPICard label="Calibration" value={loading ? '…' : fmtConf(data?.calibration_score ?? null)} sub="Confidence calibration" />
        <KPICard label="Realized Win Rate" value={loading ? '…' : fmtPct(data?.win_rate_realized ?? null)} sub="Runtime measured" />
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
        <TrainerStatusPanel trainer={data?.trainer ?? null} />
      </div>

      {/* Prediction matrix */}
      <div style={{ padding: '0 24px 24px' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Prediction Matrix</h2>
        {loading && !data ? <LoadingSkeleton rows={5} /> : <PredictionMatrix predictions={data?.predictions ?? []} accuracy={accuracyStatus} />}
      </div>

      {/* Feature importance */}
      <div style={{ padding: '0 24px 24px' }}>
        <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Feature Importance</h2>
        <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px 18px' }}>
          {loading && !data ? <LoadingSkeleton rows={4} /> : <FeatureImportanceBar items={data?.feature_importance ?? []} />}
        </div>
      </div>

      {/* Evidence panel */}
      {data && (
        <div style={{ padding: '0 24px 24px' }}>
          <h2 style={{ margin: '0 0 12px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Evidence</h2>
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: '16px' }}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(180px, 1fr))', gap: 10 }}>
              {[
                ['Source', data.source ?? '/api/v2/ai/predictions'],
                ['Endpoint', '/api/v2/ai/predictions'],
                ['Received At', data.timestamp ?? '—'],
                ['Freshness', envelope.freshness_status],
                ['Source Type', envelope.source_type],
                ['Model Version', data.model_version ?? '—'],
                ['Checkpoint', data.checkpoint ?? '—'],
                ['Calibration', fmtConf(data.calibration_score ?? null)],
                ['Emitted', String(data.total_emitted ?? '—')],
                ['Blocked', String(data.total_blocked ?? '—')],
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
          Forecast source evidence for operator-gated execution workflows.
        </p>
      </div>
    </div>
  );
}
