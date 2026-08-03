import type { DataQualityStatus, FreshnessStatus, SourceType } from './dataContract';

export type CanonicalTraderPage =
  | 'account-settings'
  | 'dashboard'
  | 'portfolio'
  | 'positions'
  | 'executions'
  | 'history'
  | 'markets'
  | 'market-detail'
  | 'trade'
  | 'derivatives'
  | 'signals'
  | 'ai-predictions'
  | 'backtests'
  | 'replay'
  | 'research'
  | 'technical-analysis'
  | 'alerts';

export type CanonicalRoleVisibility = 'trader' | 'admin' | 'superadmin';

export type CanonicalFieldType =
  | 'string'
  | 'number'
  | 'integer'
  | 'decimal'
  | 'enum'
  | 'boolean'
  | 'timestamp'
  | 'array'
  | 'object';

export type CanonicalFieldUnit =
  | 'none'
  | 'usd'
  | 'base_asset'
  | 'quote_asset'
  | 'contract'
  | 'percent'
  | 'basis_points'
  | 'ratio'
  | 'count'
  | 'milliseconds'
  | 'timestamp'
  | 'symbol'
  | 'side'
  | 'status'
  | 'id'
  | 'text';

export type CanonicalNullBehavior =
  | 'allowed_when_source_missing'
  | 'allowed_when_not_applicable'
  | 'blocked_for_required_display';

export type CanonicalFormatter =
  | 'identity'
  | 'id'
  | 'symbol'
  | 'enumStatus'
  | 'side'
  | 'usd'
  | 'price'
  | 'quantity'
  | 'percent'
  | 'basisPoints'
  | 'ratio'
  | 'integer'
  | 'timestamp'
  | 'ageMs'
  | 'text'
  | 'jsonList';

export type CanonicalFreshness =
  | { kind: 'static' }
  | { kind: 'realtime'; threshold_ms: number }
  | { kind: 'session'; threshold_ms: number }
  | { kind: 'account_refresh'; threshold_ms: number };

export interface CanonicalFieldDefinition {
  id: string;
  label: string;
  canonicalType: CanonicalFieldType;
  unit: CanonicalFieldUnit;
  decimalPrecision: number | null;
  nullBehavior: CanonicalNullBehavior;
  zeroIsValid: boolean;
  preferredSource: string;
  fallbackSource: string | null;
  freshness: CanonicalFreshness;
  displayFormatter: CanonicalFormatter;
  roleVisibility: CanonicalRoleVisibility[];
  pages: CanonicalTraderPage[];
  description: string;
}

export interface TraderSnapshotSectionMeta {
  source: string;
  source_type: SourceType;
  source_id: string | null;
  timestamp: string | null;
  received_at: string | null;
  sequence: number | null;
  lag_ms: number | null;
  freshness: FreshnessStatus;
  quality: DataQualityStatus;
  missing_fields: string[];
  warnings: string[];
}

export interface CanonicalAccountSnapshot {
  trader_id: string | null;
  account_id: string | null;
  mode: string | null;
  connection_status: string | null;
  equity: number | null;
  available_balance: number | null;
  used_balance: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  daily_pnl: number | null;
  total_pnl: number | null;
  exposure: number | null;
  drawdown: number | null;
  open_position_count: number | null;
  open_order_count: number | null;
  execution_count: number | null;
}

export interface CanonicalPositionSnapshot {
  id: string;
  symbol: string | null;
  side: string | null;
  quantity: number | null;
  entry_price: number | null;
  entry_price_source: string | null;
  mark_price: number | null;
  mark_price_source: string | null;
  mark_age_ms: number | null;
  exit_price: number | null;
  exit_price_source: string | null;
  notional: number | null;
  unrealized_pnl: number | null;
  realized_pnl: number | null;
  pnl_percent: number | null;
  stop: number | null;
  targets: number[];
  liquidation_price: number | null;
  strategy_id: string | null;
  signal_id: string | null;
  prediction_id: string | null;
  risk_status: string | null;
  decision_reasoning: string | null;
  updated_at: string | null;
}

export interface CanonicalMarketSnapshot {
  symbol: string;
  last_price: number | null;
  mark_price: number | null;
  index_price: number | null;
  change_1h: number | null;
  change_4h: number | null;
  change_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  turnover_24h: number | null;
  spread: number | null;
  funding_rate: number | null;
  predicted_funding: number | null;
  open_interest: number | null;
  oi_change_1h: number | null;
  oi_change_4h: number | null;
  oi_change_24h: number | null;
  liquidations_1h: number | null;
  liquidations_24h: number | null;
  long_short_ratio: number | null;
}

export interface CanonicalSignalSnapshot {
  id: string;
  symbol: string | null;
  direction: string | null;
  timeframe: string | null;
  entry: number | null;
  targets: number[];
  stop: number | null;
  invalidation: number | null;
  confidence: number | null;
  expected_move: number | null;
  risk_reward: number | null;
  status: string | null;
  strategy: string | null;
  model_version: string | null;
  risk_decision: string | null;
  created_at: string | null;
  expires_at: string | null;
  evidence: unknown[];
}

export interface TraderSnapshotSection<T> {
  meta: TraderSnapshotSectionMeta;
  data: T;
}

export interface TraderSnapshot {
  account: TraderSnapshotSection<CanonicalAccountSnapshot>;
  portfolio: TraderSnapshotSection<Record<string, unknown>>;
  positions: TraderSnapshotSection<CanonicalPositionSnapshot[]>;
  orders: TraderSnapshotSection<unknown[]>;
  executions: TraderSnapshotSection<unknown[]>;
  history: TraderSnapshotSection<unknown[]>;
  signals: TraderSnapshotSection<CanonicalSignalSnapshot[]>;
  predictions: TraderSnapshotSection<unknown[]>;
  risk: TraderSnapshotSection<Record<string, unknown>>;
  market_status: TraderSnapshotSection<CanonicalMarketSnapshot[]>;
  automation_status: TraderSnapshotSection<Record<string, unknown>>;
  execution_status: TraderSnapshotSection<Record<string, unknown>>;
  data_status: TraderSnapshotSection<Record<string, unknown>>;
}
