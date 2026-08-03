import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Metric, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload, useTonightReadinessPayload } from '../operatorTruthData';
import { OperatorTruthLoading, PaperOnlineRuntimeStatusPanel, RouteTruthSummary } from '../operatorTruthComponents';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface NoMutationFlags {
  real_order_attempted?: boolean;
  real_order_submitted?: boolean;
  test_order_submitted?: boolean;
  leverage_changed?: boolean;
  margin_mode_changed?: boolean;
  places_real_order?: boolean;
  routes_to_live?: boolean;
}

interface LiveCanaryStatusData {
  selected_a_plus_candidate?: unknown;
  why_none?: string;
  dry_run?: boolean;
  operator_approval_required?: boolean;
  no_mutation_flags?: NoMutationFlags;
  order_builder_dry_run?: unknown;
  post_only_plan?: unknown;
  maker_first_plan?: unknown;
  taker_fallback_reason?: string | null;
  hedge_plan?: unknown;
  reduce_close_path?: unknown;
  emergency_stop?: unknown;
  symbol_filters?: unknown;
  commission_rates?: unknown;
}

interface APlusInventoryData {
  evaluated_candidates?: number;
  a_plus_candidates?: number;
  live_ready_rows?: number;
  exact_no_a_plus_reason?: string | null;
  top_a_plus_blockers?: string[] | null;
  rejected_reason_matrix?: Record<string, number> | null;
  counts_as_final_a_plus?: boolean;
  candidate_matrix_preview?: Array<{ symbol?: string; side?: string; timeframe?: string; failed_checks?: string[] }>;
  a_plus_preview?: Array<{ symbol?: string; side?: string; timeframe?: string }>;
}

function boolText(value: unknown): string {
  if (value === true) return 'true';
  if (value === false) return 'false';
  return 'MISSING_EVIDENCE';
}

function compactValue(value: unknown): string {
  if (value === null || value === undefined || value === '') return 'MISSING_EVIDENCE';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value).slice(0, 180);
  } catch {
    return 'UNREADABLE_EVIDENCE';
  }
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value;
    if (Array.isArray(value)) {
      const first = value.find((item) => typeof item === 'string' && item.trim());
      if (typeof first === 'string') return first;
    }
  }
  return null;
}

function aPlusWhyNone(liveCanary?: LiveCanaryStatusData | null, aPlus?: APlusInventoryData | null): string {
  const previewFailedCheck = aPlus?.candidate_matrix_preview
    ?.flatMap((row) => row.failed_checks ?? [])
    .find((reason) => typeof reason === 'string' && reason.trim());
  return firstText(
    liveCanary?.why_none,
    aPlus?.exact_no_a_plus_reason,
    aPlus?.top_a_plus_blockers,
    previewFailedCheck,
  ) ?? 'A_PLUS_GATE_REASON_UNAVAILABLE';
}

function mutationSafe(flags?: NoMutationFlags): boolean {
  return !(flags?.real_order_attempted ?? false)
    && !(flags?.real_order_submitted ?? false)
    && !(flags?.test_order_submitted ?? false)
    && !(flags?.leverage_changed ?? false)
    && !(flags?.margin_mode_changed ?? false)
    && !(flags?.places_real_order ?? false)
    && !(flags?.routes_to_live ?? false);
}

export default function LiveReadinessPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  const { payload: tonightPayload } = useTonightReadinessPayload();
  const { envelope: liveCanaryEnvelope, loading: liveCanaryLoading, error: liveCanaryError } = useRealtimeResource<LiveCanaryStatusData>({
    url: '/api/v2/live-canary/status',
    source: 'live-canary-status',
    pollIntervalMs: 5_000,
    staleThresholdMs: 15_000,
    unwrapEnvelopeData: 'contract',
  });
  const { envelope: aPlusEnvelope, loading: aPlusLoading, error: aPlusError } = useRealtimeResource<APlusInventoryData>({
    url: '/api/v2/a-plus/inventory',
    source: 'live-canary-a-plus-inventory',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    unwrapEnvelopeData: 'contract',
  });
  const liveCanary = liveCanaryEnvelope.data;
  const aPlus = aPlusEnvelope.data;
  const flags = liveCanary?.no_mutation_flags;
  const selectedCandidate = compactValue(liveCanary?.selected_a_plus_candidate);
  const whyNone = aPlusWhyNone(liveCanary, aPlus);

  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Live Readiness" source="GO_NO_GO / final live gate policy" status="FINAL LIVE CAPITAL APPROVAL REQUIRED">
      <SourceRibbon labels={['operator gated', 'human-only final gate', 'dangerous controls disabled', 'execution/shadow first']} />
      <Panel id="live-canary-runtime-truth" title="Live Canary Runtime Truth" right={<span className="chip solid-block">LIVE CANARY BLOCKED</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Selected A+ candidate" value={selectedCandidate} />
          <Metric label="Why none" value={whyNone} />
          <Metric label="A+ candidates" value={aPlus?.a_plus_candidates ?? 'MISSING_EVIDENCE'} />
          <Metric label="Live-ready rows" value={aPlus?.live_ready_rows ?? 'MISSING_EVIDENCE'} />
          <Metric label="Evaluated candidates" value={aPlus?.evaluated_candidates ?? 'MISSING_EVIDENCE'} />
          <Metric label="Dry run" value={boolText(liveCanary?.dry_run)} />
          <Metric label="Operator approval required" value={boolText(liveCanary?.operator_approval_required)} />
          <Metric label="No mutation flags" value={mutationSafe(flags) ? 'NO_ORDER_TEST_LEVERAGE_MARGIN_MUTATION' : 'MUTATION_FLAG_PRESENT'} />
          <Metric label="Live gate" value={liveCanaryEnvelope.data ? 'blocked_human_only' : 'MISSING_EVIDENCE'} />
          <Metric label="Realtime source" value={liveCanaryEnvelope.source} detail={liveCanaryEnvelope.freshness_status} />
        </div>
        <div className="cockpit-card-grid">
          <div className="cockpit-evidence-gap">
            <strong>Order builder dry run</strong>
            <p>{compactValue(liveCanary?.order_builder_dry_run ?? liveCanary?.post_only_plan ?? liveCanary?.maker_first_plan)}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Taker fallback reason</strong>
            <p>{compactValue(liveCanary?.taker_fallback_reason)}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Hedge plan</strong>
            <p>{compactValue(liveCanary?.hedge_plan)}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Reduce / close path</strong>
            <p>{compactValue(liveCanary?.reduce_close_path)}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Emergency stop</strong>
            <p>{compactValue(liveCanary?.emergency_stop)}</p>
          </div>
          <div className="cockpit-evidence-gap">
            <strong>Canonical endpoints</strong>
            <p>/api/v2/live-canary/status · /api/v2/a-plus/inventory</p>
          </div>
        </div>
        {(liveCanaryLoading || aPlusLoading || liveCanaryError || aPlusError) ? (
          <p className="cockpit-evidence-gap" role={liveCanaryError || aPlusError ? 'alert' : undefined}>
            Live canary canonical status: {liveCanaryLoading || aPlusLoading ? 'connecting' : 'loaded'} · errors: {liveCanaryError ?? aPlusError ?? 'none'}
          </p>
        ) : null}
        <p className="cockpit-evidence-gap">
          Live canary cannot submit live or test orders from this page. Operator approval remains required and live remains blocked_human_only until backend contracts prove an independent A+ candidate.
        </p>
      </Panel>
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Live Readiness" /> : <OperatorTruthLoading error={truthError} />}
      <PaperOnlineRuntimeStatusPanel payload={paperRuntime} />
      {payload ? (
        <Panel id="live-readiness-hard-stop" title="Live Readiness Hard Stop" right={<span className="chip solid-block">LIVE BLOCKED</span>}>
          <div className="cockpit-analytics-grid">
            <Metric label="Live gate" value={payload.live_gate_status} />
            <Metric label="Account mode" value={payload.account_mode} />
            <Metric label="Supervisor truth" value={truthPayload?.supervisor_status.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'} />
            <Metric label="Trainer runtime" value={truthPayload?.trainer_monitor_status.status ?? 'MISSING_EVIDENCE'} />
            <Metric label="Stale payloads" value={truthPayload?.dashboard_freshness_status.stale_payload_count ?? 'MISSING_EVIDENCE'} />
            <Metric label="Missing evidence" value={truthPayload?.dashboard_freshness_status.missing_evidence_count ?? 'MISSING_EVIDENCE'} />
          </div>
          <div className="cockpit-card-grid">
            {payload.blockers.map((row) => (
              <div className="cockpit-evidence-gap" key={row.id}>
                <strong>{row.id}</strong>
                <p>{row.status}: {row.detail}</p>
              </div>
            ))}
            <div className="cockpit-evidence-gap">
              Final live/capital approval is not reached. Real orders, cancels, live keys, leverage, margin mode, and live deployment remain blocked.
            </div>
          </div>
        </Panel>
      ) : <CockpitLoading error={error} />}
      <Panel id="live-like-risk-profile" title="Live-Like Execution / Shadow Risk Profile" right={<span className="chip solid-block">CANARY BLOCKED</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Tonight status" value={tonightPayload?.status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Risk profile" value={tonightPayload?.risk_profile_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Canary preflight" value={tonightPayload?.canary_preflight_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="V2 execution runtime" value={tonightPayload?.v2_paper_runtime_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Legacy bridge" value={tonightPayload?.legacy_bridge_status ?? 'MISSING_EVIDENCE'} />
          <Metric label="Public route failures" value={tonightPayload?.public_route_failed_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Old Redis writes" value={String(tonightPayload?.old_redis_writes ?? false)} />
          <Metric label="Exchange actions" value={String(tonightPayload?.exchange_actions ?? false)} />
        </div>
        <p className="cockpit-evidence-gap">
          Live order routing and canary activation remain blocked_human_only. This page displays the preflight/risk profile only; it cannot approve or execute live orders.
        </p>
        {tonightPayload?.remaining_blockers?.length ? (
          <div className="missing-evidence-board">
            {tonightPayload.remaining_blockers.slice(0, 8).map((blocker) => (
              <div className="missing-evidence-card" key={blocker}>
                <strong>{blocker}</strong>
                <p>Resolve before any final human canary approval packet is considered.</p>
              </div>
            ))}
          </div>
        ) : null}
      </Panel>
    </DesignPageShell>
  );
}
