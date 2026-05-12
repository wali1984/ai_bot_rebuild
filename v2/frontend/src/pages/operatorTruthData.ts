import { useEffect, useState } from 'react';

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

const operatorTruthPayloadPath = '/operator_truth/latest/operator_truth_payload.json';
const paperOnlineRuntimePayloadPath = '/operator_runtime/paper_online/latest/paper_runtime_status.json';
const RUNTIME_CURRENT_SECONDS = 120;

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

function ageSeconds(generatedAt: string | null | undefined): number | null {
  if (!generatedAt) return null;
  const ms = new Date(generatedAt).getTime();
  if (Number.isNaN(ms)) return null;
  return Math.max(0, Math.round((Date.now() - ms) / 1000));
}

function runtimeIsCurrent(payload: PaperOnlineRuntimePayload | null): boolean {
  if (!payload || payload.runtime_state !== 'PAPER_RUNTIME_ONLINE_ACTIVE') return false;
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
): OperatorTruthPayload {
  const age = ageSeconds(paperRuntime.generated_at);
  const paperStatus = makeStatusRow(
    'v2 paper online runtime',
    'v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json',
    'REALTIME_RUNTIME_EVIDENCE',
    paperRuntime.generated_at,
    age,
  );
  const oldSupervisor = staleTruth?.supervisor_status;
  const oldRuntime = staleTruth?.runtime_monitor_status;
  const legacyTraderRows = oldRuntime?.trader_processes ?? [];
  const persistentControlPlaneObserved = oldSupervisor?.supervisor_processes.some((line) => /--daemon|claude_master_rebuild_planner|autonomous_governor|parallel_scheduler|codex_watchdog/.test(line)) ?? false;
  const controlPlaneStatus = persistentControlPlaneObserved
    ? 'CONTROL_PLANE_DAEMON_OBSERVED'
    : oldSupervisor?.is_supervisor_alive
      ? 'CONTROL_PLANE_WORKER_OBSERVED'
      : 'CONTROL_PLANE_DAEMON_NOT_OBSERVED';
  const latestPrediction = paperRuntime.trainer_prediction ?? null;
  const lineage = paperRuntime.current_signal_lineage ?? null;
  const lineageIds = (lineage?.lineage_ids ?? {}) as Record<string, unknown>;
  const riskDecision = paperRuntime.current_risk_decision ?? {};
  const currentBlockers = [
    ...(legacyTraderRows.length
      ? [{
          id: 'LEGACY_TRADER_PROCESS_OBSERVED_READONLY_CONTAINED',
          severity: 'safety_visibility',
          detail: 'A legacy trading/trader.py process is visible from the read-only process snapshot. The V2 paper bridge did not touch it, and live execution remains blocked_human_only.',
        }]
      : []),
    ...(!oldSupervisor?.is_supervisor_alive
      ? [{
          id: 'CONTROL_PLANE_DAEMON_NOT_OBSERVED',
          severity: 'operator_visibility',
          detail: 'No rebuild supervisor/governor daemon was observed. This is a control-plane availability issue, not evidence that V2 paper runtime is stale.',
        }]
      : []),
    {
      id: 'LIVE_GATE_BLOCKED_HUMAN_ONLY',
      severity: 'expected_safety_gate',
      detail: 'Live trading remains blocked_human_only.',
    },
    {
      id: 'REDIS_TRIM_DEFERRED_NON_BLOCKING',
      severity: 'non_blocking',
      detail: 'Redis trim approval file absent; no XTRIM may run.',
    },
  ];
  const payloadStatuses = [
    paperStatus,
    ...(staleTruth?.dashboard_freshness_status.payload_statuses ?? []).filter((row) => row.path !== paperStatus.path),
  ];

  return {
    generated_at: paperRuntime.generated_at,
    source_files: Array.from(new Set([paperStatus.path, ...(staleTruth?.source_files ?? [])])),
    live_gate_status: paperRuntime.live_gate_status,
    redis_trim_status: staleTruth?.redis_trim_status ?? 'deferred_non_blocking',
    canonical_truth_bridge: {
      status: 'PAPER_ONLINE_CANONICAL_TRUTH_ACTIVE',
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
      trader_status: legacyTraderRows.length ? 'PROCESS_OBSERVED_READONLY_CONTAINED' : 'TRADER_PROCESS_NOT_OBSERVED_OR_INTENTIONALLY_DISABLED',
      market_ingestor_status: oldRuntime?.market_ingestor_status ?? 'UNKNOWN_NEEDS_EVIDENCE',
      feature_pipeline_status: oldRuntime?.feature_pipeline_status ?? 'UNKNOWN_NEEDS_EVIDENCE',
      redis_memory_pressure_status: oldRuntime?.redis_memory_pressure_status,
      read_only_market_feed_status: paperStatus,
      paper_shadow_runtime_status: oldRuntime?.paper_shadow_runtime_status,
      paper_online_runtime_status: paperStatus,
      paper_online_runtime: paperRuntime,
      legacy_trader_containment: {
        status: legacyTraderRows.length ? 'LEGACY_TRADER_PROCESS_OBSERVED_READONLY_CONTAINED' : 'LEGACY_TRADER_NOT_OBSERVED',
        action: 'observation_only_no_restart_no_kill_no_order_action',
        process_rows: legacyTraderRows,
        evidence_source: 'read-only process snapshot from last operator truth payload',
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
  const [payload, setPayload] = useState<OperatorTruthPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = (): void => {
      Promise.allSettled([
        fetchJson<OperatorTruthPayload>(`${operatorTruthPayloadPath}?ts=${Date.now()}`),
        fetchJson<PaperOnlineRuntimePayload>(`${paperOnlineRuntimePayloadPath}?ts=${Date.now()}`),
      ]).then(([truthResult, paperResult]) => {
        if (!active) return;
        const truth = truthResult.status === 'fulfilled' ? truthResult.value : null;
        const paper = paperResult.status === 'fulfilled' ? paperResult.value : null;
        const truthAge = ageSeconds(truth?.generated_at);
        if (paper && runtimeIsCurrent(paper) && (truthAge === null || truthAge > RUNTIME_CURRENT_SECONDS)) {
          setPayload(synthesizeTruthFromPaperRuntime(truth, paper));
          setError(null);
          return;
        }
        if (truth) {
          setPayload(truth);
          setError(null);
          return;
        }
        if (paper && runtimeIsCurrent(paper)) {
          setPayload(synthesizeTruthFromPaperRuntime(null, paper));
          setError(null);
          return;
        }
        const reason = truthResult.status === 'rejected' ? truthResult.reason : paperResult.status === 'rejected' ? paperResult.reason : 'no payload';
        setPayload(null);
        setError(reason instanceof Error ? reason.message : String(reason));
      });
    };
    load();
    timer = window.setInterval(load, 10_000);
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, []);

  return { payload, error };
}

export function usePaperOnlineRuntimePayload(intervalMs = 10_000): {
  payload: PaperOnlineRuntimePayload | null;
  error: string | null;
} {
  const [payload, setPayload] = useState<PaperOnlineRuntimePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const load = (): void => {
      fetchJson<PaperOnlineRuntimePayload>(`${paperOnlineRuntimePayloadPath}?ts=${Date.now()}`)
        .then((data) => {
          if (!active) return;
          setPayload(data);
          setError(null);
        })
        .catch((err: unknown) => {
          if (!active) return;
          setPayload(null);
          setError(err instanceof Error ? err.message : String(err));
        });
    };
    load();
    timer = window.setInterval(load, intervalMs);
    return () => {
      active = false;
      if (timer !== undefined) window.clearInterval(timer);
    };
  }, [intervalMs]);

  return { payload, error };
}
