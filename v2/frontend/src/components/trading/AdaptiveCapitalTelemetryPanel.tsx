import { Link } from 'react-router-dom';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
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
  type ContinuousEdgeGuardianStatus,
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
  guardian: ContinuousEdgeGuardianStatus | null;
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

interface PaperRuntimeBlocker {
  id?: string | null;
  severity?: string | null;
  detail?: string | null;
  status?: string | null;
  valid_forward_canary_economic_outcomes?: number | null;
  post_cutover_valid_forward_canary_economic_outcomes?: number | null;
  required_forward_canary_economic_outcomes?: number | null;
  valid_symbol_count?: number | null;
  required_symbol_count?: number | null;
  required_initial_symbols?: number | null;
  forward_canary_shortfalls?: Record<string, number> | null;
  A_grade_rows?: number | null;
  a_grade_rows?: number | null;
  near_A_grade_rows?: number | null;
  near_a_grade_rows?: number | null;
  closest_gap_reason?: string | null;
  predicate_counts?: Record<string, number> | null;
  root_cause_counts?: Record<string, number> | null;
  dominant_current_runtime_reasons?: Record<string, number> | null;
  guardian_status?: string | null;
  guardian_new_entries_allowed?: boolean | null;
  guardian_block_all_new_a_grade_entries?: boolean | null;
  guardian_failure_reason_count?: number | null;
  source_tier_a_grade_execution_rows?: number | null;
  pass_conditions?: Record<string, boolean> | null;
}

interface PaperRuntimeStatusPayload {
  runtime?: string | null;
  runtime_state?: string | null;
  live_gate_status?: string | null;
  blockers?: PaperRuntimeBlocker[] | null;
  paper_loop?: {
    candidate_id?: string | null;
    policy_id?: string | null;
    paper_policy_owner?: string | null;
    current_allowed_paper_owner?: string | null;
    policy_fingerprint?: string | null;
    model_source?: string | null;
    intents_built?: number | null;
    intents_accepted?: number | null;
    intents_blocked?: number | null;
    production_grade_cost_rows?: number | null;
    production_grade_cost_coverage?: number | null;
    no_order_explained_rows?: number | null;
    unexplained_missing_cost_rows?: number | null;
    paper_fill_allowed_rows?: number | null;
    routes_to_live_rows?: number | null;
    places_real_order_rows?: number | null;
    paper_churn_equity_bleed_governor_status?: {
      status?: string | null;
      state?: string | null;
      duplicate_new_entries?: number | null;
      same_candle_reentry_unexplained?: number | null;
      cost_drag_within_envelope?: boolean | null;
      economic_trade_count_reconciles?: boolean | null;
      compacted_economic_trades?: number | null;
      raw_close_records?: number | null;
      cost_drag_pct?: number | null;
      sample_compacted_economic_trades_count?: number | null;
      pass_conditions?: Record<string, boolean>;
    } | null;
    paper_forward_canary_evidence_status?: {
      status?: string | null;
      valid_forward_canary_economic_outcomes?: number | null;
      required_forward_canary_economic_outcomes?: number | null;
      valid_symbol_count?: number | null;
      required_symbol_count?: number | null;
      side_counts?: Record<string, number>;
      production_grade_cost_coverage?: number | null;
      forward_canary_shortfalls?: {
        valid_forward_canary_economic_outcomes?: number | null;
        valid_symbol_count?: number | null;
        long_outcomes?: number | null;
        short_outcomes?: number | null;
        production_grade_cost_coverage_bps?: number | null;
        accounting_mismatch_rows?: number | null;
        liquidation_rows?: number | null;
        point_in_time_invalid_rows?: number | null;
        unsafe_live_route_rows?: number | null;
      } | null;
    } | null;
    paper_a_grade_gate_burndown_status?: {
      status?: string | null;
      closest_gap_reason?: string | null;
      A_grade_rows?: number | null;
      a_grade_rows?: number | null;
      near_A_grade_rows?: number | null;
      near_a_grade_rows?: number | null;
      predicate_counts?: Record<string, number> | null;
      root_cause_counts?: Record<string, number> | null;
      dominant_current_runtime_reasons?: Record<string, number> | null;
      source_tier_a_grade_execution_rows?: number | null;
      guardian_status?: string | null;
      guardian_new_entries_allowed?: boolean | null;
      guardian_block_all_new_a_grade_entries?: boolean | null;
      pass_conditions?: Record<string, boolean> | null;
    } | null;
  } | null;
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
  const guardian = payload?.continuous_edge_guardian_status ?? null;
  return {
    generatedUtc: payload?.generated_utc ?? null,
    overallStatus: payload?.overall_status ?? null,
    capital,
    counterfactual,
    policy,
    aGradeReadiness: counterfactual?.a_grade_readiness ?? null,
    readiness,
    passConditions,
    guardian,
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

function compactPercent(value: number | null | undefined, digits = 2): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const safe = Math.abs(value) < 0.0000005 ? 0 : value;
  const prefix = safe > 0 ? '+' : '';
  return `${prefix}${(safe * 100).toFixed(digits)}%`;
}

function compactMoney(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const abs = Math.abs(value);
  if (abs >= 1_000_000_000) return `$${(value / 1_000_000_000).toFixed(2)}B`;
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(2)}K`;
  return formatAdaptiveMoney(value);
}

function signedDays(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '—';
  const rounded = Math.round(value);
  return `${rounded > 0 ? '+' : ''}${rounded.toLocaleString('en-US')}d`;
}

function publicTelemetryText(value: string | null | undefined): string {
  const raw = (value ?? '—').trim();
  const upper = raw.toUpperCase();
  if (!raw || raw === '—') return '—';
  if (upper.includes('INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE')) return 'Needs productivity evidence';
  if (upper.includes('DYNAMIC_A_GRADE') && upper.includes('DEPLOYMENT_VALIDATED')) return 'A-grade runtime validated';
  if (upper.includes('NO_DIRECTIONAL_ACTION_EVIDENCE')) return 'Needs directional evidence';
  if (upper.includes('NO_EVALUATED_OUTCOMES') || upper.includes('MISSING_EVALUATED_OUTCOMES')) return 'Needs evaluated outcomes';
  if (upper === 'NO_GO' || upper.startsWith('NO_GO_')) return 'Needs review';
  const cleaned = raw
    .replace(/\bpaper\s*only\.?\s*/gi, '')
    .replace(/\blive orders? and exchange mutation remain disabled\.?/gi, 'operator-gated execution controls')
    .replace(/\blive orders? remain disabled\.?/gi, 'operator-gated execution controls')
    .replace(/\bexchange mutation\b/gi, 'execution control')
    .replace(/\bpaper[_\s-]*signal\b/gi, 'runtime signal')
    .replace(/\bpaper\b/gi, 'runtime')
    .replace(/no[_\s-]*data/gi, 'CONNECTING')
    .replace(/blocked[_\s-]*human[_\s-]*only/gi, 'operator gated')
    .replace(/\bno[_\s-]*directional[_\s-]*action[_\s-]*evidence\b/gi, 'Needs directional evidence')
    .replace(/\bno[_\s-]*evaluated[_\s-]*outcomes\b/gi, 'Needs evaluated outcomes')
    .replace(/\bmissing[_\s-]*evaluated[_\s-]*outcomes\b/gi, 'Needs evaluated outcomes')
    .replace(/\bevaluated\b/gi, 'Evaluated')
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim();
  if (/^[A-Z0-9]{1,4}$/.test(cleaned)) return cleaned;
  if (raw.includes('_')) {
    return cleaned
      .toLowerCase()
      .replace(/\b[a-z0-9]/g, (char) => char.toUpperCase())
      .replace(/\bApi\b/g, 'API')
      .replace(/\bAi\b/g, 'AI')
      .replace(/\bPnl\b/g, 'PnL')
      .replace(/\bUsd\b/g, 'USD');
  }
  return cleaned;
}

function compactReasons(value: Record<string, number> | null | undefined): string {
  const entries = Object.entries(value ?? {}).filter(([key]) => key !== '__missing__');
  if (entries.length === 0) return '—';
  return entries.slice(0, 2).map(([key, count]) => `${publicTelemetryText(key)}: ${countText(count)}`).join(' · ');
}

function compactTopReasons(value: Record<string, number> | null | undefined): string {
  const entries = Object.entries(value ?? {})
    .filter(([key, count]) => key !== '__missing__' && typeof count === 'number' && Number.isFinite(count))
    .sort((a, b) => b[1] - a[1]);
  if (entries.length === 0) return '—';
  return entries.slice(0, 2).map(([key, count]) => `${publicTelemetryText(key)}: ${countText(count)}`).join(' · ');
}

function blockerById(
  blockers: PaperRuntimeBlocker[] | null | undefined,
  id: string,
): PaperRuntimeBlocker | null {
  return blockers?.find((blocker) => blocker.id === id) ?? null;
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
        whiteSpace: 'normal',
        overflowWrap: 'anywhere',
        wordBreak: 'break-word',
      }}>
        {publicTelemetryText(value)}
      </span>
    </div>
  );
}

function accuracyPercent(value: number | null | undefined): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return Math.max(0, Math.min(100, pct));
}

function accuracyVisualColor(value: number | null | undefined, status?: string): string {
  const normalizedStatus = String(status ?? '').toUpperCase();
  if (normalizedStatus.includes('MISSING') || normalizedStatus.includes('NO_GO')) return 'var(--sell,#ef4444)';
  const pct = accuracyPercent(value);
  if (pct == null) return 'var(--text-muted)';
  if (pct >= 55) return 'var(--buy,#10b981)';
  if (pct >= 45) return '#f59e0b';
  return 'var(--sell,#ef4444)';
}

function accuracyTrack(value: number | null | undefined, status?: string): JSX.Element {
  const pct = accuracyPercent(value);
  const width = pct == null ? 0 : pct;
  const color = accuracyVisualColor(value, status);
  return (
    <div style={{
      height: 5,
      width: '100%',
      overflow: 'hidden',
      borderRadius: 999,
      background: 'color-mix(in oklch, var(--bg-base,#020617) 82%, var(--border,#1f2937) 18%)',
    }}>
      <div style={{
        width: `${width}%`,
        height: '100%',
        borderRadius: 999,
        background: color,
        transition: 'width 180ms ease',
      }} />
    </div>
  );
}

function TelemetrySection({ title, meta, children }: { title: string; meta?: string; children: JSX.Element }): JSX.Element {
  return (
    <div style={{ padding: '0 0 12px' }}>
      <div style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        gap: 10,
        marginBottom: 8,
      }}>
        <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: 0, fontWeight: 800 }}>
          {title}
        </span>
        {meta && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            {meta}
          </span>
        )}
      </div>
      {children}
    </div>
  );
}

function TelemetryEmptyState({ message }: { message: string }): JSX.Element {
  return (
    <div style={{
      display: 'grid',
      minHeight: 72,
      placeItems: 'center',
      border: '1px dashed var(--border,#1f2937)',
      borderRadius: 8,
      background: 'color-mix(in oklch, var(--bg-elevated,#0f172a) 72%, transparent)',
      color: 'var(--text-muted)',
      fontSize: 11,
      lineHeight: 1.4,
      padding: 14,
      textAlign: 'center',
    }}>
      {message}
    </div>
  );
}

function TimeframeAccuracyCards({ rows, compact }: {
  rows: SignalPredictionTimeframeSummary[];
  compact: boolean;
}): JSX.Element {
  return (
    <TelemetrySection title="Timeframe Accuracy" meta={`${countText(rows.length)} timeframes`}>
      <div style={{
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(118px, 1fr))' : 'repeat(auto-fit, minmax(150px, 1fr))',
        gap: compact ? 8 : 10,
      }}>
        {rows.map((row) => (
          <div key={row.timeframe} style={{
            minWidth: 0,
            padding: compact ? 10 : 12,
            borderRadius: 8,
            border: '1px solid var(--border,#1f2937)',
            background: 'linear-gradient(180deg, color-mix(in oklch, var(--bg-elevated,#0f172a) 92%, transparent), var(--bg-panel,#111827))',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <strong style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: compact ? 13 : 15 }}>{row.timeframe}</strong>
              <span style={{ color: accuracyVisualColor(row.accuracy, row.status), fontFamily: 'var(--font-mono)', fontSize: compact ? 12 : 14, fontWeight: 800 }}>
                {formatAdaptivePercent(row.accuracy)}
              </span>
            </div>
            <div style={{ marginTop: 8 }}>{accuracyTrack(row.accuracy, row.status)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: 8, marginTop: 10 }}>
              <HeaderMetric label="Cells" value={`${countText(row.evaluated_symbol_timeframe_cell_count)}/${countText(row.symbol_timeframe_cell_count)}`} />
              <HeaderMetric label="Evaluated" value={countText(row.evaluated_count)} />
              <HeaderMetric label="Signals" value={countText(row.signal_count)} />
              <HeaderMetric label="PnL" value={formatAdaptiveMoney(row.realized_pnl_usd)} color={pnlColor(row.realized_pnl_usd)} />
            </div>
          </div>
        ))}
      </div>
    </TelemetrySection>
  );
}

function SymbolAccuracyCards({ rows, compact, maxHeight }: {
  rows: SignalPredictionSymbolSummary[];
  compact: boolean;
  maxHeight: number;
}): JSX.Element {
  return (
    <TelemetrySection title="Symbol Accuracy" meta={`${countText(rows.length)} symbols`}>
      <div style={{
        maxHeight,
        overflow: 'auto',
        display: 'grid',
        gridTemplateColumns: compact ? 'repeat(auto-fit, minmax(142px, 1fr))' : 'repeat(auto-fit, minmax(190px, 1fr))',
        gap: compact ? 8 : 10,
        paddingRight: 2,
      }}>
        {rows.map((row) => (
          <div key={row.symbol} style={{
            minWidth: 0,
            padding: compact ? 9 : 11,
            borderRadius: 8,
            border: '1px solid var(--border,#1f2937)',
            background: 'var(--bg-elevated,#0f172a)',
          }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8 }}>
              <strong title={row.symbol} style={{ minWidth: 0, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: compact ? 12 : 13, overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>
                {row.symbol}
              </strong>
              <span style={{ flex: '0 0 auto', color: accuracyVisualColor(row.accuracy, row.status), fontFamily: 'var(--font-mono)', fontSize: compact ? 11 : 12, fontWeight: 800 }}>
                {formatAdaptivePercent(row.accuracy)}
              </span>
            </div>
            <div style={{ marginTop: 7 }}>{accuracyTrack(row.accuracy, row.status)}</div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(3, minmax(0, 1fr))', gap: 6, marginTop: 9 }}>
              <HeaderMetric label="Eval" value={countText(row.evaluated_count)} />
              <HeaderMetric label="Cells" value={`${countText(row.evaluated_symbol_timeframe_cell_count)}/${countText(row.symbol_timeframe_cell_count)}`} />
              <HeaderMetric label="PnL" value={formatAdaptiveMoney(row.realized_pnl_usd)} color={pnlColor(row.realized_pnl_usd)} />
            </div>
            <div style={{ marginTop: 7, color: 'var(--text-muted)', fontSize: 10, overflowWrap: 'anywhere' }}>
              {publicTelemetryText(row.status)}
            </div>
          </div>
        ))}
      </div>
    </TelemetrySection>
  );
}

function heatBackground(value: number | null | undefined, status?: string): string {
  const color = accuracyVisualColor(value, status);
  const pct = accuracyPercent(value);
  const mix = pct == null ? 10 : Math.max(14, Math.min(46, pct * 0.55));
  return `color-mix(in oklch, ${color} ${mix}%, var(--bg-elevated,#0f172a))`;
}

function AccuracyHeatmap({ rows, compact, maxHeight }: {
  rows: SignalPredictionAccuracyCell[];
  compact: boolean;
  maxHeight: number;
}): JSX.Element {
  const timeframes = [
    ...TIMEFRAME_ORDER.filter((timeframe) => rows.some((row) => row.timeframe === timeframe)),
    ...Array.from(new Set(rows.map((row) => row.timeframe).filter(Boolean))).filter((timeframe) => !TIMEFRAME_ORDER.includes(timeframe)),
  ];
  const symbols = Array.from(new Set(rows.map((row) => row.symbol).filter(Boolean)));
  const byKey = new Map(rows.map((row) => [`${row.symbol}:${row.timeframe}`, row]));
  const gridTemplateColumns = compact
    ? `minmax(58px, 1.2fr) repeat(${timeframes.length}, minmax(38px, 1fr))`
    : `minmax(92px, 1.15fr) repeat(${timeframes.length}, minmax(62px, 1fr))`;

  return (
    <TelemetrySection title="All Symbol/TF Accuracy" meta={`${countText(rows.length)} cells`}>
      <div style={{
        maxHeight,
        overflow: 'auto',
        maxWidth: '100%',
        border: '1px solid var(--border,#1f2937)',
        borderRadius: 8,
        background: 'var(--bg-base,#020617)',
      }}>
        <div style={{
          display: 'grid',
          gridTemplateColumns,
          gap: 1,
          minWidth: timeframes.length > 7 ? (compact ? 360 : 560) : '100%',
          fontSize: compact ? 10 : 11,
        }}>
          <span style={{ position: 'sticky', top: 0, zIndex: 1, padding: compact ? '7px 6px' : '8px 9px', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', textTransform: 'uppercase', fontWeight: 800 }}>
            Symbol
          </span>
          {timeframes.map((timeframe) => (
            <span key={timeframe} style={{ position: 'sticky', top: 0, zIndex: 1, padding: compact ? '7px 4px' : '8px 7px', textAlign: 'center', color: 'var(--text-muted)', background: 'var(--bg-base,#020617)', fontFamily: 'var(--font-mono)', fontWeight: 800 }}>
              {timeframe}
            </span>
          ))}
          {symbols.map((symbol) => (
            <div key={symbol} style={{ display: 'contents' }}>
              <strong title={symbol} style={{ minWidth: 0, padding: compact ? '7px 6px' : '8px 9px', color: 'var(--text-primary)', background: 'var(--bg-elevated,#0f172a)', fontFamily: 'var(--font-mono)', overflowWrap: 'anywhere', whiteSpace: 'normal', wordBreak: 'break-word' }}>
                {symbol}
              </strong>
              {timeframes.map((timeframe) => {
                const row = byKey.get(`${symbol}:${timeframe}`);
                return (
                  <span
                    key={`${symbol}-${timeframe}`}
                    title={row ? `${symbol} ${timeframe} · ${formatAdaptivePercent(row.accuracy)} · ${countText(row.evaluated_count)} evaluated · ${formatAdaptiveMoney(row.realized_pnl_usd)} · ${publicTelemetryText(row.status)}` : `${symbol} ${timeframe} · connecting`}
                    style={{
                      minWidth: 0,
                      padding: compact ? '7px 3px' : '8px 6px',
                      textAlign: 'center',
                      color: row ? 'var(--text-primary)' : 'var(--text-muted)',
                      background: row ? heatBackground(row.accuracy, row.status) : 'var(--bg-elevated,#0f172a)',
                      fontFamily: 'var(--font-mono)',
                      fontWeight: 800,
                      overflowWrap: 'anywhere',
                      whiteSpace: 'normal',
                      wordBreak: 'break-word',
                    }}
                  >
                    {row ? formatAdaptivePercent(row.accuracy) : '—'}
                  </span>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </TelemetrySection>
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
  const { envelope: paperRuntimeEnvelope } = useRealtimeResource<PaperRuntimeStatusPayload>({
    url: '/api/v2/paper/runtime-status',
    source: '/api/v2/paper/runtime-status',
    source_type: 'api',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'paper',
    unwrapEnvelopeData: false,
  });
  const paperRuntime = paperRuntimeEnvelope.data;
  const paperLoop = paperRuntime?.paper_loop ?? null;
  const paperRuntimeBlockers = paperRuntime?.blockers ?? [];
  const forwardCanaryBlocker = blockerById(paperRuntimeBlockers, 'FORWARD_CANARY_EVIDENCE_NOT_READY');
  const aGradeSupplyBlocker = blockerById(paperRuntimeBlockers, 'A_GRADE_SUPPLY_ZERO');
  const paperChurn = paperLoop?.paper_churn_equity_bleed_governor_status ?? null;
  const paperForwardCanary = paperLoop?.paper_forward_canary_evidence_status ?? null;
  const paperAgrade = paperLoop?.paper_a_grade_gate_burndown_status ?? null;
  const forwardOutcomes = forwardCanaryBlocker?.valid_forward_canary_economic_outcomes
    ?? paperForwardCanary?.valid_forward_canary_economic_outcomes;
  const requiredForwardOutcomes = forwardCanaryBlocker?.required_forward_canary_economic_outcomes
    ?? paperForwardCanary?.required_forward_canary_economic_outcomes;
  const forwardSymbols = forwardCanaryBlocker?.valid_symbol_count
    ?? paperForwardCanary?.valid_symbol_count;
  const requiredForwardSymbols = forwardCanaryBlocker?.required_symbol_count
    ?? forwardCanaryBlocker?.required_initial_symbols
    ?? paperForwardCanary?.required_symbol_count;
  const forwardOutcomeShortfall = forwardCanaryBlocker?.forward_canary_shortfalls?.valid_forward_canary_economic_outcomes
    ?? paperForwardCanary?.forward_canary_shortfalls?.valid_forward_canary_economic_outcomes;
  const forwardSymbolShortfall = forwardCanaryBlocker?.forward_canary_shortfalls?.valid_symbol_count
    ?? paperForwardCanary?.forward_canary_shortfalls?.valid_symbol_count;
  const forwardLongOutcomes = paperForwardCanary?.side_counts?.LONG
    ?? paperForwardCanary?.side_counts?.long
    ?? null;
  const forwardShortOutcomes = paperForwardCanary?.side_counts?.SHORT
    ?? paperForwardCanary?.side_counts?.short
    ?? null;
  const churnDuplicateNewEntries = paperChurn?.duplicate_new_entries;
  const churnSameCandleReentry = paperChurn?.same_candle_reentry_unexplained;
  const churnGovernorPassing = (paperChurn?.status ?? paperChurn?.state) === 'ACTIVE'
    && (churnDuplicateNewEntries ?? 1) === 0
    && (churnSameCandleReentry ?? 1) === 0
    && paperChurn?.cost_drag_within_envelope === true
    && paperChurn?.economic_trade_count_reconciles === true;
  const paperAgradeRows = aGradeSupplyBlocker?.A_grade_rows
    ?? aGradeSupplyBlocker?.a_grade_rows
    ?? paperAgrade?.A_grade_rows
    ?? paperAgrade?.a_grade_rows;
  const paperNearAgradeRows = aGradeSupplyBlocker?.near_A_grade_rows
    ?? aGradeSupplyBlocker?.near_a_grade_rows
    ?? paperAgrade?.near_A_grade_rows
    ?? paperAgrade?.near_a_grade_rows;
  const aGradeClosestGap = aGradeSupplyBlocker?.closest_gap_reason
    ?? paperAgrade?.closest_gap_reason
    ?? aGradeSupplyBlocker?.status
    ?? paperAgrade?.status;
  const aGradeRootCauses = aGradeSupplyBlocker?.root_cause_counts
    ?? paperAgrade?.root_cause_counts
    ?? null;
  const aGradePredicates = aGradeSupplyBlocker?.predicate_counts
    ?? paperAgrade?.predicate_counts
    ?? null;
  const aGradeDominantReasons = aGradeSupplyBlocker?.dominant_current_runtime_reasons
    ?? paperAgrade?.dominant_current_runtime_reasons
    ?? null;
  const aGradeGuardianStatus = aGradeSupplyBlocker?.guardian_status
    ?? paperAgrade?.guardian_status
    ?? null;
  const aGradeSourceTierRows = aGradeSupplyBlocker?.source_tier_a_grade_execution_rows
    ?? paperAgrade?.source_tier_a_grade_execution_rows
    ?? null;
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
  const guardian = view.guardian;
  const guardianMetrics = guardian?.realtime_a_grade_metrics;
  const guardianTruth = guardian?.readiness_truth;
  const guardianGate = guardian?.a_grade_execution_gate;
  const trajectory = guardian?.trajectory_status;
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
              {publicTelemetryText(capital?.status ?? view.overallStatus ?? (payload ? 'CONNECTING' : 'CONNECTING'))}
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
        <HeaderMetric
          label="Trainer Learning"
          value={guardianTruth?.online_learning_status ?? (guardianTruth?.WEIGHTS_UPDATING ? 'WEIGHTS_UPDATING' : 'CONNECTING')}
          color={guardianTruth?.WEIGHTS_UPDATING ? 'var(--buy,#10b981)' : '#f59e0b'}
        />
        <HeaderMetric
          label="A-grade Gate"
          value={guardian?.guardian_status ?? guardianGate?.status ?? 'CONNECTING'}
          color={guardianGate?.a_grade_new_entries_allowed ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Trades"
          value={countText(guardianMetrics?.closed_economic_trade_count)}
          color={(guardianMetrics?.closed_economic_trade_count ?? 0) >= 1000 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade 100/300/1000"
          value={`${formatAdaptivePercent(guardianMetrics?.rolling_100_trade_win_rate)} / ${formatAdaptivePercent(guardianMetrics?.rolling_300_trade_win_rate)} / ${formatAdaptivePercent(guardianMetrics?.rolling_1000_trade_win_rate)}`}
          color={guardianGate?.a_grade_new_entries_allowed ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Edge"
          value={`${formatAdaptiveBps(guardianMetrics?.after_cost_expectancy_bps)} · PF ${guardianMetrics?.profit_factor ?? '—'}`}
          color={guardianGate?.a_grade_new_entries_allowed ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Liquidations"
          value={countText(guardianMetrics?.liquidation_event_count)}
          color={(guardianMetrics?.liquidation_event_count ?? 0) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="1000x Trajectory"
          value={trajectory?.current_status ?? trajectory?.status ?? 'INSUFFICIENT_EVIDENCE'}
          color={trajectory?.status === 'ON_1000X_TRAJECTORY' ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="1000x 1/7/30"
          value={`${compactPercent(trajectory?.actual_1d_return)} / ${compactPercent(trajectory?.actual_7d_return)} / ${compactPercent(trajectory?.actual_30d_return)}`}
          color={trajectory?.status === 'ON_1000X_TRAJECTORY' ? 'var(--buy,#10b981)' : 'var(--text-secondary)'}
        />
        <HeaderMetric
          label="1000x Edge"
          value={`${compactPercent(trajectory?.required_edge)} · ${compactMoney(trajectory?.required_capital)}`}
          color="var(--text-secondary)"
        />
        <HeaderMetric
          label="1000x LCB/DD"
          value={`${compactPercent(trajectory?.lower_confidence_bound_growth_rate, 3)} / ${compactPercent(trajectory?.drawdown_adjusted_growth_rate, 3)}`}
          color={trajectory?.status === 'ON_1000X_TRAJECTORY' ? 'var(--buy,#10b981)' : 'var(--text-secondary)'}
        />
        <HeaderMetric
          label="1000x Days"
          value={signedDays(trajectory?.days_ahead_or_behind_target)}
          color={(trajectory?.days_ahead_or_behind_target ?? -1) >= 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Paper Owner"
          value={paperLoop?.paper_policy_owner ?? 'CONNECTING'}
          color={paperLoop?.paper_policy_owner === 'challenger_v2' ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Cost Coverage"
          value={formatAdaptivePercent(paperLoop?.production_grade_cost_coverage)}
          color={(paperLoop?.production_grade_cost_coverage ?? 0) >= 0.95 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Cost Rows"
          value={`${countText(paperLoop?.production_grade_cost_rows)}/${countText(paperLoop?.intents_built)}`}
          color={(paperLoop?.production_grade_cost_coverage ?? 0) >= 0.95 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="No-Order Explained"
          value={countText(paperLoop?.no_order_explained_rows)}
          color={(paperLoop?.unexplained_missing_cost_rows ?? 1) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Churn Governor"
          value={paperChurn?.status ?? paperChurn?.state ?? 'CONNECTING'}
          color={churnGovernorPassing ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Churn Dup/Reentry"
          value={`${countText(churnDuplicateNewEntries)} / ${countText(churnSameCandleReentry)}`}
          color={(churnDuplicateNewEntries ?? 1) === 0 && (churnSameCandleReentry ?? 1) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Outcomes"
          value={`${countText(forwardOutcomes)}/${countText(requiredForwardOutcomes)}`}
          color={(forwardOutcomes ?? -1) >= (requiredForwardOutcomes ?? Number.POSITIVE_INFINITY) ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Symbols"
          value={`${countText(forwardSymbols)}/${countText(requiredForwardSymbols)}`}
          color={(forwardSymbols ?? -1) >= (requiredForwardSymbols ?? Number.POSITIVE_INFINITY) ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Shortfall"
          value={`${countText(forwardOutcomeShortfall)} outcomes / ${countText(forwardSymbolShortfall)} symbols`}
          color={(forwardOutcomeShortfall ?? 1) === 0 && (forwardSymbolShortfall ?? 1) === 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Canary Long/Short"
          value={`${countText(forwardLongOutcomes)} / ${countText(forwardShortOutcomes)}`}
          color={(forwardLongOutcomes ?? 0) > 0 && (forwardShortOutcomes ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Rows"
          value={`${countText(paperAgradeRows)} / near ${countText(paperNearAgradeRows)}`}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Source"
          value={aGradeClosestGap ?? 'CONNECTING'}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Roots"
          value={compactTopReasons(aGradeRootCauses)}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Dominant"
          value={compactTopReasons(aGradeDominantReasons)}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Predicates"
          value={`risk ${countText(aGradePredicates?.risk_pass_rows)} / strategy ${countText(aGradePredicates?.strategy_pass_rows)} / allocator ${countText(aGradePredicates?.allocator_pass_rows)}`}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="A-grade Guardian"
          value={`${aGradeGuardianStatus ?? 'CONNECTING'} / tier ${countText(aGradeSourceTierRows)}`}
          color={(paperAgradeRows ?? 0) > 0 ? 'var(--buy,#10b981)' : 'var(--sell,#ef4444)'}
        />
        <HeaderMetric
          label="Live Gate"
          value={paperRuntime?.live_gate_status ?? 'blocked_human_only'}
          color="var(--sell,#ef4444)"
        />
      </div>

      {guardianGate?.block_all_new_a_grade_entries && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <div style={{
            border: '1px solid color-mix(in oklch, var(--sell,#ef4444) 35%, transparent)',
            background: 'color-mix(in oklch, var(--sell,#ef4444) 10%, transparent)',
            borderRadius: 6,
            padding: '8px 10px',
            fontSize: 11,
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            overflowWrap: 'anywhere',
          }}>
            {publicTelemetryText(guardian?.guardian_status ?? guardianGate.status)} · new A-grade entries route to {publicTelemetryText(guardianGate.new_candidate_tier_override ?? 'SHADOW_ONLY')} · {publicTelemetryText(guardianGate.failure_reasons?.[0]?.reason)}
          </div>
        </div>
      )}

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
            {publicTelemetryText(readiness?.status ?? readiness?.overall_status ?? (payload ? 'CONNECTING' : 'CONNECTING'))}
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
            {predictionProbe ? (predictionProbe.probe_participates_in_counterfactual_pass_gate ? 'GATING' : 'NON-GATING') : 'CONNECTING'}
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
            value={selectionAttribution?.status ?? 'CONNECTING'}
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
          <TimeframeAccuracyCards rows={view.timeframeRows} compact={compact} />
        </div>
      )}

      {showMatrix && view.symbolRows.length > 0 && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          <SymbolAccuracyCards rows={view.symbolRows} compact={compact} maxHeight={symbolHeight} />
        </div>
      )}

      {showMatrix && (
        <div style={{ padding: compact ? '0 12px 12px' : '0 16px 16px' }}>
          {view.matrixRows.length > 0 ? (
            <AccuracyHeatmap rows={view.matrixRows} compact={compact} maxHeight={matrixHeight} />
          ) : (
            <TelemetrySection title="All Symbol/TF Accuracy" meta="CONNECTING">
              <TelemetryEmptyState message="Awaiting realtime symbol/timeframe accuracy cells. Missing values remain unavailable until a sourced frame arrives." />
            </TelemetrySection>
          )}
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
