import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';

const PROFIT_TARGET_PATH = '/operator_runtime/v2_monthly_10k_profit_target_monitor/latest/operator_dashboard_payload.json';

interface ProfitTargetPayload {
  gate?: string;
  generated_est?: string;
  goal_status?: string;
  trainer_capability_status?: string;
  hedging_status?: string;
  goal_simulation_status?: string;
  monthly_target_net_usdt?: number;
  paper_equity?: number;
  paper_run_rate_monthly_pnl?: number | null;
  drawdown_adjusted_monthly_projection?: number | null;
  capital_required_for_target_at_current_edge?: number | null;
  required_monthly_return_pct?: number | null;
  current_edge_after_cost_bps?: number | null;
  current_win_rate?: number | null;
  current_win_rate_qualified?: number | null;
  current_profit_factor?: number | null;
  current_profit_factor_qualified?: number | null;
  performance_sample_status?: string;
  performance_outcome_count?: number | null;
  minimum_qualified_performance_outcomes?: number | null;
  raw_outcome_count?: number | null;
  dirty_outcome_count?: number | null;
  live_available_margin?: number | null;
  live_target_executable?: boolean;
  risk_required_for_10k?: number | null;
  top_strategy_weights?: Array<{
    strategy_family?: string;
    current_weight?: number | null;
    expectancy_after_cost_bps?: number | null;
    closed_trades?: number | null;
  }>;
  hedge_net_pnl?: number | null;
  hedge_cost?: number | null;
  hedge_benefit?: number | null;
  feedback_status?: string;
  trainer_feedback_row_count?: number | null;
  trainer_feedback_consumable_row_count?: number | null;
  trainer_feedback_quarantined_row_count?: number | null;
  trainer_feedback_total_row_count?: number | null;
  trainer_feedback_missing_field_counts?: Record<string, number>;
  trainer_feedback_quarantine_missing_field_counts?: Record<string, number>;
  trainer_feedback_readiness_summary?: string;
  trainer_missing_prediction_rows_count?: number | null;
  trainer_missing_prediction_symbols?: string[];
  trainer_missing_prediction_timeframes_by_symbol?: Record<string, string[]>;
  trainer_stale_prediction_rows_count?: number | null;
  trainer_stale_prediction_symbols?: string[];
  trainer_paper_actionability_block_reason_counts?: Record<string, number>;
  trainer_symbol_universe_alignment_status?: string;
  trainer_prediction_redis_symbol_count?: number | null;
  publisher_expected_symbol_count?: number | null;
  trainer_expected_symbol_mismatch_count?: number | null;
  trainer_expected_missing_from_redis_symbols?: string[];
  trainer_redis_extra_prediction_symbols?: string[];
  trainer_redis_extra_prediction_timeframes_by_symbol?: Record<string, string[]>;
  missing_prediction_input_reason_counts?: Record<string, number>;
  missing_prediction_input_diagnostics_by_symbol?: Record<
    string,
    {
      missing_prediction_timeframes?: string[];
      missing_closed_candle_timeframes?: string[];
      missing_feature_payload_timeframes?: string[];
      likely_root_cause?: string;
    }
  >;
  dynamic_strategy_inputs?: string[];
  blockers?: string[];
  profit_claim_policy?: string;
}

function money(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'evidence pending';
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
}

function pct(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'evidence pending';
  return `${(value * 100).toLocaleString('en-US', { maximumFractionDigits: 2 })}%`;
}

function bps(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'evidence pending';
  return `${value.toLocaleString('en-US', { maximumFractionDigits: 3 })} bps`;
}

function factor(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'evidence pending';
  return value.toLocaleString('en-US', { maximumFractionDigits: 2 });
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

function readableList(values: string[] | null | undefined, empty = 'none reported'): string {
  if (!values?.length) return empty;
  return values.join(', ');
}

function countList(values: Record<string, number> | null | undefined, limit = 5, empty = 'none reported'): string {
  const rows = Object.entries(values ?? {})
    .filter(([, count]) => Number.isFinite(count) && count > 0)
    .sort((a, b) => b[1] - a[1])
    .slice(0, limit);
  if (!rows.length) return empty;
  return rows.map(([field, count]) => `${readable(field)}: ${count}`).join(' · ');
}

function tone(status?: string): string {
  if (!status) return 'warn';
  if (status.includes('ON_TRACK') || status.includes('READY') || status.includes('CAPABLE')) return 'ok';
  if (status.includes('NO_CAPITAL') || status.includes('UNACCEPTABLE') || status.includes('NOT_SUPPORTED')) return 'block';
  return 'warn';
}

export function ProfitTargetMonitorPanel({ compact = false }: { compact?: boolean }): JSX.Element {
  const { data, error, ageSeconds } = usePayloadFile<ProfitTargetPayload>(PROFIT_TARGET_PATH, 30_000);
  const blockers = data?.blockers ?? [];
  const qualifiedCount = data?.performance_outcome_count ?? 0;
  const qualifiedMinimum = data?.minimum_qualified_performance_outcomes ?? 30;
  const missingSymbols = data?.trainer_missing_prediction_symbols ?? [];
  const missingTimeframes = data?.trainer_missing_prediction_timeframes_by_symbol ?? {};
  const expectedMissingFromRedis = data?.trainer_expected_missing_from_redis_symbols ?? missingSymbols;
  const trainerExtraSymbols = data?.trainer_redis_extra_prediction_symbols ?? [];
  const trainerExtraTimeframes = data?.trainer_redis_extra_prediction_timeframes_by_symbol ?? {};
  const missingInputReasonCounts = Object.entries(data?.missing_prediction_input_reason_counts ?? {}).slice(0, 8);
  const missingInputDiagnostics = data?.missing_prediction_input_diagnostics_by_symbol ?? {};
  const actionabilityReasons = Object.entries(data?.trainer_paper_actionability_block_reason_counts ?? {}).slice(0, 8);
  const feedbackMissingFields = countList(data?.trainer_feedback_quarantine_missing_field_counts ?? data?.trainer_feedback_missing_field_counts, 5);
  const dynamicInputs = data?.dynamic_strategy_inputs ?? [];
  const visibleExpectedMissingFromRedis = expectedMissingFromRedis.slice(0, compact ? 10 : 60);
  return (
    <section className="cockpit-panel panel bracketed" data-testid="profit-target-monitor-panel">
      <div className="panel-head">
        <h2 className="panel-title">{compact ? 'Paper Performance Objective' : '10K Monthly Net-Profit Objective'}</h2>
        <div className="panel-actions">
          <span className={`chip solid-${tone(data?.goal_status)}`}>{readable(data?.goal_status)}</span>
          <span className={`chip solid-${ageClass(ageSeconds, 120)}`}>{fmtAge(ageSeconds)}</span>
        </div>
      </div>
      <div className="panel-body">
        <div className="market-kpi-ribbon prediction-kpi-ribbon">
          <div className="cockpit-metric">
            <span>Target net</span>
            <strong>{money(data?.monthly_target_net_usdt)}</strong>
            <small>objective, not guaranteed</small>
          </div>
          <div className="cockpit-metric">
            <span>Runtime run-rate</span>
            <strong>{money(data?.paper_run_rate_monthly_pnl)}</strong>
            <small>net monthly projection</small>
          </div>
          <div className="cockpit-metric">
            <span>Capital needed</span>
            <strong>{money(data?.capital_required_for_target_at_current_edge)}</strong>
            <small>at current runtime edge</small>
          </div>
          <div className="cockpit-metric">
            <span>Required return</span>
            <strong>{pct(data?.required_monthly_return_pct)}</strong>
            <small>capital-normalized</small>
          </div>
          <div className="cockpit-metric">
            <span>Edge after cost</span>
            <strong>{bps(data?.current_edge_after_cost_bps)}</strong>
            <small>fees/slippage included</small>
          </div>
          <div className="cockpit-metric">
            <span>Win / PF</span>
            <strong>{pct(data?.current_win_rate_qualified)}</strong>
            <small>
              PF {factor(data?.current_profit_factor_qualified)} · clean {qualifiedCount}/{qualifiedMinimum}
            </small>
          </div>
          {!compact ? (
            <>
              <div className="cockpit-metric">
                <span>Trainer</span>
                <strong>{readable(data?.trainer_capability_status)}</strong>
                <small>{readable(data?.goal_simulation_status)}</small>
              </div>
              <div className="cockpit-metric">
                <span>Hedging</span>
                <strong>{readable(data?.hedging_status)}</strong>
                <small>explicit, budgeted only</small>
              </div>
              <div className="cockpit-metric">
                <span>Live margin</span>
                <strong>{money(data?.live_available_margin)}</strong>
                <small>{data?.live_target_executable ? 'executable evidence present' : 'balance-held'}</small>
              </div>
              <div className="cockpit-metric">
                <span>Risk required</span>
                <strong>{pct(data?.risk_required_for_10k)}</strong>
                <small>for 10k target</small>
              </div>
              <div className="cockpit-metric">
                <span>Hedge PnL</span>
                <strong>{money(data?.hedge_net_pnl)}</strong>
                <small>benefit {money(data?.hedge_benefit)}</small>
              </div>
              <div className="cockpit-metric">
                <span>Strategy weight</span>
                <strong>{data?.top_strategy_weights?.[0]?.strategy_family ? readable(data.top_strategy_weights[0].strategy_family) : 'evidence pending'}</strong>
                <small>{pct(data?.top_strategy_weights?.[0]?.current_weight)}</small>
              </div>
              <div className="cockpit-metric">
                <span>Feedback</span>
                <strong>{readable(data?.feedback_status)}</strong>
                <small>
                  consumable {data?.trainer_feedback_consumable_row_count ?? 0} · quarantined {data?.trainer_feedback_quarantined_row_count ?? 0}
                </small>
              </div>
            </>
          ) : null}
        </div>
        {!compact ? (
          <>
            <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '1rem' }}>
              <div className="source-health-grid__warn">
                <span>Trainer coverage gap</span>
                <strong>{data?.trainer_missing_prediction_rows_count ?? 0} missing · {data?.trainer_stale_prediction_rows_count ?? 0} stale</strong>
                <small>
                  {missingSymbols.length
                    ? `${missingSymbols.length} expected symbols missing trainer rows`
                    : 'no missing trainer symbols reported'}
                </small>
              </div>
              <div className="source-health-grid__warn">
                <span>Trainer/UI symbol alignment</span>
                <strong>{readable(data?.trainer_symbol_universe_alignment_status)}</strong>
                <small>
                  Redis trainer symbols {data?.trainer_prediction_redis_symbol_count ?? 'pending'} · expected UI symbols {data?.publisher_expected_symbol_count ?? 'pending'} · mismatch {data?.trainer_expected_symbol_mismatch_count ?? 0}
                </small>
              </div>
              <div className="source-health-grid__warn">
                <span>Execution actionability</span>
                <strong>{data?.trainer_paper_actionability_block_reason_counts ? 'blocked candidates present' : 'evidence pending'}</strong>
                <small>
                  {actionabilityReasons.length
                    ? actionabilityReasons.map(([reason, count]) => `${readable(reason)}: ${count}`).join(' · ')
                    : 'no block reason counts reported'}
                </small>
              </div>
              <div className={missingInputReasonCounts.length ? 'source-health-grid__warn' : 'source-health-grid__ok'}>
                <span>Missing prediction root cause</span>
                <strong>
                  {missingInputReasonCounts.length
                    ? missingInputReasonCounts.map(([reason, count]) => `${readable(reason)}: ${count}`).join(' · ')
                    : 'no missing input blockers reported'}
                </strong>
                <small>Read-only Redis/input coverage check for expected missing symbol-timeframe rows.</small>
              </div>
              <div className={data?.trainer_feedback_quarantined_row_count ? 'source-health-grid__warn' : 'source-health-grid__ok'}>
                <span>Trainer feedback fields</span>
                <strong>
                  {data?.trainer_feedback_total_row_count ?? 0} total · {data?.trainer_feedback_consumable_row_count ?? 0} consumable · {data?.trainer_feedback_quarantined_row_count ?? 0} quarantined
                </strong>
                <small>
                  {data?.trainer_feedback_readiness_summary
                    ? `${data.trainer_feedback_readiness_summary} Missing: ${feedbackMissingFields}.`
                    : `Missing: ${feedbackMissingFields}.`}
                </small>
              </div>
              <div className="source-health-grid__ok">
                <span>Adaptive strategy inputs</span>
                <strong>{dynamicInputs.length ? `${dynamicInputs.length} evidence families` : 'evidence pending'}</strong>
                <small>{readableList(dynamicInputs.slice(0, 10))}</small>
              </div>
            </div>

            {missingSymbols.length || trainerExtraSymbols.length ? (
              <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
                <summary>
                  <span>Trainer prediction symbol mismatch by symbol and timeframe</span>
                  <small>{expectedMissingFromRedis.length} expected missing · {trainerExtraSymbols.length} trainer extra · scrollable window</small>
                </summary>
                <div
                  className="mission-evidence-details__body trainer-prediction-scroll-window"
                  style={{ maxHeight: '260px', overflowY: 'auto' }}
                >
                  <div className="cockpit-lineage-grid">
                    {visibleExpectedMissingFromRedis.map((symbol) => {
                      const diagnostics = missingInputDiagnostics[symbol];
                      const rootCause = diagnostics?.likely_root_cause;
                      const missingClosed = diagnostics?.missing_closed_candle_timeframes ?? [];
                      const missingFeatures = diagnostics?.missing_feature_payload_timeframes ?? [];
                      return (
                        <div key={symbol}>
                          <span>{symbol}</span>
                          <strong>{readableList(missingTimeframes[symbol], 'timeframes pending')}</strong>
                          <small>
                            {rootCause
                              ? `${readable(rootCause)} · closed candles missing: ${readableList(missingClosed, 'none')} · feature sources missing: ${readableList(missingFeatures, 'none')}`
                              : 'Expected by publisher/UI, but no matching Redis trainer prediction key was found.'}
                          </small>
                        </div>
                      );
                    })}
                    {trainerExtraSymbols.map((symbol) => (
                      <div key={symbol}>
                        <span>{symbol}</span>
                        <strong>{readableList(trainerExtraTimeframes[symbol], 'timeframes pending')}</strong>
                        <small>Trainer is publishing this symbol, but it is not in the current publisher/UI expected set.</small>
                      </div>
                    ))}
                  </div>
                  {expectedMissingFromRedis.length > visibleExpectedMissingFromRedis.length ? (
                    <p className="cockpit-evidence-note" style={{ marginTop: '0.75rem' }}>
                      Showing {visibleExpectedMissingFromRedis.length} of {expectedMissingFromRedis.length} missing symbols. The full set remains in the source monitor for backend audit.
                    </p>
                  ) : null}
                </div>
              </details>
            ) : null}

            <div className="cockpit-evidence-note">
              <strong>Current blocker:</strong>{' '}
              {blockers.length ? blockers.slice(0, 3).join(' · ') : 'No monitor blocker reported.'}
              {error ? ` Source error: ${error}.` : ''}
              {' '}Performance sample: {readable(data?.performance_sample_status)}.
              {' '}Source: monthly target monitor. This panel reports feasibility only; it does not loosen risk, size trades, or authorize live orders.
            </div>
          </>
        ) : null}
      </div>
    </section>
  );
}

export default ProfitTargetMonitorPanel;
