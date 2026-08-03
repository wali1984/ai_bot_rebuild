import { expect, test } from '@playwright/test';
import { adaptiveCapitalTelemetryTestHooks } from '../../src/components/trading/AdaptiveCapitalTelemetryPanel';
import {
  shouldEnableAdaptiveCapitalFallback,
  type AdaptiveCapitalDashboardPayload,
} from '../../src/data/adaptiveCapitalProductivity';
import { gotoAs } from './_shared';
import { mockAuth, type TestAuthRole } from './helpers/auth';

test.describe('adaptive capital telemetry panel view model', () => {
  test('keeps static side payload fallback disabled while the live dashboard stream is loading or connected', () => {
    expect(shouldEnableAdaptiveCapitalFallback(null, true, null)).toBe(false);
    expect(shouldEnableAdaptiveCapitalFallback({ generated_utc: '2026-06-22T05:30:52Z' }, false, null)).toBe(false);
    expect(shouldEnableAdaptiveCapitalFallback(null, false, 'resource_websocket_error')).toBe(true);
  });

  test('resolves rolling PnL and preserves all symbol/timeframe accuracy cells', () => {
    const payload: AdaptiveCapitalDashboardPayload = {
      generated_utc: '2026-06-20T04:35:56Z',
      overall_status: 'NO_GO',
      capital_productivity_runtime_status: {
        status: 'NO_GO_INSUFFICIENT_CAPITAL_PRODUCTIVITY_EVIDENCE',
        capital_utilization_classification: 'NO_EDGE_IDLE',
        pnl_history: {
          status: 'READY',
          windows: [
            { window: '30d', realized_pnl_usd: 30, closed_trade_count: 30 },
            { window: '1d', realized_pnl_usd: -1.25, closed_trade_count: 5 },
            { window: '7d', realized_pnl_usd: 7.5, closed_trade_count: 14 },
          ],
        },
        signal_prediction_accuracy_status: {
          status: 'READY',
          overall_accuracy: 0.5,
          symbol_universe_count: 2,
          symbol_timeframe_cell_count: 4,
          evaluated_symbol_timeframe_cell_count: 2,
          evaluated_row_count: 4,
          by_timeframe: [
            { timeframe: '4h', accuracy: 0.25, evaluated_count: 4, symbol_timeframe_cell_count: 2 },
            { timeframe: '1m', accuracy: 0.75, evaluated_count: 8, symbol_timeframe_cell_count: 2 },
          ],
          by_symbol_timeframe: [
            { symbol: 'ETHUSDT', timeframe: '4h', accuracy: 0.25, evaluated_count: 4, realized_pnl_usd: -2, status: 'EVALUATED' },
            { symbol: 'BTCUSDT', timeframe: '1m', accuracy: 0.75, evaluated_count: 8, realized_pnl_usd: 3, status: 'EVALUATED' },
            { symbol: 'BTCUSDT', timeframe: '4h', accuracy: null, evaluated_count: 0, realized_pnl_usd: 0, status: 'NO_EVALUATED_OUTCOMES' },
            { symbol: 'ETHUSDT', timeframe: '1m', accuracy: null, evaluated_count: 0, realized_pnl_usd: 0, status: 'NO_SOURCE_ROWS' },
          ],
        },
      },
      adaptive_capital_policy_status: {
        status: 'NO_GO_POLICY_EVIDENCE_INSUFFICIENT',
        post_allocator_closed_outcome_count: 14,
        minimum_required_closed_outcomes: 300,
        long_closed_outcome_count: 5,
        short_closed_outcome_count: 9,
        both_long_short_evidence: true,
        symbol_count: 7,
        minimum_required_symbol_count: 30,
        symbol_diversity_deficit: 23,
      },
      operator_go_readiness: {
        status: 'NO_GO',
        overall_status: 'NO_GO',
        remaining_blockers: ['capital_productivity_runtime_status'],
        failed_conditions: ['post_policy_outcome_count'],
        evidence_to_go: {
          closed_outcomes_needed: 286,
          closed_outcomes_needed_after_current_open_positions_close: 280,
          additional_symbols_needed: 23,
          a_grade_replay_evidence_needed: 1,
          counterfactual_best_configurations_needed: 1,
          selection_attribution_rows_needed: 31,
        },
        adaptive_field_selection_evidence: {
          row_count: 49,
          required_selection_field_coverage: 1,
          leverage_selection_model_input_coverage: 0.72,
          margin_mode_selection_model_input_coverage: 0.18,
          hedge_budget_selection_model_input_coverage: 0.41,
          complete_selection_model_input_count: 18,
          complete_selection_model_input_coverage: 0.37,
        },
        adaptive_selection_attribution_status: {
          status: 'NO_GO_SELECTION_ATTRIBUTION_INCOMPLETE',
          blocker_reasons: ['MARGIN_MODE_SELECTION_MODEL_INPUT_INCOMPLETE'],
          row_count: 49,
          required_selection_field_coverage: 1,
          complete_selection_model_input_count: 18,
          complete_selection_model_input_coverage: 0.37,
          selection_model_input_missing_counts: {
            complete_selection_model_input: 31,
            margin_mode_selection_model_input: 40,
          },
          leverage_selection_model_input_coverage: 0.72,
          margin_mode_selection_model_input_coverage: 0.18,
          hedge_budget_selection_model_input_coverage: 0.41,
          required_runtime_selection_model_input_coverage: 1,
        },
        pre_submit_adaptive_field_selection_evidence: {
          row_count: 6,
          required_selection_field_coverage: 1,
          margin_mode_selection_model_input_coverage: 1,
          hedge_budget_selection_model_input_coverage: 1,
          margin_mode_selection_reason_counts: { isolated_edge_control: 4, cross_reduced: 2 },
          hedge_budget_selection_reason_counts: { hedge_disabled: 5, low_correlation_offset: 1 },
        },
        counterfactual_replay_progress: {
          a_grade_replay_evidence_deficit: 1,
          a_grade_replay_progress_pct: 0,
          a_grade_source_kind_counts: { paper_signal: 755, paper_ledger: 44 },
          a_grade_source_kind_readiness: {
            paper_signal: {
              row_count: 755,
              directional_row_count: 442,
              confidence_present_count: 755,
              confidence_at_or_above_threshold_count: 1,
              edge_present_count: 754,
              positive_after_cost_edge_count: 426,
              positive_edge_below_confidence_count: 426,
              a_grade_before_temporal_count: 0,
              event_time_valid_candidate_count: 0,
              best_configuration_count: 0,
              not_a_grade_reason_counts: { LOW_CONFIDENCE: 754, NON_DIRECTIONAL_ACTION: 313 },
              closest_near_a_grade: {
                symbol: 'BTCUSDT',
                timeframe: '5m',
                side: 'short',
                confidence: 0.69615141,
                confidence_threshold: 0.75,
                confidence_gap_to_a_grade: 0.05384859,
                after_cost_edge_bps: 80.71569824,
                reasons: ['LOW_CONFIDENCE'],
              },
            },
          },
          best_configuration_deficit_to_frontier: 1,
          closest_confidence_gap_to_a_grade: 0.05384859,
          closest_edge_gap_to_positive_bps: 0,
          configuration_count_reconciled: true,
          configurations_considered_count: 540,
          theoretical_configuration_count: 540,
        },
      },
      counterfactual_capital_sweep_status: {
        status: 'NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE',
        prediction_row_count: 2,
        prediction_counterfactual_probe: {
          status: 'NO_GO_COUNTERFACTUAL_REPLAY_NOT_COMPLETE',
          prediction_row_count: 2,
          probe_participates_in_counterfactual_pass_gate: false,
          a_grade_before_temporal_count: 1,
          event_time_valid_candidate_count: 1,
          best_configuration_count: 0,
          skipped_no_feasible_configuration_count: 1,
          skipped_not_a_grade_reason_counts: { LOW_CONFIDENCE: 1 },
          a_grade_readiness: {
            source_kind_counts: { prediction: 2 },
            source_kind_readiness: {
              prediction: {
                row_count: 2,
                confidence_at_or_above_threshold_count: 1,
                positive_after_cost_edge_count: 1,
                a_grade_before_temporal_count: 1,
                event_time_valid_candidate_count: 1,
                best_configuration_count: 0,
                no_feasible_configuration_count: 1,
                not_a_grade_reason_counts: { LOW_CONFIDENCE: 1 },
              },
            },
          },
        },
      },
      pass_condition_status: {
        status: 'NO_GO',
        condition_status_counts: { PASSED: 10, NO_GO: 6 },
        failed_conditions: ['post_policy_outcome_count'],
        conditions: [
          { id: 'mandatory_per_trade_accounting', status: 'PASSED' },
          { id: 'post_policy_outcome_count', status: 'NO_GO' },
        ],
      },
    };

    const view = adaptiveCapitalTelemetryTestHooks.resolveTelemetry(payload);

    expect(view.windows.map((row) => [row.label, row.row?.realized_pnl_usd])).toEqual([
      ['1D', -1.25],
      ['1W', 7.5],
      ['30D', 30],
    ]);
    expect(view.timeframeRows.map((row) => row.timeframe)).toEqual(['1m', '4h']);
    expect(view.policy?.post_allocator_closed_outcome_count).toBe(14);
    expect(view.policy?.both_long_short_evidence).toBe(true);
    expect(view.readiness?.evidence_to_go?.closed_outcomes_needed).toBe(286);
    expect(view.readiness?.evidence_to_go?.selection_attribution_rows_needed).toBe(31);
    expect(view.readiness?.adaptive_selection_attribution_status?.status).toBe('NO_GO_SELECTION_ATTRIBUTION_INCOMPLETE');
    expect(view.readiness?.adaptive_selection_attribution_status?.complete_selection_model_input_count).toBe(18);
    expect(view.readiness?.pre_submit_adaptive_field_selection_evidence?.margin_mode_selection_model_input_coverage).toBe(1);
    expect(view.readiness?.counterfactual_replay_progress?.configuration_count_reconciled).toBe(true);
    expect(view.readiness?.counterfactual_replay_progress?.a_grade_source_kind_readiness?.paper_signal?.positive_after_cost_edge_count).toBe(426);
    expect(view.counterfactual?.prediction_counterfactual_probe?.prediction_row_count).toBe(2);
    expect(view.counterfactual?.prediction_counterfactual_probe?.probe_participates_in_counterfactual_pass_gate).toBe(false);
    expect(view.passConditions?.condition_status_counts?.PASSED).toBe(10);
    expect(view.passConditions?.failed_conditions).toEqual(['post_policy_outcome_count']);
    expect(view.matrixRows).toHaveLength(4);
    expect(view.matrixRows.map((row) => `${row.symbol}:${row.timeframe}`)).toEqual([
      'BTCUSDT:1m',
      'BTCUSDT:4h',
      'ETHUSDT:1m',
      'ETHUSDT:4h',
    ]);
  });

  test('prefers top-level dashboard PnL and accuracy payloads when present', () => {
    const payload: AdaptiveCapitalDashboardPayload = {
      capital_productivity_runtime_status: {
        pnl_history: {
          windows: [{ window: '1d', realized_pnl_usd: 1, closed_trade_count: 1 }],
        },
        signal_prediction_accuracy_status: {
          overall_accuracy: 0.1,
          evaluated_row_count: 1,
          by_symbol_timeframe: [{ symbol: 'OLDUSDT', timeframe: '1m', evaluated_count: 1 }],
        },
      },
      pnl_history_status: {
        windows: [{ window: '1d', realized_pnl_usd: 2, closed_trade_count: 2 }],
      },
      signal_prediction_accuracy_status: {
        overall_accuracy: 0.2,
        evaluated_row_count: 2,
        by_symbol_timeframe: [{ symbol: 'NEWUSDT', timeframe: '1m', evaluated_count: 2 }],
      },
    };

    const view = adaptiveCapitalTelemetryTestHooks.resolveTelemetry(payload);

    expect(view.windows[0].row?.realized_pnl_usd).toBe(2);
    expect(view.accuracy?.overall_accuracy).toBe(0.2);
    expect(view.matrixRows.map((row) => row.symbol)).toEqual(['NEWUSDT']);
  });

  test('materializes missing universe timeframe accuracy cells as unevaluated', () => {
    const payload: AdaptiveCapitalDashboardPayload = {
      signal_prediction_accuracy_status: {
        status: 'READY',
        symbol_universe: ['ETHUSDT', 'BTCUSDT'],
        timeframes: ['5m', '1m'],
        required_symbol_timeframe_cell_count: 4,
        evaluated_symbol_timeframe_cell_count: 1,
        by_symbol_timeframe: [
          {
            symbol: 'BTCUSDT',
            timeframe: '1m',
            accuracy: 0.75,
            evaluated_count: 8,
            correct_count: 6,
            prediction_count: 8,
            signal_count: 8,
            realized_pnl_usd: 3,
            status: 'EVALUATED',
          },
        ],
      },
    };

    const view = adaptiveCapitalTelemetryTestHooks.resolveTelemetry(payload);

    expect(view.matrixRows.map((row) => `${row.symbol}:${row.timeframe}:${row.status}`)).toEqual([
      'BTCUSDT:1m:EVALUATED',
      'BTCUSDT:5m:MISSING_EVALUATED_OUTCOMES',
      'ETHUSDT:1m:MISSING_EVALUATED_OUTCOMES',
      'ETHUSDT:5m:MISSING_EVALUATED_OUTCOMES',
    ]);
    expect(view.matrixRows.filter((row) => row.evaluated_count === 0)).toHaveLength(3);
  });
});

const TELEMETRY_ROUTES: Array<{ path: string; role: TestAuthRole }> = [
  { path: '/dashboard', role: 'trader' },
  { path: '/trade', role: 'trader' },
  { path: '/binance', role: 'trader' },
  { path: '/signals', role: 'trader' },
  { path: '/ai-predictions', role: 'trader' },
  { path: '/portfolio', role: 'trader' },
  { path: '/history', role: 'trader' },
  { path: '/admin/mission-control', role: 'admin' },
  { path: '/admin/evidence', role: 'superadmin' },
  { path: '/admin/paper-trading', role: 'admin' },
  { path: '/admin/executions', role: 'admin' },
  { path: '/admin/trainer-admin', role: 'admin' },
  { path: '/admin/trainer-prediction-monitor', role: 'admin' },
  { path: '/admin/signal-explainability', role: 'admin' },
  { path: '/research/technical-analysis', role: 'trader' },
];

test.describe('adaptive capital telemetry panel routes', () => {
  for (const route of TELEMETRY_ROUTES) {
    test(`${route.path} renders adaptive capital telemetry`, async ({ page }) => {
      await mockAuth(page, route.role);
      await gotoAs(page, route.path, route.role, { waitUntil: 'domcontentloaded' });

      const panel = page.getByTestId('adaptive-capital-telemetry-panel').first();
      await expect(panel).toBeVisible({ timeout: 15_000 });
      await expect(panel).toContainText(/PnL/i);
      await expect(panel).toContainText(/Accuracy/i);
      await expect(panel).toContainText(/Evidence To GO/i);
      await expect(panel).toContainText(/A-grade Readiness/i);
      await expect(panel).toContainText(/Prediction Readiness Probe/i);
      await expect(panel).toContainText(/Pre-submit Attribution/i);
      await expect(panel).toContainText(/Selection Gate/i);
      await expect(panel).toContainText(/All Symbol\/TF Accuracy/i);
    });
  }
});
