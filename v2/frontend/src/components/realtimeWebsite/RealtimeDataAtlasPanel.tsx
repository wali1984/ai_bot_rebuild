import { useCallback, useEffect, useMemo, useState } from 'react';
import { DatabaseZap } from 'lucide-react';
import { PAYLOAD_PATHS } from '../../data/realtimeUserWebsitePayloads';
import { ageClass, fmtAge } from '../../hooks/usePayloadFile';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { ValidatedDataEnvelope } from '../../types/dataContract';

type AtlasMode = 'public' | 'system';

interface SurfaceSpec {
  key: keyof typeof PAYLOAD_PATHS;
  label: string;
  group: string;
}

interface SurfaceStatus extends SurfaceSpec {
  path: string;
  available: boolean;
  ageSeconds: number | null;
  state: string;
  detail: string;
  error: string | null;
}

type SurfaceStatusMap = Partial<Record<keyof typeof PAYLOAD_PATHS, SurfaceStatus>>;

const PUBLIC_SURFACE_KEYS = new Set<keyof typeof PAYLOAD_PATHS>([
  'frontend_truth',
  'top10_dashboards',
  'top10_binance',
  'liquidation_wss_client',
  'alternative_data',
  'alt_data_symbol_universe_scoring',
  'native_cuda_trainer',
  'orchestrator_arbitration_live',
  'trade_management_paper_live',
]);

const PUBLIC_SURFACE_LABELS: Partial<Record<keyof typeof PAYLOAD_PATHS, { label: string; group: string }>> = {
  frontend_truth: { label: 'Platform status', group: 'Platform' },
  top10_dashboards: { label: 'Market screener', group: 'Market data' },
  top10_binance: { label: 'Exchange market data', group: 'Market data' },
  liquidation_wss_client: { label: 'Liquidation feed', group: 'Market data' },
  alternative_data: { label: 'Alternative market data', group: 'Market data' },
  alt_data_symbol_universe_scoring: { label: 'Symbol universe', group: 'Market data' },
  native_cuda_trainer: { label: 'Signal model source', group: 'Signals' },
  orchestrator_arbitration_live: { label: 'Signal arbitration', group: 'Signals' },
  trade_management_paper_live: { label: 'Execution state', group: 'Execution' },
};

const SURFACE_SPECS: SurfaceSpec[] = (Object.keys(PAYLOAD_PATHS) as Array<keyof typeof PAYLOAD_PATHS>).map((key) => ({
  key,
  label: publicSafeText(key
    .replace(/^war_room_/u, 'ops room ')
    .replace(/^alt_data_/u, 'alt data ')
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())),
  group: groupForKey(String(key)),
}));

const TIMESTAMP_FIELDS = [
  'generated_at',
  'generated_utc',
  'generated_est',
  'timestamp',
  'received_at',
  'heartbeat_at',
  'last_run_ts',
  'finished_at',
  'updated_at',
] as const;

function groupForKey(key: string): string {
  if (key.includes('trainer') || key.includes('orchestrator') || key.includes('trade_management') || key.includes('paper')) return 'Trading brain';
  if (key.includes('liquidation') || key.includes('top10') || key.includes('alternative') || key.includes('alt_data')) return 'Market data';
  if (key.includes('live_canary') || key.includes('production') || key.includes('frontend')) return 'Runtime truth';
  if (key.includes('war_room') || key.includes('spark') || key.includes('legacy')) return 'Operations';
  return 'Runtime';
}

function publicSurfaceSpec(spec: SurfaceSpec): SurfaceSpec {
  const safe = PUBLIC_SURFACE_LABELS[spec.key];
  return safe ? { ...spec, label: safe.label, group: safe.group } : spec;
}

function parseAgeSeconds(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value > 10_000_000_000 ? value : value * 1000;
    return Math.max(0, Math.round((Date.now() - ms) / 1000));
  }
  if (typeof value !== 'string' || value.trim() === '') return null;
  const ms = new Date(value).getTime();
  return Number.isNaN(ms) ? null : Math.max(0, Math.round((Date.now() - ms) / 1000));
}

function payloadAgeSeconds(payload: Record<string, unknown>): number | null {
  const freshness = payload.freshness;
  if (freshness && typeof freshness === 'object') {
    const runtimeAge = (freshness as Record<string, unknown>).runtime_age_seconds
      ?? (freshness as Record<string, unknown>).age_seconds;
    if (typeof runtimeAge === 'number' && Number.isFinite(runtimeAge)) return Math.max(0, Math.round(runtimeAge));
  }
  for (const field of TIMESTAMP_FIELDS) {
    const age = parseAgeSeconds(payload[field]);
    if (age !== null) return age;
  }
  return null;
}

function asCount(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (Array.isArray(value)) return value.length;
  return null;
}

function publicSafeText(value: string): string {
  return value
    .replace(/\/operator_runtime\/[^\s)]+/gi, 'runtime data feed')
    .replace(/\/v2_[^\s)]+/gi, 'runtime data feed')
    .replace(/operator[_\s-]*runtime/gi, 'runtime')
    .replace(/cuda/gi, 'AI')
    .replace(/persistent trainer/gi, 'signal model')
    .replace(/native trainer/gi, 'signal model')
    .replace(/\btrainer\b/gi, 'signal model')
    .replace(/\bproof\b/gi, 'evidence')
    .replace(/checkpoint/gi, 'model version')
    .replace(/runtime alpha/gi, 'AI forecast')
    .replace(/enabled operator approved/gi, 'approval gated')
    .replace(/blocked human only/gi, 'operator-gated guard')
    .replace(/\blive gate\b/gi, 'execution guard')
    .replace(/\bworker health\b/gi, 'service health')
    .replace(/\bsource pending\b/gi, 'data source connecting')
    .replace(/\bjson\b/gi, 'data')
    .replace(/operator[_\s-]*dashboard/gi, 'dashboard')
    .replace(/\boperator\b/gi, 'approval')
    .replace(/\bpayloads?\b/gi, 'feeds')
    .replace(/\bpaper\b/gi, 'runtime');
}

function payloadState(payload: Record<string, unknown>): string {
  const direct = payload.classification
    ?? payload.status
    ?? payload.go_no_go
    ?? payload.worker_health
    ?? payload.data_status
    ?? payload.platform_status;
  if (direct !== null && direct !== undefined && direct !== '') return publicSafeText(String(direct).replace(/_/g, ' ').toLowerCase());
  return 'feed available';
}

function payloadDetail(payload: Record<string, unknown>): string {
  const candidates = [
    ['symbols', payload.symbols],
    ['accepted symbols', payload.accepted_symbols],
    ['signal rows', payload.prediction_grid_rows ?? payload.prediction_rows ?? payload.prediction_count],
    ['active', payload.active_count],
    ['rows', payload.rows],
    ['events', payload.events_received ?? payload.events_processed],
    ['execution guard', payload.live_gate],
  ] as const;
  const parts = candidates
    .map(([label, value]) => {
      const count = asCount(value);
      if (count !== null) return `${label}: ${count.toLocaleString('en-US')}`;
      if (typeof value === 'string' && value.trim()) return publicSafeText(`${label}: ${value.replace(/_/g, ' ').toLowerCase()}`);
      return null;
    })
    .filter((part): part is string => part !== null)
    .slice(0, 3);
  return parts.length ? parts.join(' / ') : 'summary fields pending';
}

function initialSurfaceStatus(spec: SurfaceSpec): SurfaceStatus {
  return {
    ...spec,
    path: PAYLOAD_PATHS[spec.key],
    available: false,
    ageSeconds: null,
    state: 'stream connecting',
    detail: 'opening realtime resource stream',
    error: null,
  };
}

function makeStatusMap(rows: SurfaceStatus[]): SurfaceStatusMap {
  const map: SurfaceStatusMap = {};
  rows.forEach((row) => {
    map[row.key] = row;
  });
  return map;
}

function payloadRecord(value: unknown): Record<string, unknown> | null {
  if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  if (Array.isArray(value)) return { rows: value.length };
  return null;
}

function envelopeAgeSeconds(envelope: ValidatedDataEnvelope<Record<string, unknown>>): number | null {
  const payload = payloadRecord(envelope.data);
  const payloadAge = payload ? payloadAgeSeconds(payload) : null;
  if (payloadAge !== null) return payloadAge;
  return envelope.received_at ? Math.max(0, Math.round((Date.now() - envelope.received_at) / 1000)) : null;
}

function statusFromResource(
  spec: SurfaceSpec,
  envelope: ValidatedDataEnvelope<Record<string, unknown>>,
  loading: boolean,
  error: string | null,
): SurfaceStatus {
  const payload = payloadRecord(envelope.data);
  const qualityUsable = envelope.data_quality_status === 'valid' || envelope.data_quality_status === 'partial';
  const available = Boolean(payload) && qualityUsable;
  const resourceError = error ?? envelope.errors[0] ?? envelope.warnings[0] ?? null;
  return {
    ...spec,
    path: PAYLOAD_PATHS[spec.key],
    available,
    ageSeconds: available ? envelopeAgeSeconds(envelope) : null,
    state: available && payload ? payloadState(payload) : loading ? 'stream connecting' : 'source connecting',
    detail: available && payload ? payloadDetail(payload) : publicSafeText(resourceError ?? 'opening realtime resource stream'),
    error: resourceError ? publicSafeText(resourceError) : null,
  };
}

function SurfaceStatusCard({ row, mode }: { row: SurfaceStatus; mode: AtlasMode }): JSX.Element {
  const tone = row.available ? ageClass(row.ageSeconds, 300) : 'block';
  return (
    <div className={tone === 'ok' ? 'source-health-grid__ok' : 'source-health-grid__warn'}>
      <span>{row.group}</span>
      <strong>{row.label}</strong>
      <small>{row.state}</small>
      <small>{row.available ? `${fmtAge(row.ageSeconds)} / ${row.detail}` : row.error ?? row.detail}</small>
      {mode === 'system' ? <small><code>{row.path}</code></small> : null}
    </div>
  );
}

function RealtimeAtlasFeedCard({
  spec,
  mode,
  onStatus,
}: {
  spec: SurfaceSpec;
  mode: AtlasMode;
  onStatus: (status: SurfaceStatus) => void;
}): JSX.Element {
  const path = PAYLOAD_PATHS[spec.key];
  const { envelope, loading, error } = useRealtimeResource<Record<string, unknown>>({
    url: path,
    source: path,
    source_type: 'websocket',
    pollIntervalMs: mode === 'public' ? 5_000 : 10_000,
    staleThresholdMs: mode === 'public' ? 20_000 : 30_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });
  const status = useMemo(
    () => statusFromResource(spec, envelope, loading, error),
    [envelope, error, loading, spec],
  );

  useEffect(() => {
    onStatus(status);
  }, [onStatus, status]);

  return <SurfaceStatusCard row={status} mode={mode} />;
}

export function RealtimeDataAtlasPanel({ mode = 'public' }: { mode?: AtlasMode }): JSX.Element {
  const specs = useMemo(
    () => mode === 'public' ? SURFACE_SPECS.filter((spec) => PUBLIC_SURFACE_KEYS.has(spec.key)).map(publicSurfaceSpec) : SURFACE_SPECS,
    [mode],
  );
  const initialRows = useMemo(() => specs.map(initialSurfaceStatus), [specs]);
  const [rowsByKey, setRowsByKey] = useState<SurfaceStatusMap>(() => makeStatusMap(initialRows));

  useEffect(() => {
    setRowsByKey((prev) => makeStatusMap(specs.map((spec) => prev[spec.key] ?? initialSurfaceStatus(spec))));
  }, [specs]);

  const handleStatus = useCallback((status: SurfaceStatus) => {
    setRowsByKey((prev) => {
      if (prev[status.key] === status) return prev;
      return { ...prev, [status.key]: status };
    });
  }, []);

  const rows = useMemo(
    () => specs.map((spec) => rowsByKey[spec.key] ?? initialSurfaceStatus(spec)),
    [rowsByKey, specs],
  );
  const available = rows.filter((row) => row.available).length;
  const current = rows.filter((row) => row.available && ageClass(row.ageSeconds, 300) === 'ok').length;
  const stale = rows.filter((row) => row.available && ageClass(row.ageSeconds, 300) !== 'ok').length;
  const missing = rows.length - available;

  return (
    <section className={`realtime-data-atlas ${mode === 'public' ? 'status-card' : 'cockpit-panel panel bracketed'}`} data-testid={`realtime-data-atlas-${mode}`}>
      <div>
        <span>{mode === 'public' ? 'Realtime data health' : 'Full realtime data atlas'}</span>
        <h2>{available}/{rows.length} data feeds available</h2>
        <p>
          {current} current, {stale} stale or age-unknown, {missing} connecting.
          {mode === 'public' ? ' Public view summarizes safe market, signal, and execution runtime data sources.' : ' System view lists every known frontend runtime data feed.'}
        </p>
      </div>

      <div className="cockpit-lineage-grid" style={{ marginTop: '1rem' }}>
        <div><span>Available sources</span><strong>{available}</strong><small>Readable data sources</small></div>
        <div><span>Current sources</span><strong>{current}</strong><small>Fresh within 5 minutes</small></div>
        <div><span>Needs attention</span><strong>{stale + missing}</strong><small>Stale, age-unknown, or missing</small></div>
      </div>

      <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--compact" role="region" aria-label="Scrollable realtime data atlas" style={{ marginTop: '1rem' }}>
        <div className="source-health-grid">
          {specs.map((spec) => (
            <RealtimeAtlasFeedCard key={spec.key} spec={spec} mode={mode} onStatus={handleStatus} />
          ))}
        </div>
      </div>
    </section>
  );
}
