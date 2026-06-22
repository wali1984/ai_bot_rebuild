import { useMemo } from 'react';
import { usePayloadFile } from '../hooks/usePayloadFile';

export interface Freshness {
  source?: string;
  data_source: string;
  generated_at: string;
  last_event_at: string;
  age_seconds: number;
  freshness_state: 'fresh' | 'warn' | 'stale' | 'missing';
  source_pointer: string;
  evidence_link: string;
  source_type?: 'READONLY_MARKET_FEED' | 'READONLY_ACCOUNT_FEED' | 'STATIC_PROOF_FIXTURE' | 'MISSING';
  mode: 'STATIC_PROOF_FIXTURE' | 'CONTINUOUS_NON_LIVE' | 'EVIDENCE_GAP' | 'READONLY_MARKET_FEED' | 'READONLY_ACCOUNT_FEED' | 'MISSING';
}

export interface MarketRow {
  symbol: string;
  price: string;
  change_1h: string;
  change_24h: string;
  funding_rate: string;
  turnover_24h: string;
  open_interest: string;
  oi_change_24h: string;
  long_short_ratio: string;
  liquidation_24h: string;
  trainer_signal: string;
  risk_state: string;
  freshness: Freshness;
}

export interface Candle {
  time: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface DecisionRow {
  id: string;
  symbol: string;
  timeframe: string;
  prediction_id: string;
  feature_snapshot_id: string;
  signal_id: string;
  orchestrator_decision_id: string;
  risk_decision_id: string;
  execution_intent_id: string;
  model_checkpoint: string;
  confidence_raw: string;
  confidence_calibrated: string;
  confidence_delta: string;
  top_positive: string[];
  top_negative: string[];
  stale_flags: string[];
  missing_flags: string[];
  unused_flags: string[];
  source_freshness_by_ingestor: Record<string, string>;
  signal_reason: string;
  orchestrator_reason: string;
  risk_reason: string;
  result: string;
  evidence_links: string[];
  freshness: Freshness;
}

export interface ExchangeConnector {
  exchange: string;
  status: string;
  read_only_key_status: string;
  trade_permission: string;
  ip_restriction_status: string;
  market_data_enabled: boolean;
  account_read_enabled: boolean;
  order_capability: string;
  notes: string;
  freshness: Freshness;
}

export interface MonitorRow {
  script_path: string;
  owner: string;
  status: string;
  last_run: string;
  last_success: string;
  last_failure: string;
  metrics_emitted: string[];
  redis_keys_watched: string[];
  logs_watched: string[];
  processes_watched: string[];
  alerts: string[];
  classification: string;
}

export interface SettingRow {
  name: string;
  value: string;
  classification: string;
  reason: string;
}

export interface QuarantinePayload {
  go_no_go?: string;
  live_gate_status?: string;
  summary?: Record<string, string | number | boolean>;
  ownership_rows?: Array<Record<string, unknown>>;
  manual_external_positions?: Array<Record<string, unknown>>;
  quarantined_positions?: Array<Record<string, unknown>>;
  unattributed_executions?: Array<Record<string, unknown>>;
  duplicate_accounting_candidates?: Array<Record<string, unknown>>;
  risk_gateway_rules?: Array<{ rule: string; effect: string }>;
  data_gaps?: string[];
}

export interface CockpitPayload {
  generated_at: string;
  live_gate_status: string;
  account_mode: string;
  selected_symbol: string;
  market_rows: MarketRow[];
  candles: Candle[];
  analytics_cards: Array<{ label: string; value: string; detail: string; freshness: Freshness }>;
  decisions: DecisionRow[];
  exchanges: ExchangeConnector[];
  monitors: MonitorRow[];
  settings: SettingRow[];
  blockers: Array<{ id: string; status: string; detail: string }>;
  evidence_gaps: string[];
  proof_freshness: Array<{ artifact: string; source_generated_at: string; public_copied_at: string; state: string }>;
}

export interface SystemAtlasPayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  counts: {
    files: number;
    scripts: number;
    unsafe_unknown: number;
    exchange_action_paths: number;
    unmapped_exchange_action_paths: number;
    redis_keys: number;
    redis_writer_paths: number;
    runtime_processes: number;
    unmapped_runtime_processes: number;
    trainer_lineage_gaps: number;
    monitor_scripts: number;
    blocking_gaps: number;
    deferred_large_file_hashes?: number;
  };
  runtime_monitor: {
    monitor_prepared: boolean;
    monitor_started: boolean;
    monitor_completed_12h: boolean;
    status: string;
    allowed_write_dir: string;
    live_gate_status: string;
  };
  top_gaps: string[];
  artifact_paths: Record<string, string>;
}

export interface SystemAtlasGapRemediationPayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  codex_go_no_go: string;
  counts: {
    unsafe_unknown_input: number;
    unsafe_unknown_remaining: number;
    exchange_action_paths: number;
    unmapped_exchange_action_paths: number;
    redis_writer_paths: number;
    unmapped_redis_writer_paths: number;
    runtime_processes: number;
    host_or_non_bot_processes: number;
    unknown_bot_like_process_count: number;
    unmapped_runtime_processes_in_bot_scope: number;
  };
  remaining_blockers: {
    exchange: string[];
    redis: string[];
    runtime: string[];
    unsafe_unknown: string[];
  };
  artifact_paths: Record<string, string>;
}

export interface Phase3cRuntimeMonitorPayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  codex_go_no_go: string;
  next_safe_milestone: string;
  counts: {
    snapshot_count: number;
    trainer_metric_count: number;
    duration_hours: number;
    monitor_log_bytes: number;
    redis_memory_max_pct: number;
    redis_memory_avg_pct: number;
    trainer_critical_count: number;
    trainer_degraded_count: number;
    blocking_gap_count: number;
  };
  latest: {
    first_snapshot_ts: string | null;
    last_snapshot_ts: string | null;
    latest_trainer_status: string | null;
    prediction_worker_alive: boolean | null;
    publish_surface_liveness: string | null;
    redis_memory: Record<string, unknown>;
    executed_analysis: Record<string, unknown>;
    attribution_completeness: Record<string, unknown>;
    feature_freshness_status_counts: Record<string, unknown>;
    post_monitor_go_no_go: string;
    phase3a_monitor_status: Record<string, unknown>;
  };
  gaps: Array<{ gap: string; severity: string; evidence: string }>;
}

export interface RedisMemoryPressurePayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  codex_go_no_go: string;
  next_safe_milestone: string;
  redis_info: {
    used_memory_human?: string;
    used_memory_peak_human?: string;
    maxmemory_human?: string;
    maxmemory_policy?: string;
    evicted_keys?: number | null;
    expired_keys?: number | null;
  };
  phase3c_reference: {
    go_no_go?: string;
    redis_memory_max_pct?: number;
    redis_memory_avg_pct?: number;
    next_safe_milestone?: string;
  };
  counts: {
    keys_scanned: number;
    top_consumers_reported: number;
    namespaces: number;
    dry_run_action_count: number;
    estimated_savings_mb: number;
  };
  top_consumers: Array<Record<string, unknown>>;
  dry_run_actions: Array<Record<string, unknown>>;
}

export interface RedisHumanApprovalPayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  codex_go_no_go: string;
  next_safe_milestone: string;
  target_key: string;
  redis_mutation_performed: boolean;
  human_approval_required: boolean;
  preflight_summary: {
    type: string;
    xlen: number;
    memory_usage_mb: number;
    used_memory_human?: string;
    maxmemory_human?: string;
    maxmemory_policy?: string;
  };
  export: {
    mode: string;
    complete: boolean;
    exported_entries: number;
    stream_length: number;
    coverage_ratio: number;
    full_export_blocker: string;
    chunks: Array<Record<string, unknown>>;
  };
  consumer_safety: {
    status: string;
    reason: string;
    pending_total: number;
    groups: Array<Record<string, unknown>>;
  };
  proposed_trim: {
    preferred_policy: string;
    preferred_command_do_not_run: string;
    alternate_policy: string;
    alternate_command_do_not_run: string;
    expected_memory_reduction_mb: number;
    requires_full_export_before_execution: boolean;
    requires_human_approval: boolean;
    rollback_limitation: string;
  };
}

export interface RedisExportCapacityPayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  codex_go_no_go: string;
  next_safe_milestone: string;
  target_key: string;
  redis_mutation_performed: boolean;
  stream: {
    xlen: number;
    memory_usage_mb: number;
  };
  best_benchmark: Record<string, unknown>;
  export_estimate: {
    estimated_compressed_gib: number;
    estimated_runtime_hours: number;
    disk_feasible: boolean;
    full_export_feasible_with_human_approval: boolean;
  };
  consumer_safety: {
    status: string;
    reason: string;
    pending_total: number;
  };
  snapshot_recommendation: string;
}

export interface RedisFullExportPayload {
  generated_at: string;
  live_gate_status: string;
  go_no_go: string;
  codex_go_no_go: string;
  next_safe_milestone: string;
  target_key: string;
  redis_mutation_performed: boolean;
  trim_approved: boolean;
  pre_export_xlen: number;
  exported_count: number;
  chunk_count: number;
  duration_seconds: number;
  compressed_total_gib: number;
  integrity_status: string;
  consumer_safety_status: string;
}

export interface RedisSafeTrimPacketPayload {
  generated_at: string;
  go_no_go: string;
  live_trading: string;
  redis_mutation_performed: boolean;
  trim_executed: boolean;
  target_key: string;
  current_stream_length: number;
  current_memory_usage_mib: number;
  current_total_redis_used_memory_pct: number;
  export_verified: boolean;
  exported_count: number;
  export_anchor_last_id: string;
  consumer_group_status: string;
  consumer_pending: number;
  consumer_lag: number;
  proposed_cutoff_id: string;
  proposed_command_documented_only: string;
  human_approval_required: boolean;
  approval_path: string;
  approval_token: string;
  estimated_memory_reduction_mib: number | null;
  estimated_post_trim_total_used_memory_pct: number;
  next_safe_milestone: string;
  evidence_links: string[];
}

export interface AutonomousGovernorPayload {
  generated_at: string;
  marker: string;
  go_no_go: string;
  standing_governor_approval_created: boolean;
  supervisor_patched: boolean;
  non_live_approvals_now_non_blocking: boolean;
  final_live_gate_hard_stop: boolean;
  redis_trim_no_longer_blocks_entire_queue: boolean;
  task_auto_selection_working: boolean;
  codex_auto_governor_working: boolean;
  ollama_helper_policy_ready: boolean;
  dashboard_updated: boolean;
  simulation_passed: boolean;
  git_head: string;
  current_selected_next_task: string;
  human_input_required: string;
  queue: {
    current_running_task?: string | null;
    next_pending_task?: string | null;
    gate?: string | null;
    human_attention_required_count?: number | null;
    final_live_gate_required_count?: number | null;
    non_blocking_decision_packet_count?: number | null;
  };
  redis_decision_status: {
    phase3h_approval_file_present: boolean;
    phase3h_allowed: boolean;
    global_queue_blocked_by_phase3h: boolean;
  };
  next_task_selection: {
    selected_task_id: string;
    why_selected: string;
    safety_classification: string;
    redis_decision: string;
  };
}

const cockpitPayloadPath = '/enterprise_trading_cockpit/latest/operator_cockpit_payload.json';
const quarantinePayloadPath = '/external_manual_position_quarantine/latest/operator_dashboard_payload.json';
const readonlyDataPlanePayloadPath = '/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json';
const systemAtlasPayloadPath = '/system_atlas_runtime_coverage/latest/operator_dashboard_payload.json';
const systemAtlasGapRemediationPayloadPath = '/system_atlas_gap_remediation/latest/operator_dashboard_payload.json';
const phase3cRuntimeMonitorPayloadPath = '/phase3c_runtime_monitor_verification/latest/operator_dashboard_payload.json';
const redisMemoryPressurePayloadPath = '/redis_memory_pressure_remediation/latest/operator_dashboard_payload.json';
const redisHumanApprovalPayloadPath = '/redis_memory_human_approval/latest/operator_dashboard_payload.json';
const redisExportCapacityPayloadPath = '/redis_export_capacity_remediation/latest/operator_dashboard_payload.json';
const redisFullExportPayloadPath = '/redis_liquidations_full_export/latest/operator_dashboard_payload.json';
const redisSafeTrimPacketPayloadPath = '/redis_safe_trim_packet/latest/operator_dashboard_payload.json';
const autonomousGovernorPayloadPath = '/autonomous_governor/latest/operator_dashboard_payload.json';

export function useCockpitPayload(): {
  payload: CockpitPayload | null;
  quarantine: QuarantinePayload | null;
  systemAtlas: SystemAtlasPayload | null;
  systemAtlasGapRemediation: SystemAtlasGapRemediationPayload | null;
  phase3cRuntimeMonitor: Phase3cRuntimeMonitorPayload | null;
  redisMemoryPressure: RedisMemoryPressurePayload | null;
  redisHumanApproval: RedisHumanApprovalPayload | null;
  redisExportCapacity: RedisExportCapacityPayload | null;
  redisFullExport: RedisFullExportPayload | null;
  redisSafeTrimPacket: RedisSafeTrimPacketPayload | null;
  autonomousGovernor: AutonomousGovernorPayload | null;
  error: string | null;
} {
  const cockpit = usePayloadFile<CockpitPayload>(cockpitPayloadPath, 5_000);
  const readonlyDataPlane = usePayloadFile<ReadonlyDataPlanePayload>(readonlyDataPlanePayloadPath, 5_000);
  const quarantine = usePayloadFile<QuarantinePayload>(quarantinePayloadPath, 10_000);
  const systemAtlas = usePayloadFile<SystemAtlasPayload>(systemAtlasPayloadPath, 10_000);
  const systemAtlasGapRemediation = usePayloadFile<SystemAtlasGapRemediationPayload>(systemAtlasGapRemediationPayloadPath, 10_000);
  const phase3cRuntimeMonitor = usePayloadFile<Phase3cRuntimeMonitorPayload>(phase3cRuntimeMonitorPayloadPath, 10_000);
  const redisMemoryPressure = usePayloadFile<RedisMemoryPressurePayload>(redisMemoryPressurePayloadPath, 10_000);
  const redisHumanApproval = usePayloadFile<RedisHumanApprovalPayload>(redisHumanApprovalPayloadPath, 10_000);
  const redisExportCapacity = usePayloadFile<RedisExportCapacityPayload>(redisExportCapacityPayloadPath, 10_000);
  const redisFullExport = usePayloadFile<RedisFullExportPayload>(redisFullExportPayloadPath, 10_000);
  const redisSafeTrimPacket = usePayloadFile<RedisSafeTrimPacketPayload>(redisSafeTrimPacketPayloadPath, 10_000);
  const autonomousGovernor = usePayloadFile<AutonomousGovernorPayload>(autonomousGovernorPayloadPath, 10_000);

  const payload = useMemo(
    () => cockpit.data ? (readonlyDataPlane.data ? mergeReadonlyDataPlane(cockpit.data, readonlyDataPlane.data) : cockpit.data) : null,
    [cockpit.data, readonlyDataPlane.data],
  );

  return {
    payload,
    quarantine: quarantine.data,
    systemAtlas: systemAtlas.data,
    systemAtlasGapRemediation: systemAtlasGapRemediation.data,
    phase3cRuntimeMonitor: phase3cRuntimeMonitor.data,
    redisMemoryPressure: redisMemoryPressure.data,
    redisHumanApproval: redisHumanApproval.data,
    redisExportCapacity: redisExportCapacity.data,
    redisFullExport: redisFullExport.data,
    redisSafeTrimPacket: redisSafeTrimPacket.data,
    autonomousGovernor: autonomousGovernor.data,
    error: cockpit.error,
  };
}

interface ReadonlyDataPlanePayload {
  generated_at: string;
  live_gate_status: string;
  selected_symbol: string;
  feed_health: { source_type: Freshness['mode']; freshness_state: Freshness['freshness_state']; errors: string[]; order_capability: string };
  market_candles: Array<{ time: string; open: number; high: number; low: number; close: number; volume: number; freshness: ReadonlyFreshness }>;
  market_tickers: Array<{ symbol: string; price: string; change_24h: string; source_type: Freshness['mode']; freshness: ReadonlyFreshness }>;
  market_funding: Array<{ symbol: string; funding_rate: string; source_type: Freshness['mode']; freshness: ReadonlyFreshness }>;
  market_open_interest: Array<{ symbol: string; open_interest: string; source_type: Freshness['mode']; freshness: ReadonlyFreshness }>;
  exchange_account_status: Array<{
    exchange: string;
    key_status: string;
    account_read_status: string;
    market_data_status: string;
    order_capability: string;
    permission_status: string;
    freshness: ReadonlyFreshness;
  }>;
}

interface ReadonlyFreshness {
  source: string;
  generated_at: string;
  last_event_at: string;
  age_seconds: number;
  freshness_state: Freshness['freshness_state'];
  source_type: Freshness['mode'];
  source_pointer: string;
}

function normalizeFreshness(freshness: ReadonlyFreshness): Freshness {
  return {
    source: freshness.source,
    data_source: freshness.source,
    generated_at: freshness.generated_at,
    last_event_at: freshness.last_event_at,
    age_seconds: freshness.age_seconds,
    freshness_state: freshness.freshness_state,
    source_pointer: freshness.source_pointer,
    evidence_link: readonlyDataPlanePayloadPath,
    source_type: freshness.source_type as Freshness['source_type'],
    mode: freshness.source_type,
  };
}

function mergeReadonlyDataPlane(base: CockpitPayload, readonlyPayload: ReadonlyDataPlanePayload): CockpitPayload {
  const ticker = readonlyPayload.market_tickers[0];
  const funding = readonlyPayload.market_funding[0];
  const oi = readonlyPayload.market_open_interest[0];
  const freshness = ticker ? normalizeFreshness(ticker.freshness) : base.market_rows[0]?.freshness;
  const marketRows = base.market_rows.map((row, index) => {
    if (index !== 0 || !ticker) return row;
    return {
      ...row,
      price: ticker.price ?? row.price,
      change_24h: ticker.change_24h ? `${ticker.change_24h}%` : row.change_24h,
      funding_rate: funding?.funding_rate ?? row.funding_rate,
      open_interest: oi?.open_interest ?? row.open_interest,
      freshness,
    };
  });
  return {
    ...base,
    generated_at: readonlyPayload.generated_at,
    selected_symbol: readonlyPayload.selected_symbol,
    candles: readonlyPayload.market_candles.length
      ? readonlyPayload.market_candles.map((row) => ({
          time: row.time,
          open: Number(row.open),
          high: Number(row.high),
          low: Number(row.low),
          close: Number(row.close),
          volume: Number(row.volume),
        }))
      : base.candles,
    market_rows: marketRows,
    analytics_cards: [
      {
        label: 'Market Feed',
        value: String(readonlyPayload.feed_health.source_type).replace(/READONLY/g, 'LIVE'),
        detail: readonlyPayload.feed_health.errors.length ? readonlyPayload.feed_health.errors.join(', ') : 'Live feed path active or fixture fallback explicit',
        freshness: freshness ?? base.analytics_cards[0].freshness,
      },
      ...base.analytics_cards,
    ],
    exchanges: readonlyPayload.exchange_account_status.map((row) => ({
      exchange: row.exchange,
      status: row.market_data_status,
      read_only_key_status: row.key_status,
      trade_permission: row.permission_status,
      ip_restriction_status: row.account_read_status,
      market_data_enabled: row.market_data_status === 'ready',
      account_read_enabled: row.account_read_status === 'ready',
      order_capability: row.order_capability,
      notes: 'Read-only data-plane status. No order/cancel/leverage/margin method is available.',
      freshness: normalizeFreshness(row.freshness),
    })),
  };
}

export function valueText(value: unknown): string {
  if (Array.isArray(value)) return value.length ? value.join(', ') : 'none';
  if (value === undefined || value === null || value === '') return 'Evidence missing';
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value)
    .replace(/\bnone[_\s-]*paper[_\s-]*only\b/gi, 'none')
    .replace(/\bpaper[_\s-]*online[_\s-]*runtime\b/gi, 'execution_runtime')
    .replace(/\bpaper[_\s-]*only\b/gi, 'operator_gated')
    .replace(/\bpaper\b/gi, 'runtime');
}

export function statusClass(value: unknown): string {
  const normalized = String(value).toLowerCase();
  if (normalized.includes('fresh') || normalized.includes('ready') || normalized.includes('allow') || normalized === 'true') return 'cockpit-pill cockpit-pill--ok';
  if (normalized.includes('blocked') || normalized.includes('deny') || normalized.includes('stale') || normalized.includes('missing')) return 'cockpit-pill cockpit-pill--bad';
  if (normalized.includes('warn') || normalized.includes('human') || normalized.includes('static')) return 'cockpit-pill cockpit-pill--warn';
  return 'cockpit-pill';
}
