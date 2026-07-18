import { useState } from 'react';
import { Panel, Metric } from '../../pages/cockpitComponents';
import { ageClass, fmtAge, usePayloadFile } from '../../hooks/usePayloadFile';
import {
  PIPELINE_CONTROL_API_ENABLED,
  PIPELINE_RUN_ENDPOINT,
  PIPELINE_STATUS_ENDPOINT,
  PIPELINE_STATUS_STATIC_PATH,
  formatPipelinePercent,
  pipelineTone,
  type PipelineControlStatus,
  type PipelineRunResult,
  type PipelineRunType,
} from '../../data/pipelineControl';
import { StatusPill } from './TradingPrimitives';

const RUN_TYPE_LABELS: Record<PipelineRunType, string> = {
  trainer_cycle: 'Trainer',
  replay: 'Replay',
  backtest: 'Backtest',
  full_pipeline: 'Full pipeline',
};

const RUN_TYPE_DESCRIPTIONS: Record<PipelineRunType, string> = {
  trainer_cycle: 'Refreshes native CUDA PPO/MASA learning and prediction rows from current clean V2 feature snapshots. It publishes model output only; it cannot place exchange orders.',
  replay: 'Reconstructs historical decision states so trainer, risk, orchestrator, and runtime behavior can be debugged against the data available at the decision time.',
  backtest: 'Measures strategy quality on historical/replay rows: expectancy, false positives, false negatives, drawdown, and after-cost behavior before trusting a change.',
  full_pipeline: 'Runs the safe V2 execution/training data path together: data freshness, features, predictions, risk, orchestrator, execution ledger, portfolio equity, and website payloads.',
};
const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface LiveGateRuntimePayload {
  live_gate?: string;
  execution_live_symbols?: string[];
}

function blockerText(blockers: string[]): string {
  if (!blockers.length) return 'ready';
  return blockers.slice(0, 3).map((blocker) => blocker.replace(/_/g, ' ')).join(', ');
}

function statusTone(value: string | undefined): 'ok' | 'warn' | 'block' | 'neutral' {
  if (value === 'CURRENT' || value === 'QUEUED' || value === 'DRY_RUN_NOT_QUEUED') return 'ok';
  if (!value || value.includes('MISSING')) return 'block';
  return 'warn';
}

export function PipelineControlPanel({ surface }: { surface: string }): JSX.Element {
  const { data, error, ageSeconds } = usePayloadFile<PipelineControlStatus>(PIPELINE_STATUS_ENDPOINT, 10_000);
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  const [runType, setRunType] = useState<PipelineRunType>('full_pipeline');
  const [symbolScope, setSymbolScope] = useState<'all' | 'visible'>('all');
  const [result, setResult] = useState<PipelineRunResult | null>(null);
  const [requestState, setRequestState] = useState<string>('idle');

  const visibleSymbols = (data?.rows ?? [])
    .filter((row) => row.chart_visible)
    .map((row) => row.symbol)
    .filter((symbol, index, arr) => arr.indexOf(symbol) === index)
    .slice(0, 60);
  const requestSymbols = symbolScope === 'visible' ? visibleSymbols : undefined;
  const rows = (data?.rows ?? []).slice(0, 24);
  const blockerEntries = Object.entries(data?.compatibility.blocker_counts ?? {})
    .sort((a, b) => b[1] - a[1])
    .slice(0, 8);

  async function sendRun(dryRun: boolean): Promise<void> {
    if (!PIPELINE_CONTROL_API_ENABLED) {
      setRequestState(`api-disabled: static status only from ${PIPELINE_STATUS_STATIC_PATH}`);
      return;
    }
    setRequestState(dryRun ? 'dry-run:pending' : 'queue:pending');
    try {
      const response = await fetch(PIPELINE_RUN_ENDPOINT, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          run_type: runType,
          symbols: requestSymbols,
          timeframes: data?.timeframes ?? ['1m', '5m', '15m', '1h', '4h'],
          dry_run: dryRun,
          requested_by: `website:${surface}`,
          reason: `${dryRun ? 'dry_run' : 'queue'} from ${surface}`,
        }),
      });
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(payload?.detail ?? `HTTP ${response.status}`);
      setResult(payload as PipelineRunResult);
      setRequestState(`${dryRun ? 'dry-run' : 'queue'}:${(payload as PipelineRunResult).queue_state}`);
    } catch (errorValue) {
      setRequestState(errorValue instanceof Error ? errorValue.message : String(errorValue));
    }
  }

  return (
    <Panel
      id={`pipeline-control-${surface}`}
      title="Trainer / Replay / Backtest Control"
      right={<span className={`chip solid-${ageClass(ageSeconds, 60)}`}>{fmtAge(ageSeconds)}</span>}
    >
      {error ? <p className="cockpit-evidence-gap">Pipeline source reconnecting: {error}</p> : null}
      <div className="cockpit-analytics-grid">
        <Metric label="Symbols" value={data?.symbols.length ?? 0} detail={`${data?.timeframes.join(', ') ?? 'no timeframes'}`} />
        <Metric label="Trainer compatible" value={formatPipelinePercent(data?.compatibility.trainer_compatible_percent)} detail={`${data?.compatibility.trainer_compatible_count ?? 0} rows`} />
        <Metric label="Backtest compatible" value={formatPipelinePercent(data?.compatibility.backtest_compatible_percent)} detail={`${data?.compatibility.backtest_compatible_count ?? 0} rows`} />
        <Metric label="Replay compatible" value={formatPipelinePercent(data?.compatibility.replay_compatible_percent)} detail={`${data?.compatibility.replay_compatible_count ?? 0} rows`} />
        <Metric label="Visible charts" value={data?.compatibility.chart_visible_symbol_count ?? 0} detail={data?.website_visualization?.market_chart_manifest_path ?? 'chart manifest missing'} />
        <Metric label="Live gate" value={liveGateRuntime?.live_gate ?? data?.live_gate ?? 'loading'} detail={`${liveGateRuntime?.execution_live_symbols?.length ?? 0} execution symbols; API cannot place orders`} />
      </div>

      <div className="cockpit-lineage-grid" style={{ marginTop: '1rem' }}>
        <div>
          <span>Run type</span>
          <select value={runType} onChange={(event) => setRunType(event.target.value as PipelineRunType)}>
            {((data?.allowed_run_types ?? ['full_pipeline', 'trainer_cycle', 'replay', 'backtest']) as PipelineRunType[]).map((type) => (
              <option key={type} value={type}>{RUN_TYPE_LABELS[type] ?? type}</option>
            ))}
          </select>
        </div>
        <div>
          <span>Symbol scope</span>
          <select value={symbolScope} onChange={(event) => setSymbolScope(event.target.value as 'all' | 'visible')}>
            <option value="all">All resolved symbols</option>
            <option value="visible">Visible chart symbols</option>
          </select>
        </div>
        <div>
          <span>Dry run</span>
          <button
            type="button"
            className="ingestor-action-button"
            disabled={!PIPELINE_CONTROL_API_ENABLED}
            title={PIPELINE_CONTROL_API_ENABLED ? 'Validate through the typed V2 backend API' : 'Disabled: /api/v2/pipeline/run is not enabled for this static website build'}
            onClick={() => void sendRun(true)}
          >
            Validate
          </button>
        </div>
        <div>
          <span>Queue worker run</span>
          <button
            type="button"
            className="ingestor-action-button"
            disabled={!PIPELINE_CONTROL_API_ENABLED}
            title={PIPELINE_CONTROL_API_ENABLED ? 'Queue through the typed V2 backend API' : 'Disabled: /api/v2/pipeline/run is not enabled for this static website build'}
            onClick={() => void sendRun(false)}
          >
            Queue
          </button>
        </div>
      </div>
      <p className="cockpit-evidence-note">
        State: {requestState}. Status source: {PIPELINE_STATUS_ENDPOINT}. Requests require the typed backend API and are recorded to {data?.control_stream_key ?? 'v2:pipeline:control:requests'} for workers; FastAPI does not run trainer jobs inline.
      </p>
      <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '1rem' }}>
        {((data?.allowed_run_types ?? ['full_pipeline', 'trainer_cycle', 'replay', 'backtest']) as PipelineRunType[]).map((type) => (
          <div className="source-health-grid__ok" key={type}>
            <span>{RUN_TYPE_LABELS[type] ?? type}</span>
            <strong>{type === runType ? 'selected' : 'available'}</strong>
            <small>{RUN_TYPE_DESCRIPTIONS[type]}</small>
          </div>
        ))}
      </div>
      {result ? (
        <div className="cockpit-lineage-grid" style={{ marginTop: '0.75rem' }}>
          <div><span>Control request</span><strong><code>{result.control_request_id}</code></strong></div>
          <div><span>Queue state</span><strong>{result.queue_state}</strong></div>
          <div><span>Stream id</span><strong><code>{result.stream_id ?? 'not queued'}</code></strong></div>
          <div><span>Exchange action</span><strong>{String(result.exchange_action_taken)}</strong></div>
        </div>
      ) : null}

      {blockerEntries.length ? (
        <div className="source-health-grid prediction-blocker-grid" style={{ marginTop: '1rem' }}>
          {blockerEntries.map(([blocker, count]) => (
            <div className="source-health-grid__warn" key={blocker}>
              <span>{blocker.replace(/_/g, ' ')}</span>
              <strong>{count}</strong>
              <small>compatibility blocker rows</small>
            </div>
          ))}
        </div>
      ) : null}

      <div className="market-table prediction-table" role="table" aria-label="Pipeline compatibility by symbol" style={{ marginTop: '1rem' }}>
        <div className="market-table__row market-table__row--head" role="row">
          <span>Symbol</span>
          <span>TF</span>
          <span>Trainer</span>
          <span>Backtest</span>
          <span>Replay</span>
          <span>Chart</span>
          <span>Sources</span>
          <span>Blockers</span>
        </div>
        {rows.map((row) => (
          <div className="market-table__row" role="row" key={`${row.symbol}-${row.timeframe}`}>
            <span className="market-symbol">{row.symbol}</span>
            <span>{row.timeframe}</span>
            <span><StatusPill tone={pipelineTone(row.trainer_compatible)}>{row.trainer_compatible ? 'ready' : 'blocked'}</StatusPill></span>
            <span><StatusPill tone={pipelineTone(row.backtest_compatible)}>{row.backtest_compatible ? 'ready' : 'blocked'}</StatusPill></span>
            <span><StatusPill tone={pipelineTone(row.replay_compatible)}>{row.replay_compatible ? 'ready' : 'blocked'}</StatusPill></span>
            <span><StatusPill tone={statusTone(row.chart_status)}>{row.chart_status}</StatusPill></span>
            <span className="num">{row.required_sources_present}/{row.required_sources_total} req</span>
            <span>{blockerText(row.blockers)}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}
