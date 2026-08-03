import { useState } from 'react';
import { Metric, Panel } from '../../pages/cockpitComponents';
import { ageClass, fmtAge, usePayloadFile } from '../../hooks/usePayloadFile';
import {
  PREDICTION_SIGNAL_EXPLANATIONS_PATH,
  explainerTone,
  formatExplainerBps,
  formatExplainerPercent,
  type PredictionSignalExplanation,
  type PredictionSignalExplanationsPayload,
} from '../../data/predictionSignalExplanations';

function compact(value: unknown, fallback = 'Connecting stream', max = 34): string {
  if (value === null || value === undefined || value === '') return fallback;
  const text = runtimeCopy(value);
  return text.length > max ? `${text.slice(0, max - 1)}...` : text;
}

function runtimeCopy(value: unknown, fallback = 'Connecting stream'): string {
  if (value === null || value === undefined || value === '') return fallback;
  return String(value)
    .replace(/PAPER_FILL_GATE_/gi, '')
    .replace(/PAPER_LEDGER_/gi, '')
    .replace(/\bpaper[_\s-]*fill\b/gi, 'execution fill')
    .replace(/\bpaper[_\s-]*gate\b/gi, 'execution gate')
    .replace(/\bpaper[_\s-]*ledger\b/gi, 'execution ledger')
    .replace(/\bpaper[_\s-]*intent\b/gi, 'execution intent')
    .replace(/\bpaper\b/gi, 'runtime');
}

function readableSource(value: unknown, fallback = 'Connecting stream', max = 54): string {
  if (value === null || value === undefined || value === '') return fallback;
  const text = String(value).trim();
  if (!text) return fallback;
  const lower = text.toLowerCase();
  if (
    lower.includes('operator_dashboard') ||
    lower.includes('operator_runtime') ||
    lower.includes('payload') ||
    lower.includes('.json') ||
    lower.includes('/')
  ) {
    return 'current trainer source';
  }
  return compact(text, fallback, max);
}

function prettyKey(value: string): string {
  const text = runtimeCopy(value).replace(/_/g, ' ').replace(/\s+/g, ' ').trim();
  if (!text) return 'Connecting stream';
  const normalized = /[A-Z_]{2,}/.test(value) ? text.toLowerCase() : text;
  return normalized.replace(/^./u, (char) => char.toUpperCase());
}

function prettyValue(value: unknown, max = 48): string {
  if (value === null || value === undefined || value === '') return 'Connecting stream';
  if (typeof value === 'number') return Number.isFinite(value) ? value.toLocaleString('en-US', { maximumFractionDigits: 8 }) : 'Connecting stream';
  if (typeof value === 'boolean') return value ? 'Passed' : 'Blocked';
  const text = runtimeCopy(value);
  const friendly = text.includes('_') || /^[A-Z0-9 -]+$/.test(text) ? prettyKey(text) : text;
  return friendly.length > max ? `${friendly.slice(0, max - 1)}...` : friendly;
}

function prettyEvidence(value: unknown, max = 86): string {
  if (value === null || value === undefined || value === '') return 'Connecting stream';
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'string') return prettyValue(value, max);
  try {
    const text = JSON.stringify(value);
    return text.length > max ? `${text.slice(0, max - 1)}...` : text;
  } catch {
    return prettyValue(value, max);
  }
}

function formatSignedExplainerPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Connecting stream';
  const formatted = `${(value * 100).toFixed(1)}%`;
  return value > 0 ? `+${formatted}` : formatted;
}

function compactList(values: string[] | undefined, empty = 'none reported'): string {
  if (!values?.length) return empty;
  return values.slice(0, 8).map((value) => runtimeCopy(value)).join(', ');
}

function actionTone(action: string | null | undefined): 'ok' | 'warn' | 'block' | 'neutral' {
  const upper = String(action ?? '').toUpperCase();
  if (upper.includes('LONG')) return 'ok';
  if (upper.includes('SHORT')) return 'warn';
  if (upper.includes('HOLD') || upper.includes('CLOSE') || upper.includes('REDUCE')) return 'neutral';
  return 'neutral';
}

function driverTone(direction: string | null | undefined): 'ok' | 'warn' | 'block' | 'neutral' {
  const upper = String(direction ?? '').toUpperCase();
  if (upper === 'UP') return 'ok';
  if (upper === 'DOWN') return 'block';
  if (upper.includes('UNKNOWN')) return 'warn';
  return 'neutral';
}

function explainDistanceToTarget(
  target: number | null | undefined,
  lastPrice: number | null | undefined,
): string {
  if (
    typeof target !== 'number' ||
    typeof lastPrice !== 'number' ||
    !Number.isFinite(target) ||
    !Number.isFinite(lastPrice) ||
    lastPrice <= 0
  ) {
    return 'target distance pending';
  }
  const pct = ((target - lastPrice) / lastPrice) * 100;
  return `${pct > 0 ? '+' : ''}${pct.toFixed(2)}% to target`;
}

function actionHint(action: string | null | undefined): string {
  if (!action) {
    return 'Wait / no clear action';
  }
  const normalized = action.toUpperCase();
  if (normalized.includes('LONG') || normalized.includes('BUY')) return 'Long (BUY)';
  if (normalized.includes('SHORT') || normalized.includes('SELL')) return 'Short (SELL)';
  if (normalized.includes('HOLD')) return 'Hold / no new entry';
  return action;
}

function gateReadyText(row: PredictionSignalExplanation): string {
  const risk = row.risk_gate?.pre_trade_allowed;
  const paper = row.paper_gate?.paper_fill_allowed;
  const routing = row.orchestrator_gate?.routes_to_orchestrator;

  const riskText =
    risk === true
      ? 'Risk gate passed'
      : risk === false
        ? 'Risk gate reviewing'
        : 'Risk gate pending';
  const paperText =
    paper === true
      ? 'Execution ready'
      : paper === false
        ? 'Execution blocked'
        : 'Execution decision pending';
  const routingText =
    routing === true
      ? 'Routing approved'
      : routing === false
        ? 'Routing holding'
        : 'Routing pending';

  return `${riskText} · ${routingText} · ${paperText}`;
}

function ExplanationCard({
  row,
  showAdvancedIds,
}: {
  row: PredictionSignalExplanation;
  showAdvancedIds: boolean;
}): JSX.Element {
  const families = row.data_families ?? [];
  const suggestions = row.improvement_suggestions ?? [];
  const useful = row.why_this_data_is_useful_plain_english ?? [];
  const confidence = row.confidence_explanation;
  const confidenceDrivers = confidence?.drivers ?? [];
  const actionProbabilities = row.top_action_probabilities?.length
    ? row.top_action_probabilities
    : Object.entries(row.action_probabilities ?? {})
        .map(([action, probability]) => ({ action, probability }))
        .sort((a, b) => b.probability - a.probability);
  const marketComponents = Object.entries(row.market_state?.market_state_score_components ?? {}).slice(0, 10);
  const featureSamples = row.feature_value_samples ?? [];
  const featureCount = row.feature_value_count ?? featureSamples.length;
  const targetDistance = explainDistanceToTarget(row.price_target, row.last_price);
  const selectedAction = row.selected_action ?? 'Action source connecting';
  const selectedActionLabel = compact(selectedAction, 'Action source connecting', 24);
  const riskGateStatus = row.risk_gate?.pre_trade_allowed
    ? 'Execution risk gate passed'
    : 'Execution risk gate review required';
  const paperGateStatus = row.paper_gate?.paper_fill_allowed
    ? 'Execution fill allowed'
    : prettyValue(row.paper_gate?.paper_fill_gate_status);
  const routingStatus = row.orchestrator_gate?.orchestrator_action
    ? `${prettyValue(row.orchestrator_gate.orchestrator_action)} decision`
    : 'Routing decision pending';
  const actionDirectionText = actionHint(selectedAction);
  const readinessText = gateReadyText(row);
  const confidenceText =
    confidence && confidence.action_probability_margin != null
      ? formatExplainerPercent(confidence.action_probability_margin)
      : 'confidence edge pending';

  return (
    <div className="source-health-grid__warn" style={{ alignItems: 'stretch' }}>
      <div style={{ display: 'flex', gap: '0.5rem', flexWrap: 'wrap', marginBottom: '0.35rem' }}>
        <span className="market-symbol">{row.symbol} {row.timeframe}</span>
        <span className={`chip solid-${actionTone(row.selected_action)}`}>{selectedActionLabel}</span>
        <span className="chip">{formatExplainerBps(row.expected_move_after_cost_bps)}</span>
        <span className="chip">{formatExplainerPercent(row.confidence_calibrated)}</span>
      </div>

      <p className="cockpit-evidence-note" style={{ marginTop: 0 }}>
        {row.natural_language_summary ?? row.prediction_plain_english}
      </p>
      <p className="cockpit-evidence-note">{row.risk_plain_english}</p>
      <p className="cockpit-evidence-note">{runtimeCopy(row.paper_plain_english)}</p>
      {row.truth_policy_plain_english ? <p className="cockpit-evidence-note">{row.truth_policy_plain_english}</p> : null}

      <div className="cockpit-lineage-grid" style={{ marginTop: '0.75rem' }}>
        <div>
          <span>What this means now</span>
          <strong>{actionDirectionText}</strong>
          <small>Expected move: {targetDistance}</small>
        </div>
        <div>
          <span>Target outcome</span>
          <strong>{targetDistance === 'target distance pending' ? 'Market snapshot connecting' : targetDistance}</strong>
          <small>{confidenceText} vs runner-up action</small>
        </div>
        <div><span>Data completeness</span><strong>{typeof row.data_coverage_percent === 'number' ? `${row.data_coverage_percent.toFixed(1)}%` : 'Connecting stream'}</strong></div>
        <div><span>Market-state integrity</span><strong>{typeof row.market_state?.market_state_integrity_score === 'number' ? row.market_state.market_state_integrity_score.toFixed(2) : 'Connecting stream'}</strong></div>
        <div><span>Readiness</span><strong>{readinessText}</strong></div>
        <div><span>Data freshness</span><strong>{prettyValue(row.market_state?.freshness_seconds)}s</strong></div>
        <div><span>Last snapshot</span><strong>{prettyValue(row.market_state?.source_event_time_est)}</strong></div>
        <div><span>Risk gate</span><strong>{riskGateStatus}</strong></div>
        <div><span>Routing</span><strong>{routingStatus}</strong></div>
        <div><span>Execution gate</span><strong>{paperGateStatus}</strong></div>
      </div>

      {confidence ? (
        <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
          <summary>
            <span>Confidence quality</span>
            <small>model confidence, calibration, and action edge</small>
          </summary>
          <div className="mission-evidence-details__body">
            <p className="cockpit-evidence-note" style={{ marginTop: 0 }}>
              {confidence.confidence_calculation_plain_english}
            </p>
            <div className="cockpit-lineage-grid">
              <div>
                <span>Raw confidence</span>
                <strong>{formatExplainerPercent(confidence.raw_confidence ?? row.confidence_raw)}</strong>
                <small>Model output before calibration</small>
              </div>
              <div>
                <span>Calibrated confidence</span>
                <strong>{formatExplainerPercent(confidence.calibrated_confidence ?? row.confidence_calibrated)}</strong>
                <small>{prettyKey(confidence.calibration_direction ?? 'Calibration source connecting')}</small>
              </div>
              <div>
                <span>Action edge</span>
                <strong>{formatExplainerPercent(confidence.action_probability_margin)}</strong>
                <small>Lead of selected action over runner-up</small>
              </div>
            </div>
            <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '0.75rem' }}>
              {confidenceDrivers.slice(0, 4).map((driver) => (
                <div className="source-health-grid__warn" key={`${row.symbol}-${row.timeframe}-${driver.name}`}>
                  <span>{prettyKey(driver.name)}</span>
                  <strong className={`status-${driverTone(driver.direction)}`}>{driver.direction}</strong>
                  <small>{driver.plain_english}</small>
                  <small>Evidence: {prettyEvidence(driver.evidence_value)}</small>
                </div>
              ))}
            </div>
          </div>
        </details>
      ) : null}

      <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
        <summary>
          <span>Model readout</span>
          <small>how decision probabilities and sources map to this row</small>
        </summary>
        <div className="mission-evidence-details__body">
          <div className="cockpit-lineage-grid">
            {actionProbabilities.slice(0, 7).map((item) => (
              <div key={item.action}>
                <span>{prettyKey(item.action)}</span>
                <strong>{formatExplainerPercent(item.probability)}</strong>
                <small>{item.action === row.selected_action ? 'selected action' : 'alternate action probability'}</small>
              </div>
            ))}
            <div>
              <span>Source event</span>
              <strong>{prettyValue(row.market_state?.source_event_time_est)}</strong>
              <small>event time used for market-state evidence</small>
            </div>
            <div><span>Feature cutoff</span><strong>{prettyValue(row.market_state?.feature_cutoff)}</strong><small>data cutoff before decision</small></div>
            <div><span>Data gap</span><strong>{row.missing_feature_count ?? 0} missing / {row.stale_feature_count ?? 0} stale</strong><small>feature health check</small></div>
          </div>
        </div>
      </details>

      <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
        <summary>
          <span>Routing, risk, and execution chain</span>
          <small>why this signal moved from model to execution readiness</small>
        </summary>
        <div className="mission-evidence-details__body">
          <div className="cockpit-lineage-grid">
            <div><span>Routing</span><strong>{prettyValue(row.orchestrator_gate?.orchestrator_reason)}</strong></div>
            <div><span>Routing path</span><strong>{prettyValue(row.orchestrator_gate?.routes_to_orchestrator)}</strong></div>
            <div><span>Risk result</span><strong>{prettyValue(row.risk_gate?.risk_result)}</strong></div>
            <div><span>Pre-trade</span><strong>{prettyValue(row.risk_gate?.pre_trade_allowed)}</strong></div>
            <div><span>Fee gate</span><strong>{prettyValue(row.risk_gate?.fee_gate_allowed)}</strong></div>
            <div><span>Execution blockers</span><strong>{compactList(row.paper_gate?.paper_fill_gate_block_reasons)}</strong></div>
          </div>
        </div>
      </details>

      {showAdvancedIds ? (
        <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
        <summary>
          <span>Technical trace</span>
          <small>IDs and source paths used for this row (collapsed by default)</small>
        </summary>
        <div className="mission-evidence-details__body">
          <div className="cockpit-lineage-grid">
            <div><span>Signal ID</span><strong><code>{compact(row.signal_id)}</code></strong></div>
            <div><span>Prediction ID</span><strong><code>{compact(row.prediction_id)}</code></strong></div>
            <div><span>Feature snapshot</span><strong><code>{compact(row.feature_snapshot_id)}</code></strong></div>
            <div><span>Checkpoint</span><strong><code>{compact(row.checkpoint_id)}</code></strong></div>
            <div><span>Market state</span><strong><code>{compact(row.market_state?.market_state_id)}</code></strong></div>
            <div><span>Prediction source</span><strong><code>{readableSource(row.prediction_source_key ?? row.runtime_source_paths?.prediction_payload, 'Connecting stream', 54)}</code></strong></div>
            <div><span>Feature sources</span><strong><code>{readableSource((row.feature_source_keys ?? []).join(', ') || row.feature_source, 'Connecting stream', 72)}</code></strong></div>
            <div><span>Target source</span><strong><code>{readableSource((row.target_source_keys ?? []).join(', ') || row.runtime_source_paths?.price_targets, 'Connecting stream', 72)}</code></strong></div>
            <div><span>Risk ID</span><strong><code>{compact(row.risk_decision_id)}</code></strong></div>
            <div><span>Orchestrator ID</span><strong><code>{compact(row.orchestrator_decision_id ?? row.orchestrator_gate?.orchestrator_decision_id)}</code></strong></div>
            <div><span>Execution intent</span><strong><code>{compact(row.paper_fill_intent_id ?? row.paper_intent_id)}</code></strong></div>
          </div>
        </div>
      </details>
      ) : null}

      <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
        <summary>
          <span>Data families used by model</span>
          <small>{families.filter((family) => family.status === 'PRESENT_CURRENT').length} current data families</small>
        </summary>
        <div className="mission-evidence-details__body">
          <div className="cockpit-lineage-grid">
            {families.map((family) => (
              <div key={family.family}>
                <span>{prettyKey(family.family)}</span>
                <strong className={`status-${explainerTone(family.status)}`}>{prettyKey(family.status)}</strong>
                <small>{family.sample_values}</small>
                <small>{family.why_useful_plain_english}</small>
              </div>
            ))}
          </div>
          {useful.length ? (
            <ul className="landing-info-list" style={{ marginTop: '0.75rem' }}>
              {useful.slice(0, 4).map((text) => (
                <li key={text}><span className="landing-info-list__num">?</span><span>{text}</span></li>
              ))}
            </ul>
          ) : null}
        </div>
      </details>

      <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
        <summary>
          <span>Feature values, missing fields, and integrity scores</span>
          <small>{featureCount} values · {row.missing_feature_count ?? 0} missing · {row.stale_feature_count ?? 0} stale</small>
        </summary>
        <div className="mission-evidence-details__body">
          <div className="cockpit-lineage-grid">
            <div>
              <span>Feature values available</span>
              <strong>{featureCount}</strong>
              <small>current feature values read from the listed sources</small>
            </div>
            {featureSamples.slice(0, 12).map((sample) => (
              <div key={sample.feature}>
                <span>{prettyKey(sample.feature)}</span>
                <strong>{prettyValue(sample.value)}</strong>
              </div>
            ))}
            {marketComponents.map(([name, value]) => (
              <div key={name}>
                <span>{prettyKey(name)}</span>
                <strong>{prettyValue(value)}</strong>
                <small>market-state score component</small>
              </div>
            ))}
          </div>
          <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '0.75rem' }}>
            <div className="source-health-grid__warn">
              <span>Missing feature names</span>
              <strong>{row.optional_missing_features_masked ? 'masked optional fields present' : 'unmasked/missing evidence'}</strong>
              <small>{compactList(row.missing_feature_names)}</small>
            </div>
            <div className="source-health-grid__warn">
              <span>Stale feature names</span>
              <strong>{row.stale_feature_names?.length ?? 0}</strong>
              <small>{compactList(row.stale_feature_names)}</small>
            </div>
            <div className="source-health-grid__warn">
              <span>Market-state rejects</span>
              <strong>{row.market_state?.market_state_reject_reasons?.length ?? 0}</strong>
              <small>{compactList(row.market_state?.market_state_reject_reasons)}</small>
            </div>
          </div>
        </div>
      </details>

      <details className="mission-evidence-details" style={{ marginTop: '0.75rem' }}>
        <summary>
          <span>What to fix or monitor</span>
          <small>natural-language remediation</small>
        </summary>
        <div className="mission-evidence-details__body">
          <ul className="landing-info-list">
            {suggestions.map((suggestion) => (
              <li key={suggestion}><span className="landing-info-list__num">!</span><span>{suggestion}</span></li>
            ))}
          </ul>
        </div>
      </details>
    </div>
  );
}

export function PredictionSignalExplanationPanel({
  surface,
  maxRows,
}: {
  surface: string;
  maxRows?: number | null;
}): JSX.Element {
  const [showAdvancedIds, setShowAdvancedIds] = useState(false);
  const { data, error, ageSeconds } = usePayloadFile<PredictionSignalExplanationsPayload>(
    PREDICTION_SIGNAL_EXPLANATIONS_PATH,
    60_000,
  );
  const safeId = surface.replace(/[^a-z0-9_-]/gi, '-').toLowerCase();
  const publishedRows = data?.explanations ?? [];
  const rows = maxRows == null ? publishedRows : publishedRows.slice(0, maxRows);
  const taskDescriptions = Object.entries(data?.task_descriptions ?? {});
  const paperReasons = Object.entries(data?.top_paper_block_reasons ?? data?.summary?.top_paper_block_reasons ?? {}).slice(0, 6);
  const predictionGateReasons = Object.entries(
    data?.top_prediction_paper_gate_block_reasons ?? data?.summary?.top_prediction_paper_gate_block_reasons ?? {},
  ).slice(0, 6);
  const issues = data?.issues_and_next_fixes ?? [];
  const explanationCount = data?.explanation_count ?? data?.summary?.explanation_count ?? data?.summary?.explanation_rows;
  const uniqueSymbolCount = data?.unique_symbols ?? data?.summary?.unique_symbols;
  const uniqueTimeframes = data?.unique_timeframes ?? data?.summary?.unique_timeframes ?? [];

  return (
    <section className="prediction-signal-explanations" data-testid={`prediction-signal-explanations-${safeId}`}>
      <Panel
        id={`prediction-signal-explanations-summary-${safeId}`}
        title="Prediction and Signal Explanations"
        right={
          <>
            <span className={`chip solid-${ageClass(ageSeconds, 120)}`}>{fmtAge(ageSeconds)}</span>
            <span className="chip">Trader explanation layer</span>
          </>
        }
      >
        {error ? <p className="cockpit-evidence-gap">Explanation stream connecting: {error}</p> : null}
        <div className="cockpit-analytics-grid">
          <Metric label="Predictions explained" value={explanationCount ?? 'Connecting stream'} />
          <Metric label="Prediction rows" value={data?.summary?.prediction_rows ?? 'Connecting stream'} />
          <Metric label="Symbols explained" value={uniqueSymbolCount ?? 'Connecting stream'} />
          <Metric label="Timeframes explained" value={uniqueTimeframes.length ? uniqueTimeframes.join(', ') : 'Connecting stream'} />
          <Metric label="Execution routing" value={data?.summary?.live_gate ? 'Operator gated' : 'Connecting stream'} />
          <Metric label="Trader mode" value={prettyValue(data?.summary?.trader_state)} />
          <Metric label="Execution guard" value={prettyValue(data?.summary?.live_submit_blocker, 64)} />
          <Metric label="Execution accepted/blocked" value={`${data?.summary?.paper_accepted_count ?? 0}/${data?.summary?.paper_blocked_count ?? 0}`} />
          <Metric label="Execution-eligible predictions" value={data?.summary?.prediction_paper_fill_allowed_count ?? 'Connecting stream'} />
          <Metric label="Routed signal candidates" value={data?.summary?.prediction_routes_to_orchestrator_count ?? 'Connecting stream'} />
        </div>
        <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '1rem' }}>
          {(data?.plain_english_overview ?? []).slice(0, 5).map((text) => (
            <div className="source-health-grid__ok" key={text}>
              <span>Plain English</span>
              <strong>Signal explanation</strong>
              <small>{text}</small>
            </div>
          ))}
        </div>
        <button
          className="lineage-raw-toggle"
          type="button"
          onClick={() => setShowAdvancedIds((value) => !value)}
          style={{ marginTop: '0.8rem' }}
        >
          {showAdvancedIds ? 'Hide technical trace' : 'Show technical trace'}
        </button>
      </Panel>

      {paperReasons.length || predictionGateReasons.length ? (
        <Panel id={`prediction-signal-execution-blockers-${safeId}`} title="Execution Block Reasons In Plain English">
          <div className="source-health-grid prediction-blocker-grid">
            {[
              ...paperReasons.map(([reason, count]) => ({ reason, count, source: 'execution ledger' })),
              ...predictionGateReasons.map(([reason, count]) => ({ reason, count, source: 'prediction gate' })),
            ].map(({ reason, count, source }) => (
              <div className="source-health-grid__warn" key={`${source}-${reason}`}>
                <span>{prettyKey(reason)}</span>
                <strong>{count}</strong>
                <small>
                  {reason.includes('MARKET_STATE')
                    ? 'The execution gate needs market-state integrity evidence before it can treat the candidate as executable.'
                    : `The ${source} is holding or blocking this candidate until the source reason is resolved.`}
                </small>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}

      {issues.length ? (
        <Panel id={`prediction-signal-current-fixes-${safeId}`} title="Current Explanation Gaps To Watch">
          <ul className="landing-info-list">
            {issues.map((issue) => (
              <li key={issue}><span className="landing-info-list__num">!</span><span>{issue}</span></li>
            ))}
          </ul>
        </Panel>
      ) : null}

      <Panel id={`prediction-signal-explanation-cards-${safeId}`} title="Current Prediction Reasoning">
        {rows.length ? (
          <div className="trainer-prediction-scroll-window trainer-prediction-scroll-window--explanations" role="region" aria-label="Scrollable current prediction reasoning">
            <p className="cockpit-evidence-note">
              Showing {rows.length.toLocaleString('en-US')} detailed explanation rows published by the explainer.
              The full signal symbol/timeframe grid is shown in the prediction matrix panels.
            </p>
            <div className="source-health-grid prediction-blocker-grid">
              {rows.map((row) => (
                <ExplanationCard
                  key={`${row.symbol}-${row.timeframe}-${row.prediction_id ?? row.natural_language_summary ?? row.selected_action ?? row.symbol}`}
                  row={row}
                  showAdvancedIds={showAdvancedIds}
                />
              ))}
            </div>
          </div>
        ) : (
          <p className="cockpit-evidence-gap">No current prediction explanation rows are published yet.</p>
        )}
      </Panel>

      {taskDescriptions.length ? (
        <Panel id={`prediction-signal-task-descriptions-${safeId}`} title="Signal explanation guide">
          <div className="cockpit-lineage-grid">
            {taskDescriptions.map(([task, description]) => (
              <div key={task}>
                <span>{prettyKey(task)}</span>
                <strong>{prettyValue(description, 120)}</strong>
              </div>
            ))}
          </div>
        </Panel>
      ) : null}
    </section>
  );
}
