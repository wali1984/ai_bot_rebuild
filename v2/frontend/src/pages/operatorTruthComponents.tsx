import { Panel, Metric } from './cockpitComponents';
import type { CoinankMarketIntelligencePayload, OperatorTruthPayload, OperatorTruthStatusRow, PaperOnlineRuntimePayload } from './operatorTruthData';
import { statusClass, valueText } from './cockpitData';

const MISSING = 'Evidence missing — cannot explain without guessing.';

function boolStatus(value: boolean): string {
  return value ? 'yes' : 'no';
}

function sourceChip(classification: string): JSX.Element {
  const tone = classification.includes('MISSING') || classification.includes('STALE')
    ? 'solid-warn'
    : classification.includes('STATIC')
      ? 'solid-paper'
      : 'solid-ok';
  return <span className={`chip ${tone}`}>{classification}</span>;
}

function truthTone(value: unknown): 'good' | 'warn' | 'bad' | 'paper' {
  const text = valueText(value).toUpperCase();
  if (text.includes('BLOCKED_HUMAN_ONLY') || text.includes('DEFERRED_NON_BLOCKING') || text.includes('STATIC_PROOF_FIXTURE') || text.includes('V2_PROOF_ARTIFACT')) return 'paper';
  if (text.includes('MISSING') || text.includes('STALE') || text.includes('CONFLICT') || text.includes('FAIL') || text.includes('DEGRADED') || text.includes('NOT_OBSERVED')) return 'bad';
  if (text.includes('WARN') || text.includes('PENDING') || text.includes('FIXTURE') || text === 'NO' || text === 'FALSE') return 'warn';
  return 'good';
}

function evidenceClassLabel(row?: OperatorTruthStatusRow): string {
  if (!row) return 'MISSING_EVIDENCE';
  if (row.missing) return 'MISSING_EVIDENCE';
  if (row.stale) return 'STALE_PAYLOAD';
  return row.classification;
}

function nestedText(source: Record<string, unknown> | null | undefined, path: string[], fallback = 'MISSING_EVIDENCE'): string {
  let cursor: unknown = source;
  for (const key of path) {
    if (!cursor || typeof cursor !== 'object' || !(key in cursor)) return fallback;
    cursor = (cursor as Record<string, unknown>)[key];
  }
  return valueText(cursor ?? fallback);
}

function controlPlaneValue(payload: OperatorTruthPayload): string {
  return payload.supervisor_status.control_plane_status
    ?? (payload.supervisor_status.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_RUNTIME_SNAPSHOT');
}

function formatAge(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined) return 'unknown age';
  if (seconds < 60) return `${seconds}s`;
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h`;
  return `${Math.floor(seconds / 86400)}d`;
}

function TruthStateCard({ label, value, detail, source }: { label: string; value: unknown; detail: string; source: string }): JSX.Element {
  const tone = truthTone(value);
  return (
    <div className={`truth-state-card truth-state-card--${tone}`}>
      <span className="truth-state-card__label">{label}</span>
      <strong className={statusClass(value)}>{valueText(value)}</strong>
      <small>{detail}</small>
      <span className="truth-source-chip">{source}</span>
    </div>
  );
}

export function OperatorTruthLoading({ error }: { error: string | null }): JSX.Element {
  return (
    <Panel id="operator-truth-loading" title="Operator Truth Payload">
      <p className="cockpit-evidence-gap">
        {error ? `Evidence missing - operator truth payload unavailable: ${error}` : 'Loading operator truth payload...'}
      </p>
    </Panel>
  );
}

export function OperatorTruthCommandDeck({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const supervisor = payload.supervisor_status;
  const runtime = payload.runtime_monitor_status;
  const trainer = payload.trainer_monitor_status;
  const signal = payload.signal_lineage_status;
  const freshness = payload.dashboard_freshness_status;
  const supervisorState = controlPlaneValue(payload);
  const restartRuntime = payload.legacy_trainer_restart_runtime;
  const liveObserver = payload.live_observer_shadow_twin;
  const legacyRestartStatus = nestedText(restartRuntime, ['legacy_trainer', 'status'], '');
  const liveObserverStatus = nestedText(liveObserver, ['status'], '');
  const plannerState = supervisor.master_planner_running ? 'MASTER_PLANNER_RUNNING' : 'MASTER_PLANNER_NOT_RUNNING';
  const governorState = supervisor.autonomous_governor_active ? 'AUTONOMOUS_GOVERNOR_ACTIVE' : 'AUTONOMOUS_GOVERNOR_NOT_OBSERVED';
  const runningTask = supervisor.current_running_task ?? 'NO_ACTIVE_SUPERVISOR_TASK';
  const nextTask = payload.current_next_task ?? supervisor.true_next_task ?? supervisor.next_pending_task ?? 'MISSING_NEXT_TASK';
  const hasCurrentTrainer = trainer.status === 'REALTIME_RUNTIME_EVIDENCE' || trainer.status === 'V2_PAPER_TRAINER_WRAPPER_CURRENT';
  const trainerPredictionDetail = hasCurrentTrainer
    ? `latest prediction ${valueText(trainer.latest_prediction?.prediction_id)}`
    : 'current prediction unavailable; fixture examples are separated';
  const signalLineageDetail = signal.status === 'REALTIME_RUNTIME_EVIDENCE'
    ? `latest signal ${valueText(signal.latest_signal?.signal_id)}; risk ${valueText(signal.latest_signal?.risk_decision_id)}`
    : 'current signal lineage missing; static proof is not current';

  return (
    <section className="operator-command-deck panel bracketed hatch-strong" data-testid="operator-command-deck" aria-label="Operator runtime truth command deck">
      <span className="br-bl" aria-hidden="true" />
      <span className="br-br" aria-hidden="true" />
      <div className="operator-command-deck__header">
        <div>
          <p className="eyebrow">Realtime operator truth / no guessing</p>
          <h1>NERVYX OBSERVE Truth Deck</h1>
          <p>
            This surface separates runtime evidence, static proof fixtures, stale payloads, and missing evidence. It does not promote any proof marker to live truth.
          </p>
        </div>
        <div className="operator-command-deck__status">
          <span className="chip solid-block">LIVE TRADING: {payload.live_gate_status}</span>
          <span className={`chip ${truthTone(supervisorState) === 'good' ? 'solid-ok' : 'solid-warn'}`}>{supervisorState}</span>
          <span className={`chip ${hasCurrentTrainer ? 'solid-ok' : 'solid-warn'}`}>{trainer.status}</span>
          {legacyRestartStatus ? <span className={`chip ${truthTone(legacyRestartStatus) === 'good' ? 'solid-ok' : 'solid-warn'}`}>Legacy trainer: {legacyRestartStatus}</span> : null}
          {liveObserverStatus ? <span className={`chip ${truthTone(liveObserverStatus) === 'good' ? 'solid-ok' : 'solid-warn'}`}>Observer: {liveObserverStatus}</span> : null}
          {payload.canonical_truth_bridge ? <span className="chip solid-ok">{payload.canonical_truth_bridge.status}</span> : null}
          <span className="chip solid-paper">Redis trim: {payload.redis_trim_status}</span>
        </div>
      </div>
      <div className="truth-command-grid">
        <TruthStateCard
          label="Supervisor heartbeat"
          value={supervisorState}
          detail={`${plannerState}; ${governorState}; active workers ${supervisor.supervisor_processes.length}; snapshot ${supervisor.canonical_snapshot_fresh ? 'fresh' : 'status-file based'}`}
          source={payload.canonical_truth_bridge ? 'PAPER_ONLINE_CANONICAL_TRUTH_BRIDGE' : 'RUNTIME_MONITOR_PAYLOAD'}
        />
        <TruthStateCard
          label="Current task"
          value={runningTask}
          detail={`Last completed: ${supervisor.last_completed_task ?? 'none'}; next: ${nextTask}`}
          source="agent_supervisor/status"
        />
        <TruthStateCard
          label="Trainer runtime"
          value={trainer.status}
          detail={`process rows ${trainer.trainer_processes.length}; ${trainerPredictionDetail}`}
          source="REALTIME_RUNTIME_EVIDENCE"
        />
        <TruthStateCard
          label="Legacy orchestrator"
          value={runtime.orchestrator_status}
          detail={`observed rows ${runtime.orchestrator_processes.length}; trader ${runtime.trader_status}`}
          source="RUNTIME_PROCESS_LIST"
        />
        <TruthStateCard
          label="Market ingest"
          value={runtime.market_ingestor_status ?? 'MISSING_EVIDENCE'}
          detail={`observed rows ${runtime.market_ingestor_processes?.length ?? 0}; runtime process observation`}
          source="RUNTIME_PROCESS_LIST"
        />
        <TruthStateCard
          label="Feature pipeline"
          value={runtime.feature_pipeline_status ?? 'MISSING_EVIDENCE'}
          detail={`observed rows ${runtime.feature_pipeline_processes?.length ?? 0}; no service mutation`}
          source="RUNTIME_PROCESS_LIST"
        />
        <TruthStateCard
          label="Signal lineage"
          value={signal.status}
          detail={signalLineageDetail}
          source={signal.status === 'REALTIME_RUNTIME_EVIDENCE' ? 'RUNTIME_MONITOR_PAYLOAD' : 'ARCHIVE_ONLY_FIXTURE'}
        />
        <TruthStateCard
          label="Legacy observer twin"
          value={nestedText(liveObserver, ['legacy_shadow_twin', 'risk_decision', 'risk_result'], liveObserverStatus || 'MISSING_EVIDENCE')}
          detail={`source ${nestedText(liveObserver, ['legacy_shadow_twin', 'legacy_source', 'stream'], 'missing')}; paper ${nestedText(liveObserver, ['legacy_shadow_twin', 'paper_ledger_entry', 'paper_result'], 'missing')}`}
          source="LEGACY_RUNTIME_BRIDGE / V2_SHADOW_TWIN"
        />
        <TruthStateCard
          label="Payload freshness"
          value={`${freshness.stale_payload_count} STALE / ${freshness.static_fixture_count} STATIC`}
          detail={`${freshness.payloads_checked} payloads checked; ${freshness.missing_evidence_count} missing evidence items`}
          source="PUBLIC_PAYLOAD_AUDIT"
        />
        <TruthStateCard
          label="Missing evidence"
          value={`${payload.current_blockers.length} blockers`}
          detail={payload.current_blockers[0]?.detail ?? MISSING}
          source="MISSING_EVIDENCE_REGISTER"
        />
        <TruthStateCard
          label="Operator action"
          value="NO LIVE ACTION"
          detail="Human input is required only at FINAL_LIVE_CAPITAL_APPROVAL_REQUIRED."
          source="LIVE_GATE_POLICY"
        />
      </div>
      <div className="truth-classification-rail" aria-label="Data truth classification legend">
        {['REALTIME_RUNTIME_EVIDENCE', 'LIVE_MARKET_FEED', 'ACCOUNT_FEED', 'RUNTIME_MONITOR_PAYLOAD', 'V2_PROOF_ARTIFACT', 'ARCHIVE_ONLY_FIXTURE', 'STALE_PAYLOAD', 'MISSING_EVIDENCE'].map((label) => (
          <span key={label} className={`truth-source-chip truth-source-chip--${truthTone(label)}`}>{label}</span>
        ))}
      </div>
    </section>
  );
}

export function RuntimeTruthMatrix({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const redis = payload.runtime_monitor_status.redis_memory_pressure_status;
  const paperOnline = payload.runtime_monitor_status.paper_online_runtime_status;
  const rows = [
    ['Canonical truth source', payload.canonical_truth_bridge?.status ?? 'OPERATOR_TRUTH_PAYLOAD', payload.canonical_truth_bridge?.source ?? 'operator_truth/latest/operator_truth_payload.json'],
    ['Control plane', controlPlaneValue(payload), payload.supervisor_status.canonical_snapshot_fresh ? 'fresh process/runtime bridge snapshot' : 'agent_supervisor/status/current_status.json'],
    ['Current task', payload.supervisor_status.current_running_task ?? 'NO_ACTIVE_SUPERVISOR_TASK', `last completed: ${payload.supervisor_status.last_completed_task ?? 'none'}`],
    ['Master planner', payload.supervisor_status.master_planner_running ? 'RUNNING' : 'NOT_RUNNING', 'process list + status payload'],
    ['Autonomous governor', payload.supervisor_status.autonomous_governor_active ? 'ACTIVE' : 'NOT_OBSERVED', 'process list + status payload'],
    ['Market ingestors', payload.runtime_monitor_status.market_ingestor_status ?? 'MISSING_EVIDENCE', `${payload.runtime_monitor_status.market_ingestor_processes?.length ?? 0} process rows`],
    ['Feature pipeline', payload.runtime_monitor_status.feature_pipeline_status ?? 'MISSING_EVIDENCE', `${payload.runtime_monitor_status.feature_pipeline_processes?.length ?? 0} process rows`],
    ['Trainer process', payload.runtime_monitor_status.trainer_status, 'runtime process scan / V2 execution wrapper'],
    ['Trainer prediction stream', payload.trainer_monitor_status.status, 'trainer monitor payload'],
    ['Signal explainability', payload.signal_lineage_status.status, 'signal lineage payload'],
    ['V2 execution runtime', paperOnline?.status ?? 'MISSING_EVIDENCE', paperOnline?.path ?? 'operator_runtime/execution/latest'],
    ['Legacy observer twin', payload.runtime_monitor_status.live_observer_runtime_status?.status ?? nestedText(payload.live_observer_shadow_twin, ['status'], 'MISSING_EVIDENCE'), 'operator_runtime/live_observer/latest'],
    ['Redis memory pressure', redis?.status ?? 'MISSING_EVIDENCE', redis?.path ?? 'Redis runtime state / payload audit'],
    ['Static fixture count', String(payload.dashboard_freshness_status.static_fixture_count), 'public payload audit'],
    ['Stale payload count', String(payload.dashboard_freshness_status.stale_payload_count), 'public payload audit'],
    ['Live gate', payload.live_gate_status, 'safety policy'],
  ] satisfies Array<[string, unknown, string]>;
  return (
    <section className="runtime-truth-matrix" data-testid="runtime-truth-matrix" aria-label="Runtime truth matrix">
      {rows.map(([label, value, source]) => (
        <div className={`runtime-truth-cell runtime-truth-cell--${truthTone(value)}`} key={label}>
          <span>{label}</span>
          <strong className={statusClass(value)}>{valueText(value)}</strong>
          <small>{source}</small>
        </div>
      ))}
    </section>
  );
}

export function LiveObserverShadowTwinPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const observer = payload.live_observer_shadow_twin;
  const riskResult = nestedText(observer, ['legacy_shadow_twin', 'risk_decision', 'risk_result']);
  const riskReason = nestedText(observer, ['legacy_shadow_twin', 'risk_decision', 'risk_reason_code']);
  const paperResult = nestedText(observer, ['legacy_shadow_twin', 'paper_ledger_entry', 'paper_result']);
  const sourceStream = nestedText(observer, ['legacy_shadow_twin', 'legacy_source', 'stream']);
  const visibleRecords = observer && typeof observer.gui_runtime_truth === 'object'
    ? (observer.gui_runtime_truth as Record<string, unknown>).current_records_visible as Record<string, unknown> | undefined
    : undefined;
  return (
    <Panel
      id="live-observer-shadow-twin"
      title="Legacy Live Observer / V2 Shadow Twin"
      right={<span className={observer ? 'chip solid-ok' : 'chip solid-warn'}>{observer ? 'REALTIME_RUNTIME_EVIDENCE' : 'MISSING_EVIDENCE'}</span>}
    >
      <div className="cockpit-lineage-grid">
        <div><span>bridge status</span><strong>{nestedText(observer, ['legacy_read_only_bridge', 'status'])}</strong></div>
        <div><span>source stream</span><strong>{sourceStream}</strong></div>
        <div><span>legacy signal_id</span><strong>{nestedText(observer, ['legacy_shadow_twin', 'normalized_signal', 'signal_id'])}</strong></div>
        <div><span>legacy symbol/action</span><strong>{nestedText(observer, ['legacy_shadow_twin', 'normalized_signal', 'symbol'])} / {nestedText(observer, ['legacy_shadow_twin', 'normalized_signal', 'action'])}</strong></div>
        <div><span>Risk Gateway result</span><strong className={statusClass(riskResult)}>{riskResult}</strong></div>
        <div><span>risk reason</span><strong>{riskReason}</strong></div>
        <div><span>execution result</span><strong>{paperResult}</strong></div>
        <div><span>audit ledger</span><strong>{nestedText(observer, ['audit_ledger', 'status'])}</strong></div>
        <div><span>V2 Redis namespace</span><strong>{nestedText(observer, ['v2_bounded_redis_namespace', 'status'])}</strong></div>
        <div><span>trainer parity</span><strong>{nestedText(observer, ['trainer_bridge_parity', 'parity_status'])}</strong></div>
      </div>
      <p className="cockpit-evidence-note">
        This bridge observes legacy account-access evidence and mirrors it into V2 execution/shadow records. It does not write old Redis, does not command the legacy trader, and Risk Gateway remains final authority.
      </p>
      {visibleRecords ? (
        <div className="truth-working-grid">
          {Object.entries(visibleRecords).map(([label, value]) => (
            <div className={`truth-working-card truth-working-card--${truthTone(value)}`} key={label}>
              <span>{label}</span>
              <strong>{valueText(value)}</strong>
            </div>
          ))}
        </div>
      ) : null}
      {Array.isArray(observer?.blockers) && observer.blockers.length ? (
        <div className="missing-evidence-board">
          {observer.blockers.map((row: Record<string, unknown>) => (
            <div className="missing-evidence-card" key={valueText(row.id)}>
              <strong>{valueText(row.id)}</strong>
              <p>{valueText(row.severity)}: {valueText(row.detail)}</p>
            </div>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

export function PaperOnlineRuntimeStatusPanel({ payload }: { payload: PaperOnlineRuntimePayload | null }): JSX.Element {
  const state = payload?.runtime_state ?? 'PAPER_ONLINE_RUNTIME_MISSING';
  const market = payload?.market_feed;
  const lineage = payload?.current_signal_lineage as Record<string, unknown> | undefined;
  const lineageIds = lineage?.lineage_ids as Record<string, unknown> | undefined;
  const signal = lineage?.signal as Record<string, unknown> | undefined;
  const trainerPrediction = payload?.trainer_prediction as Record<string, unknown> | undefined;
  const riskDecision = payload?.current_risk_decision as Record<string, unknown> | undefined;
  const executionIntent = lineage?.execution_intent as Record<string, unknown> | undefined;
  const latestPaperEvent = payload?.last_paper_event as Record<string, unknown> | undefined;
  return (
    <Panel
      id="v2-execution-runtime"
      title="V2 Execution Runtime"
      right={<span className={payload ? 'chip solid-ok' : 'chip solid-warn'}>{payload ? 'REALTIME_RUNTIME_EVIDENCE' : 'MISSING_EVIDENCE'}</span>}
    >
      <div className="cockpit-analytics-grid">
        <Metric label="Runtime state" value={state} />
        <Metric label="Loop available" value={String(payload?.continuous_loop_available ?? false)} />
        <Metric label="Last tick" value={payload?.paper_loop?.last_tick_at ?? 'MISSING_EVIDENCE'} />
        <Metric label="Execution events" value={payload?.paper_loop?.paper_event_count ?? 'MISSING_EVIDENCE'} />
        <Metric label="Execution action" value={payload?.last_paper_event?.paper_action ?? 'MISSING_EVIDENCE'} />
        <Metric label="Risk result" value={payload?.last_paper_event?.risk_gateway_result ?? 'MISSING_EVIDENCE'} />
        <Metric label="Observed price" value={market?.price ?? 'MISSING_EVIDENCE'} />
        <Metric label="Market source" value={market?.source_type ?? 'MISSING_EVIDENCE'} />
      </div>
      <div className="cockpit-lineage-grid">
        <div><span>exchange orders</span><strong>{String(payload?.exchange_orders ?? false)}</strong></div>
        <div><span>legacy Redis writes</span><strong>{String(payload?.legacy_redis_writes ?? false)}</strong></div>
        <div><span>leverage changes</span><strong>{String(payload?.leverage_changes ?? false)}</strong></div>
        <div><span>margin mode changes</span><strong>{String(payload?.margin_mode_changes ?? false)}</strong></div>
        <div><span>live gate</span><strong>{payload?.live_gate_status ?? 'blocked_human_only'}</strong></div>
        <div><span>market age</span><strong>{formatAge(market?.age_seconds)}</strong></div>
        <div><span>prediction_id</span><strong>{valueText(lineageIds?.prediction_id ?? trainerPrediction?.prediction_id ?? 'MISSING_EVIDENCE')}</strong></div>
        <div><span>feature_snapshot_id</span><strong>{valueText(lineageIds?.feature_snapshot_id ?? trainerPrediction?.feature_snapshot_id ?? 'MISSING_EVIDENCE')}</strong></div>
        <div><span>signal_id</span><strong>{valueText(lineageIds?.signal_id ?? signal?.signal_id ?? 'MISSING_EVIDENCE')}</strong></div>
        <div><span>risk_decision_id</span><strong>{valueText(lineageIds?.risk_decision_id ?? riskDecision?.risk_decision_id ?? 'MISSING_EVIDENCE')}</strong></div>
        <div><span>execution_intent_id</span><strong>{valueText(lineageIds?.execution_intent_id ?? executionIntent?.execution_intent_id ?? 'MISSING_EVIDENCE')}</strong></div>
        <div><span>execution ledger event</span><strong>{valueText(latestPaperEvent?.paper_ledger_entry_id ?? latestPaperEvent?.paper_event_id ?? 'MISSING_EVIDENCE')}</strong></div>
      </div>
      <p className="cockpit-evidence-note">
        {payload
          ? 'Continuous V2 execution runtime is online and operator-gated. It writes local V2 runtime payloads only; exchange orders stay gated.'
          : 'Evidence missing - cannot explain without guessing. Start the operator-gated execution runtime service.'}
      </p>
      {payload?.blockers?.length ? (
        <div className="missing-evidence-board">
          {payload.blockers.map((row) => (
            <div className="missing-evidence-card" key={row.id}>
              <strong>{row.id}</strong>
              <p>{row.severity}: {row.detail}</p>
            </div>
          ))}
        </div>
      ) : null}
    </Panel>
  );
}

export function CoinankMarketIntelligencePanel({ payload, error, context = 'Market Intelligence' }: { payload: CoinankMarketIntelligencePayload | null; error?: string | null; context?: string }): JSX.Element {
  const source = payload?.source ?? 'MISSING_EVIDENCE';
  const availability = payload?.availability ?? {};
  const endpointCounts = payload?.endpoint_key_counts ?? {};
  const missing = payload?.missing_evidence ?? [];
  const activeSymbols = Array.isArray(payload?.active_symbols) ? payload.active_symbols : [];
  const hotSymbols = Array.isArray(payload?.hot_symbols) ? payload.hot_symbols : [];
  const requiredTfs = Array.isArray(payload?.required_tfs) ? payload.required_tfs : [];
  const requiredTfStatus = payload?.required_tfs_status ?? {};
  const forbiddenSourceChecks = payload?.forbidden_source_checks ?? {};
  return (
    <Panel
      id={`coinank-market-intelligence-${context.toLowerCase().replace(/[^a-z0-9]+/g, '-')}`}
      title={`${context} - CoinAnk Plan-3 Read-Only Bridge`}
      right={<span className={payload ? 'chip solid-ok' : 'chip solid-warn'}>{source}</span>}
    >
      {payload ? (
        <>
          <div className="cockpit-analytics-grid">
            <Metric label="Payload generated" value={payload.generated_at} />
            <Metric label="Live gate" value={payload.live_gate_status} />
            <Metric label="Endpoint manifest" value={payload.endpoint_manifest_version} />
            <Metric label="Active symbols" value={activeSymbols.length} />
            <Metric label="Global 11 contract" value={payload.global_11_key_contract_status} />
            <Metric label="CVD keys" value={endpointCounts.agg_cvd ?? 0} />
            <Metric label="SMC keys" value={endpointCounts.indicator_smc ?? 0} />
            <Metric label="Weighted funding keys" value={endpointCounts.weighted_funding ?? 0} />
          </div>
          <div className="cockpit-lineage-grid">
            <div><span>Required TFs</span><strong>{requiredTfs.length ? requiredTfs.map((tf) => `${tf}:${requiredTfStatus[tf] ? 'yes' : 'missing'}`).join(' / ') : 'MISSING_EVIDENCE'}</strong></div>
            <div><span>Hot symbols</span><strong>{hotSymbols.length ? hotSymbols.slice(0, 8).join(', ') : 'MISSING_EVIDENCE'}</strong></div>
            <div><span>Liquidation orders</span><strong>{String(availability.liquidation_orders ?? false)}</strong></div>
            <div><span>Long/short</span><strong>{String(availability.long_short ?? false)}</strong></div>
            <div><span>Forbidden last-price/KLine source</span><strong>{String(forbiddenSourceChecks.kline_endpoint_keys_observed ?? false)}</strong></div>
            <div><span>Forbidden orderbook source</span><strong>{String(forbiddenSourceChecks.orderbook_endpoint_keys_observed ?? false)}</strong></div>
          </div>
          <p className="cockpit-evidence-note">{payload.data_truth_rule}</p>
          {missing.length ? (
            <details className="mission-evidence-details">
              <summary>
                <span>Missing CoinAnk evidence</span>
                <small>{missing.length} item{missing.length === 1 ? '' : 's'} remain explicit, not mocked.</small>
              </summary>
              <div className="mission-evidence-details__body">
                <div className="missing-evidence-board">
                  {missing.slice(0, 12).map((item) => (
                    <div className="missing-evidence-card" key={item}>
                      <strong>MISSING_EVIDENCE</strong>
                      <p>{item}</p>
                    </div>
                  ))}
                </div>
              </div>
            </details>
          ) : null}
        </>
      ) : (
        <p className="cockpit-evidence-gap">
          Evidence missing — cannot explain CoinAnk market intelligence without guessing. Missing source: `/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json`. {error ?? ''}
        </p>
      )}
    </Panel>
  );
}

function RuntimeProcessGroup({ label, status, rows, note }: { label: string; status: string; rows: string[]; note: string }): JSX.Element {
  return (
    <div className={`runtime-process-group runtime-process-group--${truthTone(status)}`}>
      <div className="runtime-process-group__head">
        <span>{label}</span>
        <strong className={statusClass(status)}>{status}</strong>
      </div>
      <p>{note}</p>
      <details className="truth-details">
        <summary>{rows.length} runtime observed process row{rows.length === 1 ? '' : 's'}</summary>
        <div className="truth-raw-list">
          {rows.length ? rows.map((line) => (
            <code key={`${label}-${line}`}>{line}</code>
          )) : <p className="cockpit-evidence-gap">No process rows observed for this group.</p>}
        </div>
      </details>
    </div>
  );
}

export function ActualRuntimeNowPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const runtime = payload.runtime_monitor_status;
  const supervisor = payload.supervisor_status;
  const groups = [
    {
      label: 'Control plane',
      status: controlPlaneValue(payload),
      rows: supervisor.supervisor_processes,
      note: `Current task: ${supervisor.current_running_task ?? 'none'}; last completed: ${supervisor.last_completed_task ?? 'none'}; next: ${payload.current_next_task ?? 'missing'}.`,
    },
    {
      label: 'Market ingestors',
      status: runtime.market_ingestor_status ?? 'MISSING_EVIDENCE',
      rows: runtime.market_ingestor_processes ?? [],
      note: 'Observed from process list only. This dashboard did not start, stop, or mutate market ingest services.',
    },
    {
      label: 'Feature pipeline',
      status: runtime.feature_pipeline_status ?? 'MISSING_EVIDENCE',
      rows: runtime.feature_pipeline_processes ?? [],
      note: 'Feature pipeline process evidence is runtime observation; feature freshness still requires payload evidence.',
    },
    {
      label: 'Orchestrator',
      status: runtime.orchestrator_status,
      rows: runtime.orchestrator_processes,
      note: 'Orchestrator can propose/enrich/deconflict only. Risk Gateway remains final authority.',
    },
    {
      label: 'Trader',
      status: runtime.trader_status,
      rows: runtime.trader_processes,
      note: 'Process observation only. No order, cancel, leverage, margin, or live action was performed by this dashboard.',
    },
    {
      label: 'Trainer runtime',
      status: payload.trainer_monitor_status.status,
      rows: payload.trainer_monitor_status.trainer_processes,
      note: payload.trainer_monitor_status.status === 'TRAINER_RUNTIME_EVIDENCE_MISSING'
        ? 'Trainer runtime evidence is missing. Fixture predictions are separated from current trainer state.'
        : payload.trainer_monitor_status.status === 'V2_PAPER_TRAINER_WRAPPER_CURRENT'
        ? 'Current V2 runtime trainer wrapper evidence is present; legacy trainer process parity is still a separate readiness blocker.'
          : 'Trainer process evidence is present in the runtime process snapshot.',
    },
  ];
  return (
    <Panel id="actual-runtime-now" title="Actual Runtime Now" right={<span className="chip solid-warn">Read-only observation</span>}>
      <div className="actual-runtime-grid">
        {groups.map((group) => (
          <RuntimeProcessGroup key={group.label} {...group} />
        ))}
      </div>
    </Panel>
  );
}

export function RouteTruthSummary({ payload, title }: { payload: OperatorTruthPayload; title: string }): JSX.Element {
  return (
    <section className="route-truth-summary panel bracketed" data-testid="route-truth-summary">
      <span className="br-bl" aria-hidden="true" />
      <span className="br-br" aria-hidden="true" />
      <div>
        <p className="eyebrow">{title} truth summary</p>
        <h2>Current evidence state</h2>
      </div>
      <div className="route-truth-summary__grid">
        <TruthStateCard label="Control plane" value={controlPlaneValue(payload)} detail="Dashboard must disclose missing control-plane daemons and stale historical status files separately." source={payload.canonical_truth_bridge ? 'PAPER_ONLINE_CANONICAL_TRUTH_BRIDGE' : 'RUNTIME_MONITOR_PAYLOAD'} />
        <TruthStateCard label="Trainer" value={payload.trainer_monitor_status.status} detail="No prediction can be explained unless runtime evidence exists." source="REALTIME_RUNTIME_EVIDENCE" />
        <TruthStateCard label="Signal lineage" value={payload.signal_lineage_status.status} detail="Static proof lineage is not current runtime truth." source={payload.signal_lineage_status.status} />
        <TruthStateCard label="Payloads" value={`${payload.dashboard_freshness_status.stale_payload_count} stale`} detail={`${payload.dashboard_freshness_status.static_fixture_count} static fixtures; ${payload.dashboard_freshness_status.missing_evidence_count} missing.`} source="PUBLIC_PAYLOAD_AUDIT" />
      </div>
    </section>
  );
}

export function TruthStatusStrip({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const supervisor = payload.supervisor_status;
  const freshness = payload.dashboard_freshness_status;
  return (
    <section className="truth-status-strip" data-testid="operator-truth-status-strip" aria-label="Current operator truth status">
      <Metric label="Live gate" value={payload.live_gate_status} />
      <Metric label="Control plane" value={controlPlaneValue(payload)} />
      <Metric label="Master planner running" value={boolStatus(supervisor.master_planner_running)} />
      <Metric label="Autonomous governor" value={boolStatus(supervisor.autonomous_governor_active)} />
      <Metric label="Active workers" value={String(supervisor.supervisor_processes.length)} />
      <Metric label="Running task" value={supervisor.current_running_task ?? 'none'} />
      <Metric label="Next task" value={payload.current_next_task ?? 'MISSING'} />
      <Metric label="Redis trim" value={payload.redis_trim_status} />
      <Metric label="Stale payloads" value={String(freshness.stale_payload_count)} />
      <Metric label="Missing evidence" value={String(freshness.missing_evidence_count)} />
    </section>
  );
}

export function LegacyRuntimeMonitorPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const runtime = payload.runtime_monitor_status;
  const restartRuntime = payload.legacy_trainer_restart_runtime;
  return (
    <Panel id="operator-truth-legacy-runtime" title="Old System / Legacy Runtime Monitor" right={sourceChip('REALTIME_RUNTIME_EVIDENCE')}>
      <div className="cockpit-lineage-grid">
        <div><span>orchestrator</span><strong>{runtime.orchestrator_status}</strong></div>
        <div><span>trainer</span><strong>{runtime.trainer_status}</strong></div>
        <div><span>trader</span><strong>{runtime.trader_status}</strong></div>
        <div><span>market ingestors</span><strong>{runtime.market_ingestor_status ?? 'MISSING_EVIDENCE'}</strong></div>
        <div><span>feature pipeline</span><strong>{runtime.feature_pipeline_status ?? 'MISSING_EVIDENCE'}</strong></div>
        <div><span>active process rows</span><strong>{runtime.active_processes.length}</strong></div>
        <div><span>redis memory pressure</span><strong>{runtime.redis_memory_pressure_status?.status ?? 'MISSING_EVIDENCE'}</strong></div>
        <div><span>evidence source</span><strong>operator_truth_payload.json</strong></div>
      </div>
      {runtime.legacy_trader_containment ? (
        <p className="cockpit-evidence-gap">
          {runtime.legacy_trader_containment.status}: {runtime.legacy_trader_containment.action}. The dashboard did not restart, kill, or command legacy trader state.
        </p>
      ) : null}
      {restartRuntime ? (
        <div className="cockpit-lineage-grid">
          <div><span>legacy restart capture</span><strong>{nestedText(restartRuntime, ['status'])}</strong></div>
          <div><span>legacy trainer</span><strong>{nestedText(restartRuntime, ['legacy_trainer', 'status'])}</strong></div>
          <div><span>GPU state</span><strong>{nestedText(restartRuntime, ['gpu_runtime', 'status'])}</strong></div>
          <div><span>publish risk</span><strong>{nestedText(restartRuntime, ['legacy_publish_risk', 'status'])}</strong></div>
          <div><span>latest exchange order observed</span><strong>{nestedText(restartRuntime, ['legacy_publish_risk', 'latest_exchange_order_id'], 'none')}</strong></div>
          <div><span>parity</span><strong>{nestedText(restartRuntime, ['parity', 'status'])}</strong></div>
        </div>
      ) : null}
      <details className="truth-details">
        <summary>Read-only observed process rows ({runtime.active_processes.length})</summary>
        <div className="truth-raw-list">
          {runtime.active_processes.length ? runtime.active_processes.map((line) => (
            <code key={line}>{line}</code>
          )) : <p className="cockpit-evidence-gap">No matching legacy/trainer/trader process rows observed.</p>}
        </div>
      </details>
    </Panel>
  );
}

export function TrainerPredictionTruthPanel({ payload }: { payload: OperatorTruthPayload; }): JSX.Element {
  const trainer = payload.trainer_monitor_status;
  const latest = trainer.latest_prediction;
  const restartRuntime = payload.legacy_trainer_restart_runtime;
  const hasCurrentTrainer = trainer.status === 'REALTIME_RUNTIME_EVIDENCE' || trainer.status === 'V2_PAPER_TRAINER_WRAPPER_CURRENT';
  return (
    <Panel id="operator-truth-trainer-prediction" title="Trainer Prediction Monitor Preview" right={sourceChip(trainer.status)}>
      <div className="cockpit-lineage-grid">
        <div><span>status</span><strong>{trainer.status}</strong></div>
        <div><span>payload age seconds</span><strong>{valueText(trainer.payload_age_seconds)}</strong></div>
        <div><span>prediction worker from payload</span><strong>{valueText(trainer.prediction_worker_alive_from_stale_payload)}</strong></div>
        <div><span>latest trainer status from payload</span><strong>{valueText(trainer.latest_trainer_status_from_payload)}</strong></div>
        <div><span>prediction_id</span><strong>{hasCurrentTrainer ? valueText(latest?.prediction_id) : 'CURRENT_PREDICTION_MISSING'}</strong></div>
        <div><span>feature_snapshot_id</span><strong>{hasCurrentTrainer ? valueText(latest?.feature_snapshot_id) : 'CURRENT_FEATURE_SNAPSHOT_MISSING'}</strong></div>
        <div><span>model/checkpoint</span><strong>{hasCurrentTrainer ? valueText(latest?.model_checkpoint) : 'CURRENT_MODEL_EVIDENCE_MISSING'}</strong></div>
        <div><span>raw / calibrated confidence</span><strong>{hasCurrentTrainer ? `${valueText(latest?.confidence_raw)} / ${valueText(latest?.confidence_calibrated)}` : 'CURRENT_CONFIDENCE_MISSING'}</strong></div>
      </div>
      <p className="cockpit-evidence-gap">
        {hasCurrentTrainer
          ? 'Realtime trainer process evidence is present.'
          : 'TRAINER_RUNTIME_EVIDENCE_MISSING. Static proof predictions are not current trainer output and are only available in collapsed proof sections.'}
      </p>
      {restartRuntime ? (
        <>
          <div className="cockpit-lineage-grid">
            <div><span>legacy trainer after restart</span><strong>{nestedText(restartRuntime, ['legacy_trainer', 'status'])}</strong></div>
            <div><span>legacy monitor</span><strong>{nestedText(restartRuntime, ['legacy_trainer', 'monitor_status'])}</strong></div>
            <div><span>legacy output</span><strong>{nestedText(restartRuntime, ['legacy_trainer_output', 'status'])}</strong></div>
            <div><span>latest legacy symbol</span><strong>{nestedText(restartRuntime, ['legacy_trainer_output', 'symbol'])}</strong></div>
            <div><span>latest legacy confidence</span><strong>{nestedText(restartRuntime, ['legacy_trainer_output', 'confidence'])}</strong></div>
            <div><span>legacy feature snapshot</span><strong>{nestedText(restartRuntime, ['feature_snapshot', 'status'])}</strong></div>
            <div><span>V2 wrapper</span><strong>{nestedText(restartRuntime, ['v2_wrapper', 'status'])}</strong></div>
            <div><span>parity</span><strong>{nestedText(restartRuntime, ['parity', 'status'])}</strong></div>
          </div>
          <p className="cockpit-evidence-gap">
            Legacy restart evidence is shown separately from V2 runtime wrapper evidence. Full parity is not claimed unless the parity status explicitly says so.
          </p>
        </>
      ) : null}
    </Panel>
  );
}

export function SignalLineageTruthPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const signal = payload.signal_lineage_status;
  const latest = signal.latest_signal;
  const restartRuntime = payload.legacy_trainer_restart_runtime;
  const hasCurrentSignal = signal.status === 'REALTIME_RUNTIME_EVIDENCE';
  return (
    <Panel id="operator-truth-signal-lineage" title="Signal Explainability Preview" right={sourceChip(signal.status)}>
      {latest && hasCurrentSignal ? (
        <div className="cockpit-lineage-grid">
          {([
            ['signal_id', latest.signal_id],
            ['prediction_id', latest.prediction_id],
            ['feature_snapshot_id', latest.feature_snapshot_id],
            ['orchestrator_decision_id', latest.orchestrator_decision_id],
            ['risk_decision_id', latest.risk_decision_id],
            ['execution_intent_id', latest.execution_intent_id],
            ['orchestrator reason', latest.orchestrator_reason],
            ['risk reason', latest.risk_reason],
            ['result', latest.result],
          ] satisfies Array<[string, unknown]>).map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{valueText(value)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="cockpit-evidence-gap">{MISSING}</p>
      )}
      {!hasCurrentSignal ? (
        <p className="cockpit-evidence-gap">CURRENT_SIGNAL_LINEAGE_MISSING. Static proof examples are not shown as current signal lineage.</p>
      ) : null}
      {restartRuntime ? (
        <p className="cockpit-evidence-gap">
          Legacy restart publish risk: {nestedText(restartRuntime, ['legacy_publish_risk', 'status'])}. This dashboard did not stop, start, or command legacy execution.
        </p>
      ) : null}
    </Panel>
  );
}

export function WhatIsWorkingPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const rows = [
    ['control-plane truth bridge', controlPlaneValue(payload)],
    ['live market feed', payload.proof_artifact_statuses.find((row) => row.label.includes('readonly market'))?.status ?? 'MISSING_EVIDENCE'],
    ['trainer predictions', payload.trainer_monitor_status.status],
    ['signal lineage', payload.signal_lineage_status.status],
    ['risk gateway', payload.source_files.some((path) => path.includes('risk_gateway')) ? 'V2_PROOF_ARTIFACT' : 'MISSING_EVIDENCE'],
    ['execution online', payload.runtime_monitor_status.paper_online_runtime_status?.status ?? 'MISSING_EVIDENCE'],
    ['execution/shadow proof', payload.proof_artifact_statuses.find((row) => row.label.includes('paper'))?.status ?? 'MISSING_EVIDENCE'],
    ['website payload freshness', payload.dashboard_freshness_status.stale_payload_count ? 'STALE_PAYLOADS_PRESENT' : 'CURRENT_SNAPSHOT'],
  ];
  return (
    <Panel id="operator-truth-working-status" title="What Is Actually Working?">
      <div className="truth-working-grid">
        {rows.map(([label, value]) => (
          <div className={`truth-working-card truth-working-card--${truthTone(value)}`} key={label}>
            <span>{label}</span>
            <strong className={statusClass(value)}>{value}</strong>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function PayloadFreshnessPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const freshness = payload.dashboard_freshness_status;
  return (
    <Panel id="operator-truth-payload-freshness" title="Payload Freshness And Evidence Classification" right={<span className="chip solid-warn">Not runtime truth unless marked realtime</span>}>
      <div className="payload-freshness-summary">
        <Metric label="Payloads checked" value={freshness.payloads_checked} />
        <Metric label="Stale payloads" value={freshness.stale_payload_count} />
        <Metric label="Static fixtures" value={freshness.static_fixture_count} />
        <Metric label="Missing evidence" value={freshness.missing_evidence_count} />
      </div>
      <details className="truth-details">
        <summary>Open detailed payload table. Static and stale rows are not live runtime truth.</summary>
        <div className="cockpit-market-table" role="table">
          <div className="cockpit-table-row cockpit-table-row--head" role="row">
            <span>Payload</span><span>Class</span><span>Status</span><span>Age</span><span>Realtime</span><span>Static</span><span>Missing</span><span>Source</span>
          </div>
          {payload.dashboard_freshness_status.payload_statuses.map((row) => (
            <div className="cockpit-table-row" role="row" key={row.path}>
              <span>{row.label}</span>
              <span className={statusClass(row.classification)}>{evidenceClassLabel(row)}</span>
              <span className={statusClass(row.status)}>{row.status}</span>
              <span>{formatAge(row.age_seconds)}</span>
              <span>{boolStatus(row.is_realtime)}</span>
              <span>{boolStatus(row.is_static_fixture)}</span>
              <span>{boolStatus(row.missing)}</span>
              <span>{row.path}</span>
            </div>
          ))}
        </div>
      </details>
    </Panel>
  );
}

export function MissingEvidencePanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  return (
    <Panel id="operator-truth-missing-evidence" title="Exact Missing Evidence And Blockers" right={sourceChip('MISSING_EVIDENCE')}>
      <div className="missing-evidence-board">
        {payload.current_blockers.map((row) => (
          <div className="missing-evidence-card" key={row.id}>
            <strong>{row.id}</strong>
            <p>{row.severity}: {row.detail}</p>
          </div>
        ))}
      </div>
    </Panel>
  );
}
