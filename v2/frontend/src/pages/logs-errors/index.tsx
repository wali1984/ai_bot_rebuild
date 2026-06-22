import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Panel } from '../cockpitComponents';
import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';

const LOG_INTELLIGENCE_PATH =
  '/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json';
const CONTINUOUS_REMEDIATION_PATH =
  '/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation_status.json';
const SCRIPT_MONITOR_PATH =
  '/operator_runtime/v2_script_monitor/latest/v2_script_monitor_status.json';
const LOG_ERRORS_STATUS_PATH =
  '/operator_runtime/v2_log_errors_status/latest/v2_log_errors_status.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface RemediationHint {
  id: string;
  severity: string;
  first_seen: string;
  last_seen: string;
  source_log_or_script: string;
  legacy_evidence: string;
  v2_evidence: string;
  recommended_claude_task: string;
}

interface LogIntelligencePayload {
  generated_at: string;
  heartbeat_at: string;
  freshness_seconds: number;
  approves_live: boolean;
  latest_remediation_hints: RemediationHint[];
}

interface ContinuousRemediationPayload {
  generated_at?: string;
  generated_utc?: string;
  status?: string;
  remediation_cycles?: number;
  active_blockers?: string[];
  resolved_blockers?: string[];
}

interface LogErrorsStatus {
  generated_utc: string;
  classification: string;
  v2_failed_services: number;
  error_count_24h: number;
  warn_count_24h: number;
  live_gate: string;
}

interface LiveGateRuntimePayload {
  live_gate?: string;
}

function severityClass(s: string): string {
  if (s === 'ERROR' || s === 'CRITICAL') return 'metric--block';
  if (s === 'WARN' || s === 'WARNING') return 'metric--warn';
  return 'metric--neutral';
}

export default function LogsErrorsPage(): JSX.Element {
  const { data: logData, error: logError, ageSeconds: logAge } =
    usePayloadFile<LogIntelligencePayload>(LOG_INTELLIGENCE_PATH, 30_000);
  const { data: remData, ageSeconds: remAge } =
    usePayloadFile<ContinuousRemediationPayload>(CONTINUOUS_REMEDIATION_PATH, 30_000);
  const { data: errStatus } =
    usePayloadFile<LogErrorsStatus>(LOG_ERRORS_STATUS_PATH, 60_000);
  const { data: liveGateRuntime } =
    usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);

  return (
    <article
      className="enterprise-cockpit-page"
      data-testid="page-logs-errors"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">System Logs &amp; Errors</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="hero-meta">
          <span className="badge badge--neutral">read-only · V2 namespace</span>
        </div>
      </header>

      {errStatus && (
        <Panel id="logs-summary" title="Error / Warning Summary">
          <div className="cockpit-analytics-grid">
            <div className="metric">
              <span className="metric-label">Classification</span>
              <span className={`metric-value ${errStatus.classification?.includes('OK') ? 'metric--ok' : 'metric--warn'}`}>
                {errStatus.classification}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Failed V2 services</span>
              <span className={`metric-value ${errStatus.v2_failed_services === 0 ? 'metric--ok' : 'metric--block'}`}>
                {errStatus.v2_failed_services}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Errors (24h)</span>
              <span className={`metric-value ${errStatus.error_count_24h === 0 ? 'metric--ok' : 'metric--block'}`}>
                {errStatus.error_count_24h}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Warnings (24h)</span>
              <span className={`metric-value ${errStatus.warn_count_24h === 0 ? 'metric--ok' : 'metric--warn'}`}>
                {errStatus.warn_count_24h}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Live gate</span>
              <span className={`metric-value ${(liveGateRuntime as {live_order_submit_allowed?: boolean} | null)?.live_order_submit_allowed === true ? 'metric--ok' : 'metric--warn'}`}>
                {(liveGateRuntime as {live_order_submit_allowed?: boolean, live_blocked?: boolean, live_blocker?: string} | null)?.live_order_submit_allowed === false || (liveGateRuntime as {live_blocked?: boolean} | null)?.live_blocked === true
                  ? ((liveGateRuntime as {live_blocker?: string} | null)?.live_blocker ?? 'BLOCKED')
                  : (liveGateRuntime?.live_gate ?? errStatus.live_gate)}
              </span>
            </div>
          </div>
        </Panel>
      )}

      <Panel id="logs-log-intelligence" title="Legacy Log Intelligence Observer">
        {logError ? (
          <p className="cockpit-evidence-gap">
            Log intelligence payload unavailable: {logError}
          </p>
        ) : logData ? (
          <>
            <div className="cockpit-analytics-grid">
              <div className="metric">
                <span className="metric-label">Heartbeat age</span>
                <span className={`metric-value metric--${ageClass(logAge, 120)}`}>
                  {fmtAge(logAge)}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Approves live</span>
                <span className={`metric-value ${logData.approves_live ? 'metric--ok' : 'metric--block'}`}>
                  {String(logData.approves_live)}
                </span>
              </div>
              <div className="metric">
                <span className="metric-label">Hints count</span>
                <span className="metric-value">
                  {logData.latest_remediation_hints?.length ?? 0}
                </span>
              </div>
            </div>
            {logData.latest_remediation_hints && logData.latest_remediation_hints.length > 0 && (
              <div className="cockpit-table-wrap" style={{ marginTop: '1rem' }}>
                <table className="cockpit-table">
                  <thead>
                    <tr>
                      <th>Severity</th>
                      <th>ID</th>
                      <th>Source</th>
                      <th>Evidence</th>
                      <th>V2 Coverage</th>
                    </tr>
                  </thead>
                  <tbody>
                    {logData.latest_remediation_hints.map((h, i) => (
                      <tr key={`${h.id}-${i}`}>
                        <td className={severityClass(h.severity)}>{h.severity}</td>
                        <td><code className="monospace small">{h.id}</code></td>
                        <td className="small">{h.source_log_or_script?.split('/').pop() ?? '—'}</td>
                        <td className="small">{h.legacy_evidence}</td>
                        <td className="small">{h.v2_evidence}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </>
        ) : (
          <p className="cockpit-evidence-gap">Loading log intelligence data…</p>
        )}
      </Panel>

      {remData && (
        <Panel id="logs-remediation" title="Continuous Remediation Status">
          <div className="cockpit-analytics-grid">
            <div className="metric">
              <span className="metric-label">Status</span>
              <span className={`metric-value ${remData.status?.includes('OK') ? 'metric--ok' : 'metric--warn'}`}>
                {remData.status ?? '—'}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Remediation cycles</span>
              <span className="metric-value">{remData.remediation_cycles ?? '—'}</span>
            </div>
            <div className="metric">
              <span className="metric-label">Active blockers</span>
              <span className={`metric-value ${(remData.active_blockers?.length ?? 0) === 0 ? 'metric--ok' : 'metric--warn'}`}>
                {remData.active_blockers?.length ?? 0}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Resolved blockers</span>
              <span className="metric-value metric--ok">
                {remData.resolved_blockers?.length ?? 0}
              </span>
            </div>
            <div className="metric">
              <span className="metric-label">Payload age</span>
              <span className={`metric-value metric--${ageClass(remAge, 300)}`}>
                {fmtAge(remAge)}
              </span>
            </div>
          </div>
        </Panel>
      )}
    </article>
  );
}
