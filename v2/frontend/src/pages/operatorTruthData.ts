import { useMemo } from 'react';
import { usePayloadFile } from '../hooks/usePayloadFile';

export interface OperatorTruthStatusRow {
  label: string;
  path: string;
  classification: string;
  generated_at: string | null;
  age_seconds: number | null;
  is_realtime: boolean;
  is_static_fixture: boolean;
  stale: boolean;
  missing: boolean;
  status: string;
}

export interface OperatorTruthPayload {
  generated_at: string;
  source_files: string[];
  live_gate_status: string;
  redis_trim_status: string;
  canonical_truth_bridge?: {
    status: string;
    source: string;
    generated_at: string;
    paper_runtime_age_seconds: number | null;
    operator_truth_was_stale: boolean;
  };
  current_next_task: string | null;
  supervisor_status: {
    is_supervisor_alive: boolean;
    heartbeat_stale: boolean;
    master_planner_running: boolean;
    autonomous_governor_active: boolean;
    current_running_task: string | null;
    last_completed_task?: string | null;
    last_task_status?: string | null;
    next_pending_task: string | null;
    true_next_task: string | null;
    stale_or_conflicting: boolean;
    control_plane_status?: string;
    canonical_snapshot_fresh?: boolean;
    historical_status_files_stale?: boolean;
    active_processes: string[];
    supervisor_processes: string[];
    status_conflicts: Record<string, unknown>;
  };
  runtime_monitor_status: {
    active_processes: string[];
    orchestrator_processes: string[];
    trainer_processes: string[];
    trader_processes: string[];
    market_ingestor_processes?: string[];
    feature_pipeline_processes?: string[];
    orchestrator_status: string;
    trainer_status: string;
    trader_status: string;
    market_ingestor_status?: string;
    feature_pipeline_status?: string;
    redis_memory_pressure_status?: OperatorTruthStatusRow;
    read_only_market_feed_status?: OperatorTruthStatusRow;
    paper_shadow_runtime_status?: OperatorTruthStatusRow;
    paper_online_runtime_status?: OperatorTruthStatusRow;
    paper_online_runtime?: PaperOnlineRuntimePayload | null;
    live_observer_runtime_status?: OperatorTruthStatusRow;
    live_observer_runtime?: Record<string, unknown> | null;
    legacy_trader_containment?: {
      status: string;
      action: string;
      process_rows: string[];
      evidence_source: string;
    };
  };
  trainer_monitor_status: {
    status: string;
    trainer_processes: string[];
    payload_age_seconds: number | null;
    latest_trainer_status_from_payload: string | null;
    prediction_worker_alive_from_stale_payload: boolean | null;
    prediction_lineage_gap: string | null;
    latest_prediction: Record<string, unknown> | null;
    missing_evidence: Array<Record<string, string>>;
  };
  signal_lineage_status: {
    status: string;
    latest_signal: Record<string, unknown> | null;
    missing_evidence: Array<Record<string, string>>;
  };
  dashboard_freshness_status: {
    payloads_checked: number;
    stale_payload_count: number;
    missing_evidence_count: number;
    static_fixture_count: number;
    payload_statuses: OperatorTruthStatusRow[];
  };
  static_fixture_panels: OperatorTruthStatusRow[];
  stale_payloads: OperatorTruthStatusRow[];
  missing_evidence: Array<{ id: string; severity: string; detail: string }>;
  current_blockers: Array<{ id: string; severity: string; detail: string }>;
  proof_artifact_statuses: OperatorTruthStatusRow[];
  legacy_trainer_restart_runtime?: Record<string, unknown> | null;
  live_observer_shadow_twin?: Record<string, unknown> | null;
  classifications: Record<string, string>;
}

export interface PaperOnlineRuntimePayload {
  generated_at: string;
  runtime: string;
  runtime_state: string;
  live_gate_status: string;
  mode: string;
  continuous_loop_available: boolean;
  loop_interval_seconds: number;
  writes_only_local_v2_artifacts: boolean;
  legacy_redis_writes: boolean;
  exchange_orders: boolean;
  leverage_changes: boolean;
  margin_mode_changes: boolean;
  redis_trim_approval_created: boolean;
  market_feed: {
    symbol: string;
    price: number | null;
    source_type: string;
    source: string;
    source_pointer: string;
    generated_at: string;
    last_event_at: string | null;
    age_seconds: number | null;
    freshness_state: string;
    errors: string[];
  };
  paper_loop: {
    state: string;
    tick_id: string;
    last_tick_at: string;
    paper_event_count: number;
    last_paper_event_count: number;
    last_shadow_decision_count: number;
    last_risk_block_count: number;
  };
  paper_account: {
    currency: string;
    starting_equity: number;
    equity: number;
    realized_pnl: number;
    unrealized_pnl: number;
    open_position_count: number;
    position_source: string;
  };
  trainer_prediction?: Record<string, unknown>;
  current_signal_lineage?: Record<string, unknown>;
  current_risk_decision?: Record<string, unknown>;
  paper_ledger_tail?: Array<Record<string, unknown>>;
  last_paper_event: Record<string, unknown>;
  safety: Record<string, unknown>;
  blockers: Array<{ id: string; severity: string; detail: string }>;
  freshness: {
    status: string;
    generated_at: string;
    runtime_age_seconds: number;
    market_age_seconds: number | null;
    source_type: string;
  };
}

export interface TonightReadinessPayload {
  generated_at: string;
  status: string;
  v2_paper_runtime_status: string;
  legacy_bridge_status: string;
  trainer_status: string;
  signal_lineage_status: string;
  risk_profile_status: string;
  canary_preflight_status: string;
  public_route_failed_count: number | null;
  local_route_failed_count: number | null;
  remaining_blockers: string[];
  live_gate_status: string;
  old_redis_writes: boolean;
  exchange_actions: boolean;
}

export interface CoinankCallLogHealth {
  recent_success_count?: number;
  recent_error_count?: number;
  recent_empty_count?: number;
  recent_sample_size?: number;
  recent_window_seconds?: number;
  recent_success_endpoints?: string[];
  recent_empty_endpoints?: string[];
  recent_error_examples?: unknown[];
  sample_size?: number;
}

export interface CoinankMarketIntelligencePayload {
  // Current live schema: coinank_direct_runtime_status_v1
  schema_version?: string;
  classification?: string;
  generated_utc?: string;
  generated_est?: string;
  freshness_seconds?: number;
  last_update_age_seconds?: number;
  runtime_mode?: string;
  worker_id?: string;
  endpoints_count?: number;
  metrics_count?: number;
  current_endpoint_success_count?: number;
  current_endpoint_error_count?: number;
  current_call_log_health?: CoinankCallLogHealth;
  direct_key_counts?: Record<string, number>;
  direct_ingestor_service?: string;
  direct_global_aggregator_service?: string;
  direct_legacy_key_write_enabled?: boolean;
  heartbeat_present?: boolean;
  heartbeat_ttl_seconds?: number;
  missing_api_blockers?: string[];
  never_successful_active_endpoints?: string[];
  intentionally_disabled_endpoints?: Record<string, unknown>;
  global_aggregate_result?: Record<string, unknown>;
  v2_redis_feature_input?: Record<string, unknown>;
  v2_redis_global_write_enabled?: boolean;
  // Legacy plan-3 bridge schema (older payload snapshots; retained optional for
  // backward compatibility with tradingPlatformPanels consumers)
  generated_at?: string;
  source?: string;
  live_gate_status?: string;
  legacy_source_file_hash?: string | null;
  legacy_monitor_file_hash?: string | null;
  endpoint_manifest_version?: string;
  required_tfs?: string[];
  required_tfs_status?: Record<string, boolean>;
  active_symbols?: string[];
  hot_symbols?: string[];
  endpoint_count?: number | null;
  radar_symbols?: unknown;
  availability?: Record<string, boolean>;
  endpoint_key_counts?: Record<string, number>;
  sample_endpoint_keys?: Record<string, string[]>;
  global_11_key_contract_status?: string;
  unified_features_sample_status?: Record<string, string | null | undefined>;
  forbidden_source_checks?: Record<string, boolean>;
  runtime_classifications?: string[];
  missing_evidence?: string[];
  stale_evidence?: string[];
  current_blockers?: Array<{ id: string; severity: string; detail: string }>;
  legacy_redis_writes_by_this_task?: boolean;
  legacy_bot_modified_by_this_task?: boolean;
  exchange_actions_by_this_task?: boolean;
  data_truth_rule?: string;
}

const operatorTruthPayloadPath = '/operator_truth/latest/operator_truth_payload.json';
const paperOnlineRuntimePayloadPath = '/api/v2/paper/runtime-status';
const legacyPaperRuntimePayloadPaths = new Set([
  'v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json',
  '/operator_runtime/paper_online/latest/paper_runtime_status.json',
]);
const liveObserverRuntimePayloadPath = '/operator_runtime/live_observer/latest/current_runtime_truth_payload.json';
const coinankMarketIntelligencePayloadPath = '/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json';
const tonightReadinessPayloadPath = '/tonight_live_like_paper_shadow/latest/operator_dashboard_payload.json';
const RUNTIME_CURRENT_SECONDS = 120;

function ageSeconds(generatedAt: string | null | undefined): number | null {
  if (!generatedAt) return null;
  const ms = new Date(generatedAt).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.round((Date.now() - ms) / 1000));
}

const ACTIVE_RUNTIME_STATES = new Set([
  'PAPER_RUNTIME_ONLINE_ACTIVE',
  'ACTIVE',
  'RUNNING_CYCLE',
  'V2_TRADE_MANAGEMENT_PAPER_CYCLE_RUNNING',
]);

function runtimeIsCurrent(payload: PaperOnlineRuntimePayload | null): boolean {
  if (!payload) return false;
  if (!ACTIVE_RUNTIME_STATES.has(payload.runtime_state ?? '')) return false;
  const age = ageSeconds(payload.generated_at);
  return age !== null && age <= RUNTIME_CURRENT_SECONDS;
}

function makeStatusRow(
  label: string,
  path: string,
  classification: string,
  generatedAt: string,
  age: number | null,
): OperatorTruthStatusRow {
  const stale = age === null || age > RUNTIME_CURRENT_SECONDS;
  return {
    label,
    path,
    classification,
    generated_at: generatedAt,
    age_seconds: age,
    is_realtime: classification === 'REALTIME_RUNTIME_EVIDENCE',
    is_static_fixture: classification === 'STATIC_PROOF_FIXTURE',
    stale,
    missing: false,
    status: stale ? 'STALE' : 'CURRENT',
  };
}

function synthesizeTruthFromPaperRuntime(
  staleTruth: OperatorTruthPayload | null,
  paperRuntime: PaperOnlineRuntimePayload,
  liveObserverRuntime: Record<string, unknown> | null = null,
): OperatorTruthPayload {
  const age = ageSeconds(paperRuntime.generated_at);
  const staleTruthAge = ageSeconds(staleTruth?.generated_at);
  const staleTruthIsFresh = staleTruthAge !== null && staleTruthAge <= RUNTIME_CURRENT_SECONDS;
  const paperStatus = makeStatusRow(
    'v2 execution runtime',
    paperOnlineRuntimePayloadPath,
    'REALTIME_RUNTIME_EVIDENCE',
    paperRuntime.generated_at,
    age,
  );
  const oldSupervisor = staleTruthIsFresh ? staleTruth?.supervisor_status : undefined;
  const oldRuntime = staleTruthIsFresh ? staleTruth?.runtime_monitor_status : undefined;
  const legacyTraderRows = oldRuntime?.trader_processes ?? [];
  const persistentControlPlaneObserved = oldSupervisor?.supervisor_processes.some((line) => /--daemon|claude_master_rebuild_planner|autonomous_governor|parallel_scheduler|codex_watchdog/.test(line)) ?? false;
  const controlPlaneStatus = persistentControlPlaneObserved
    ? 'CONTROL_PLANE_DAEMON_OBSERVED'
    : oldSupervisor?.is_supervisor_alive
      ? 'CONTROL_PLANE_WORKER_OBSERVED'
      : staleTruthIsFresh
        ? 'CONTROL_PLANE_DAEMON_NOT_OBSERVED'
        : 'CONTROL_PLANE_CURRENT_EVIDENCE_REQUIRES_OPERATOR_TRUTH_REFRESH';
  const latestPrediction = paperRuntime.trainer_prediction ?? null;
  const lineage = paperRuntime.current_signal_lineage ?? null;
  const lineageIds = (lineage?.lineage_ids ?? {}) as Record<string, unknown>;
  const riskDecision = paperRuntime.current_risk_decision ?? {};
  const currentBlockers = [
    ...(legacyTraderRows.length
      ? [{
          id: 'LEGACY_TRADER_PROCESS_OBSERVED_RUNTIME_CONTAINED',
          severity: 'safety_visibility',
          detail: 'A legacy trading/trader.py process is visible from the runtime process snapshot. The V2 runtime bridge did not touch it, and order submission remains operator gated.',
        }]
      : []),
    ...(!oldSupervisor?.is_supervisor_alive
      ? [{
          id: staleTruthIsFresh ? 'CONTROL_PLANE_DAEMON_NOT_OBSERVED' : 'CONTROL_PLANE_CURRENT_EVIDENCE_REQUIRES_OPERATOR_TRUTH_REFRESH',
          severity: 'operator_visibility',
          detail: staleTruthIsFresh
            ? 'No rebuild supervisor/governor daemon was observed. This is a control-plane availability issue, not evidence that V2 execution runtime is stale.'
            : 'The operator truth payload is stale, so browser-side execution runtime truth cannot prove current supervisor process state. Refresh operator truth from the local control plane.',
        }]
      : []),
    {
      id: 'LIVE_GATE_BLOCKED_HUMAN_ONLY',
      severity: 'expected_safety_gate',
      detail: 'Live order routing remains blocked_human_only.',
    },
    {
      id: 'REDIS_TRIM_DEFERRED_NON_BLOCKING',
      severity: 'non_blocking',
      detail: 'Redis trim approval file absent; no XTRIM may run.',
    },
  ];
  const payloadStatuses = [
    paperStatus,
    ...(staleTruth?.dashboard_freshness_status.payload_statuses ?? []).filter(
      (row) => row.path !== paperStatus.path && !legacyPaperRuntimePayloadPaths.has(row.path),
    ),
  ];

  return {
    generated_at: paperRuntime.generated_at,
    source_files: Array.from(new Set([paperStatus.path, ...(staleTruth?.source_files ?? [])])),
    live_gate_status: paperRuntime.live_gate_status,
    redis_trim_status: staleTruth?.redis_trim_status ?? 'deferred_non_blocking',
    canonical_truth_bridge: {
      status: 'V2_TRADE_MANAGEMENT_PAPER_CANONICAL_TRUTH_ACTIVE',
      source: paperStatus.path,
      generated_at: paperRuntime.generated_at,
      paper_runtime_age_seconds: age,
      operator_truth_was_stale: true,
    },
    current_next_task: oldSupervisor?.true_next_task ?? oldSupervisor?.next_pending_task ?? staleTruth?.current_next_task ?? null,
    supervisor_status: {
      is_supervisor_alive: oldSupervisor?.is_supervisor_alive ?? false,
      heartbeat_stale: false,
      master_planner_running: oldSupervisor?.master_planner_running ?? false,
      autonomous_governor_active: oldSupervisor?.autonomous_governor_active ?? false,
      current_running_task: oldSupervisor?.current_running_task ?? null,
      last_completed_task: oldSupervisor?.last_completed_task ?? null,
      last_task_status: oldSupervisor?.last_task_status ?? null,
      next_pending_task: oldSupervisor?.next_pending_task ?? null,
      true_next_task: oldSupervisor?.true_next_task ?? null,
      stale_or_conflicting: false,
      control_plane_status: controlPlaneStatus,
      canonical_snapshot_fresh: true,
      historical_status_files_stale: staleTruth ? ageSeconds(staleTruth.generated_at) !== null && (ageSeconds(staleTruth.generated_at) ?? 0) > RUNTIME_CURRENT_SECONDS : true,
      active_processes: oldSupervisor?.active_processes ?? oldRuntime?.active_processes ?? [],
      supervisor_processes: oldSupervisor?.supervisor_processes ?? [],
      status_conflicts: {
        ...(oldSupervisor?.status_conflicts ?? {}),
        canonical_truth_bridge: 'paper_runtime_payload_is_primary',
      },
    },
    runtime_monitor_status: {
      active_processes: oldRuntime?.active_processes ?? [],
      orchestrator_processes: oldRuntime?.orchestrator_processes ?? [],
      trainer_processes: oldRuntime?.trainer_processes ?? [],
      trader_processes: legacyTraderRows,
      market_ingestor_processes: oldRuntime?.market_ingestor_processes ?? [],
      feature_pipeline_processes: oldRuntime?.feature_pipeline_processes ?? [],
      orchestrator_status: oldRuntime?.orchestrator_status ?? 'UNKNOWN_NEEDS_EVIDENCE',
      trainer_status: 'V2_PAPER_TRAINER_WRAPPER_CURRENT',
      trader_status: legacyTraderRows.length ? 'PROCESS_OBSERVED_RUNTIME_CONTAINED' : 'TRADER_PROCESS_NOT_OBSERVED_OR_INTENTIONALLY_DISABLED',
      market_ingestor_status: oldRuntime?.market_ingestor_status ?? 'UNKNOWN_NEEDS_EVIDENCE',
      feature_pipeline_status: oldRuntime?.feature_pipeline_status ?? 'UNKNOWN_NEEDS_EVIDENCE',
      redis_memory_pressure_status: oldRuntime?.redis_memory_pressure_status,
      read_only_market_feed_status: paperStatus,
      paper_shadow_runtime_status: oldRuntime?.paper_shadow_runtime_status,
      paper_online_runtime_status: paperStatus,
      paper_online_runtime: paperRuntime,
      live_observer_runtime_status: oldRuntime?.live_observer_runtime_status,
      live_observer_runtime: liveObserverRuntime ?? oldRuntime?.live_observer_runtime ?? null,
      legacy_trader_containment: {
        status: legacyTraderRows.length ? 'LEGACY_TRADER_PROCESS_OBSERVED_RUNTIME_CONTAINED' : 'LEGACY_TRADER_NOT_OBSERVED',
        action: 'observation_only_no_restart_no_kill_no_order_action',
        process_rows: legacyTraderRows,
        evidence_source: 'runtime process snapshot from last operator truth payload',
      },
    },
    trainer_monitor_status: {
      status: 'V2_PAPER_TRAINER_WRAPPER_CURRENT',
      trainer_processes: oldRuntime?.trainer_processes ?? [],
      payload_age_seconds: age,
      latest_trainer_status_from_payload: 'V2_PAPER_TRAINER_WRAPPER_CURRENT',
      prediction_worker_alive_from_stale_payload: null,
      prediction_lineage_gap: null,
      latest_prediction: latestPrediction,
      missing_evidence: [],
    },
    signal_lineage_status: {
      status: lineage ? 'REALTIME_RUNTIME_EVIDENCE' : 'MISSING_EVIDENCE',
      latest_signal: lineage
        ? {
            signal_id: lineageIds.signal_id,
            prediction_id: lineageIds.prediction_id,
            feature_snapshot_id: lineageIds.feature_snapshot_id,
            orchestrator_decision_id: lineageIds.orchestrator_decision_id,
            risk_decision_id: lineageIds.risk_decision_id,
            execution_intent_id: lineageIds.execution_intent_id,
            signal_reason: (lineage.signal as Record<string, unknown> | undefined)?.proposed_action,
            orchestrator_reason: (lineage.orchestrator_decision as Record<string, unknown> | undefined)?.decision_reason,
            risk_reason: (riskDecision as Record<string, unknown>).risk_reason_code,
            result: (riskDecision as Record<string, unknown>).risk_result,
            evidence_links: [paperStatus.path],
          }
        : null,
      missing_evidence: lineage ? [] : [{ id: 'CURRENT_SIGNAL_LINEAGE_MISSING', detail: 'Evidence missing — cannot explain without guessing.' }],
    },
    dashboard_freshness_status: {
      payloads_checked: payloadStatuses.length,
      stale_payload_count: payloadStatuses.filter((row) => row.stale).length,
      missing_evidence_count: 0,
      static_fixture_count: payloadStatuses.filter((row) => row.is_static_fixture).length,
      payload_statuses: payloadStatuses,
    },
    static_fixture_panels: staleTruth?.static_fixture_panels ?? [],
    stale_payloads: payloadStatuses.filter((row) => row.stale),
    missing_evidence: [],
    current_blockers: currentBlockers,
    proof_artifact_statuses: staleTruth?.proof_artifact_statuses ?? [],
    legacy_trainer_restart_runtime: staleTruth?.legacy_trainer_restart_runtime ?? null,
    live_observer_shadow_twin: liveObserverRuntime ?? staleTruth?.live_observer_shadow_twin ?? null,
    classifications: staleTruth?.classifications ?? {
      REALTIME_RUNTIME_EVIDENCE: 'Current runtime evidence.',
      STALE_PAYLOAD: 'Generated artifact is older than its freshness threshold.',
      MISSING_EVIDENCE: 'Evidence missing — cannot explain without guessing.',
    },
  };
}

export function useOperatorTruthPayload(): {
  payload: OperatorTruthPayload | null;
  error: string | null;
} {
  const truth = usePayloadFile<OperatorTruthPayload>(operatorTruthPayloadPath, 10_000);
  const paper = usePayloadFile<PaperOnlineRuntimePayload>(paperOnlineRuntimePayloadPath, 10_000);
  const liveObserver = usePayloadFile<Record<string, unknown>>(liveObserverRuntimePayloadPath, 10_000);

  const payload = useMemo(() => {
    const truthPayload = truth.data;
    const paperPayload = paper.data;
    const liveObserverPayload = liveObserver.data;
    const truthAge = ageSeconds(truthPayload?.generated_at);
    if (paperPayload && runtimeIsCurrent(paperPayload) && (truthAge === null || truthAge > RUNTIME_CURRENT_SECONDS)) {
      return synthesizeTruthFromPaperRuntime(truthPayload, paperPayload, liveObserverPayload);
    }
    if (truthPayload) return truthPayload;
    if (paperPayload && runtimeIsCurrent(paperPayload)) {
      return synthesizeTruthFromPaperRuntime(null, paperPayload, liveObserverPayload);
    }
    return null;
  }, [liveObserver.data, paper.data, truth.data]);

  return { payload, error: payload ? null : truth.error ?? paper.error };
}

export function usePaperOnlineRuntimePayload(intervalMs = 10_000): {
  payload: PaperOnlineRuntimePayload | null;
  error: string | null;
} {
  const stream = usePayloadFile<PaperOnlineRuntimePayload>(paperOnlineRuntimePayloadPath, intervalMs);
  return { payload: stream.data, error: stream.error };
}

export function useTonightReadinessPayload(intervalMs = 10_000): {
  payload: TonightReadinessPayload | null;
  error: string | null;
} {
  const stream = usePayloadFile<TonightReadinessPayload>(tonightReadinessPayloadPath, intervalMs);
  return { payload: stream.data, error: stream.error };
}

export function useCoinankMarketIntelligencePayload(intervalMs = 10_000): {
  payload: CoinankMarketIntelligencePayload | null;
  error: string | null;
} {
  const stream = usePayloadFile<CoinankMarketIntelligencePayload>(coinankMarketIntelligencePayloadPath, intervalMs);
  return { payload: stream.data, error: stream.error };
}
