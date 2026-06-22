import { Link } from 'react-router-dom';
import {
  adaptiveStatusColor,
  formatAdaptiveBps,
  formatAdaptiveMoney,
  formatAdaptivePercent,
  missingAccuracyCellCount,
  pnlWindow,
  type AdaptiveCapitalAGradeReadiness,
  type AdaptiveCapitalAGradeSourceReadiness,
  type AdaptiveCapitalCounterfactualStatus,
  type AdaptiveCapitalPolicyStatus,
  type AdaptiveCapitalOperatorGoReadiness,
  type AdaptiveCapitalPassConditionStatus,
  type AdaptiveCapitalDashboardPayload,
  type CapitalProductivityRuntimeStatus,
  type PnlHistoryStatus,
  type PnlHistoryWindow,
  type SignalPredictionAccuracyCell,
  type SignalPredictionAccuracyStatus,
  type SignalPredictionSymbolSummary,
  type SignalPredictionTimeframeSummary,
} from '../../data/adaptiveCapitalProductivity';

const TIMEFRAME_ORDER = ['1m', '5m', '15m', '1h', '4h'];

interface TelemetryViewModel {
  generatedUtc: string | null;
  overallStatus: string | null;
  capital: CapitalProductivityRuntimeStatus | null;
  counterfactual: AdaptiveCapitalCounterfactualStatus | null;
  policy: AdaptiveCapitalPolicyStatus | null;
  aGradeReadiness: AdaptiveCapitalAGradeReadiness | null;
  readiness: AdaptiveCapitalOperatorGoReadiness | null;
  passConditions: AdaptiveCapitalPassConditionStatus | null;
  pnlHistory: PnlHistoryStatus | null;
  accuracy: SignalPredictionAccuracyStatus | null;
  windows: Array<{ label: '1D' | '1W' | '30D'; row: PnlHistoryWindow | null }>;
  timeframeRows: SignalPredictionTimeframeSummary[];
  symbolRows: SignalPredictionSymbolSummary[];
  matrixRows: SignalPredictionAccuracyCell[];
}

interface AdaptiveCapitalTelemetryPanelProps {
  payload: AdaptiveCapitalDashboardPayload | null | undefined;
  title?: string;
  compact?: boolean;
  showCapital?: boolean;
  showMatrix?: boolean;
  maxMatrixHeight?: number;
}

function timeframeSortValue(timeframe: string): number {
  const known = TIMEFRAME_ORDER.indexOf(timeframe);
  return known >= 0 ? known : TIMEFRAME_ORDER.length + timeframe.localeCompare('zzzz');
}

function sortAccuracyCells(rows: SignalPredictionAccuracyCell[] | null | undefined): SignalPredictionAccuracyCell[] {
  return [...(rows ?? [])].sort((a, b) => {
    const symbolCompare = String(a.symbol ?? '').localeCompare(String(b.symbol ?? ''));
    if (symbolCompare !== 0) return symbolCompare;
    return timeframeSortValue(String(a.timeframe ?? '')) - timeframeSortValue(String(b.timeframe ?? ''));
  });
}

function completeAccuracyCells(
  accuracy: SignalPredictionAccuracyStatus | null | undefined,
): SignalPredictionAccuracyCell[] {
  const explicitRows = accuracy?.by_symbol_timeframe ?? [];
  const symbols = new Set<string>();
  const timeframes = new Set<string>();

  for (const symbol of accuracy?.symbol_universe ?? []) {
    if (symbol) symbols.add(String(symbol).toUpperCase());
  }
  for (const timeframe of accuracy?.required_timeframes ?? accuracy?.timeframes ?? []) {
    if (timeframe) timeframes.add(String(timeframe));
  }
  for (const row of explicitRows) {
    if (row.symbol) symbols.add(String(row.symbol).toUpperCase());
    if (row.timeframe) timeframes.add(String(row.timeframe));
  }

  if (!symbols.size || !timeframes.size) return sortAccuracyCells(explicitRows);

  const byKey = new Map<string, SignalPredictionAccuracyCell>();
  for (const row of explicitRows) {
    const symbol = String(row.symbol ?? '').toUpperCase();
    const timeframe = String(row.timeframe ?? '');
    if (!symbol || !timeframe) continue;
    byKey.set(`${symbol}:${timeframe}`, { ...row, symbol });
  }

  for (const symbol of symbols) {
    for (const timeframe of timeframes) {
      const key = `${symbol}:${timeframe}`;
      if (!byKey.has(key)) {
        byKey.set(key, {
          symbol,
          timeframe,
          signal_count: 0,
          prediction_count: 0,
          evaluated_count: 0,
          correct_count: 0,
          incorrect_count: 0,
          flat_count: 0,
          realized_pnl_usd: 0,
          accuracy: null,
          status: 'MISSING_EVALUATED_OUTCOMES',
        });
      }
    }
  }

  return sortAccuracyCells([...byKey.values()]);
}

function sortTimeframeRows(rows: SignalPredictionTimeframeSummary[] | null | undefined): SignalPredictionTimeframeSummary[] {
  return [...(rows ?? [])].sort(
    (a, b) => timeframeSortValue(String(a.timeframe ?? '')) - timeframeSortValue(String(b.timeframe ?? '')),
  );
}

function sortSymbolRows(rows: SignalPredictionSymbolSummary[] | null | undefined): SignalPredictionSymbolSummary[] {
  return [...(rows ?? [])].sort((a, b) => {
    const evaluatedDelta = (b.evaluated_count ?? 0) - (a.evaluated_count ?? 0);
    if (evaluatedDelta !== 0) return evaluatedDelta;
    return String(a.symbol ?? '').localeCompare(String(b.symbol ?? ''));
  });
}

function resolveTelemetry(payload: AdaptiveCapitalDashboardPayload | null | undefined): TelemetryViewModel {
  const rawCapital = payload?.capital_productivity_runtime_status ?? null;
  const progress = rawCapital?.capital_productivity_progress ?? payload?.operator_go_readiness?.capital_productivity_progress;
  const capital = rawCapital
    ? {
        ...rawCapital,
        capital_utilization_classification: rawCapital.capital_utilization_classification ?? progress?.capital_utilization_classification,
        allocated_margin_usd: rawCapital.allocated_margin_usd ?? progress?.allocated_margin_usd,
        gross_open_notional_usd: rawCapital.gross_open_notional_usd ?? progress?.gross_open_notional_usd,
        effective_portfolio_leverage: rawCapital.effective_portfolio_leverage ?? progress?.effective_portfolio_leverage,
        capital_utilization_pct: rawCapital.capital_utilization_pct ?? progress?.capital_utilization_pct,
        return_on_deployed_margin: rawCapital.return_on_deployed_margin ?? progress?.return_on_deployed_margin,
        after_cost_expectancy_bps: rawCapital.after_cost_expectancy_bps ?? progress?.after_cost_expectancy_bps,
        positive_edge_non_a_grade_opportunity_count: rawCapital.positive_edge_non_a_grade_opportunity_count ?? progress?.positive_edge_non_a_grade_opportunity_count,
        positive_edge_non_a_grade_diagnostics: rawCapital.positive_edge_non_a_grade_diagnostics ?? {
          near_a_grade_positive_edge_count: progress?.near_a_grade_positive_edge_count,
          min_confidence_gap_to_a_grade: progress?.closest_positive_edge_confidence_gap_to_a_grade,
        },
      }
    : null;
  const counterfactual = payload?.counterfactual_capital_sweep_status ?? null;
  const rawPolicy = payload?.adaptive_capital_policy_status ?? null;
  const policy = rawPolicy || progress
    ? {
        ...(rawPolicy ?? {}),
        post_allocator_closed_outcome_count: rawPolicy?.post_allocator_closed_outcome_count ?? progress?.current_closed_outcome_count,
        minimum_required_closed_outcomes: rawPolicy?.minimum_required_closed_outcomes ?? progress?.minimum_required_closed_outcomes,
        long_closed_outcome_count: rawPolicy?.long_closed_outcome_count ?? progress?.long_closed_outcome_count,
        short_closed_outcome_count: rawPolicy?.short_closed_outcome_count ?? progress?.short_closed_outcome_count,
        both_long_short_evidence: rawPolicy?.both_long_short_evidence ?? progress?.both_long_short_evidence,
        symbol_count: rawPolicy?.symbol_count ?? progress?.current_symbol_count,
        minimum_required_symbol_count: rawPolicy?.minimum_required_symbol_count ?? progress?.minimum_required_symbol_count,
        symbol_diversity_deficit: rawPolicy?.symbol_diversity_deficit ?? progress?.symbol_diversity_deficit,
      }
    : null;
  const readiness = payload?.operator_go_readiness ?? null;
  const passConditions = payload?.pass_condition_status
    ?? (readiness?.pass_condition_status_counts || readiness?.failed_conditions
      ? {
          status: readiness.status,
          condition_status_counts: readiness.pass_condition_status_counts,
          failed_conditions: readiness.failed_conditions,
          conditions: [],
        }
      : null);
  const pnlHistory = payload?.pnl_history_status ?? capital?.pnl_history ?? null;
  const accuracy = payload?.signal_prediction_accuracy_status ?? capital?.signal_prediction_accuracy_status ?? null;
  return {
    generatedUtc: payload?.generated_utc ?? null,
    overallStatus: payload?.overall_status ?? null,
    capital,
    counterfactual,
    policy,
    aGradeReadiness: counterfactual?.a_grade_readiness ?? null,
    readiness,
    passConditions,
    pnlHistory,
    accuracy,
    windows: [
      { label: '1D', row: pnlWindow(pnlHistory, '1d') },
      { label: '1W', row: pnlWindow(pnlHistory, '7d') },
      { label: '30D', row: pnlWindow(pnlHistory, '30d') },
    ],
    timeframeRows: sortTimeframeRows(accuracy?.by_timeframe),
    symbolRows: sortSymbolRows(accuracy?.by_symbol),
    matrixRows: completeAccuracyCells(accuracy),
  };
}

function pnlColor(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value) || value === 0) return 'var(--text-secondary)';
  return value > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)';
}

function countText(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  return value.toLocaleString('en-US');
}

function publicTelemetryText(value: string | null | undefined): string {
  return (value ?? '—')
    .replace(/paper/gi, 'RUNTIME')
    .replace(/no[_\s-]*data/gi, 'Awaiting feed')
    .replace(/blocked[_\s-]*human[_\s-]*only/gi, 'operator_gated');
}

function compactReasons(value: Record<string, number> | null | undefined): string {
  const entries = Object.entries(value ?? {}).filter(([key]) => key !== '__missing__');
  if (entries.length === 0) return '—';
  return entries.slice(0, 2).map(([key, count]) => `${publicTelemetryText(key)}: ${countText(count)}`).join(' · ');
}

function sourceReadiness(
  readiness: AdaptiveCapitalAGradeReadiness | null | undefined,
  progress: AdaptiveCapitalOperatorGoReadiness['counterfactual_replay_progress'] | null | undefined,
  sourceKind: string,
): AdaptiveCapitalAGradeSourceReadiness | null {
  return progress?.a_grade_source_kind_readiness?.[sourceKind]
    ?? readiness?.source_kind_readiness?.[sourceKind]
    ?? null;
}

function HeaderMetric({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ minWidth: 0 }}>
      <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </span>
      <span style={{
        display: 'block',
        marginTop: 2,
        fontSize: 13,
        lineHeight: 1.2,
        fontWeight: 800,
        fontFamily: 'var(--font-mono)',
        color: color ?? 'var(--text-primary)',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
      }}>
        {publicTelemetryText(value)}
      </span>
    </div>
  );
}

export function AdaptiveCapitalTelemetryPanel({
  payload,
  title = 'Capital Productivity',
  compact = false,
  showCapital = true,
  showMatrix = false,
  maxMatrixHeight,
}: AdaptiveCapitalTelemetryPanelProps): JSX.Element {
  const view = resolveTelemetry(payload);
  const capital = view.capital;
  const policy = view.policy;
  const readiness = view.readiness;
  const evidenceToGo = readiness?.evidence_to_go;
  const runtimeFieldEvidence = readiness?.adaptive_field_selection_evidence;
  const selectionAttribution = readiness?.adaptive_selection_attribution_status;
  const preSubmitFieldEvidence = readiness?.pre_submit_adaptive_field_selection_evidence;
  const replayProgress = readiness?.counterfactual_replay_progress;
  const aGradeReadiness = view.aGradeReadiness;
  const paperSignalAgrade = sourceReadiness(aGradeReadiness, replayProgress, 'paper_signal');
  const predictionProbe = view.counterfactual?.prediction_counterfactual_probe
    ?? replayProgress?.prediction_counterfactual_probe
    ?? null;
  const nearAgradeProbe = view.counterfactual?.near_a_grade_counterfactual_probe
    ?? replayProgress?.near_a_grade_counterfactual_probe
    ?? null;
  const predictionReadiness = predictionProbe?.a_grade_readiness
    ?? replayProgress?.prediction_a_grade_readiness
    ?? null;
  const predictionAgrade = sourceReadiness(predictionReadiness, null, 'prediction');
  const closestAgrade = replayProgress?.closest_near_a_grade
    ?? paperSignalAgrade?.closest_near_a_grade
    ?? aGradeReadiness?.closest_near_a_grade_by_source_kind?.paper_signal
    ?? null;
  const paperSignalSourceCount = replayProgress?.a_grade_source_kind_counts?.paper_signal
    ?? aGradeReadiness?.source_kind_counts?.paper_signal
    ?? paperSignalAgrade?.row_count;
  const predictionSourceCount = predictionProbe?.prediction_row_count
    ?? predictionReadiness?.source_kind_counts?.prediction
    ?? predictionAgrade?.row_count;
  const passConditions = view.passConditions;
  const accuracy = view.accuracy;
  const accuracyCellTotal = accuracy?.symbol_timeframe_cell_count ?? accuracy?.required_symbol_timeframe_cell_count;
  const positiveEdgeDiagnostics = capital?.positive_edge_non_a_grade_diagnostics;
  const matrixHeight = maxMatrixHeight ?? (compact ? 180 : 280);
  const symbolHeight = compact ? 160 : 220;

  return (
    <section
      data-testid="adaptive-capital-telemetry-panel"
      style={{
        background: 'var(--bg-panel,#111827)',
        border: '1px solid var(--border,#1f2937)',
        borderRadius: 'var(--radius,8px)',
        overflow: 'hidden',
      }}
    >
      <div style={{
        display: 'flex',
        alignItems: 'flex-start',
        justifyContent: 'space-between',
        gap: 12,
        padding: compact ? '10px 12px' : '12px 16px',
        borderBottom: '1px solid var(--border,#1f2937)',
      }}>
        <div style={{ minWidth: 0 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <h3 style={{ margin: 0, fontSize: compact ? 12 : 13, color: 'var(--text-primary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
              {title}
            </h3>
            <span style={{
              padding: '2px 7px',
              borderRadius: 999,
              fontSize: 10,
              fontWeight: 800,
              fontFamily: 'var(--font-mono)',
              background: 'color-mix(in oklch, var(--bg-elevated,#0f172a) 80%, transparent)',
              color: adaptiveStatusColor(capital?.status ?? view.overallStatus),
              border: '1px solid var(--border,#1f2937)',
            }}>
              {publicTelemetryText(capital?.status ?? view.overallStatus ?? (payload ? 'Awaiting feed' : 'CONNECTING'))}
            </span>
          </div>
          <p style={{ margin: '4px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
            Real-time platform telemetry.
          </p>
        </div>
        <Link to="/signals" style={{ color: 'var(--accent,#3b82f6)', textDecoration: 'none', fontSize: 11, fontWeight: 700 }}>
          Signals
        </Link>
      </div>

      <div style={{
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(120px, 1fr))' : 'repeat(auto-fit, minmax(135px, 1fr))',
        gap: compact ? 8 : 10,
        padding: compact ? 12 : 16,
      }}>
        {view.windows.map(({ label, row }) => (
          <HeaderMetric
            key={label}
            label={`${label} PnL`}
            value={formatAdaptiveMoney(row?.realized_pnl_usd)}
            color={pnlColor(row?.realized_pnl_usd)}
          />
        ))}
        <HeaderMetric
          label="Accuracy"
          value={formatAdaptivePercent(accuracy?.overall_accuracy)}
          color={adaptiveStatusColor(accuracy?.status)}
        />
        <HeaderMetric label="Evaluated" value={countText(accuracy?.evaluated_row_count)} />
        <HeaderMetric label="Universe" value={`${countText(accuracy?.symbol_universe_count)} symbols`} />
        <HeaderMetric label="TF Cells" value={`${countText(accuracy?.evaluated_symbol_timeframe_cell_count)}/${countText(accuracyCellTotal)}`} />
        <HeaderMetric
          label="Missing Cells"
          value={countText(missingAccuracyCellCount(accuracy))}
          color={missingAccuracyCellCount(accuracy) ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
        />
        <HeaderMetric
          label="Pass Gates"
          value={`${countText(passConditions?.condition_status_counts?.PASSED)}/${countText(passConditions?.conditions?.length)}`}
          color={adaptiveStatusColor(passConditions?.status)}
        />
        <HeaderMetric label="Failed Gates" value={countText(passConditions?.failed_conditions?.length)} color={adaptiveStatusColor(passConditions?.status)} />
      </div>

      {showCapital && (
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(130px, 1fr))' : 'repeat(auto-fit, minmax(150px, 1fr))',
          gap: 10,
          padding: compact ? '0 12px 12px' : '0 16px 16px',
        }}>
          <HeaderMetric label="Capital Class" value={capital?.capital_utilization_classification ?? '-'} color={adaptiveStatusColor(capital?.status)} />
          <HeaderMetric label="Allocated" value={formatAdaptiveMoney(capital?.allocated_margin_usd)} />
          <HeaderMetric label="Open Notional" value={formatAdaptiveMoney(capital?.gross_open_notional_usd)} />
          <HeaderMetric label="Utilization" value={formatAdaptivePercent(capital?.capital_utilization_pct)} />
          <HeaderMetric label="Deployed Return" value={formatAdaptivePercent(capital?.return_on_deployed_margin)} color={pnlColor(capital?.return_on_deployed_margin)} />
          <HeaderMetric label="After Cost Edge" value={formatAdaptiveBps(capital?.after_cost_expectancy_bps)} color={adaptiveStatusColor(capital?.status)} />
          <HeaderMetric
            label="Positive Edge Idle"
            value={countText(capital?.positive_edge_non_a_grade_opportunity_count)}
            color={(capital?.positive_edge_non_a_grade_opportunity_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="Near A-grade Edge"
            value={countText(positiveEdgeDiagnostics?.near_a_grade_positive_edge_count)}
            color={(positiveEdgeDiagnostics?.near_a_grade_positive_edge_count ?? 0) > 0 ? '#f59e0b' : 'var(--text-secondary)'}
          />
          <HeaderMetric
            label="Closest Gap"
            value={formatAdaptivePercent(positiveEdgeDiagnostics?.min_confidence_gap_to_a_grade)}
            color={(positiveEdgeDiagnostics?.min_confidence_gap_to_a_grade ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Policy Outcomes"
            value={`${countText(policy?.post_allocator_closed_outcome_count)}/${countText(policy?.minimum_required_closed_outcomes)}`}
            color={adaptiveStatusColor(policy?.status)}
          />
          <HeaderMetric
            label="Long / Short"
            value={`${countText(policy?.long_closed_outcome_count)} / ${countText(policy?.short_closed_outcome_count)}`}
            color={policy?.both_long_short_evidence ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Policy Symbols"
            value={`${countText(policy?.symbol_count)}/${countText(policy?.minimum_required_symbol_count ?? policy?.minimum_required_symbols)}`}
            color={(policy?.symbol_diversity_deficit ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
        </div>
      )}

      <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 6 }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Evidence To GO
          </span>
          <span style={{ fontSize: 10, color: adaptiveStatusColor(readiness?.status ?? readiness?.overall_status), fontFamily: 'var(--font-mono)' }}>
            {publicTelemetryText(readiness?.status ?? readiness?.overall_status ?? (payload ? 'Awaiting feed' : 'CONNECTING'))}
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Closed To GO"
            value={`${countText(evidenceToGo?.closed_outcomes_needed)} / ${countText(evidenceToGo?.closed_outcomes_needed_after_current_open_positions_close)}`}
            color={(evidenceToGo?.closed_outcomes_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Symbols To GO"
            value={countText(evidenceToGo?.additional_symbols_needed)}
            color={(evidenceToGo?.additional_symbols_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="A-grade Replay To GO"
            value={countText(evidenceToGo?.a_grade_replay_evidence_needed)}
            color={(evidenceToGo?.a_grade_replay_evidence_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Best Configs To GO"
            value={countText(evidenceToGo?.counterfactual_best_configurations_needed)}
            color={(evidenceToGo?.counterfactual_best_configurations_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Attribution To GO"
            value={countText(evidenceToGo?.selection_attribution_rows_needed)}
            color={(evidenceToGo?.selection_attribution_rows_needed ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Counterfactual Configs"
            value={`${countText(replayProgress?.configurations_considered_count)}/${countText(replayProgress?.theoretical_configuration_count)}`}
            color={replayProgress?.configuration_count_reconciled ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="A-grade Progress"
            value={formatAdaptivePercent(replayProgress?.a_grade_replay_progress_pct)}
            color={(replayProgress?.a_grade_replay_evidence_deficit ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '10px 0 6px' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            A-grade Readiness
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {countText(paperSignalSourceCount)} signals · {countText(predictionSourceCount)} predictions
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Positive Edge"
            value={countText(paperSignalAgrade?.positive_after_cost_edge_count)}
            color={(paperSignalAgrade?.positive_after_cost_edge_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Below Conf"
            value={countText(paperSignalAgrade?.positive_edge_below_confidence_count ?? paperSignalAgrade?.positive_edge_but_below_confidence_count)}
            color={(paperSignalAgrade?.positive_edge_below_confidence_count ?? paperSignalAgrade?.positive_edge_but_below_confidence_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="A-grade Rows"
            value={countText(paperSignalAgrade?.a_grade_before_temporal_count)}
            color={(paperSignalAgrade?.a_grade_before_temporal_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Event-valid"
            value={countText(paperSignalAgrade?.event_time_valid_candidate_count)}
            color={(paperSignalAgrade?.event_time_valid_candidate_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Best Configs"
            value={countText(paperSignalAgrade?.best_configuration_count)}
            color={(paperSignalAgrade?.best_configuration_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Near Event-valid"
            value={countText(nearAgradeProbe?.event_time_valid_candidate_count)}
            color={(nearAgradeProbe?.event_time_valid_candidate_count ?? 0) > 0 ? '#f59e0b' : 'var(--text-secondary)'}
          />
          <HeaderMetric
            label="Near Best Configs"
            value={countText(nearAgradeProbe?.best_configuration_count)}
            color={(nearAgradeProbe?.best_configuration_count ?? 0) > 0 ? '#f59e0b' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Near No Config"
            value={countText(nearAgradeProbe?.skipped_no_feasible_configuration_count)}
            color={(nearAgradeProbe?.skipped_no_feasible_configuration_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="Closest Gap"
            value={formatAdaptivePercent(closestAgrade?.confidence_gap_to_a_grade)}
            color={(closestAgrade?.confidence_gap_to_a_grade ?? 1) <= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Closest Edge"
            value={formatAdaptiveBps(closestAgrade?.after_cost_edge_bps)}
          />
          <HeaderMetric
            label="Closest Signal"
            value={closestAgrade?.symbol && closestAgrade?.timeframe ? `${closestAgrade.symbol} ${closestAgrade.timeframe}` : '—'}
          />
          <HeaderMetric
            label="A-grade Reasons"
            value={compactReasons(paperSignalAgrade?.not_a_grade_reason_counts)}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '10px 0 6px' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Prediction Readiness Probe
          </span>
          <span style={{ fontSize: 10, color: adaptiveStatusColor(predictionProbe?.status), fontFamily: 'var(--font-mono)' }}>
            {predictionProbe ? (predictionProbe.probe_participates_in_counterfactual_pass_gate ? 'GATING' : 'NON-GATING') : (payload ? 'Awaiting feed' : 'CONNECTING')}
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Prediction Rows"
            value={countText(predictionProbe?.prediction_row_count)}
            color={adaptiveStatusColor(predictionProbe?.status)}
          />
          <HeaderMetric
            label="Pred A-grade"
            value={countText(predictionProbe?.a_grade_before_temporal_count)}
            color={(predictionProbe?.a_grade_before_temporal_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Pred Event-valid"
            value={countText(predictionProbe?.event_time_valid_candidate_count)}
            color={(predictionProbe?.event_time_valid_candidate_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Pred Best Configs"
            value={countText(predictionProbe?.best_configuration_count)}
            color={(predictionProbe?.best_configuration_count ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
          />
          <HeaderMetric
            label="Pred No Config"
            value={countText(predictionProbe?.skipped_no_feasible_configuration_count)}
            color={(predictionProbe?.skipped_no_feasible_configuration_count ?? 0) > 0 ? 'var(--sell,#ef4444)' : 'var(--buy,#10b981)'}
          />
          <HeaderMetric
            label="Pred Reasons"
            value={compactReasons(
              predictionAgrade?.not_a_grade_reason_counts
                ?? predictionProbe?.skipped_not_a_grade_reason_counts,
            )}
          />
        </div>
        <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, margin: '10px 0 6px' }}>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Pre-submit Attribution
          </span>
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {countText(preSubmitFieldEvidence?.row_count)} rows
          </span>
        </div>
        <div style={{
          display: 'grid',
          gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(140px, 1fr))' : 'repeat(auto-fit, minmax(160px, 1fr))',
          gap: 10,
        }}>
          <HeaderMetric
            label="Selection Gate"
            value={selectionAttribution?.status ?? (payload ? 'Awaiting feed' : 'CONNECTING')}
            color={adaptiveStatusColor(selectionAttribution?.status)}
          />
          <HeaderMetric
            label="Selection Complete"
            value={`${formatAdaptivePercent(selectionAttribution?.complete_selection_model_input_coverage)} / ${countText(selectionAttribution?.complete_selection_model_input_count)} rows`}
            color={adaptiveStatusColor(selectionAttribution?.complete_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Fields"
            value={`${formatAdaptivePercent(runtimeFieldEvidence?.required_selection_field_coverage)} / ${countText(runtimeFieldEvidence?.row_count)} rows`}
            color={adaptiveStatusColor(runtimeFieldEvidence?.required_selection_field_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Leverage"
            value={formatAdaptivePercent(runtimeFieldEvidence?.leverage_selection_model_input_coverage)}
            color={adaptiveStatusColor(runtimeFieldEvidence?.leverage_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Margin"
            value={formatAdaptivePercent(runtimeFieldEvidence?.margin_mode_selection_model_input_coverage)}
            color={adaptiveStatusColor(runtimeFieldEvidence?.margin_mode_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Runtime Hedge"
            value={formatAdaptivePercent(runtimeFieldEvidence?.hedge_budget_selection_model_input_coverage)}
            color={adaptiveStatusColor(runtimeFieldEvidence?.hedge_budget_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Pre-submit Fields"
            value={formatAdaptivePercent(preSubmitFieldEvidence?.required_selection_field_coverage)}
            color={adaptiveStatusColor(preSubmitFieldEvidence?.required_selection_field_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Pre-submit Margin"
            value={formatAdaptivePercent(preSubmitFieldEvidence?.margin_mode_selection_model_input_coverage)}
            color={adaptiveStatusColor(preSubmitFieldEvidence?.margin_mode_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Pre-submit Hedge"
            value={formatAdaptivePercent(preSubmitFieldEvidence?.hedge_budget_selection_model_input_coverage)}
            color={adaptiveStatusColor(preSubmitFieldEvidence?.hedge_budget_selection_model_input_coverage === 1 ? 'PASSED' : 'NO_GO')}
          />
          <HeaderMetric
            label="Margin Reasons"
            value={compactReasons(preSubmitFieldEvidence?.margin_mode_selection_reason_counts)}
          />
          <HeaderMetric
            label="Hedge Reasons"
            value={compactReasons(preSubmitFieldEvidence?.hedge_budget_selection_reason_counts)}
          />
        </div>
      </div>

      {view.timeframeRows.length > 0 && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <div style={{ display: 'grid', gridTemplateColumns: '70px repeat(4, minmax(70px, 1fr))', gap: 1, fontSize: 11, overflowX: 'auto' }}>
            {['TF', 'Accuracy', 'Evaluated', 'Cells', 'PnL'].map((label) => (
              <span key={label} style={{ padding: '6px 7px', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }}>
                {label}
              </span>
            ))}
            {view.timeframeRows.map((row) => (
              <div key={row.timeframe} style={{ display: 'contents' }}>
                <strong style={{ padding: '6px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{row.timeframe}</strong>
                <span style={{ padding: '6px 7px', color: adaptiveStatusColor(row.status), background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{formatAdaptivePercent(row.accuracy)}</span>
                <span style={{ padding: '6px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.evaluated_count)}</span>
                <span style={{ padding: '6px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.evaluated_symbol_timeframe_cell_count)}/{countText(row.symbol_timeframe_cell_count)}</span>
                <span style={{ padding: '6px 7px', color: pnlColor(row.realized_pnl_usd), background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{formatAdaptiveMoney(row.realized_pnl_usd)}</span>
              </div>
            ))}
          </div>
        </div>
      )}

      {showMatrix && view.symbolRows.length > 0 && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              Symbol Accuracy
            </span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {countText(view.symbolRows.length)} symbols
            </span>
          </div>
          <div style={{ maxHeight: symbolHeight, overflow: 'auto', border: '1px solid var(--border,#1f2937)', borderRadius: 6 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '120px repeat(7, minmax(72px, 1fr))', gap: 1, minWidth: 760, fontSize: 11 }}>
              {['Symbol', 'Accuracy', 'Eval', 'Cells', 'Signals', 'Pred', 'PnL', 'Status'].map((label) => (
                <span key={label} style={{ position: 'sticky', top: 0, zIndex: 1, padding: '6px 7px', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }}>
                  {label}
                </span>
              ))}
              {view.symbolRows.map((row) => (
                <div key={row.symbol} style={{ display: 'contents' }}>
                  <strong style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{row.symbol}</strong>
                  <span style={{ padding: '5px 7px', color: adaptiveStatusColor(row.status), background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{formatAdaptivePercent(row.accuracy)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.evaluated_count)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.evaluated_symbol_timeframe_cell_count)}/{countText(row.symbol_timeframe_cell_count)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.signal_count)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.prediction_count)}</span>
                  <span style={{ padding: '5px 7px', color: pnlColor(row.realized_pnl_usd), background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{formatAdaptiveMoney(row.realized_pnl_usd)}</span>
                  <span title={publicTelemetryText(row.status)} style={{ padding: '5px 7px', color: 'var(--text-muted)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{publicTelemetryText(row.status)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}

      {showMatrix && view.matrixRows.length > 0 && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', gap: 10, marginBottom: 6 }}>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
              All Symbol/TF Accuracy
            </span>
            <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
              {countText(view.matrixRows.length)} cells
            </span>
          </div>
          <div style={{ maxHeight: matrixHeight, overflow: 'auto', border: '1px solid var(--border,#1f2937)', borderRadius: 6 }}>
            <div style={{ display: 'grid', gridTemplateColumns: '110px 60px repeat(6, minmax(72px, 1fr))', gap: 1, minWidth: 790, fontSize: 11 }}>
              {['Symbol', 'TF', 'Accuracy', 'Eval', 'Signals', 'Pred', 'PnL', 'Status'].map((label) => (
                <span key={label} style={{ position: 'sticky', top: 0, zIndex: 1, padding: '6px 7px', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', textTransform: 'uppercase', fontSize: 9, letterSpacing: '0.06em' }}>
                  {label}
                </span>
              ))}
              {view.matrixRows.map((row) => (
                <div key={`${row.symbol}-${row.timeframe}`} style={{ display: 'contents' }}>
                  <strong style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{row.symbol}</strong>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{row.timeframe}</span>
                  <span style={{ padding: '5px 7px', color: adaptiveStatusColor(row.status), background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{formatAdaptivePercent(row.accuracy)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.evaluated_count)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.signal_count)}</span>
                  <span style={{ padding: '5px 7px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{countText(row.prediction_count)}</span>
                  <span style={{ padding: '5px 7px', color: pnlColor(row.realized_pnl_usd), background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)' }}>{formatAdaptiveMoney(row.realized_pnl_usd)}</span>
                  <span title={publicTelemetryText(row.status)} style={{ padding: '5px 7px', color: 'var(--text-muted)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{publicTelemetryText(row.status)}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

export const adaptiveCapitalTelemetryTestHooks = {
  resolveTelemetry,
  sortAccuracyCells,
  sortTimeframeRows,
};
