import { useEffect, useMemo, useState } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import type { PageMeta } from '../../types/page';

interface ProofScenario {
  scenario_id: string;
  symbol: string;
  direction: string;
  confidence: number;
  risk_decision: string;
  block_or_allow_reason: string;
  live_gate_status: string;
  feature_snapshot_id: string;
  prediction_id: string;
  decision_id: string;
  risk_decision_id: string;
  execution_intent_id: string;
  paper_trade_id?: string;
  shadow_decision_id?: string;
  paper_pnl: string;
  explanation_payload?: {
    summary: string;
    causes: string[];
    operator_visible: boolean;
    no_live_side_effects: boolean;
  };
}

interface ReplayProof {
  generated_at: string;
  mode: string;
  live_gate_status: string;
  scenario_count: number;
  allowed_count: number;
  blocked_count: number;
  gross_paper_pnl: string;
  scenarios: ProofScenario[];
}

interface PaperLedgerProof {
  live_gate_status: string;
  events: Array<ProofScenario & { ledger_event_type: string; non_live_only: boolean }>;
}

interface ShadowProof {
  live_gate_status: string;
  comparisons: Array<ProofScenario & { legacy_action: string; v2_action: string; diverged: boolean }>;
}

interface RiskProof {
  live_gate_status: string;
  decisions: Array<ProofScenario & { requested_action: string; risk_action: string; risk_reason: string }>;
}

interface ExplainabilityProof {
  live_gate_status: string;
  explanations: ProofScenario[];
}

interface ProofBundle {
  goNoGo: string;
  rollup: string;
  replay: ReplayProof;
  paper: PaperLedgerProof;
  shadow: ShadowProof;
  risk: RiskProof;
  explainability: ExplainabilityProof;
}

interface HistoricalTradeRow {
  trade_id: string;
  day: string;
  symbol: string;
  legacy_action: string;
  v2_action: string;
  legacy_realized_pnl: string;
  v2_paper_pnl: string;
  risk_decision: string;
  reason: string;
  confidence: number;
  feature_snapshot_id: string;
  prediction_id: string;
  decision_id: string;
  risk_decision_id: string;
  execution_intent_id: string;
  paper_trade_id: string;
  shadow_decision_id: string;
  live_gate_status: string;
}

interface Historical30DProof {
  generated_at: string;
  go_no_go: string;
  live_gate_status: string;
  summary: {
    period_days: number;
    scenario_count: number;
    v2_block_count: number;
    v2_preserved_winner_count: number;
    v2_reduced_or_rejected_count: number;
    legacy_realized_pnl_fixture_sum: string;
    v2_paper_pnl_fixture_sum: string;
    estimated_loss_avoided_by_v2: string;
    lab_hedge_unwind_represented: boolean;
  };
  legacy_vs_v2: HistoricalTradeRow[];
  risk_blocks: HistoricalTradeRow[];
  preserved_winners: HistoricalTradeRow[];
  reduced_or_rejected: HistoricalTradeRow[];
  paper_ledger_summary: {
    event_count: number;
    allowed_events: number;
    blocked_or_reduced_events: number;
    paper_pnl_fixture_sum: string;
  };
  shadow_summary: {
    comparison_count: number;
    divergence_count: number;
  };
  limitations: string[];
}

const basePath = '/non_live_operational_proof/latest';
const historicalBasePath = '/historical_30d_replay_and_paper_proof/latest';

async function fetchText(path: string): Promise<string> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.text();
}

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

function statusClass(value: string): string {
  const normalized = value.toLowerCase();
  if (normalized.includes('pass') || normalized.includes('ready') || normalized === 'allow') return 'proof-pill proof-pill--ok';
  if (normalized.includes('deny') || normalized.includes('block')) return 'proof-pill proof-pill--blocked';
  return 'proof-pill';
}

function ProofHeader({ bundle }: { bundle: ProofBundle }): JSX.Element {
  return (
    <section className="operator-proof-hero" data-testid="operator-proof-hero">
      <div>
        <p className="operator-proof-kicker">Non-live local evidence</p>
        <h1>{meta.title}</h1>
        <p>{meta.description}</p>
      </div>
      <div className="operator-proof-status">
        <span className={statusClass(bundle.goNoGo)} data-testid="operator-proof-marker">
          {bundle.goNoGo}
        </span>
        <span className="proof-pill proof-pill--blocked" data-testid="operator-live-gate">
          {bundle.replay.live_gate_status}
        </span>
      </div>
    </section>
  );
}

function SummaryGrid({ bundle }: { bundle: ProofBundle }): JSX.Element {
  const divergentCount = bundle.shadow.comparisons.filter((item) => item.diverged).length;
  const ledgerTypes = Array.from(new Set(bundle.paper.events.map((event) => event.ledger_event_type))).sort();
  return (
    <section className="operator-proof-grid" aria-label="Proof summary">
      <Metric label="Scenarios" value={String(bundle.replay.scenario_count)} />
      <Metric label="Allowed" value={String(bundle.replay.allowed_count)} />
      <Metric label="Blocked" value={String(bundle.replay.blocked_count)} />
      <Metric label="Paper PnL" value={bundle.replay.gross_paper_pnl} />
      <Metric label="Ledger Events" value={String(bundle.paper.events.length)} detail={ledgerTypes.join(', ')} />
      <Metric label="Shadow Divergences" value={String(divergentCount)} />
    </section>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }): JSX.Element {
  return (
    <div className="operator-proof-metric">
      <span>{label}</span>
      <strong>{value}</strong>
      {detail ? <small>{detail}</small> : null}
    </div>
  );
}

function RiskBlocks({ risk }: { risk: RiskProof }): JSX.Element {
  const blocked = risk.decisions.filter((decision) => decision.risk_decision === 'deny');
  return (
    <section className="operator-proof-section" data-testid="risk-blocks">
      <h2>Risk Blocks</h2>
      <div className="operator-proof-table" role="table" aria-label="Risk blocks">
        <div role="row" className="operator-proof-table__header">
          <span>Scenario</span>
          <span>Symbol</span>
          <span>Decision</span>
          <span>Reason</span>
        </div>
        {blocked.map((decision) => (
          <div role="row" key={decision.scenario_id}>
            <span>{decision.scenario_id}</span>
            <span>{decision.symbol}</span>
            <span className={statusClass(decision.risk_decision)}>{decision.risk_decision}</span>
            <span>{decision.block_or_allow_reason}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function PaperLedger({ paper }: { paper: PaperLedgerProof }): JSX.Element {
  return (
    <section className="operator-proof-section" data-testid="paper-ledger-evidence">
      <h2>Paper Ledger Evidence</h2>
      <div className="operator-proof-table" role="table" aria-label="Paper ledger">
        <div role="row" className="operator-proof-table__header">
          <span>Event</span>
          <span>Symbol</span>
          <span>Paper Trade</span>
          <span>PnL</span>
        </div>
        {paper.events.map((event, index) => (
          <div role="row" key={`${event.paper_trade_id}-${event.ledger_event_type}-${index}`}>
            <span>{event.ledger_event_type}</span>
            <span>{event.symbol}</span>
            <span>{event.paper_trade_id}</span>
            <span>{event.paper_pnl}</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function ShadowComparison({ shadow }: { shadow: ShadowProof }): JSX.Element {
  return (
    <section className="operator-proof-section" data-testid="shadow-comparison">
      <h2>Shadow Comparison</h2>
      <div className="operator-proof-table" role="table" aria-label="Shadow comparison">
        <div role="row" className="operator-proof-table__header">
          <span>Scenario</span>
          <span>Legacy</span>
          <span>V2</span>
          <span>Difference</span>
        </div>
        {shadow.comparisons.map((comparison) => (
          <div role="row" key={comparison.shadow_decision_id}>
            <span>{comparison.scenario_id}</span>
            <span>{comparison.legacy_action}</span>
            <span>{comparison.v2_action}</span>
            <span className={comparison.diverged ? 'proof-pill proof-pill--blocked' : 'proof-pill'}>
              {comparison.diverged ? 'diverged' : 'same'}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function Explainability({ explainability }: { explainability: ExplainabilityProof }): JSX.Element {
  const lab = explainability.explanations.find((item) => item.symbol === 'LABUSDT');
  return (
    <section className="operator-proof-section" data-testid="decision-explainability">
      <h2>Decision Explainability</h2>
      {lab ? (
        <div className="operator-proof-detail">
          <h3>{lab.symbol} hedge unwind block</h3>
          <p>{lab.explanation_payload?.summary}</p>
          <ul>
            {(lab.explanation_payload?.causes ?? []).map((cause) => (
              <li key={cause}>{cause}</li>
            ))}
          </ul>
          <dl>
            <dt>feature_snapshot_id</dt>
            <dd>{lab.feature_snapshot_id}</dd>
            <dt>prediction_id</dt>
            <dd>{lab.prediction_id}</dd>
            <dt>risk_decision_id</dt>
            <dd>{lab.risk_decision_id}</dd>
          </dl>
        </div>
      ) : null}
    </section>
  );
}

function Historical30DSection({ historical }: { historical: Historical30DProof }): JSX.Element {
  return (
    <section className="operator-proof-section" data-testid="historical-30d-proof">
      <div className="operator-proof-section__heading">
        <h2>Historical 30D Replay And Paper Proof</h2>
        <div className="operator-proof-status">
          <span className={statusClass(historical.go_no_go)} data-testid="historical-30d-marker">
            {historical.go_no_go}
          </span>
          <span className="proof-pill proof-pill--blocked">{historical.live_gate_status}</span>
        </div>
      </div>
      <section className="operator-proof-grid" aria-label="Historical 30D summary">
        <Metric label="Days" value={String(historical.summary.period_days)} />
        <Metric label="Scenarios" value={String(historical.summary.scenario_count)} />
        <Metric label="V2 Blocks" value={String(historical.summary.v2_block_count)} />
        <Metric label="Winners Preserved" value={String(historical.summary.v2_preserved_winner_count)} />
        <Metric label="Reduced/Rejected" value={String(historical.summary.v2_reduced_or_rejected_count)} />
        <Metric label="Loss Avoided" value={historical.summary.estimated_loss_avoided_by_v2} />
        <Metric label="Paper PnL" value={historical.summary.v2_paper_pnl_fixture_sum} />
        <Metric label="Shadow Divergences" value={String(historical.shadow_summary.divergence_count)} />
      </section>
      <HistoricalTable
        title="Legacy vs V2 Decision Comparison"
        rows={historical.legacy_vs_v2}
        testId="historical-legacy-vs-v2"
      />
      <HistoricalTable title="Blocked Losses" rows={historical.risk_blocks} testId="historical-blocked-losses" />
      <HistoricalTable
        title="Preserved Winners"
        rows={historical.preserved_winners}
        testId="historical-preserved-winners"
      />
      <HistoricalTable
        title="Reduced Or Rejected Trades"
        rows={historical.reduced_or_rejected}
        testId="historical-reduced-rejected"
      />
      <div className="operator-proof-detail" data-testid="historical-paper-shadow-summary">
        <h3>Paper Ledger 30D And Shadow Summary</h3>
        <dl>
          <dt>paper ledger events</dt>
          <dd>{historical.paper_ledger_summary.event_count}</dd>
          <dt>blocked or reduced</dt>
          <dd>{historical.paper_ledger_summary.blocked_or_reduced_events}</dd>
          <dt>shadow comparisons</dt>
          <dd>{historical.shadow_summary.comparison_count}</dd>
          <dt>shadow divergences</dt>
          <dd>{historical.shadow_summary.divergence_count}</dd>
        </dl>
      </div>
      <div className="operator-proof-detail" data-testid="historical-data-gaps">
        <h3>Limitations And Data Gaps</h3>
        <ul>
          {historical.limitations.map((item) => (
            <li key={item}>{item}</li>
          ))}
        </ul>
      </div>
    </section>
  );
}

function HistoricalTable({
  title,
  rows,
  testId,
}: {
  title: string;
  rows: HistoricalTradeRow[];
  testId: string;
}): JSX.Element {
  return (
    <section className="operator-proof-section" data-testid={testId}>
      <h3>{title}</h3>
      <div className="operator-proof-table operator-proof-table--historical" role="table" aria-label={title}>
        <div role="row" className="operator-proof-table__header">
          <span>Trade</span>
          <span>Symbol</span>
          <span>Legacy</span>
          <span>V2</span>
          <span>Decision</span>
          <span>Reason</span>
          <span>PnL</span>
        </div>
        {rows.map((row) => (
          <div role="row" key={`${testId}-${row.trade_id}`}>
            <span>{row.trade_id}</span>
            <span>{row.symbol}</span>
            <span>{row.legacy_action}</span>
            <span>{row.v2_action}</span>
            <span className={statusClass(row.risk_decision)}>{row.risk_decision}</span>
            <span>{row.reason}</span>
            <span>
              {row.legacy_realized_pnl} {'->'} {row.v2_paper_pnl}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

export default function OperatorProofDashboardPage(): JSX.Element {
  const [bundle, setBundle] = useState<ProofBundle | null>(null);
  const [historical, setHistorical] = useState<Historical30DProof | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetchText(`${basePath}/GO_NO_GO.md`),
      fetchText(`${basePath}/aggregate_non_live_proof_rollup.md`),
      fetchJson<ReplayProof>(`${basePath}/replay_backtest_result.json`),
      fetchJson<PaperLedgerProof>(`${basePath}/paper_ledger_result.json`),
      fetchJson<ShadowProof>(`${basePath}/shadow_comparison_result.json`),
      fetchJson<RiskProof>(`${basePath}/risk_gateway_result.json`),
      fetchJson<ExplainabilityProof>(`${basePath}/decision_explainability_result.json`),
      fetchJson<Historical30DProof>(`${historicalBasePath}/operator_dashboard_payload.json`),
    ])
      .then(([goNoGo, rollup, replay, paper, shadow, risk, explainability, historicalProof]) => {
        if (!active) return;
        setBundle({ goNoGo: goNoGo.trim(), rollup, replay, paper, shadow, risk, explainability });
        setHistorical(historicalProof);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setError(err instanceof Error ? err.message : 'proof artifacts unavailable');
      });
    return () => {
      active = false;
    };
  }, []);

  const pageAttrs = useMemo(
    () => ({
      className: 'operator-proof-page',
      'data-testid': 'operator-proof-dashboard',
      'data-page-id': (meta as PageMeta).id,
      'data-page-surface': meta.surface,
      'data-page-min-role': rbac.minRole,
      'data-page-path': route.path,
    }),
    [],
  );

  if (error) {
    return (
      <article {...pageAttrs}>
        <h1>{meta.title}</h1>
        <p role="alert">Proof artifacts unavailable: {error}</p>
      </article>
    );
  }

  if (!bundle || !historical) {
    return (
      <article {...pageAttrs}>
        <h1>{meta.title}</h1>
        <p>Loading proof artifacts...</p>
      </article>
    );
  }

  return (
    <article {...pageAttrs}>
      <ProofHeader bundle={bundle} />
      <SummaryGrid bundle={bundle} />
      <RiskBlocks risk={bundle.risk} />
      <PaperLedger paper={bundle.paper} />
      <ShadowComparison shadow={bundle.shadow} />
      <Explainability explainability={bundle.explainability} />
      <Historical30DSection historical={historical} />
      <section className="operator-proof-section" data-testid="proof-rollup">
        <h2>Aggregate Rollup</h2>
        <pre>{bundle.rollup}</pre>
      </section>
    </article>
  );
}
