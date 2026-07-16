import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { ErrorState } from '../../components/ui/ErrorState';
import { MetricCard } from '../../components/ui/MetricCard';
import { KPIGrid } from '../../components/ui/KPIGrid';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { useAdaptiveCapitalDashboard } from '../../data/adaptiveCapitalProductivity';

interface TARecord {
  symbol: string;
  timeframe: string;
  generated_utc: string;
  source_label: string;
  families_present: string[];
  indicators: Record<string, number | null>;
}

interface TAStatusData {
  classification: string;
  symbols_covered: number;
  symbols_fresh: number;
  ta_keys_total: number;
  ta_keys_fresh: number;
  sample_btc_1m: TARecord | null;
}

interface FeaturePipelineData {
  // /api/v2/ai/predictions does not emit `classification`/`snapshots_built`; it
  // returns trainer_status + count + feature_count + data_coverage. Map to those.
  classification?: string;
  snapshots_built?: number;
  trainer_status?: string;
  count?: number;
  feature_count?: number;
  data_coverage?: number;
}

function fmt(v: number | null | undefined): string {
  if (v == null) return '—';
  if (Math.abs(v) < 0.01) return v.toExponential(3);
  if (Math.abs(v) > 10000) return v.toFixed(2);
  return v.toFixed(4);
}

const KEY_INDICATORS: [string, string][] = [
  ['ta_RSI_14', 'RSI(14)'],
  ['ta_MACD_12_26_9_macd', 'MACD'],
  ['ta_MACD_12_26_9_signal', 'MACD Signal'],
  ['ta_ATR_14', 'ATR(14)'],
  ['ta_SMA_20', 'SMA(20)'],
  ['ta_EMA_12', 'EMA(12)'],
  ['ta_EMA_26', 'EMA(26)'],
  ['ta_BB_width_pct', 'BB Width %'],
];

export default function TechnicalAnalysisPage(): JSX.Element {
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const ta = useRealtimeResource<TAStatusData>({
    url: '/api/v2/ai/model-state',
    source: '/api/v2/ai/model-state',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
  });

  const fp = useRealtimeResource<FeaturePipelineData>({
    url: '/api/v2/ai/predictions',
    source: '/api/v2/ai/predictions',
    source_type: 'websocket',
    pollIntervalMs: 60_000,
    staleThresholdMs: 120_000,
    mode: 'read_only',
  });

  const data = ta.envelope.data;
  const fpData = fp.envelope.data;

  return (
    <article
      data-testid="page-technical-analysis"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ padding: '0 0 48px 0' }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', borderBottom: '1px solid var(--border)', background: 'var(--bg-panel)' }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Technical Analysis</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>{meta.description}</p>
          </div>
          <div style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
            <FreshnessBadge status={ta.envelope.freshness_status} lagMs={ta.envelope.lag_ms} />
            <SourceBadge sourceType={ta.envelope.source_type} source={ta.envelope.source} />
          </div>
        </div>
      </div>

      <div style={{ padding: '20px 24px' }}>
        {ta.loading && !data && <LoadingSkeleton rows={6} />}
        {!ta.loading && ta.error && !data && (
          <ErrorState message="Technical analysis stream reconnecting." retry={ta.refetch} />
        )}

        <section style={{ marginBottom: 24 }}>
          <AdaptiveCapitalTelemetryPanel
            payload={adaptiveCapital.data}
            title="Prediction Accuracy + Capital Productivity"
            compact
            showMatrix
            maxMatrixHeight={220}
          />
        </section>

        {/* Feature Pipeline Status */}
        {fpData && (
          <section style={{ marginBottom: 24 }}>
            <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px', color: 'var(--text-primary)' }}>Feature Pipeline</h2>
            <KPIGrid columns={3}>
              <MetricCard label="Classification" value={fpData.classification ?? fpData.trainer_status ?? '—'} freshness={ta.envelope.freshness_status === 'fresh' ? 'fresh' : 'stale'} />
              <MetricCard label="Predictions Built" value={(fpData.snapshots_built ?? fpData.count)?.toString() ?? '—'} />
              <MetricCard label="Feature Coverage" value={fpData.data_coverage != null ? `${fpData.data_coverage.toFixed(1)}%` : (fpData.feature_count != null ? `${fpData.feature_count} feats` : '—')} />
            </KPIGrid>
          </section>
        )}

        {/* TA Coverage */}
        {data && (
          <>
            <section style={{ marginBottom: 24 }}>
              <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 12px', color: 'var(--text-primary)' }}>TA Coverage</h2>
              <KPIGrid columns={4}>
                <MetricCard label="Classification" value={data.classification ?? '—'} />
                <MetricCard label="Symbols Covered" value={data.symbols_covered?.toString() ?? '—'} />
                <MetricCard label="Symbols Fresh" value={data.symbols_fresh?.toString() ?? '—'} freshness={data.symbols_fresh === data.symbols_covered ? 'fresh' : 'stale'} />
                <MetricCard label="TA Keys Fresh / Total" value={`${data.ta_keys_fresh ?? 0} / ${data.ta_keys_total ?? 0}`} freshness={data.ta_keys_total > 0 && data.ta_keys_fresh / data.ta_keys_total >= 0.9 ? 'fresh' : data.ta_keys_fresh > 0 ? 'stale' : 'offline'} />
              </KPIGrid>
            </section>

            {data.sample_btc_1m && (
              <section style={{ marginBottom: 24 }}>
                <h2 style={{ fontSize: 15, fontWeight: 600, margin: '0 0 4px', color: 'var(--text-primary)' }}>
                  Sample: {data.sample_btc_1m.symbol} · {data.sample_btc_1m.timeframe}
                </h2>
                <p style={{ fontSize: 12, color: 'var(--text-muted)', margin: '0 0 12px' }}>
                  Source: {data.sample_btc_1m.source_label} · Families: {data.sample_btc_1m.families_present.join(', ')} · Generated: {data.sample_btc_1m.generated_utc}
                </p>
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 8 }}>
                  {KEY_INDICATORS.map(([key, label]) => {
                    const val = data.sample_btc_1m!.indicators[key];
                    return (
                      <div key={key} style={{
                        padding: '10px 14px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)',
                        background: 'var(--bg-panel)',
                      }}>
                        <div style={{ fontSize: 11, color: 'var(--text-muted)', marginBottom: 4 }}>{label}</div>
                        <div style={{
                          fontFamily: 'var(--font-mono)', fontWeight: 700, fontSize: 15,
                          color: val != null ? 'var(--text-primary)' : 'var(--text-muted)',
                        }}>
                          {fmt(val)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              </section>
            )}
          </>
        )}

        {!ta.loading && !ta.error && !data && (
          <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)', fontSize: 14 }}>
            Technical analysis data not yet available. The feature pipeline produces this data when the backend service is running.
          </div>
        )}
      </div>
    </article>
  );
}
