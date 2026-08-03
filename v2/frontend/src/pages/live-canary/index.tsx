import type { ReactNode } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import meta from './meta';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

const LIVE_CANARY_ENDPOINT = '/api/v2/live-canary/status';
const A_PLUS_ENDPOINT = '/api/v2/a-plus/inventory';
const SC = { ok: '#22c55e', warn: '#f59e0b', error: '#ef4444', info: '#60a5fa', muted: '#94a3b8' };

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
  live_gate?: string | null;
  status_payload?: Record<string, unknown>;
}

interface APlusCandidateRow {
  symbol?: string;
  side?: string;
  timeframe?: string;
  strategy_id?: string;
  a_plus?: boolean;
  failed_checks?: string[];
  missing_evidence_checks?: string[];
  passed_check_count?: number;
  check_count?: number;
}

interface APlusInventoryData {
  evaluated_candidates?: number;
  a_plus_candidates?: number;
  adaptive_override_candidates?: number;
  live_ready_rows?: number;
  full_candidate_count?: number;
  payload_compacted?: boolean;
  exact_no_a_plus_reason?: string | null;
  top_a_plus_blockers?: string[] | null;
  rejected_reason_matrix?: Record<string, number> | null;
  counts_as_final_a_plus?: boolean;
  candidate_matrix_preview?: APlusCandidateRow[];
  a_plus_preview?: APlusCandidateRow[];
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

function MetricCard({ label, value, tone = 'info' }: { label: string; value: ReactNode; tone?: keyof typeof SC }): JSX.Element {
  return (
    <div style={{ padding: '10px 12px', borderRadius: 7, border: `1px solid ${SC[tone]}44`, background: 'var(--bg-elevated)' }}>
      <div style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 13, fontWeight: 750, fontFamily: 'var(--font-mono)', color: SC[tone], overflowWrap: 'anywhere' }}>{value}</div>
    </div>
  );
}

function APlusGateFunnel({ aPlus }: { aPlus?: APlusInventoryData | null }): JSX.Element {
  const matrix = Object.entries(aPlus?.rejected_reason_matrix ?? {}).sort(([, a], [, b]) => b - a);
  const maxCount = matrix.length ? matrix[0][1] : 1;
  const rows = aPlus?.candidate_matrix_preview ?? [];
  const evaluated = aPlus?.evaluated_candidates ?? 0;
  return (
    <div data-testid="a-plus-gate-funnel" style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 8 }}>
      <div className="glass" style={{ padding: '10px 12px' }}>
        <strong style={{ display: 'block', marginBottom: 6, fontSize: 12, color: 'var(--text-primary)' }}>
          A+ gate rejection matrix — {evaluated} evaluated this cycle
        </strong>
        {matrix.length === 0 ? (
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
            {evaluated > 0 ? 'No failed checks reported.' : 'No rejection matrix published yet — check paper loop freshness.'}
          </p>
        ) : matrix.map(([check, count]) => (
          <div key={check} style={{ marginBottom: 6 }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
              <span style={{ color: 'var(--text-secondary)' }}>{check.replace(/_/g, ' ')}</span>
              <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>{count}/{evaluated || '—'}</span>
            </div>
            <div style={{ height: 4, borderRadius: 2, background: 'var(--bg-elevated)' }}>
              <div style={{ width: `${Math.min(100, (count / maxCount) * 100)}%`, height: 4, borderRadius: 2, background: SC.warn }} />
            </div>
          </div>
        ))}
      </div>
      <div className="glass" style={{ padding: '10px 12px', overflowX: 'auto' }}>
        <strong style={{ display: 'block', marginBottom: 6, fontSize: 12, color: 'var(--text-primary)' }}>
          Per-candidate failed checks (first {rows.length} of {aPlus?.full_candidate_count ?? evaluated})
        </strong>
        {rows.length === 0 ? (
          <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>No candidate matrix rows published this cycle.</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 11 }}>
            <thead>
              <tr>
                {['Candidate', 'Checks', 'Failed checks'].map((h) => (
                  <th key={h} style={{ textAlign: 'left', padding: '3px 8px 3px 0', color: 'var(--text-muted)', fontWeight: 600, borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap' }}>{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 12).map((row, i) => (
                <tr key={`${row.symbol}-${row.timeframe}-${row.side}-${i}`}>
                  <td style={{ padding: '4px 8px 4px 0', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', verticalAlign: 'top' }}>
                    {row.symbol ?? '—'} {row.timeframe ?? ''} {row.side ?? ''}
                  </td>
                  <td style={{ padding: '4px 8px 4px 0', fontFamily: 'var(--font-mono)', whiteSpace: 'nowrap', verticalAlign: 'top', color: (row.failed_checks?.length ?? 0) === 0 ? SC.ok : SC.warn }}>
                    {row.passed_check_count ?? '—'}/{row.check_count ?? '—'}
                  </td>
                  <td style={{ padding: '4px 0', color: (row.failed_checks?.length ?? 0) === 0 ? SC.ok : 'var(--text-secondary)', lineHeight: 1.35 }}>
                    {(row.failed_checks?.length ?? 0) === 0 ? 'none — strict A+' : (row.failed_checks ?? []).join(', ').replace(/_/g, ' ')}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}

function EvidenceCard({ label, value }: { label: string; value: unknown }): JSX.Element {
  return (
    <div className="glass" style={{ padding: '10px 12px' }}>
      <strong style={{ display: 'block', marginBottom: 5, fontSize: 12, color: 'var(--text-primary)' }}>{label}</strong>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--text-secondary)', lineHeight: 1.4, overflowWrap: 'anywhere' }}>{compactValue(value)}</p>
    </div>
  );
}

export default function LiveCanaryPage(): JSX.Element {
  const { envelope: liveCanaryEnvelope, loading: liveCanaryLoading, error: liveCanaryError } = useRealtimeResource<LiveCanaryStatusData>({
    url: LIVE_CANARY_ENDPOINT,
    source: 'live-canary-status',
    pollIntervalMs: 5_000,
    staleThresholdMs: 15_000,
    unwrapEnvelopeData: 'contract',
  });
  const { envelope: aPlusEnvelope, loading: aPlusLoading, error: aPlusError } = useRealtimeResource<APlusInventoryData>({
    url: A_PLUS_ENDPOINT,
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
  const safe = mutationSafe(flags);

  return (
    <main data-testid="page-live-canary" style={{ display: 'flex', flexDirection: 'column', gap: 16, padding: '18px clamp(14px, 2vw, 28px)', background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}>
      <section style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', gap: 12, flexWrap: 'wrap' }}>
        <div>
          <p style={{ margin: '0 0 4px', fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: '0.08em' }}>
            {meta.title} runtime
          </p>
          <h1 style={{ margin: 0, fontSize: 24, fontWeight: 800, color: 'var(--text-primary)' }}>Live Canary Runtime Truth</h1>
          <p style={{ margin: '6px 0 0', maxWidth: 820, color: 'var(--text-secondary)', fontSize: 13, lineHeight: 1.45 }}>
            Trader-safe read-only canary status: selected A+ candidate, why none, dry-run order builder, hedge plan, symbol filters, emergency stop, and no-mutation flags.
          </p>
        </div>
        <div style={{ padding: '8px 10px', borderRadius: 7, border: `1px solid ${SC.warn}66`, color: SC.warn, fontFamily: 'var(--font-mono)', fontSize: 12, fontWeight: 800 }}>
          LIVE BLOCKED / DRY RUN / OPERATOR REQUIRED
        </div>
      </section>

      <section data-testid="cockpit-live-canary-runtime-truth" className="glass" style={{ padding: 14, display: 'flex', flexDirection: 'column', gap: 12 }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap' }}>
          <div>
            <h2 style={{ margin: 0, fontSize: 15, fontWeight: 800, color: 'var(--text-primary)' }}>Live Canary Runtime Truth</h2>
            <p style={{ margin: '3px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
              Canonical endpoints: {LIVE_CANARY_ENDPOINT} and {A_PLUS_ENDPOINT}.
            </p>
          </div>
          <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: SC.muted }}>
            {liveCanaryEnvelope.freshness_status} / {aPlusEnvelope.freshness_status}
          </span>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
          <MetricCard label="Selected A+ candidate" value={selectedCandidate} tone={selectedCandidate === 'MISSING_EVIDENCE' ? 'warn' : 'info'} />
          <MetricCard label="Why none" value={whyNone} tone="warn" />
          <MetricCard label="A+ candidates (strict)" value={aPlus?.a_plus_candidates ?? 'MISSING_EVIDENCE'} tone={(aPlus?.a_plus_candidates ?? 0) > 0 ? 'info' : 'warn'} />
          <MetricCard label="Adaptive-override (not strict A+)" value={aPlus?.adaptive_override_candidates ?? 'MISSING_EVIDENCE'} tone="info" />
          <MetricCard label="Live-ready rows" value={aPlus?.live_ready_rows ?? 'MISSING_EVIDENCE'} tone={(aPlus?.live_ready_rows ?? 0) > 0 ? 'info' : 'warn'} />
          <MetricCard label="Evaluated candidates" value={aPlus?.evaluated_candidates ?? 'MISSING_EVIDENCE'} tone="info" />
          <MetricCard label="Dry run" value={boolText(liveCanary?.dry_run)} tone={liveCanary?.dry_run === false ? 'error' : 'ok'} />
          <MetricCard label="Operator approval required" value={boolText(liveCanary?.operator_approval_required)} tone={liveCanary?.operator_approval_required === false ? 'error' : 'warn'} />
          <MetricCard label="No mutation flags" value={safe ? 'NO_ORDER_TEST_LEVERAGE_MARGIN_MUTATION' : 'MUTATION_FLAG_PRESENT'} tone={safe ? 'ok' : 'error'} />
          <MetricCard label="Live gate" value={liveCanary?.live_gate ?? 'blocked_human_only'} tone="warn" />
          <MetricCard label="Counts as final A+" value={boolText(aPlus?.counts_as_final_a_plus)} tone={aPlus?.counts_as_final_a_plus ? 'error' : 'info'} />
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
          <EvidenceCard label="Order builder dry run" value={liveCanary?.order_builder_dry_run ?? liveCanary?.post_only_plan ?? liveCanary?.maker_first_plan} />
          <EvidenceCard label="Taker fallback reason" value={liveCanary?.taker_fallback_reason} />
          <EvidenceCard label="Hedge plan" value={liveCanary?.hedge_plan} />
          <EvidenceCard label="Reduce / close path" value={liveCanary?.reduce_close_path} />
          <EvidenceCard label="Emergency stop" value={liveCanary?.emergency_stop} />
          <EvidenceCard label="Symbol filters" value={liveCanary?.symbol_filters} />
          <EvidenceCard label="Commission rates" value={liveCanary?.commission_rates} />
        </div>

        <APlusGateFunnel aPlus={aPlus} />

        {(liveCanaryLoading || aPlusLoading || liveCanaryError || aPlusError) ? (
          <p style={{ margin: 0, fontSize: 12, color: liveCanaryError || aPlusError ? SC.error : 'var(--text-muted)' }} role={liveCanaryError || aPlusError ? 'alert' : undefined}>
            Live canary canonical status: {liveCanaryLoading || aPlusLoading ? 'connecting' : 'loaded'}; errors: {liveCanaryError ?? aPlusError ?? 'none'}.
          </p>
        ) : null}

        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
          This page cannot submit live orders, test orders, leverage changes, or margin changes. Operator approval remains required and live remains blocked_human_only until backend contracts prove an independent A+ candidate.
        </p>
      </section>
    </main>
  );
}
