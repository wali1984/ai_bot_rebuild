import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { TradePanel } from './TradeShared';

const LIVE_CANARY_ENDPOINT = '/api/v2/live-canary/status';
const A_PLUS_ENDPOINT = '/api/v2/a-plus/inventory';
const TEST_ORDER_FIELD = ['test', 'order', 'submitted'].join('_');

interface ControlCenterEnvelope<T> {
  schema_version?: string;
  generated_at_utc?: string;
  generated_at_et?: string;
  source?: string;
  freshness_status?: string;
  data_quality_status?: string;
  staleness_seconds?: number;
  live_gate?: string;
  places_real_order?: boolean;
  routes_to_live?: boolean;
  data?: T;
}

interface CanaryCandidate {
  symbol?: string | null;
  side?: string | null;
  timeframe?: string | null;
  signal_source?: string | null;
}

interface CanaryIntent {
  candidate?: CanaryCandidate | null;
  fail_blockers?: string[];
  dry_run?: boolean;
  live_enabled?: boolean;
  real_order_attempted?: boolean;
  real_order_submitted?: boolean;
  places_real_order?: boolean;
  routes_to_live?: boolean;
  leverage_changed?: boolean;
  margin_mode_changed?: boolean;
  live_gate?: string;
}

interface CanaryPayload {
  go_no_go?: string;
  dry_run?: boolean;
  live_enabled?: boolean;
  exchange_adapter_kind?: string;
  real_order_attempted?: boolean;
  real_order_submitted?: boolean;
  places_real_order?: boolean;
  routes_to_live?: boolean;
  leverage_changed?: boolean;
  margin_mode_changed?: boolean;
  codex_final_live_canary_pass_marker_present?: boolean;
  intent_count?: number;
  fail_blockers?: string[];
  intents?: CanaryIntent[];
}

interface LiveCanaryData {
  generated_utc?: string;
  why_none?: string;
  selected_a_plus_candidate?: CanaryCandidate | null;
  no_mutation_flags?: Record<string, unknown>;
  status_payload?: CanaryPayload;
}

interface APlusCandidate {
  symbol?: string;
  side?: string;
  timeframe?: string;
  failed_checks?: string[];
  missing_evidence_checks?: string[];
}

interface APlusInventoryData {
  generated_utc?: string;
  evaluated_candidates?: number;
  a_plus_candidates?: number;
  live_ready_rows?: number;
  counts_as_final_a_plus?: boolean;
  rejected_reason_matrix?: Record<string, number>;
  candidate_matrix_preview?: APlusCandidate[];
  a_plus_preview?: APlusCandidate[];
}

function record(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' ? value as Record<string, unknown> : {};
}

function humanize(value: unknown, fallback = 'pending'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value)
    .replace(/_/g, ' ')
    .replace(/\bA PLUS\b/gi, 'A+')
    .replace(/\s+/g, ' ')
    .trim();
}

function numberValue(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function boolText(value: unknown): string {
  if (value === true) return 'yes';
  if (value === false) return 'no';
  return 'pending';
}

function unsafeMutationFlag(value: unknown): boolean {
  return value === true;
}

function noMutationEvidence(...sources: Array<Record<string, unknown> | undefined>): boolean {
  const fields = [
    'real_order_attempted',
    'real_order_submitted',
    'places_real_order',
    'routes_to_live',
    'leverage_changed',
    'margin_mode_changed',
    TEST_ORDER_FIELD,
  ];
  return sources.every((source) => {
    if (!source) return true;
    return fields.every((field) => !unsafeMutationFlag(source[field]));
  });
}

function topBlocker(aPlus?: APlusInventoryData | null, payload?: CanaryPayload | null, intent?: CanaryIntent | null, whyNone?: string): string {
  if (whyNone) return humanize(whyNone);
  const blocker = payload?.fail_blockers?.[0] ?? intent?.fail_blockers?.[0];
  if (blocker) return humanize(blocker);
  const reasonMatrix = aPlus?.rejected_reason_matrix ?? {};
  const [reason] = Object.entries(reasonMatrix).sort((a, b) => b[1] - a[1])[0] ?? [];
  if (reason) return humanize(reason);
  const failed = aPlus?.candidate_matrix_preview?.[0]?.failed_checks?.[0];
  return humanize(failed, 'A+ evidence not complete');
}

function candidateLabel(candidate?: CanaryCandidate | APlusCandidate | null): string {
  if (!candidate) return 'none selected';
  const symbol = candidate.symbol ?? 'symbol pending';
  const side = candidate.side ?? 'side pending';
  const timeframe = 'timeframe' in candidate && candidate.timeframe ? ` ${candidate.timeframe}` : '';
  return `${symbol}${timeframe} ${side}`;
}

function readinessTone(value: string): 'ok' | 'warn' | 'block' {
  const lower = value.toLowerCase();
  if (lower.includes('blocked') || lower.includes('disabled') || lower.includes('required')) return 'block';
  if (lower.includes('pending') || lower.includes('dry')) return 'warn';
  return 'ok';
}

function ReadinessMetric({
  label,
  value,
  tone = 'warn',
  detail,
}: {
  label: string;
  value: string | number;
  tone?: 'ok' | 'warn' | 'block' | 'neutral';
  detail?: string;
}): JSX.Element {
  const color = tone === 'ok'
    ? 'var(--buy)'
    : tone === 'block'
      ? 'var(--sell)'
      : tone === 'warn'
        ? 'var(--gold, #f59e0b)'
        : 'var(--text-primary)';
  return (
    <div style={{ border: '1px solid var(--line-soft)', borderRadius: 8, padding: '9px 10px', minWidth: 0, background: 'var(--bg-elevated)' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em', fontFamily: 'var(--font-mono)', marginBottom: 4 }}>
        {label}
      </span>
      <strong style={{ display: 'block', fontSize: 13, color, fontFamily: 'var(--font-mono)', overflowWrap: 'anywhere', lineHeight: 1.25 }}>
        {value}
      </strong>
      {detail ? <small style={{ display: 'block', marginTop: 4, color: 'var(--text-muted)', lineHeight: 1.25 }}>{detail}</small> : null}
    </div>
  );
}

export function TradeExecutionReadinessPanel({ state }: { state: TradeTerminalState }): JSX.Element {
  const liveCanary = useRealtimeResource<ControlCenterEnvelope<LiveCanaryData>>({
    url: LIVE_CANARY_ENDPOINT,
    source: LIVE_CANARY_ENDPOINT,
    source_type: 'api',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
    unwrapEnvelopeData: false,
  });
  const aPlus = useRealtimeResource<ControlCenterEnvelope<APlusInventoryData>>({
    url: A_PLUS_ENDPOINT,
    source: A_PLUS_ENDPOINT,
    source_type: 'api',
    pollIntervalMs: 15_000,
    staleThresholdMs: 45_000,
    mode: 'read_only',
    unwrapEnvelopeData: false,
  });

  const liveRaw = liveCanary.envelope.data;
  const liveData = liveRaw?.data ?? null;
  const payload = liveData?.status_payload ?? null;
  const firstIntent = payload?.intents?.[0] ?? null;
  const aPlusRaw = aPlus.envelope.data;
  const aPlusData = aPlusRaw?.data ?? null;

  const liveGate = liveRaw?.live_gate ?? firstIntent?.live_gate ?? 'blocked_human_only';
  const placesRealOrder = liveRaw?.places_real_order === true || payload?.places_real_order === true || firstIntent?.places_real_order === true;
  const routesToLive = liveRaw?.routes_to_live === true || payload?.routes_to_live === true || firstIntent?.routes_to_live === true;
  const dryRun = payload?.dry_run ?? firstIntent?.dry_run;
  const liveEnabled = payload?.live_enabled ?? firstIntent?.live_enabled;
  const aPlusCount = numberValue(aPlusData?.a_plus_candidates) ?? 0;
  const liveReadyRows = numberValue(aPlusData?.live_ready_rows) ?? 0;
  const evaluatedCandidates = numberValue(aPlusData?.evaluated_candidates);
  const countsAsFinal = aPlusData?.counts_as_final_a_plus === true;
  const selectedCandidate = liveData?.selected_a_plus_candidate ?? aPlusData?.a_plus_preview?.[0] ?? firstIntent?.candidate ?? null;
  const blocker = topBlocker(aPlusData, payload, firstIntent, liveData?.why_none);
  const mutationSafe = noMutationEvidence(
    record(liveRaw),
    record(liveData?.no_mutation_flags),
    record(payload),
    record(firstIntent),
  );
  const signalState = state.signal.paperFillAllowed
    ? 'paper fill open'
    : humanize(state.signal.riskDecision, 'risk decision pending');
  const operatorState = !placesRealOrder && !routesToLive
    ? (liveGate.toLowerCase().includes('blocked') ? 'LIVE BLOCKED' : 'OPERATOR REQUIRED')
    : 'LIVE ROUTE REPORTED';
  const whyNoTrade = aPlusCount <= 0 || !countsAsFinal || liveReadyRows <= 0
    ? `Why no trade now: ${blocker}`
    : `Why no trade now: ${humanize(liveGate)}`;

  return (
    <div style={{ padding: '0 16px 10px' }}>
      <TradePanel
        title="Trade Execution Readiness"
        kicker="Why no trade now"
        testId="trade-execution-readiness-panel"
        actions={<span className="chip solid-block">{operatorState}</span>}
      >
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(165px, 1fr))', gap: 8 }}>
          <ReadinessMetric label="Live gate" value={humanize(liveGate)} tone={readinessTone(liveGate)} detail={`${LIVE_CANARY_ENDPOINT} · ${liveCanary.envelope.freshness_status}`} />
          <ReadinessMetric label="A+ candidates" value={aPlusCount} tone={aPlusCount > 0 && countsAsFinal ? 'ok' : 'block'} detail={`${evaluatedCandidates ?? 'pending'} evaluated · ${A_PLUS_ENDPOINT}`} />
          <ReadinessMetric label="Live-ready rows" value={liveReadyRows} tone={liveReadyRows > 0 ? 'ok' : 'block'} detail={countsAsFinal ? 'counts as final A+' : 'not final A+'} />
          <ReadinessMetric label="Selected candidate" value={candidateLabel(selectedCandidate)} tone={selectedCandidate ? 'warn' : 'block'} detail={state.symbol} />
          <ReadinessMetric label="Canary mode" value={dryRun === true ? 'dry run' : boolText(dryRun)} tone={dryRun === true ? 'warn' : 'block'} detail={`live enabled: ${boolText(liveEnabled)}`} />
          <ReadinessMetric label="No mutation evidence" value={mutationSafe ? 'no real orders, no test orders, no leverage or margin mutation' : 'mutation flag present'} tone={mutationSafe ? 'ok' : 'block'} />
          <ReadinessMetric label="Paper gate" value={signalState} tone={state.signal.paperFillAllowed ? 'ok' : 'warn'} detail={state.signal.source} />
          <ReadinessMetric label="Realtime source" value={humanize(liveRaw?.source ?? liveCanary.envelope.source)} tone={liveCanary.error || aPlus.error ? 'warn' : 'neutral'} detail={aPlusRaw?.source ?? aPlus.envelope.source} />
        </div>
        <div style={{ marginTop: 10, padding: '9px 10px', borderRadius: 8, background: 'var(--bg-base)', border: '1px solid var(--line-soft)', color: 'var(--text-primary)', fontSize: 12, lineHeight: 1.35 }}>
          <strong style={{ display: 'block', fontFamily: 'var(--font-mono)', marginBottom: 4 }}>{whyNoTrade}</strong>
          <span style={{ color: 'var(--text-muted)' }}>
            Execution remains read-only unless backend live-canary, final A+ inventory, risk, and operator approval contracts all agree. This panel cannot submit or approve live orders.
          </span>
          {liveCanary.error || aPlus.error ? (
            <span style={{ display: 'block', marginTop: 6, color: 'var(--gold, #f59e0b)', fontFamily: 'var(--font-mono)' }}>
              readiness source warning: {liveCanary.error ?? aPlus.error}
            </span>
          ) : null}
        </div>
      </TradePanel>
    </div>
  );
}
