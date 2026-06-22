import meta from './meta';
import rbac from './rbac';
import route from './route';
import { DesignPageShell } from '../designShell';
import { usePayloadFile } from '../../hooks/usePayloadFile';
import { publicRuntimeCopy } from '../../lib/tradeCopy';

const EXEC_PAYLOAD_PATH = '/v2_report_center/latest/executive_status_payload.json';
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface BigStateEntry {
  key: string;
  value: 'YES' | 'NO' | string;
  plain_english: string;
  evidence?: Record<string, unknown>;
}

interface BlockerEntry {
  key: string;
  plain_english: string;
  evidence?: Record<string, unknown>;
}

interface ProgressBlock {
  plain_english: string;
  [k: string]: unknown;
}

interface NextActionEntry {
  key: string;
  owner: string;
  plain_english: string;
  blocks?: string[];
}

interface ExecutiveSummary {
  schema_version?: string;
  headline?: string;
  big_state_banner?: BigStateEntry[];
  top_blockers_plain?: BlockerEntry[];
  current_progress?: Record<string, ProgressBlock>;
  plain_english_truth?: string;
  next_required_actions?: NextActionEntry[];
  marker_glossary?: Record<string, string>;
  safety_invariants_plain_english?: string[];
  live_gate?: string;
  live_symbols?: string[];
}

interface ExecutiveStatusPayload {
  schema_version?: string;
  generated_at?: string;
  executive_summary?: ExecutiveSummary;
  report_aggregates?: Record<string, number>;
  current_scorecard_overall_score?: number;
  live_gate?: string;
  live_symbols?: string[];
}

interface LiveGateRuntimePayload {
  live_gate?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
}

function listText(items: string[] | undefined): string {
  if (!items?.length) return 'none';
  return items.join(', ');
}

function payloadAge(generatedAt?: string): number | null {
  if (!generatedAt) return null;
  const ms = new Date(generatedAt).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.round((Date.now() - ms) / 1000));
}

function formatFreshness(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'no payload';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  if (seconds < 60 * 60) return `${Math.round(seconds / 60)}m`;
  if (seconds < 60 * 60 * 24) return `${Math.round(seconds / 3600)}h`;
  return `${Math.round(seconds / 86400)}d`;
}

function toneForYesNo(value: string | undefined): 'ok' | 'block' | 'warn' | 'paper' {
  if (value === 'YES') return 'ok';
  if (value === 'NO') return 'block';
  return 'warn';
}

function BigStateBannerInline({ exec }: { exec: ExecutiveSummary | undefined }): JSX.Element {
  const entries = exec?.big_state_banner ?? [];
  return (
    <section
      className="report-overview-grid"
      aria-label="Executive big state banner"
      data-testid="executive-big-state-banner"
    >
      {entries.length === 0 ? (
        <div className="report-callout report-callout--warn">
          <strong>Executive summary payload is missing.</strong>
          <span>Showing safe defaults: nothing is approved.</span>
        </div>
      ) : null}
      {entries.map((e) => {
        const tone = toneForYesNo(e.value);
        return (
          <div
            key={e.key}
            className={`report-metric-card report-metric-card--${tone}`}
            data-testid={`exec-state-${e.key}`}
          >
            <span>{publicRuntimeCopy(e.key.replace(/_/g, ' '))}</span>
            <strong>{e.value}</strong>
            <small>{publicRuntimeCopy(e.plain_english)}</small>
          </div>
        );
      })}
    </section>
  );
}

function PlainEnglishTruthPanel({ exec }: { exec: ExecutiveSummary | undefined }): JSX.Element {
  return (
    <section className="report-panel report-panel--span" aria-label="Plain-English current truth">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Plain-English Truth</p>
          <h2>Where we actually are right now</h2>
        </div>
        <span className="chip">live telemetry</span>
      </div>
      <p>{publicRuntimeCopy(exec?.plain_english_truth, 'No truth statement in payload.')}</p>
      {exec?.headline ? (
        <pre className="report-fact-grid" aria-label="Executive headline">
          <code>{publicRuntimeCopy(exec.headline)}</code>
        </pre>
      ) : null}
    </section>
  );
}

function TopBlockersPanel({ exec }: { exec: ExecutiveSummary | undefined }): JSX.Element {
  const blockers = exec?.top_blockers_plain ?? [];
  return (
    <section className="report-panel report-panel--span" aria-label="Top blockers in plain English">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Top Blockers</p>
          <h2>What is blocking</h2>
        </div>
        <span className={blockers.length ? 'chip solid-block' : 'chip solid-ok'}>
          {blockers.length} blockers
        </span>
      </div>
      {blockers.length === 0 ? (
        <p className="report-empty">No active blockers in payload.</p>
      ) : (
        <div className="report-card-list">
          {blockers.map((b) => (
            <article
              className="report-work-card report-work-card--block"
              key={b.key}
              data-testid={`exec-blocker-${b.key}`}
            >
              <strong>{publicRuntimeCopy(b.key.replace(/_/g, ' '))}</strong>
              <p>{publicRuntimeCopy(b.plain_english)}</p>
              {b.evidence ? (
                <small>
                  {Object.entries(b.evidence)
                    .map(([k, v]) => `${publicRuntimeCopy(k)}=${publicRuntimeCopy(String(v))}`)
                    .join(' · ')}
                </small>
              ) : null}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function CurrentProgressPanel({ exec }: { exec: ExecutiveSummary | undefined }): JSX.Element {
  const progress = exec?.current_progress ?? {};
  const entries = Object.entries(progress);
  return (
    <section className="report-panel report-panel--span" aria-label="Current progress">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Current Progress</p>
          <h2>What is actually running</h2>
        </div>
        <span className="chip">{entries.length} components</span>
      </div>
      {entries.length === 0 ? (
        <p className="report-empty">No progress block in payload.</p>
      ) : (
        <div className="report-card-list">
          {entries.map(([name, body]) => (
            <article
              className="report-work-card"
              key={name}
              data-testid={`exec-progress-${name}`}
            >
              <strong>{publicRuntimeCopy(name.replace(/_/g, ' '))}</strong>
              <p>{publicRuntimeCopy(body?.plain_english ?? '')}</p>
              <small>
                {Object.entries(body ?? {})
                  .filter(([k]) => k !== 'plain_english')
                  .map(([k, v]) => `${publicRuntimeCopy(k)}=${publicRuntimeCopy(typeof v === 'object' ? JSON.stringify(v) : String(v))}`)
                  .join(' · ')}
              </small>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function NextActionsPanel({ exec }: { exec: ExecutiveSummary | undefined }): JSX.Element {
  const actions = exec?.next_required_actions ?? [];
  return (
    <section className="report-panel report-panel--span" aria-label="Next required actions">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Next Required Actions</p>
          <h2>What to do next</h2>
        </div>
        <span className="chip">{actions.length} actions</span>
      </div>
      {actions.length === 0 ? (
        <p className="report-empty">No next actions in payload.</p>
      ) : (
        <div className="report-card-list">
          {actions.map((a) => (
            <article
              className={
                a.owner === 'OPERATOR'
                  ? 'report-work-card report-work-card--warn'
                  : 'report-work-card'
              }
              key={a.key}
              data-testid={`exec-next-action-${a.key}`}
            >
              <strong>{publicRuntimeCopy(a.key.replace(/_/g, ' '))}</strong>
              <p>{publicRuntimeCopy(a.plain_english)}</p>
              <div className="report-chip-row">
                <span
                  className={
                    a.owner === 'OPERATOR' ? 'chip solid-warn' : 'chip solid-paper'
                  }
                >
                  owner {a.owner}
                </span>
                {(a.blocks ?? []).map((b) => (
                  <span className="chip" key={`${a.key}-${b}`}>
                    blocks {publicRuntimeCopy(b.replace(/_/g, ' '))}
                  </span>
                ))}
              </div>
            </article>
          ))}
        </div>
      )}
    </section>
  );
}

function MarkerGlossaryPanel({ exec }: { exec: ExecutiveSummary | undefined }): JSX.Element {
  const glossary = Object.entries(exec?.marker_glossary ?? {});
  return (
    <section className="report-panel report-panel--span" aria-label="Plain-English marker glossary">
      <div className="report-panel__head">
        <div>
          <p className="eyebrow">Marker Glossary</p>
          <h2>Plain English for every technical marker</h2>
        </div>
        <span className="chip">{glossary.length} markers</span>
      </div>
      {glossary.length === 0 ? (
        <p className="report-empty">No glossary in payload.</p>
      ) : (
        <div className="report-lane-table" role="table">
          <div className="report-lane-row report-lane-row--head" role="row">
            <span>Marker</span>
            <span>Plain English</span>
          </div>
          {glossary.map(([marker, english]) => (
            <div className="report-lane-row" role="row" key={marker}>
              <code>{publicRuntimeCopy(marker)}</code>
              <span>{publicRuntimeCopy(english)}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function SafetyInvariantsPanel({ exec, liveGateRuntime }: { exec: ExecutiveSummary | undefined; liveGateRuntime?: LiveGateRuntimePayload | null }): JSX.Element {
  const items = exec?.safety_invariants_plain_english ?? [];
  const liveGate = liveGateRuntime?.live_gate ?? exec?.live_gate ?? 'loading';
  const liveSymbols = liveGateRuntime?.execution_live_symbols ?? liveGateRuntime?.live_symbols ?? exec?.live_symbols;
  return (
    <section className="report-safety-banner" role="status" aria-label="Safety invariants">
      <div>
        {items.length === 0 ? (
          <strong>Safety invariants payload missing — defaults apply.</strong>
        ) : (
          items.map((line) => <strong key={line}>{publicRuntimeCopy(line)}</strong>)
        )}
      </div>
      <div className="report-safety-banner__facts">
        <code>live_gate={publicRuntimeCopy(liveGate)}</code>
        <code>execution_symbols={publicRuntimeCopy(listText(liveSymbols))}</code>
        <code>approves_live=false</code>
        <code>approves_canary=false</code>
        <code>approves_legacy_shutdown=false</code>
        <code>approves_redis_trim=false</code>
      </div>
    </section>
  );
}

export default function ExecutiveStatusPage(): JSX.Element {
  const payloadQ = usePayloadFile<ExecutiveStatusPayload>(EXEC_PAYLOAD_PATH, 15_000);
  const liveGateQ = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);

  const exec = payloadQ.data?.executive_summary;
  const failed = payloadQ.error;

  return (
    <DesignPageShell
      meta={meta}
      rbac={rbac}
      route={route}
      eyebrow="Executive Clarity"
      source="V2_REPORT_CENTER_EXECUTIVE_STATUS_PAYLOAD"
      status="CLARITY LAYER · NO APPROVALS"
    >
      <SafetyInvariantsPanel exec={exec} liveGateRuntime={liveGateQ.data} />

      {failed ? (
        <section
          className="report-error-banner"
          role="alert"
          aria-label="Executive payload stale or connecting"
        >
          <strong>EXECUTIVE_STATUS_PAYLOAD_STALE_OR_UNAVAILABLE</strong>
          <span>
            Executive summary failed to load. Defaults apply: nothing is migrated,
            nothing is ready for live, nothing is approved.
          </span>
        </section>
      ) : null}

      <section className="report-title-band" aria-label="Executive summary header">
        <div>
          <p className="eyebrow">Five Questions, Five Answers</p>
          <h1>Executive status</h1>
          <p>
            Plain-English answers to: Are we migrated? Can legacy shut down? Can
            we go live? What is blocking? What is the next action? This view is a
            clarity layer over the report center; it cannot enable live, cancel
            shutdown, or adopt symbols.
          </p>
        </div>
        <div className="report-refresh-strip" aria-label="Realtime refresh status">
          <span className={payloadQ.loading ? 'report-pulse report-pulse--active' : 'report-pulse'} />
          <div>
            <strong>{payloadQ.loading ? 'Streaming executive payload' : 'Live resource stream active'}</strong>
            <small>WebSocket resource stream · API fallback enabled</small>
          </div>
          <code>payload age {formatFreshness(payloadAge(payloadQ.data?.generated_at))}</code>
        </div>
      </section>

      <BigStateBannerInline exec={exec} />

      <PlainEnglishTruthPanel exec={exec} />

      <div className="report-dashboard-grid">
        <TopBlockersPanel exec={exec} />
        <CurrentProgressPanel exec={exec} />
        <NextActionsPanel exec={exec} />
        <MarkerGlossaryPanel exec={exec} />
      </div>
    </DesignPageShell>
  );
}
