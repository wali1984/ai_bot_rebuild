// Admin canonical data types — every admin page must use these types.
// If the same service status appears on Overview, Data, and Orchestration it must use this shared type.

export type ServiceStatus = 'ok' | 'warn' | 'error' | 'unknown';
export type SourceStatus = 'ok' | 'warn' | 'error' | 'gap' | 'unknown';
export type JobStatus = 'running' | 'complete' | 'failed' | 'queued' | 'cancelled';
export type RiskStatus = 'allow' | 'block' | 'warn' | 'unknown';
export type TraderMode = 'paper' | 'live' | 'replay' | 'backtest';
export type TraderStatus = 'active' | 'idle' | 'error' | 'stopped';
export type TraderRiskStatus = 'ok' | 'warn' | 'blocked';
export type IncidentSeverity = 'critical' | 'high' | 'medium' | 'low';

export interface AdminService {
  id: string;
  name: string;
  status: ServiceStatus;
  heartbeat_at: string | null;
  lag_ms: number | null;
  error_count: number;
  warning_count: number;
  owner: string;
  version: string | null;
}

export interface AdminSource {
  id: string;
  dataset: string;
  status: SourceStatus;
  last_record_at: string | null;
  lag_ms: number | null;
  throughput: number | null;
  gap_count: number;
  duplicate_count: number;
  error_count: number;
  downstream_consumers: string[];
}

export interface AdminJob {
  id: string;
  type: string;
  status: JobStatus;
  progress: number;
  current_step: string | null;
  started_at: string | null;
  updated_at: string | null;
  error: string | null;
  owner_service: string;
}

export interface AdminRiskRule {
  rule_id: string;
  status: RiskStatus;
  threshold: number;
  current_value: number;
  block_count: number;
  last_decision_at: string | null;
}

export interface AdminTrader {
  id: string;
  mode: TraderMode;
  status: TraderStatus;
  heartbeat_at: string | null;
  strategy_ids: string[];
  symbols: string[];
  position_count: number;
  order_count: number;
  pnl: number | null;
  risk_status: TraderRiskStatus;
}

export interface AdminIncident {
  id: string;
  severity: IncidentSeverity;
  missing_source: string;
  expected_endpoint: string;
  owner_service: string;
  last_success_at: string | null;
  current_error: string;
  affected_pages: string[];
  remediation_action: string;
  incident_id: string;
}

export interface ControlAction {
  action_id: string;
  description: string;
  dry_run_result: string | null;
  reason: string;
  confirmed: boolean;
  audit_id: string | null;
  error: string | null;
  backend_response: unknown;
}

export interface AdminOverviewPayload {
  generated_at: string;
  live_gate: string;
  services: AdminService[];
  active_incidents: AdminIncident[];
  data_health: SourceStatus;
  intelligence_health: ServiceStatus;
  orchestration_health: ServiceStatus;
  risk_status: RiskStatus;
  execution_status: ServiceStatus;
  exchange_status: ServiceStatus;
}

export interface AdminDataPayload {
  generated_at: string;
  sources: AdminSource[];
  pipeline_health: SourceStatus;
  ingestor_active_count: number;
  ingestor_total_count: number;
  monitor_scripts_total: number;
  monitor_scripts_active: number;
}

export interface AdminIntelligencePayload {
  generated_at: string;
  trainer_status: ServiceStatus;
  model_version: string | null;
  checkpoint_at: string | null;
  prediction_lag_ms: number | null;
  signal_count_24h: number;
  accuracy_7d: number | null;
  jobs: AdminJob[];
}

export interface AdminOrchestrationPayload {
  generated_at: string;
  orchestrator_status: ServiceStatus;
  queue_depth: number;
  traders: AdminTrader[];
  active_strategies: string[];
  decision_latency_ms: number | null;
}
