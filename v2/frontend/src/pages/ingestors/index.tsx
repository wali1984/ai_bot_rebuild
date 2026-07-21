import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Panel } from '../cockpitComponents';
import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';
import { publicRuntimeCopy } from '../../lib/tradeCopy';

const INGESTORS_STATUS_PATH =
  '/operator_runtime/v2_ingestors_status/latest/v2_ingestors_status.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';
const RUNTIME_TRUTH_PATH = '/operator_runtime/v2_runtime_truth/latest/operator_runtime_truth.json';
const NATIVE_INGESTORS_LIVE_PATH = '/operator_runtime/v2_native_ingestors/live/latest/v2_native_ingestors_live_status.json';

interface FreshnessEntry {
  observed_key_count: number;
  storage_ttl_positive_count: number;
  persistent_key_count: number;
  scan_complete: boolean;
  source_event_freshness_inferred_from_ttl: false;
}

interface IngestorEntry {
  name: string;
  service: string;
  status: string;
  active: boolean;
  heartbeat_ttl_seconds: number;
  last_generated_utc: string | null;
  symbols_count: number;
  keys_written_count: number;
  worker_id: string | null;
  control_enabled?: boolean;
  allowed_control_actions?: string[];
  control_endpoint?: string | null;
  runtime_mode?: string;
  trader_execution_enabled?: boolean;
  dynamic_symbol_refresh_enabled?: boolean;
}

interface IngestorsPayload {
  generated_utc: string;
  classification: string;
  active_count: number;
  total_count: number;
  live_gate: string;
  runtime_mode?: string;
  dynamic_symbol_universe_enabled?: boolean;
  dynamic_symbol_refresh_without_restart?: boolean;
  trader_execution_enabled?: boolean;
  website_control_surface?: {
    enabled: boolean;
    allowed_actions: string[];
    blocked_actions: string[];
  };
  ingestors: IngestorEntry[];
  redis_freshness: Record<string, FreshnessEntry>;
}

interface LiveGateRuntimePayload {
  live_gate?: string;
}

interface RuntimeTruth {
  ingestor_active_count?: number;
  ingestor_total_count?: number;
  ingestor_status?: string;
  ta_keys_fresh?: number;
  ta_status?: string;
  feature_ta_coverage?: { ta_keys_fresh?: number; ta_status?: string };
  coinank_status?: string;
  trader_execution_enabled?: boolean;
  live_gate?: string;
}

interface NativeIngestorsLive {
  classification?: string;
  live_gate?: string;
  live_data_enabled?: boolean;
  live_decision_input_enabled?: boolean;
  kline_timeframes?: string[];
  execution_live_symbols?: string[];
  finished_at?: string | null;
}

function statusBadge(active: boolean, status: string): JSX.Element {
  const cls = active ? 'badge--ok' : 'badge--block';
  const label = active ? 'LIVE' : 'STALE';
  return <span className={`badge ${cls}`}>{status || label}</span>;
}

function coreHeartbeatClass(classification: string | undefined): string {
  return classification?.startsWith('INGESTOR_CORE_HEARTBEATS_CURRENT')
    ? 'metric--ok'
    : 'metric--warn';
}

export default function IngestorsPage(): JSX.Element {
  const { data, error, ageSeconds } = usePayloadFile<IngestorsPayload>(
    INGESTORS_STATUS_PATH,
    30_000,
  );
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const { data: runtimeTruth, ageSeconds: runtimeTruthAge } = usePayloadFile<RuntimeTruth>(RUNTIME_TRUTH_PATH, 15_000);
  const { data: nativeLive, ageSeconds: nativeLiveAge } = usePayloadFile<NativeIngestorsLive>(NATIVE_INGESTORS_LIVE_PATH, 30_000);
  // NOTE: ingestor control actions previously POSTed to
  // /api/v1/ingestors/{service}/control, but that v1 router is an OPTIONS-only
  // scaffold — every click returned 404. Controls are rendered disabled until a
  // real control endpoint exists; no fake action state is shown.

  return (
    <article
      className="enterprise-cockpit-page"
      style={{
        background:
          'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)',
      }}
      data-testid="page-ingestors"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Data Ingestors</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="hero-meta">
          <span className={(liveGateRuntime as {live_order_submit_allowed?: boolean} | null)?.live_order_submit_allowed === true ? 'badge badge--ok' : 'badge badge--neutral'}>LIVE_GATE: {(liveGateRuntime as {live_order_submit_allowed?: boolean, live_blocked?: boolean, live_blocker?: string} | null)?.live_blocked === true ? ((liveGateRuntime as {live_blocker?: string} | null)?.live_blocker ?? 'BLOCKED') : (liveGateRuntime?.live_gate ?? 'loading')}</span>
        </div>
      </header>

      <Panel id="ingestors-live-health" title="Live Ingestor Health (Real-Time)" right={<span className={`chip solid-${(runtimeTruthAge ?? 999) < 60 ? 'ok' : 'warn'}`}>Runtime truth: {fmtAge(runtimeTruthAge)}</span>}>
        <div className="cockpit-analytics-grid">
          <div className="metric">
            <span className="metric-label">Active ingestors</span>
            <span className={`metric-value ${(runtimeTruth?.ingestor_active_count ?? 0) > 0 ? 'metric--ok' : 'metric--warn'}`}>
              {runtimeTruth?.ingestor_active_count ?? '—'} / {runtimeTruth?.ingestor_total_count ?? '—'}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Ingestor health</span>
            <span className={`metric-value ${coreHeartbeatClass(runtimeTruth?.ingestor_status)}`}>
                  {publicRuntimeCopy(runtimeTruth?.ingestor_status)}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">TA keys fresh</span>
            <span className="metric-value metric--ok">
              {runtimeTruth?.feature_ta_coverage?.ta_keys_fresh ?? runtimeTruth?.ta_keys_fresh ?? '—'}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">TA status</span>
            <span className={`metric-value ${(runtimeTruth?.feature_ta_coverage?.ta_status ?? runtimeTruth?.ta_status ?? '').includes('OK') ? 'metric--ok' : 'metric--warn'}`}>
              {runtimeTruth?.feature_ta_coverage?.ta_status ?? runtimeTruth?.ta_status ?? '—'}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">CoinAnk status</span>
            <span className={`metric-value ${(runtimeTruth?.coinank_status ?? '').includes('OK') ? 'metric--ok' : 'metric--warn'}`}>
              {runtimeTruth?.coinank_status ?? '—'}
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Native live gate</span>
            <span className="metric-value">{nativeLive?.live_gate ?? liveGateRuntime?.live_gate ?? '—'}</span>
          </div>
          <div className="metric">
            <span className="metric-label">Native classification</span>
            <span className={`metric-value ${(nativeLive?.classification ?? '').includes('OK') || (nativeLive?.classification ?? '').includes('READY') ? 'metric--ok' : 'metric--warn'}`}>
              {publicRuntimeCopy(nativeLive?.classification)} ({fmtAge(nativeLiveAge)})
            </span>
          </div>
          <div className="metric">
            <span className="metric-label">Kline timeframes</span>
            <span className="metric-value">{nativeLive?.kline_timeframes?.join(', ') ?? '—'}</span>
          </div>
        </div>
        <p className="cockpit-evidence-note">
          Sources: {RUNTIME_TRUTH_PATH} + {NATIVE_INGESTORS_LIVE_PATH}. This panel is always fresh.
        </p>
      </Panel>

      {error && <p className="cockpit-evidence-gap">Historical ingestor detail payload unavailable: {error}</p>}

      {data && (
        <>
          <Panel id="ingestors-summary" title="Ingestor Summary (Cached Snapshot)" right={<span className={`chip solid-${(ageSeconds ?? 999) < 600 ? 'ok' : 'warn'}`}>age: {fmtAge(ageSeconds)}</span>}>
            <div className="cockpit-analytics-grid">
              <div className="metric">
                <span className="metric-label">Classification</span>
                <span className={`metric-value ${coreHeartbeatClass(data.classification)}`}>
                  {publicRuntimeCopy(data.classification)}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Active / Total</span>
                <span className="metric-value">{data.active_count} / {data.total_count}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Payload age</span>
                <span className={`metric-value metric--${ageClass(ageSeconds, 60)}`}>
                  {fmtAge(ageSeconds)}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Live gate</span>
                <span className="metric-value metric--block">{publicRuntimeCopy(data.live_gate)}</span>
              </div>
              <div className="metric">
                <span className="metric-label">Dynamic symbols</span>
                <span className={`metric-value ${data.dynamic_symbol_refresh_without_restart ? 'metric--ok' : 'metric--warn'}`}>
                  {data.dynamic_symbol_refresh_without_restart ? 'auto-refresh' : 'manual'}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Trader execution</span>
                <span className="metric-value metric--block">
                  {String(data.trader_execution_enabled ?? false)}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Website controls</span>
                <span className={`metric-value ${data.website_control_surface?.enabled ? 'metric--ok' : 'metric--warn'}`}>
                  {data.website_control_surface?.enabled ? 'enabled' : 'blocked'}
                </span>
              </div>
            </div>
          </Panel>

          <Panel id="ingestors-table" title="Ingestor Status">
            <div className="cockpit-table-wrap">
              <table className="cockpit-table">
                <thead>
                  <tr>
                    <th>Ingestor</th>
                    <th>Service</th>
                    <th>Status</th>
                    <th>TTL (s)</th>
                    <th>Symbols</th>
                    <th>Keys written</th>
                    <th>Last generated</th>
                    <th>Controls</th>
                  </tr>
                </thead>
                <tbody>
                  {data.ingestors.map((ing) => (
                    <tr key={ing.name} className={ing.active ? '' : 'row--warn'}>
                      <td><strong>{publicRuntimeCopy(ing.name)}</strong></td>
                      <td><code className="monospace small">{publicRuntimeCopy(ing.service)}</code></td>
                      <td>{statusBadge(ing.active, publicRuntimeCopy(ing.status))}</td>
                      <td className={ing.heartbeat_ttl_seconds > 0 ? 'metric--ok' : 'metric--block'}>
                        {ing.heartbeat_ttl_seconds}
                      </td>
                      <td>{ing.symbols_count ?? '—'}</td>
                      <td>{ing.keys_written_count ?? '—'}</td>
                      <td className="small">{ing.last_generated_utc ?? '—'}</td>
                      <td>
                        <div className="ingestor-actions" aria-label={`${ing.name} controls`}>
                          {(ing.allowed_control_actions ?? []).map((action) => (
                            <button
                              key={action}
                              type="button"
                              className="ingestor-action-button"
                              disabled
                              title={`${action} ${ing.service} — control API not implemented (/api/v1/ingestors control is a scaffold that returns 404); button disabled instead of failing silently`}
                            >
                              {action}
                            </button>
                          ))}
                        </div>
                        <small className="small">{ing.dynamic_symbol_refresh_enabled ? 'dynamic' : 'controls not wired'}</small>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          <Panel id="ingestors-freshness" title="Redis Key Retention (Not Source Freshness)">
            <div className="cockpit-analytics-grid">
              {Object.entries(data.redis_freshness).map(([label, f]) => (
                <div key={label} className="metric">
                  <span className="metric-label">{label}</span>
                  <span className="metric-value">
                    {f.storage_ttl_positive_count} expiring / {f.persistent_key_count} persistent /{' '}
                    {f.observed_key_count} observed
                  </span>
                  <small className="small">
                    {f.scan_complete ? 'complete bounded scan' : 'truncated bounded scan'}; TTL does not prove
                    source-event freshness
                  </small>
                </div>
              ))}
            </div>
          </Panel>
        </>
      )}
    </article>
  );
}
