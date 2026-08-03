export const PIPELINE_CONTROL_API_ENABLED = import.meta.env.VITE_ENABLE_PIPELINE_CONTROL_API !== 'false';
export const PIPELINE_STATUS_STATIC_PATH =
  '/operator_runtime/v2_pipeline_control/latest/pipeline_control_status.json';
export const PIPELINE_STATUS_ENDPOINT = PIPELINE_CONTROL_API_ENABLED
  ? '/api/v2/pipeline/status'
  : PIPELINE_STATUS_STATIC_PATH;
export const PIPELINE_RUN_ENDPOINT = '/api/v2/pipeline/run';

export type PipelineRunType = 'trainer_cycle' | 'replay' | 'backtest' | 'full_pipeline';

export interface PipelineControlProbe {
  key: string;
  present: boolean;
  source_type: string;
}

export interface PipelineCompatibilityRow {
  symbol: string;
  timeframe: string;
  trainer_compatible: boolean;
  backtest_compatible: boolean;
  replay_compatible: boolean;
  chart_visible: boolean;
  blockers: string[];
  required_sources_present: number;
  required_sources_total: number;
  optional_sources_present: number;
  optional_sources_total: number;
  chart_payload_path: string;
  chart_status: string;
  probes: PipelineControlProbe[];
}

export interface PipelineCompatibilitySummary {
  row_count: number;
  trainer_compatible_count: number;
  backtest_compatible_count: number;
  replay_compatible_count: number;
  chart_visible_symbol_count: number;
  trainer_compatible_percent: number;
  backtest_compatible_percent: number;
  replay_compatible_percent: number;
  blocker_counts: Record<string, number>;
}

export interface PipelineControlStatus {
  schema_version: string;
  generated_utc: string;
  live_gate: string;
  live_symbols: string[];
  exchange_action_taken: boolean;
  control_stream_key: string;
  control_last_request_key: string;
  allowed_run_types: PipelineRunType[];
  symbols: string[];
  timeframes: string[];
  compatibility: PipelineCompatibilitySummary;
  rows: PipelineCompatibilityRow[];
  last_request?: PipelineRunResult | null;
  website_visualization?: Record<string, string>;
}

export interface PipelineRunResult {
  schema_version: string;
  control_request_id: string;
  generated_utc: string;
  run_type: PipelineRunType;
  symbols: string[];
  timeframes: string[];
  dry_run: boolean;
  accepted: boolean;
  queue_state: string;
  live_gate: string;
  live_symbols: string[];
  exchange_action_taken: boolean;
  trainer_api_executed_job_inline: boolean;
  control_stream_key: string;
  stream_id?: string | null;
  audit_stream_id?: string | null;
  last_request_written?: boolean;
  compatibility: PipelineCompatibilitySummary;
}

export function formatPipelinePercent(value: unknown): string {
  const n = typeof value === 'number' && Number.isFinite(value) ? value : null;
  return n === null ? '—' : `${n.toFixed(1)}%`;
}

export function pipelineTone(ok: boolean): 'ok' | 'block' {
  return ok ? 'ok' : 'block';
}
