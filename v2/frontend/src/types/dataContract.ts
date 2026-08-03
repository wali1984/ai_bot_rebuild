/**
 * Shared data contract for all V2 frontend pages and backend API responses.
 *
 * Every visible metric, card, table cell, or chart must be wrapped in a
 * ValidatedDataEnvelope. Components must not render a metric without source
 * and freshness metadata.
 */

export type SourceType =
  | 'websocket'
  | 'sse'
  | 'api'
  | 'repository'
  | 'redis_live'
  | 'stream'
  | 'cache'
  | 'static_payload'
  | 'static_snapshot'
  | 'unavailable';

export type FreshnessStatus = 'fresh' | 'delayed' | 'stale' | 'offline' | 'unavailable';

export type DataQualityStatus = 'valid' | 'partial' | 'invalid' | 'missing' | 'degraded';

export type DataMode = 'public' | 'read_only' | 'paper' | 'live_blocked' | 'admin';

export interface ValidatedDataEnvelope<T = unknown> {
  data: T | null;

  source: string;
  source_type: SourceType;
  endpoint?: string;
  stream_topic?: string;
  repository?: string;
  ingestor_id?: string;
  service_id?: string;

  symbol?: string;
  exchange?: string;
  trader_context?: unknown;
  account_scope?: unknown;

  timestamp: number | null;
  received_at: number | null;
  lag_ms: number | null;

  freshness_status: FreshnessStatus;
  data_quality_status: DataQualityStatus;

  missing_fields: string[];
  warnings: string[];
  errors: string[];

  mode: DataMode;

  audit_id?: string;
  run_id?: string;
  job_id?: string;
  model_version?: string;
  strategy_id?: string;
  order_id?: string;
  trade_id?: string;
}

export type IncidentSeverity = 'critical' | 'warning' | 'info';

export interface DataSourceIncident {
  id: string;
  page: string;
  component: string;
  source: string;
  owner: string;
  severity: IncidentSeverity;
  message: string;
  remediation: string;
  first_seen: number;
  last_seen: number;
  resolved: boolean;
}

export function makeEmptyEnvelope<T>(
  source: string,
  opts?: Partial<ValidatedDataEnvelope<T>>
): ValidatedDataEnvelope<T> {
  return {
    data: null,
    source,
    source_type: 'unavailable',
    timestamp: null,
    received_at: null,
    lag_ms: null,
    freshness_status: 'unavailable',
    data_quality_status: 'missing',
    missing_fields: [],
    warnings: [],
    errors: [],
    mode: 'read_only',
    ...opts,
  };
}

export function isEnvelopeFresh(env: ValidatedDataEnvelope<unknown>): boolean {
  return env.freshness_status === 'fresh';
}

export function isEnvelopeUsable(env: ValidatedDataEnvelope<unknown>): boolean {
  return (
    env.data !== null &&
    (env.freshness_status === 'fresh' || env.freshness_status === 'delayed') &&
    (env.data_quality_status === 'valid' || env.data_quality_status === 'partial')
  );
}

export function isStaticSnapshot(env: ValidatedDataEnvelope<unknown>): boolean {
  return env.source_type === 'static_snapshot';
}

export function lagLabel(lagMs: number | null): string {
  if (lagMs === null) return '—';
  if (lagMs < 1000) return `${lagMs}ms`;
  if (lagMs < 60_000) return `${(lagMs / 1000).toFixed(1)}s`;
  return `${Math.floor(lagMs / 60_000)}m`;
}

export function freshnessColor(status: FreshnessStatus): string {
  switch (status) {
    case 'fresh': return 'var(--ok)';
    case 'delayed': return 'var(--warn)';
    case 'stale': return 'var(--error)';
    case 'offline': return 'var(--error)';
    case 'unavailable': return 'var(--text-muted)';
  }
}

export function qualityColor(status: DataQualityStatus): string {
  switch (status) {
    case 'valid': return 'var(--ok)';
    case 'partial': return 'var(--warn)';
    case 'invalid': return 'var(--error)';
    case 'missing': return 'var(--text-muted)';
    case 'degraded': return 'var(--warn)';
  }
}
