// Canonical admin field registry.
// All admin pages must resolve display format from this registry.
// If a field appears on multiple pages, its format is defined once here.

import type { ServiceStatus, SourceStatus, JobStatus, RiskStatus, TraderRiskStatus, IncidentSeverity } from '../types/adminData';

export type FieldUnit =
  | 'timestamp'
  | 'ms'
  | 'count'
  | 'usd'
  | 'percent'
  | 'records_per_min'
  | 'semver'
  | 'text'
  | 'url'
  | 'enum';

export interface FieldDefinition {
  key: string;
  label: string;
  unit: FieldUnit;
  freshness_s: number;
  min_role: 'public' | 'reviewer' | 'admin' | 'superadmin';
  source_endpoint: string;
  description: string;
}

export const ADMIN_FIELD_REGISTRY: Record<string, FieldDefinition> = {
  'service.id': { key: 'service.id', label: 'Service ID', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Stable service identifier' },
  'service.name': { key: 'service.name', label: 'Service', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Human-readable service name' },
  'service.status': { key: 'service.status', label: 'Status', unit: 'enum', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'ok | warn | error | unknown' },
  'service.heartbeat_at': { key: 'service.heartbeat_at', label: 'Last Heartbeat', unit: 'timestamp', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'ISO-8601 timestamp of last heartbeat' },
  'service.lag_ms': { key: 'service.lag_ms', label: 'Lag', unit: 'ms', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Processing lag in milliseconds' },
  'service.error_count': { key: 'service.error_count', label: 'Errors', unit: 'count', freshness_s: 60, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Error events in last window' },
  'service.warning_count': { key: 'service.warning_count', label: 'Warnings', unit: 'count', freshness_s: 60, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Warning events in last window' },
  'service.owner': { key: 'service.owner', label: 'Owner', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Team or module that owns this service' },
  'service.version': { key: 'service.version', label: 'Version', unit: 'semver', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/services', description: 'Deployed version string' },

  'source.id': { key: 'source.id', label: 'Source ID', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Stable data source identifier' },
  'source.dataset': { key: 'source.dataset', label: 'Dataset', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Dataset name' },
  'source.status': { key: 'source.status', label: 'Status', unit: 'enum', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'ok | warn | error | gap | unknown' },
  'source.last_record_at': { key: 'source.last_record_at', label: 'Last Record', unit: 'timestamp', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'ISO-8601 timestamp of most recent record' },
  'source.lag_ms': { key: 'source.lag_ms', label: 'Lag', unit: 'ms', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Pipeline lag in milliseconds' },
  'source.throughput': { key: 'source.throughput', label: 'Throughput', unit: 'records_per_min', freshness_s: 30, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Records per minute' },
  'source.gap_count': { key: 'source.gap_count', label: 'Gaps', unit: 'count', freshness_s: 60, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Data gap events' },
  'source.duplicate_count': { key: 'source.duplicate_count', label: 'Duplicates', unit: 'count', freshness_s: 60, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Duplicate record events' },
  'source.error_count': { key: 'source.error_count', label: 'Errors', unit: 'count', freshness_s: 60, min_role: 'reviewer', source_endpoint: '/api/v2/admin/data/sources', description: 'Error events from this source' },

  'job.id': { key: 'job.id', label: 'Job ID', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'Job identifier' },
  'job.type': { key: 'job.type', label: 'Type', unit: 'text', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'Job category' },
  'job.status': { key: 'job.status', label: 'Status', unit: 'enum', freshness_s: 15, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'running | complete | failed | queued | cancelled' },
  'job.progress': { key: 'job.progress', label: 'Progress', unit: 'percent', freshness_s: 15, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: '0–100 completion percentage' },
  'job.current_step': { key: 'job.current_step', label: 'Step', unit: 'text', freshness_s: 15, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'Current processing step' },
  'job.started_at': { key: 'job.started_at', label: 'Started', unit: 'timestamp', freshness_s: 0, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'Job start timestamp' },
  'job.updated_at': { key: 'job.updated_at', label: 'Updated', unit: 'timestamp', freshness_s: 15, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'Last update timestamp' },
  'job.error': { key: 'job.error', label: 'Error', unit: 'text', freshness_s: 15, min_role: 'reviewer', source_endpoint: '/api/v2/admin/jobs', description: 'Error message if failed' },

  'risk.rule_id': { key: 'risk.rule_id', label: 'Rule', unit: 'text', freshness_s: 0, min_role: 'admin', source_endpoint: '/api/v2/admin/risk/rules', description: 'Risk rule identifier' },
  'risk.status': { key: 'risk.status', label: 'Decision', unit: 'enum', freshness_s: 10, min_role: 'admin', source_endpoint: '/api/v2/admin/risk/rules', description: 'allow | block | warn | unknown' },
  'risk.threshold': { key: 'risk.threshold', label: 'Threshold', unit: 'text', freshness_s: 0, min_role: 'admin', source_endpoint: '/api/v2/admin/risk/rules', description: 'Configured threshold value' },
  'risk.current_value': { key: 'risk.current_value', label: 'Current', unit: 'text', freshness_s: 10, min_role: 'admin', source_endpoint: '/api/v2/admin/risk/rules', description: 'Live measured value' },
  'risk.block_count': { key: 'risk.block_count', label: 'Blocks', unit: 'count', freshness_s: 10, min_role: 'admin', source_endpoint: '/api/v2/admin/risk/rules', description: 'Total block decisions' },
  'risk.last_decision_at': { key: 'risk.last_decision_at', label: 'Last Decision', unit: 'timestamp', freshness_s: 10, min_role: 'admin', source_endpoint: '/api/v2/admin/risk/rules', description: 'Timestamp of most recent risk decision' },

  'trader.id': { key: 'trader.id', label: 'Trader ID', unit: 'text', freshness_s: 0, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'Trader bot identifier' },
  'trader.mode': { key: 'trader.mode', label: 'Mode', unit: 'enum', freshness_s: 15, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'paper | live | replay | backtest' },
  'trader.status': { key: 'trader.status', label: 'Status', unit: 'enum', freshness_s: 15, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'active | idle | error | stopped' },
  'trader.heartbeat_at': { key: 'trader.heartbeat_at', label: 'Last Heartbeat', unit: 'timestamp', freshness_s: 15, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'Last trader heartbeat' },
  'trader.position_count': { key: 'trader.position_count', label: 'Positions', unit: 'count', freshness_s: 15, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'Open position count' },
  'trader.order_count': { key: 'trader.order_count', label: 'Orders', unit: 'count', freshness_s: 15, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'Open order count' },
  'trader.pnl': { key: 'trader.pnl', label: 'PnL', unit: 'usd', freshness_s: 15, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'Realized + unrealized PnL' },
  'trader.risk_status': { key: 'trader.risk_status', label: 'Risk', unit: 'enum', freshness_s: 10, min_role: 'admin', source_endpoint: '/api/v2/admin/traders', description: 'ok | warn | blocked' },
};

// Display format helpers

export function formatFieldValue(
  fieldKey: string,
  value: unknown,
): string {
  const def = ADMIN_FIELD_REGISTRY[fieldKey];
  if (value == null) return '—';
  switch (def?.unit) {
    case 'ms': return `${Number(value).toLocaleString()} ms`;
    case 'count': return Number(value).toLocaleString();
    case 'usd': return `$${Number(value).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
    case 'percent': return `${Number(value).toFixed(1)}%`;
    case 'records_per_min': return `${Number(value).toLocaleString()} /min`;
    case 'timestamp': return relativeAge(String(value));
    default: return String(value);
  }
}

export function relativeAge(iso: string | null | undefined): string {
  if (!iso) return '—';
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 0) return '0s';
  if (diff < 60_000) return `${Math.floor(diff / 1000)}s ago`;
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

export function statusColor(status: ServiceStatus | SourceStatus | RiskStatus | TraderRiskStatus | JobStatus | IncidentSeverity | string): string {
  switch (status) {
    case 'ok': case 'allow': case 'active': case 'complete': return 'var(--ok)';
    case 'warn': case 'running': case 'queued': return 'var(--warn)';
    case 'error': case 'block': case 'failed': case 'critical': return 'var(--error)';
    case 'gap': case 'blocked': case 'high': return 'var(--error)';
    case 'medium': return 'var(--warn)';
    case 'low': return 'var(--text-secondary)';
    default: return 'var(--text-muted)';
  }
}

export function statusBg(status: string): string {
  switch (status) {
    case 'ok': case 'allow': case 'active': case 'complete': return 'var(--buy-bg)';
    case 'warn': case 'running': case 'queued': case 'medium': return 'color-mix(in oklch, var(--warn) 12%, transparent)';
    case 'error': case 'block': case 'failed': case 'critical': case 'high': case 'gap': case 'blocked': return 'var(--sell-bg)';
    default: return 'var(--bg-elevated)';
  }
}
