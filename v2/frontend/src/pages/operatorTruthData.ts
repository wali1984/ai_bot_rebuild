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

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

export function useOperatorTruthPayload(): {
  payload: OperatorTruthPayload | null;
  error: string | null;
} {
  const [payload, setPayload] = useState<OperatorTruthPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchJson<OperatorTruthPayload>(operatorTruthPayloadPath)
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
    return () => {
      active = false;
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
