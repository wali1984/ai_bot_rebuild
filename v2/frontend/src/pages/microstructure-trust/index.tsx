import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Panel } from '../cockpitComponents';
import { fmtAge, usePayloadFile } from '../../hooks/usePayloadFile';

const BASE = '/operator_runtime/v2_microstructure_trust/latest';

interface PolicyStatus {
  generated_at?: string;
  live_gate?: string;
  public_orderbook_default_trust?: string;
  public_orderbook_default_trust_cap?: number;
  public_book_can_approve_trade_alone?: boolean;
  final_a_plus_min_composite_trust?: number;
  reduced_size_tier_allowed?: boolean;
  reduced_size_counts_as_final_a_plus?: boolean;
  reduced_size_routes_to_live?: boolean;
  reduced_size_paper_only?: boolean;
  hidden_liquidity_not_observable?: boolean;
  public_depth_spoofable?: boolean;
  sweep_time_book_reliability_risk?: string;
  decision_requires_cross_validation?: boolean;
}

interface TrustSummary {
  generated_at?: string;
  rows?: number;
  symbols?: string[];
  avg_microstructure_trust_score?: number | null;
  avg_public_orderbook_trust_score?: number | null;
  avg_composite_microstructure_trust_score?: number | null;
  final_a_plus_min_composite_trust?: number;
  low_trust_rows?: number;
  blocked_or_reduced_rows?: number;
  a_grade_eligible_rows?: number;
  final_a_plus_eligible_rows?: number;
  reduced_size_bootstrap_candidate_rows?: number;
  missing_composite_confirmation_rows?: number;
}

interface FeedSummary {
  rows?: number;
  fail_closed_rows?: number;
  sequence_gap_rows?: number;
  avg_feed_quality_score?: number | null;
}

interface TruthStatus {
  generated_at?: string;
  symbols_covered?: number;
  stale_symbols?: string[];
  sequence_gaps?: string[];
  trainer_consumes_microstructure?: boolean;
  risk_consumes_microstructure?: boolean;
  orchestrator_consumes_microstructure?: boolean;
  allocator_consumes_microstructure?: boolean;
  paper_fills_consume_microstructure?: boolean;
  why_candidate_blocked_visible?: boolean;
  why_candidate_is_not_final_a_plus_visible?: boolean;
  final_a_plus_candidates?: number;
  reduced_size_bootstrap_candidates?: number;
  public_book_trust_live_ready?: boolean;
  reduced_size_counts_as_final_a_plus?: boolean;
  reduced_size_routes_to_live?: boolean;
}

interface ConsumptionStatus {
  runtime_microstructure_rows?: number;
  low_trust_rows?: number;
  blocked_or_reduced_rows?: number;
  sample_block_reasons?: Array<Record<string, unknown>>;
}

interface CompositeStatus {
  runtime_microstructure_rows?: number;
  public_orderbook_trust_score_alone_final_a_plus_rows?: number;
  composite_score_missing_but_legacy_score_above_threshold_rows?: number;
  missing_confirmation_fields_above_threshold_rows?: number;
  hard_fail?: boolean;
  hard_fail_reasons?: string[];
}

interface BootstrapStatus {
  candidate_rows?: number;
  paper_only?: boolean;
  routes_to_live?: boolean;
  places_real_order?: boolean;
  counts_as_final_a_plus?: boolean;
  mandatory_size_haircut?: boolean;
}

interface FinalTrustStatus {
  final_a_plus_candidates?: number;
  hard_fail?: boolean;
  hard_fail_reasons?: string[];
  reduced_size_as_final_a_plus_rows?: number;
  b_grade_as_final_a_plus_rows?: number;
  composite_missing_final_a_plus_rows?: number;
}

function yn(value: unknown): string {
  return value === true ? 'YES' : value === false ? 'NO' : 'PENDING';
}

function Metric({ label, value }: { label: string; value: string | number | null | undefined }): JSX.Element {
  return (
    <div className="metric">
      <span className="metric-label">{label}</span>
      <span className="metric-value">{value ?? 'pending'}</span>
    </div>
  );
}

export default function MicrostructureTrustPage(): JSX.Element {
  const policy = usePayloadFile<PolicyStatus>(`${BASE}/public_orderbook_trust_policy_status.json`, 15_000);
  const trust = usePayloadFile<TrustSummary>(`${BASE}/microstructure_trust_score_summary.json`, 15_000);
  const composite = usePayloadFile<CompositeStatus>(`${BASE}/microstructure_composite_trust_status.json`, 15_000);
  const bootstrap = usePayloadFile<BootstrapStatus>(`${BASE}/a_plus_reduced_size_bootstrap_runtime_status.json`, 15_000);
  const finalTrust = usePayloadFile<FinalTrustStatus>(`${BASE}/final_a_plus_trust_gate_status.json`, 15_000);
  const feed = usePayloadFile<FeedSummary>(`${BASE}/microstructure_feed_quality_summary.json`, 15_000);
  const website = usePayloadFile<TruthStatus>(`${BASE}/website_trust_semantics_truth_status.json`, 15_000);
  const risk = usePayloadFile<ConsumptionStatus>(`${BASE}/risk_microstructure_consumption_status.json`, 15_000);
  const paper = usePayloadFile<ConsumptionStatus>(`${BASE}/paper_microstructure_cost_evidence_status.json`, 15_000);
  const sampleBlocks = risk.data?.sample_block_reasons ?? paper.data?.sample_block_reasons ?? [];

  return (
    <article
      className="enterprise-cockpit-page"
      style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)' }}
      data-testid="page-microstructure-trust"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
    >
      <header className="enterprise-cockpit-hero">
        <div>
          <p className="cockpit-kicker">Adversarial Microstructure</p>
          <h1>{meta.title}</h1>
          <p>{meta.description}</p>
        </div>
        <div className="hero-meta">
          <span className="badge badge--neutral">LIVE_GATE: {policy.data?.live_gate ?? 'blocked_human_only'}</span>
        </div>
      </header>

      <Panel id="public-book-trust" title="Public Book Trust" right={<span className="chip">Updated {fmtAge(policy.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Default book trust" value={policy.data?.public_orderbook_default_trust} />
          <Metric label="Public book cap" value={policy.data?.public_orderbook_default_trust_cap} />
          <Metric label="Book can approve alone" value={yn(policy.data?.public_book_can_approve_trade_alone)} />
          <Metric label="Book live-ready" value={yn(website.data?.public_book_trust_live_ready)} />
          <Metric label="Hidden liquidity observable" value={yn(policy.data?.hidden_liquidity_not_observable === false)} />
          <Metric label="Public depth spoofable" value={yn(policy.data?.public_depth_spoofable)} />
          <Metric label="Sweep reliability risk" value={policy.data?.sweep_time_book_reliability_risk} />
          <Metric label="Cross validation required" value={yn(policy.data?.decision_requires_cross_validation)} />
        </div>
      </Panel>

      <Panel id="composite-microstructure-trust" title="Composite Microstructure Trust" right={<span className="chip">Scores {fmtAge(trust.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Symbols covered" value={trust.data?.symbols?.length ?? website.data?.symbols_covered} />
          <Metric label="Trust rows" value={trust.data?.rows} />
          <Metric label="Average public book" value={trust.data?.avg_public_orderbook_trust_score} />
          <Metric label="Average composite" value={trust.data?.avg_composite_microstructure_trust_score ?? trust.data?.avg_microstructure_trust_score} />
          <Metric label="A+ composite minimum" value={trust.data?.final_a_plus_min_composite_trust ?? policy.data?.final_a_plus_min_composite_trust} />
          <Metric label="Low trust rows" value={trust.data?.low_trust_rows} />
          <Metric label="Blocked/reduced rows" value={trust.data?.blocked_or_reduced_rows} />
          <Metric label="Missing confirmations" value={trust.data?.missing_composite_confirmation_rows} />
        </div>
      </Panel>

      <Panel id="reduced-size-bootstrap" title="REDUCED_SIZE Bootstrap" right={<span className="chip">Bootstrap {fmtAge(bootstrap.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Candidates" value={bootstrap.data?.candidate_rows ?? trust.data?.reduced_size_bootstrap_candidate_rows ?? website.data?.reduced_size_bootstrap_candidates} />
          <Metric label="Paper only" value={yn(bootstrap.data?.paper_only ?? policy.data?.reduced_size_paper_only)} />
          <Metric label="Routes to live" value={yn(bootstrap.data?.routes_to_live ?? policy.data?.reduced_size_routes_to_live)} />
          <Metric label="Counts as final A+" value={yn(bootstrap.data?.counts_as_final_a_plus ?? policy.data?.reduced_size_counts_as_final_a_plus)} />
          <Metric label="Places real order" value={yn(bootstrap.data?.places_real_order)} />
          <Metric label="Mandatory haircut" value={yn(bootstrap.data?.mandatory_size_haircut)} />
        </div>
      </Panel>

      <Panel id="final-a-plus-trust" title="Final A+ Trust" right={<span className="chip">Final {fmtAge(finalTrust.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Final A+ rows" value={finalTrust.data?.final_a_plus_candidates ?? trust.data?.final_a_plus_eligible_rows ?? website.data?.final_a_plus_candidates} />
          <Metric label="Composite missing final rows" value={finalTrust.data?.composite_missing_final_a_plus_rows} />
          <Metric label="REDUCED_SIZE final rows" value={finalTrust.data?.reduced_size_as_final_a_plus_rows} />
          <Metric label="B-grade final rows" value={finalTrust.data?.b_grade_as_final_a_plus_rows} />
          <Metric label="Trust hard fail" value={yn(finalTrust.data?.hard_fail ?? composite.data?.hard_fail)} />
          <Metric label="Hard fail reasons" value={(finalTrust.data?.hard_fail_reasons ?? composite.data?.hard_fail_reasons ?? []).join(', ') || 'none'} />
        </div>
      </Panel>

      <Panel id="feed-latency-sequence" title="Feed Latency And Sequence Gaps" right={<span className="chip">Feed {fmtAge(feed.ageSeconds)}</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Feed rows" value={feed.data?.rows} />
          <Metric label="Fail-closed rows" value={feed.data?.fail_closed_rows} />
          <Metric label="Sequence gap rows" value={feed.data?.sequence_gap_rows} />
          <Metric label="Average feed score" value={feed.data?.avg_feed_quality_score} />
          <Metric label="Stale symbols" value={(website.data?.stale_symbols ?? []).join(', ') || 'none'} />
          <Metric label="Sequence gaps" value={(website.data?.sequence_gaps ?? []).join(', ') || 'none'} />
        </div>
      </Panel>

      <Panel id="sweep-risk-confirmation" title="Sweep Risk And Cross-Venue Confirmation">
        <div className="cockpit-analytics-grid">
          <Metric label="Risk consumes trust" value={yn(website.data?.risk_consumes_microstructure)} />
          <Metric label="Orchestrator consumes trust" value={yn(website.data?.orchestrator_consumes_microstructure)} />
          <Metric label="Allocator consumes trust" value={yn(website.data?.allocator_consumes_microstructure)} />
          <Metric label="Paper fills consume trust" value={yn(website.data?.paper_fills_consume_microstructure)} />
          <Metric label="Trainer consumes trust" value={yn(website.data?.trainer_consumes_microstructure)} />
          <Metric label="Non-final reason visible" value={yn(website.data?.why_candidate_is_not_final_a_plus_visible ?? website.data?.why_candidate_blocked_visible)} />
        </div>
      </Panel>

      <Panel id="why-candidate-not-final-a-plus" title="Why Candidate Is Not Final A+">
        <div className="cockpit-market-table" role="table">
          <div className="cockpit-table-row cockpit-table-row--head" role="row">
            <span>Symbol</span><span>Timeframe</span><span>Action</span><span>Public</span><span>Composite</span><span>Missing confirmations</span>
          </div>
          {sampleBlocks.length ? sampleBlocks.slice(0, 8).map((row, index) => (
            <div className="cockpit-table-row" role="row" key={`${row.symbol ?? 'row'}-${index}`}>
              <span>{String(row.symbol ?? 'pending')}</span>
              <span>{String(row.timeframe ?? 'pending')}</span>
              <span>{String(row.microstructure_action ?? 'pending')}</span>
              <span>{String(row.public_orderbook_trust_score ?? row.orderbook_trust_score ?? 'pending')}</span>
              <span>{String(row.composite_microstructure_trust_score ?? row.microstructure_trust_score ?? 'pending')}</span>
              <span>{Array.isArray(row.composite_confirmation_missing_fields) ? row.composite_confirmation_missing_fields.join(', ') || 'none' : Array.isArray(row.missing_components) ? row.missing_components.join(', ') || 'none' : 'none'}</span>
            </div>
          )) : (
            <div className="cockpit-table-row" role="row">
              <span>pending</span><span>pending</span><span>NO_TRADE</span><span>pending</span><span>pending</span><span>waiting for monitor rows</span>
            </div>
          )}
        </div>
      </Panel>
    </article>
  );
}
