import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';

const RUNTIME_ALPHA_BASE = '/operator_runtime/v2_runtime_alpha_remediated_adaptive_12h_dynamic_strategy_leverage_margin/latest';
const DASHBOARD_PATH = `${RUNTIME_ALPHA_BASE}/operator_dashboard_payload.json`;
const SOAK_PATH = `${RUNTIME_ALPHA_BASE}/adaptive_12h_paper_soak_status.json`;
const LOCAL_TRAINER_CONTRACT_PATH = `${RUNTIME_ALPHA_BASE}/local_trainer_core_contract_status.json`;
const TRAINER_PATH = `${RUNTIME_ALPHA_BASE}/trainer_10k_objective_readiness_status.json`;
const STRATEGY_PATH = `${RUNTIME_ALPHA_BASE}/dynamic_strategy_brain_runtime_status.json`;
const MARKET_BRAIN_PATH = `${RUNTIME_ALPHA_BASE}/all_timeframe_market_brain_status.json`;
const PAPER_READINESS_PATH = `${RUNTIME_ALPHA_BASE}/paper_trader_adaptive_readiness_status.json`;
const LEVERAGE_PATH = `${RUNTIME_ALPHA_BASE}/dynamic_leverage_recommendation_status.json`;
const MARGIN_PATH = `${RUNTIME_ALPHA_BASE}/dynamic_margin_mode_recommendation_status.json`;
const PROJECTION_PATH = `${RUNTIME_ALPHA_BASE}/monthly_10k_goal_12h_soak_projection_status.json`;

interface RuntimeAlphaDashboardPayload {
  gate?: string;
  status?: string;
  proof_status?: string;
  blockers?: string[];
  completion_window_elapsed_seconds?: number | null;
  completion_window_required_seconds?: number | null;
  paper_only?: boolean;
  live_order_submitted?: boolean;
  test_order_called?: boolean;
  exchange_leverage_mutation?: boolean;
  exchange_margin_mode_mutation?: boolean;
  position_size_selection_status?: string;
  dynamic_strategy_status?: string;
  dynamic_leverage_status?: string;
  dynamic_margin_mode_status?: string;
  dynamic_exit_logic_status?: string;
  paper_trader_adaptive_readiness_status?: string;
  trainer_10k_objective_status?: string;
  monthly_10k_goal_status?: string;
  monthly_10k_goal_blockers?: string[];
  missing_symbol_timeframe_count?: number | null;
  missing_symbol_timeframes_by_symbol?: Record<string, string[]>;
  missing_symbol_timeframes?: RuntimeAlphaMissingPredictionRow[];
}

interface RuntimeAlphaSoakPayload {
  proof_status?: string;
  soak_12h_complete?: boolean;
  completion_window_elapsed_seconds?: number | null;
  completion_window_required_seconds?: number | null;
  observation_density_status?: string;
  last_observation_freshness_status?: string;
  density_eligible_observation_count?: number | null;
  minimum_required_observations?: number | null;
  high_severity_alerts?: string[];
  static_sizing_regression_status?: string;
  same_symbol_stack_status?: string;
  same_symbol_hedge_status?: string;
  live_balance_hold_status?: string;
  paper_pnl_reconciliation_status?: string;
  open_positions_count?: number | null;
  closed_positions_count?: number | null;
  outcome_label_count?: number | null;
  trainer_feedback_row_count?: number | null;
  paper_equity?: number | null;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
}

interface RuntimeAlphaTrainerPayload {
  status?: string;
  trainer_source?: string;
  trainer_source_required?: string;
  model_source?: string;
  model_source_required?: string;
  local_trainer_core_status?: string;
  native_core_entrypoint?: string;
  legacy_hybrid_reference?: string;
  wrapper_role?: string;
  dynamic_symbol_count?: number | null;
  required_timeframes?: string[];
  prediction_grid_rows?: number | null;
  current_prediction_count?: number | null;
  missing_prediction_count?: number | null;
  stale_prediction_count?: number | null;
  training_steps_last_hour?: number | null;
  goal_status?: string;
  goal_blocker?: string;
  projected_monthly_pnl?: number | null;
}

interface RuntimeAlphaTrainerContractPayload {
  status?: string;
  trainer_source?: string;
  trainer_source_required?: string;
  model_source?: string;
  model_source_required?: string;
  native_core_entrypoint?: string;
  legacy_hybrid_reference?: string;
  legacy_reference_role?: string;
  wrapper_role?: string;
  wrappers_allowed?: boolean;
  wrapper_allowed_roles?: string[];
  wrapper_forbidden_roles?: string[];
  dynamic_symbol_count?: number | null;
  timeframe_count?: number | null;
  prediction_grid_rows?: number | null;
  current_prediction_count?: number | null;
  missing_prediction_count?: number | null;
  stale_prediction_count?: number | null;
  missing_symbol_timeframe_count?: number | null;
  missing_symbol_timeframes_by_symbol?: Record<string, string[]>;
  missing_symbol_timeframes?: RuntimeAlphaMissingPredictionRow[];
  source_contract_ok?: boolean;
  model_contract_ok?: boolean;
  dynamic_symbol_timeframe_grid_ok?: boolean;
  all_dynamic_symbols_must_use_local_model?: boolean;
}

interface RuntimeAlphaStrategyPayload {
  status?: string;
  required_timeframes?: string[];
  dynamic_selection_inputs?: string[];
  strategy_selection_policy?: string;
  strategy_selection_must_not_be_static?: boolean;
  missing_symbol_timeframe_count?: number | null;
  missing_symbol_timeframes_by_symbol?: Record<string, string[]>;
  missing_symbol_timeframes?: RuntimeAlphaMissingPredictionRow[];
  strategies?: Array<{
    strategy_family?: string;
    current_weight?: number | null;
    enabled_for_paper?: boolean;
    market_regime?: string;
    signal_count?: number | null;
    accepted_count?: number | null;
    blocked_count?: number | null;
    closed_trade_count?: number | null;
    win_rate?: number | null;
    expectancy_after_cost_bps?: number | null;
    profit_factor?: number | null;
    weight_change_reason?: string;
    risk_veto_count?: number | null;
    allocator_veto_count?: number | null;
  }>;
}

interface RuntimeAlphaMarketBrainPayload {
  status?: string;
  market_row_count?: number | null;
  symbol_count?: number | null;
  timeframe_count?: number | null;
  current_prediction_count?: number | null;
  missing_prediction_count?: number | null;
  stale_prediction_count?: number | null;
  missing_symbol_timeframe_count?: number | null;
  missing_symbol_timeframes_by_symbol?: Record<string, string[]>;
  missing_symbol_timeframes?: RuntimeAlphaMissingPredictionRow[];
  required_timeframes?: string[];
  market_state_integrity?: string;
  trade_actionability?: string;
  strategy_preference?: string;
  leverage_preference?: number | null;
  margin_mode_preference?: string;
  hedge_preference?: string;
  markets?: Array<{
    symbol?: string;
    timeframe?: string;
    confidence_calibrated?: number | null;
    expected_move_after_cost_bps?: number | null;
    strategy_preference?: string;
    trade_actionability?: string;
    leverage_preference?: number | null;
    margin_mode_preference?: string;
    hedge_preference?: string;
    prediction_id?: string;
    feature_snapshot_id?: string;
  }>;
}

interface RuntimeAlphaMissingPredictionRow {
  symbol?: string;
  timeframe?: string;
  required_prediction_key?: string;
  trainer_source?: string;
  trainer_source_required?: string;
  model_source?: string;
  model_source_required?: string;
  missing_stale_reason?: string;
  remediation?: string;
}

interface RuntimeAlphaPaperPayload {
  status?: string;
  accepted_allocation_count?: number | null;
  blocked_allocation_count?: number | null;
  allocator_decision_counts?: Record<string, number>;
  position_size_allocator?: string;
  position_size_selection_status?: string;
  position_size_selection_inputs?: string[];
  paper_trader_uses_adaptive_allocator?: boolean;
  paper_trader_uses_lifecycle_guard?: boolean;
  paper_trader_uses_risk_evaluator?: boolean;
  paper_trader_uses_exit_coordinator?: boolean;
  paper_trader_uses_dynamic_strategy_weights?: boolean;
  paper_trader_blocks_accidental_hedges?: boolean;
  paper_trader_updates_realized_unrealized_pnl?: boolean;
  paper_trader_writes_outcome_labels?: boolean;
  paper_trader_writes_trainer_feedback_rows?: boolean;
}

interface RuntimeAlphaLeveragePayload {
  status?: string;
  paper_only?: boolean;
  exchange_mutation?: boolean;
  live_leverage_mutation_allowed?: boolean;
  inputs?: Record<string, unknown>;
  candidates?: Array<{
    symbol?: string;
    timeframe?: string;
    recommended_leverage?: number | null;
    max_safe_leverage?: number | null;
    risk_veto?: boolean;
    leverage_reason?: string;
  }>;
}

interface RuntimeAlphaMarginPayload {
  status?: string;
  paper_only?: boolean;
  exchange_mutation?: boolean;
  live_margin_mode_mutation_allowed?: boolean;
  recommended_margin_mode?: string;
  margin_mode_reason?: string;
  risk_veto?: boolean;
  inputs?: Record<string, unknown>;
}

interface RuntimeAlphaProjectionPayload {
  goal_status?: string;
  goal_blockers?: string[];
  live_goal_status?: string;
  paper_12h_net_pnl?: number | null;
  projected_daily_net_pnl?: number | null;
  projected_monthly_net_pnl?: number | null;
  performance_sample_status?: string;
  performance_outcome_count?: number | null;
  minimum_qualified_performance_outcomes?: number | null;
  risk_acceptable?: boolean;
  risk_required_for_10k?: number | null;
  current_capital_sufficient?: boolean;
  guaranteed_profit_claimed?: boolean;
  guaranteed_win_rate_claimed?: boolean;
}

function readable(value: string | null | undefined): string {
  if (!value) return 'evidence pending';
  return value
    .replace(/payload/gi, 'source')
    .replace(/operator_dashboard/gi, 'operator monitor')
    .replace(/operator_runtime/gi, 'runtime source')
    .replace(/_/g, ' ')
    .toLowerCase()
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function count(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'pending';
  return value.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function money(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'pending';
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

function pct(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'pending';
  return `${(value * 100).toLocaleString('en-US', { maximumFractionDigits: 1 })}%`;
}

function bps(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'pending';
  const pct = value / 100;
  return `${pct >= 0 ? '+' : ''}${pct.toLocaleString('en-US', { maximumFractionDigits: 2 })}%`;
}

function gateTone(value: string | null | undefined): string {
  if (!value) return 'warn';
  if (value.includes('READY') || value.includes('CLEAR') || value.includes('ACTIVE') || value.includes('RECONCILED')) return 'ok';
  if (value.includes('BLOCK') || value.includes('NEGATIVE') || value.includes('NO_CAPITAL')) return 'block';
  return 'warn';
}

function progressPct(elapsed: number | null | undefined, required: number | null | undefined): string {
  if (typeof elapsed !== 'number' || typeof required !== 'number' || required <= 0) return 'pending';
  return `${Math.min(100, (elapsed / required) * 100).toLocaleString('en-US', { maximumFractionDigits: 1 })}%`;
}

function boolText(value: boolean | null | undefined): string {
  if (value === true) return 'yes';
  if (value === false) return 'no';
  return 'pending';
}

function topCounts(values: Record<string, number> | null | undefined): string {
  const rows = Object.entries(values ?? {})
    .filter(([, value]) => Number.isFinite(value))
    .sort((a, b) => b[1] - a[1])
    .slice(0, 5);
  if (!rows.length) return 'evidence pending';
  return rows.map(([key, value]) => `${readable(key)}: ${value}`).join(' · ');
}

export function RuntimeAlphaDynamicReadinessPanel({ compact = false }: { compact?: boolean }): JSX.Element {
  const { data: dashboard, error: dashboardError, ageSeconds: dashboardAge } = usePayloadFile<RuntimeAlphaDashboardPayload>(DASHBOARD_PATH, 30_000);
  const { data: soak } = usePayloadFile<RuntimeAlphaSoakPayload>(SOAK_PATH, 30_000);
  const { data: trainerContract } = usePayloadFile<RuntimeAlphaTrainerContractPayload>(LOCAL_TRAINER_CONTRACT_PATH, 30_000);
  const { data: trainer } = usePayloadFile<RuntimeAlphaTrainerPayload>(TRAINER_PATH, 30_000);
  const { data: strategy } = usePayloadFile<RuntimeAlphaStrategyPayload>(STRATEGY_PATH, 30_000);
  const { data: marketBrain } = usePayloadFile<RuntimeAlphaMarketBrainPayload>(MARKET_BRAIN_PATH, 30_000);
  const { data: paper } = usePayloadFile<RuntimeAlphaPaperPayload>(PAPER_READINESS_PATH, 30_000);
  const { data: leverage } = usePayloadFile<RuntimeAlphaLeveragePayload>(LEVERAGE_PATH, 30_000);
  const { data: margin } = usePayloadFile<RuntimeAlphaMarginPayload>(MARGIN_PATH, 30_000);
  const { data: projection } = usePayloadFile<RuntimeAlphaProjectionPayload>(PROJECTION_PATH, 30_000);

  const blockers = dashboard?.blockers ?? [];
  const marketRows = marketBrain?.markets ?? [];
  const visibleMarketRows = compact ? marketRows.slice(0, 10) : marketRows;
  const strategies = strategy?.strategies ?? [];
  const visibleStrategies = compact ? strategies.slice(0, 5) : strategies;
  const missingPredictionRows = trainerContract?.missing_symbol_timeframes
    ?? marketBrain?.missing_symbol_timeframes
    ?? strategy?.missing_symbol_timeframes
    ?? dashboard?.missing_symbol_timeframes
    ?? [];
  const visibleMissingPredictionRows = missingPredictionRows.slice(0, compact ? 10 : 60);
  const elapsed = dashboard?.completion_window_elapsed_seconds ?? soak?.completion_window_elapsed_seconds;
  const required = dashboard?.completion_window_required_seconds ?? soak?.completion_window_required_seconds;
  const goalBlockers = projection?.goal_blockers ?? dashboard?.monthly_10k_goal_blockers ?? [];
  const trainerSourceOk = Boolean(
    (trainerContract?.source_contract_ok && trainerContract?.model_contract_ok && trainerContract?.dynamic_symbol_timeframe_grid_ok)
      || (
        trainer?.trainer_source
        && trainer.trainer_source_required
        && trainer.trainer_source === trainer.trainer_source_required
        && trainer.model_source
        && trainer.model_source_required
        && trainer.model_source === trainer.model_source_required
      ),
  );

  return (
    <section className="cockpit-panel panel bracketed" data-testid="runtime-alpha-dynamic-readiness-panel">
      <div className="panel-head">
        <h2 className="panel-title">{compact ? 'Local Trainer Proof' : 'NERVYX CORE: Local Trainer And Execution Lifecycle'}</h2>
        <div className="panel-actions">
          <span className={`chip solid-${gateTone(dashboard?.gate ?? dashboard?.status)}`}>{readable(dashboard?.status ?? dashboard?.gate)}</span>
          <span className={`chip solid-${ageClass(dashboardAge, 300)}`}>{fmtAge(dashboardAge)}</span>
        </div>
      </div>
      <div className="panel-body">
        <div className="market-kpi-ribbon prediction-kpi-ribbon">
          <div className="cockpit-metric">
            <span>Trainer core</span>
            <strong>{readable(trainerContract?.status ?? trainer?.local_trainer_core_status)}</strong>
            <small>{trainerSourceOk ? 'source/model/grid match local trainer contract' : 'source/model/grid contract pending'}</small>
          </div>
          <div className="cockpit-metric">
            <span>Wrapper role</span>
            <strong>{readable(trainerContract?.wrapper_role ?? trainer?.wrapper_role)}</strong>
            <small>proof/launch guard, not a replacement model</small>
          </div>
          <div className="cockpit-metric">
            <span>Dynamic grid</span>
            <strong>{count(marketBrain?.symbol_count ?? trainer?.dynamic_symbol_count)} symbols</strong>
            <small>{count(marketBrain?.timeframe_count)} TFs · {count(trainer?.prediction_grid_rows ?? marketBrain?.market_row_count)} rows</small>
          </div>
          <div className="cockpit-metric">
            <span>Missing/stale</span>
            <strong>{count(trainer?.missing_prediction_count ?? marketBrain?.missing_prediction_count)} / {count(trainer?.stale_prediction_count ?? marketBrain?.stale_prediction_count)}</strong>
            <small>missing / stale prediction rows</small>
          </div>
          <div className="cockpit-metric">
            <span>12h proof</span>
            <strong>{progressPct(elapsed, required)}</strong>
            <small>{count(elapsed)}s / {count(required)}s · {readable(dashboard?.proof_status ?? soak?.proof_status)}</small>
          </div>
          <div className="cockpit-metric">
            <span>Account equity</span>
            <strong>{money(soak?.paper_equity)}</strong>
            <small>realized {money(soak?.realized_pnl_usd)} · unrealized {money(soak?.unrealized_pnl_usd)}</small>
          </div>
          {!compact ? (
            <>
              <div className="cockpit-metric">
                <span>Training steps</span>
                <strong>{count(trainer?.training_steps_last_hour)}</strong>
                <small>last hour</small>
              </div>
              <div className="cockpit-metric">
                <span>Allocator</span>
                <strong>{readable(paper?.position_size_selection_status ?? dashboard?.position_size_selection_status)}</strong>
                <small>{paper?.position_size_allocator ?? 'allocator evidence pending'}</small>
              </div>
              <div className="cockpit-metric">
                <span>Strategy</span>
                <strong>{readable(strategy?.status ?? dashboard?.dynamic_strategy_status)}</strong>
                <small>{strategy?.dynamic_selection_inputs?.slice(0, 4).join(', ') ?? 'inputs pending'}</small>
              </div>
              <div className="cockpit-metric">
                <span>Leverage</span>
                <strong>{readable(leverage?.status ?? dashboard?.dynamic_leverage_status)}</strong>
                <small>exchange mutation {boolText(leverage?.exchange_mutation ?? dashboard?.exchange_leverage_mutation)}</small>
              </div>
              <div className="cockpit-metric">
                <span>Margin mode</span>
                <strong>{readable(margin?.recommended_margin_mode ?? margin?.status ?? dashboard?.dynamic_margin_mode_status)}</strong>
                <small>exchange mutation {boolText(margin?.exchange_mutation ?? dashboard?.exchange_margin_mode_mutation)}</small>
              </div>
              <div className="cockpit-metric">
                <span>Live/order safety</span>
                <strong>{dashboard?.live_order_submitted ? 'live order submitted' : 'no live order'}</strong>
                <small>test order {boolText(dashboard?.test_order_called)} · runtime telemetry active</small>
              </div>
              <div className="cockpit-metric">
                <span>10k feasibility</span>
                <strong>{readable(projection?.goal_status ?? dashboard?.monthly_10k_goal_status)}</strong>
                <small>{goalBlockers[0] ?? 'evidence blocker pending'}</small>
              </div>
            </>
          ) : null}
        </div>

        {!compact ? (
          <>
            <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '1rem' }}>
              <div className={trainerSourceOk ? 'source-health-grid__ok' : 'source-health-grid__warn'}>
                <span>Local trainer source of truth</span>
                <strong>{trainerContract?.trainer_source ?? trainer?.trainer_source ?? 'pending'}</strong>
                <small>
                  Model: {trainerContract?.model_source ?? trainer?.model_source ?? 'pending'} · Core: {trainerContract?.native_core_entrypoint ?? trainer?.native_core_entrypoint ?? 'pending'}
                </small>
              </div>
              <div className="source-health-grid__ok">
                <span>Legacy parity reference</span>
                <strong>{trainerContract?.legacy_hybrid_reference ?? trainer?.legacy_hybrid_reference ?? 'pending'}</strong>
                <small>{readable(trainerContract?.legacy_reference_role)}; wrappers may launch/export proof but cannot replace model output.</small>
              </div>
              <div className={`source-health-grid__${gateTone(soak?.observation_density_status)}`}>
                <span>Soak density and freshness</span>
                <strong>
                  {readable(soak?.observation_density_status)} · {readable(soak?.last_observation_freshness_status)}
                </strong>
                <small>
                  observations {count(soak?.density_eligible_observation_count)}/{count(soak?.minimum_required_observations)} · alerts {soak?.high_severity_alerts?.length ?? 0}
                </small>
              </div>
              <div className={`source-health-grid__${gateTone(soak?.static_sizing_regression_status)}`}>
                <span>Lifecycle guards</span>
                <strong>
                  sizing {readable(soak?.static_sizing_regression_status)} · stack {readable(soak?.same_symbol_stack_status)}
                </strong>
                <small>
                  hedge {readable(soak?.same_symbol_hedge_status)} · live hold {readable(soak?.live_balance_hold_status)}
                </small>
              </div>
              <div className={`source-health-grid__${gateTone(soak?.paper_pnl_reconciliation_status)}`}>
                <span>Execution outcomes and feedback</span>
                <strong>
                  closed {count(soak?.closed_positions_count)} · labels {count(soak?.outcome_label_count)} · feedback {count(soak?.trainer_feedback_row_count)}
                </strong>
                <small>PnL reconciliation: {readable(soak?.paper_pnl_reconciliation_status)}</small>
              </div>
              <div className="source-health-grid__warn">
                <span>Current blocker</span>
                <strong>{blockers.length ? blockers.slice(0, 2).join(' · ') : 'no blocker reported'}</strong>
                <small>{dashboardError ? `Source error: ${dashboardError}` : `Goal: ${readable(trainer?.goal_status ?? dashboard?.monthly_10k_goal_status)} · ${readable(trainer?.goal_blocker)}`}</small>
              </div>
              <div className={`source-health-grid__${missingPredictionRows.length ? 'block' : 'ok'}`}>
                <span>Missing trainer grid rows</span>
                <strong>{count(trainerContract?.missing_symbol_timeframe_count ?? dashboard?.missing_symbol_timeframe_count ?? missingPredictionRows.length)}</strong>
                <small>
                  {missingPredictionRows.length
                    ? missingPredictionRows.slice(0, 3).map((row) => `${row.symbol ?? 'symbol'} ${row.timeframe ?? 'tf'}`).join(' · ')
                    : 'all dynamic symbol/timeframe rows covered'}
                </small>
              </div>
              <div className={`source-health-grid__${gateTone(projection?.goal_status ?? dashboard?.monthly_10k_goal_status)}`}>
                <span>10k target feasibility</span>
                <strong>{readable(projection?.goal_status ?? dashboard?.monthly_10k_goal_status)}</strong>
                <small>
                  projected monthly {money(projection?.projected_monthly_net_pnl)} · outcomes {count(projection?.performance_outcome_count)}/{count(projection?.minimum_qualified_performance_outcomes)}
                </small>
              </div>
            </div>

            {missingPredictionRows.length ? (
              <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }} open>
                <summary>
                  <span>Missing local trainer prediction rows</span>
                  <small>{count(missingPredictionRows.length)} missing Redis prediction keys</small>
                </summary>
                <div className="mission-evidence-details__body trainer-prediction-scroll-window" style={{ maxHeight: '260px', overflowY: 'auto' }}>
                  <div className="signal-stream-table" role="table">
                    <div className="signal-stream-row signal-stream-row--head" role="row">
                      <span>Symbol</span>
                      <span>TF</span>
                      <span>Required Redis key</span>
                      <span>Trainer source</span>
                      <span>Model source</span>
                      <span>Remediation</span>
                    </div>
                    {visibleMissingPredictionRows.map((row, index) => (
                      <div className="signal-stream-row" role="row" key={`${row.symbol ?? 'symbol'}-${row.timeframe ?? 'tf'}-${index}`}>
                        <span><strong>{row.symbol ?? 'pending'}</strong></span>
                        <span>{row.timeframe ?? 'pending'}</span>
                        <span title={row.required_prediction_key ?? 'missing key pending'}>{row.required_prediction_key ?? 'pending'}</span>
                        <span title={row.trainer_source_required ?? 'required source pending'}>{readable(row.trainer_source)}</span>
                        <span title={row.model_source_required ?? 'required model pending'}>{readable(row.model_source)}</span>
                        <span title={row.remediation ?? 'remediation pending'}>{row.remediation ?? 'Generate local trainer prediction with lineage.'}</span>
                      </div>
                    ))}
                  </div>
                </div>
              </details>
            ) : null}

            <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }} open>
              <summary>
                <span>10k feasibility evidence</span>
                <small>{goalBlockers.length ? `${goalBlockers.length} blocker(s)` : 'no target blocker reported'}</small>
              </summary>
              <div className="mission-evidence-details__body">
                <div className="cockpit-lineage-grid">
                  <div><span>runtime 12h net PnL</span><strong>{money(projection?.paper_12h_net_pnl)}</strong></div>
                  <div><span>daily projection</span><strong>{money(projection?.projected_daily_net_pnl)}</strong></div>
                  <div><span>monthly projection</span><strong>{money(projection?.projected_monthly_net_pnl)}</strong></div>
                  <div><span>live capital</span><strong>{projection?.current_capital_sufficient ? 'sufficient' : 'not sufficient'}</strong></div>
                  <div><span>risk acceptable</span><strong>{boolText(projection?.risk_acceptable)}</strong></div>
                  <div><span>sample status</span><strong>{readable(projection?.performance_sample_status)}</strong></div>
                </div>
                {goalBlockers.length ? (
                  <div className="cockpit-card-grid" style={{ marginTop: '0.75rem' }}>
                    {goalBlockers.map((item) => (
                      <div className="cockpit-evidence-gap" key={item}>{item}</div>
                    ))}
                  </div>
                ) : null}
              </div>
            </details>

            <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }} open>
              <summary>
                <span>All dynamic symbol/timeframe prediction rows</span>
                <small>{count(marketRows.length)} rows from market brain source</small>
              </summary>
              <div className="mission-evidence-details__body trainer-prediction-scroll-window" style={{ maxHeight: '360px', overflowY: 'auto' }}>
                <div className="signal-stream-table" role="table">
                  <div className="signal-stream-row signal-stream-row--head" role="row">
                    <span>Symbol</span>
                    <span>TF</span>
                    <span>Confidence</span>
                    <span>Edge</span>
                    <span>Strategy</span>
                    <span>Actionability</span>
                    <span>Lineage</span>
                  </div>
                  {visibleMarketRows.map((row, index) => (
                    <div className="signal-stream-row" role="row" key={`${row.symbol ?? 'symbol'}-${row.timeframe ?? 'tf'}-${row.prediction_id ?? index}`}>
                      <span><strong>{row.symbol ?? 'pending'}</strong></span>
                      <span>{row.timeframe ?? 'pending'}</span>
                      <span>{pct(row.confidence_calibrated)}</span>
                      <span>{bps(row.expected_move_after_cost_bps)}</span>
                      <span>{readable(row.strategy_preference)}</span>
                      <span>{readable(row.trade_actionability)}</span>
                      <span title={row.feature_snapshot_id ?? 'feature snapshot pending'}>{row.prediction_id ?? 'pending'}</span>
                    </div>
                  ))}
                </div>
              </div>
            </details>

            <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
              <summary>
                <span>Strategy weights and allocator evidence</span>
                <small>{count(strategies.length)} strategy families · {topCounts(paper?.allocator_decision_counts)}</small>
              </summary>
              <div className="mission-evidence-details__body trainer-prediction-scroll-window" style={{ maxHeight: '300px', overflowY: 'auto' }}>
                <div className="signal-stream-table" role="table">
                  <div className="signal-stream-row signal-stream-row--head" role="row">
                    <span>Strategy</span>
                    <span>Weight</span>
                    <span>Signals</span>
                    <span>Closed</span>
                    <span>Win</span>
                    <span>Expectancy</span>
                    <span>Reason</span>
                  </div>
                  {visibleStrategies.map((row) => (
                    <div className="signal-stream-row" role="row" key={row.strategy_family ?? 'strategy'}>
                      <span><strong>{readable(row.strategy_family)}</strong></span>
                      <span>{pct(row.current_weight)}</span>
                      <span>{count(row.signal_count)}</span>
                      <span>{count(row.closed_trade_count)}</span>
                      <span>{pct(row.win_rate)}</span>
                      <span>{bps(row.expectancy_after_cost_bps)}</span>
                      <span>{readable(row.weight_change_reason)}</span>
                    </div>
                  ))}
                </div>
              </div>
              <p className="cockpit-evidence-note">
                Dynamic inputs: {strategy?.dynamic_selection_inputs?.join(', ') ?? paper?.position_size_selection_inputs?.join(', ') ?? 'pending'}.
                Strategy policy: {strategy?.strategy_selection_policy ?? 'pending'}.
              </p>
            </details>

            <p className="cockpit-evidence-note" style={{ marginTop: '0.75rem' }}>
              Sources: runtime dashboard, local trainer contract, trainer readiness, market brain, and monthly projection.
              It does not submit orders, call test-order, change leverage, change margin mode, loosen risk, or claim the monthly profit target is certain.
            </p>
          </>
        ) : (
          <p className="cockpit-evidence-note" style={{ marginTop: '0.75rem' }}>
            Local trainer core: {trainerContract?.native_core_entrypoint ?? trainer?.native_core_entrypoint ?? 'pending'} · dynamic coverage:
            {' '}{count(marketBrain?.symbol_count)} symbols x {count(marketBrain?.timeframe_count)} timeframes.
            Blocker: {blockers[0] ?? 'none reported'}.
          </p>
        )}
      </div>
    </section>
  );
}

export default RuntimeAlphaDynamicReadinessPanel;
