export type ApiV2SourceType = 'api' | 'repository' | 'redis_live' | 'static_payload' | 'unavailable';
export type ApiV2Mode = 'paper' | 'read_only' | 'live_blocked' | 'paper_preview_unverified';

export interface TraderContext {
  scope: 'public_read_only' | 'authenticated_trader';
  trader_id: string | null;
  paper_account_id: string | null;
  username: string | null;
  exchange_accounts: Array<Record<string, unknown>>;
  account_specific: boolean;
  warnings: string[];
}

export interface AccountScopeProof {
  scope: 'public_read_only' | 'authenticated_trader' | string | null;
  trader_id: string | null;
  paper_account_id: string | null;
  data_trader_id?: string | null;
  data_paper_account_id?: string | null;
  authenticated: boolean;
  actor_scope_present: boolean;
  data_account_specific: boolean;
  data_scope_matches_actor?: boolean;
  scope_verified: boolean;
  live_trading_enabled: false;
  exchange_mutation_enabled: false;
  warnings: string[];
}

export interface ApiV2Envelope<T> {
  data: T | null;
  source: string;
  source_type: ApiV2SourceType;
  endpoint: string;
  timestamp: string | null;
  received_at: string;
  lag_ms: number | null;
  stale: boolean;
  missing_fields: string[];
  warnings: string[];
  symbol?: string | null;
  exchange?: string | null;
  mode: ApiV2Mode;
  trader_context?: TraderContext | null;
  account_scope?: AccountScopeProof | null;
}

export interface MarketTickerData {
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
  funding_rate: number | null;
  next_funding: string | null;
  open_interest: number | null;
  open_interest_change: number | null;
  bid: number | null;
  ask: number | null;
  spread_bps: number | null;
}

export interface MarketCandle {
  time?: number;
  open_time_ms?: number;
  close_time_ms?: number;
  open?: number;
  high?: number;
  low?: number;
  close?: number;
  volume?: number;
  quote_volume?: number | null;
  trade_count?: number | null;
  taker_buy_base_volume?: number | null;
  taker_buy_quote_volume?: number | null;
  is_final?: boolean;
  source?: string;
}

export interface MarketCandlesData {
  symbol: string;
  timeframe: string;
  candles: MarketCandle[];
  candle_count: number;
}

export interface MarketIndicatorPoint {
  time?: number | string;
  value?: number | null;
}

export interface MarketIndicatorsData {
  symbol: string;
  timeframe: string;
  ema20: MarketIndicatorPoint[];
  ema50: MarketIndicatorPoint[];
  bb_upper: MarketIndicatorPoint[];
  bb_lower: MarketIndicatorPoint[];
  bb_middle: MarketIndicatorPoint[];
  ai_target: MarketIndicatorPoint[];
  indicator_count: number;
  controls_enabled: boolean;
}

export interface MarketDepthData {
  symbol: string;
  bids: Array<[number | null, number | null]>;
  asks: Array<[number | null, number | null]>;
  spread_bps: number | null;
  depth_type?: string;
}

export interface RecentTradeData {
  time: string;
  price: number;
  size: number;
  side: 'buy' | 'sell';
}

export interface RecentTradesData {
  symbol: string;
  trades: RecentTradeData[];
}

export interface MarketDerivativesData {
  symbol: string;
  funding_rate: number | null;
  next_funding: string | null;
  open_interest: number | null;
  open_interest_change: number | null;
  funding_history: Array<Record<string, unknown>>;
  open_interest_history: Array<Record<string, unknown>>;
  liquidations_1h: number | null;
  liquidations_24h: number | null;
  liquidation_stream_status?: {
    status: string;
    source: string;
    symbol: string;
    stream_active: boolean;
    symbol_in_stream?: boolean;
    events_available: boolean;
    events_xlen?: number | null;
    levels_available: boolean;
    timestamp?: string | null;
    lag_ms?: number | null;
    stale?: boolean;
    live_trading_enabled: false;
    exchange_mutation_enabled: false;
  } | null;
  liquidation_levels?: {
    symbol: string;
    long_level: number | null;
    short_level: number | null;
    long_distance_pct: number | null;
    short_distance_pct: number | null;
    source: string;
    timestamp: string | null;
  } | null;
  long_short_ratio: number | null;
  basis: number | null;
  exchange_comparison: Array<Record<string, unknown>>;
  production_source_validation?: {
    configured: boolean;
    valid: boolean;
    status: string;
    funding_realtime_verified?: boolean;
    open_interest_realtime_verified?: boolean;
    liquidation_source_verified?: boolean;
    long_short_source_verified?: boolean;
    basis_source_verified?: boolean;
    exchange_comparison_verified?: boolean;
    freshness_enforced?: boolean;
    stale_marking_verified?: boolean;
    source_labels_verified?: boolean;
    no_static_presented_as_live?: boolean;
    fake_live_data_detected?: boolean;
    live_trading_enabled: boolean;
    exchange_mutation_enabled: boolean;
    live_submit_available?: boolean;
    live_cancel_available?: boolean;
    missing_fields: string[];
    warnings: string[];
  };
}

export interface MarketStreamStatusData {
  symbol: string;
  source: string;
  last_event: string | null;
  last_frame_at: string | null;
  last_error: string | null;
  connect_attempts: number;
  native_frames: number;
  fallback_snapshots: number;
  updated_at: string | null;
  lag_ms: number | null;
  stale: boolean;
}

export interface AlertItem {
  id: string;
  trader_id?: string | null;
  paper_account_id?: string | null;
  alert_type: string;
  symbol: string;
  condition: string;
  threshold?: number | null;
  enabled: boolean;
  muted: boolean;
  delivery_enabled: boolean;
  delivery_status: string;
  audit_event_count?: number;
  created_at?: string;
  updated_at?: string;
}

export interface AlertsData {
  alerts: AlertItem[];
  supported_alert_types: string[];
  preferences: Record<string, unknown> | null;
  delivery_channels: unknown[];
  create_enabled: boolean;
  edit_enabled: boolean;
  mute_enabled: boolean;
  delivery_enabled: boolean;
  audit_logging_enabled: boolean;
  repository_status?: string;
  delivery_status?: string;
  last_action?: Record<string, unknown>;
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
}

export interface PortfolioData {
  equity: number | null;
  realized_pnl: number | null;
  unrealized_pnl: number | null;
  positions: unknown[];
  mode: 'paper';
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
}

export interface PositionsData {
  positions: unknown[];
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
}

export interface AccountReadinessData {
  trader_id: string | null;
  paper_account_id: string | null;
  account_scope: 'public_read_only' | 'authenticated_trader';
  account_specific: boolean;
  account_present: boolean;
  repository_status: string;
  repository_kind: string;
  tenant_isolation_status: string;
  unique_paper_account_scope: boolean;
  paper_account_uniqueness_enforced: boolean;
  trader_scope_required: boolean;
  production_repository: boolean;
  durable_database_repository: boolean;
  production_writer_validation: string;
  migration_status: string;
  backup_restore_status: string;
  retention_policy_status: string;
  trader_account_scope_smoke_status: string;
  trader_account_scope_smoke_artifact_valid: boolean;
  production_trader_repository_smoke_status: string;
  production_trader_repository_smoke_artifact_valid: boolean;
  supported_local_domains: string[];
  contains_credentials: false;
  live_trading_enabled: false;
  exchange_mutation_enabled: false;
}

export interface ExchangeReadOnlyAccountData {
  trader_id: string | null;
  paper_account_id: string | null;
  exchange_account_id: string | null;
  exchange: string | null;
  account_type: string | null;
  account_specific: boolean;
  read_only: boolean;
  live_trading_enabled: false;
  account_snapshot: {
    total_wallet_balance?: number | null;
    available_balance?: number | null;
    total_unrealized_profit?: number | null;
    total_margin_balance?: number | null;
    total_maint_margin?: number | null;
    maintenance_margin_ratio_pct?: number | null;
    can_trade?: boolean | null;
  } | null;
  positions: Array<Record<string, unknown>>;
  positions_count: number;
  trade_permission_status: string;
  margin_mode_evidence: unknown;
  leverage_evidence: unknown;
  credential_status?: {
    configured: boolean;
    raw_credential_value_exposed: false;
    live_trading_enabled: false;
  };
}

export interface OrdersData {
  orders?: unknown[];
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
}

export interface ExecutionsData {
  executions?: unknown[];
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
}

export interface AuditEventsData {
  audit_events?: unknown[];
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
  audit_policy?: {
    audit_chain_version?: string;
    tamper_evident?: boolean;
    retention_policy?: string;
    retention_limit?: number;
    event_count?: number;
    durability?: string;
    production_durable_store?: boolean;
    live_mutation_prohibited?: boolean;
  };
  audit_ledger?: {
    ledger_kind?: string;
    append_only_local_file?: boolean;
    event_count?: number;
    path_configured?: boolean;
    production_durable_store?: boolean;
    live_mutation_prohibited?: boolean;
  };
  audit_ledger_events?: unknown[];
}

export interface SignalData {
  active_signal?: Record<string, unknown> | null;
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  account_specific?: boolean;
}

export interface OrderPreviewRequest {
  symbol: string;
  side: 'buy' | 'sell';
  order_type: 'market' | 'limit' | 'stop';
  quantity: number;
  price?: number | null;
  stop_price?: number | null;
  reduce_only?: boolean | null;
  take_profit?: number | null;
  stop_loss?: number | null;
  trader_id?: string | null;
  paper_account_id?: string | null;
  mode: 'paper' | 'read_only' | 'live';
}

export interface PaperExecutionPolicy {
  status?: string;
  mode?: 'paper';
  account_scope?: string;
  submit_policy: string;
  fill_policy: string;
  manual_fill_policy?: string;
  execution_policy: string;
  cancel_policy: string;
  local_paper_repository_enabled?: boolean;
  local_paper_staging_enabled?: boolean;
  local_paper_cancel_enabled?: boolean;
  local_manual_fill_enabled?: boolean;
  auto_fill_enabled?: boolean;
  verified_production_paper_submit_cancel?: boolean;
  verified_paper_execution_service?: boolean;
  production_environment?: boolean;
  production_paper_actions_enabled?: boolean;
  production_paper_actions_status?: string;
  local_paper_actions_allowed_in_production?: boolean;
  production_requires_verified_paper_execution_service?: boolean;
  product_decision?: string;
  production_validation_status?: string;
  durable_audit_policy_status?: string;
  durable_repository_enabled?: boolean;
  requires_authenticated_trader_scope?: boolean;
  requires_backend_owned_order_id?: boolean;
  live_transport_enabled: false;
  exchange_mutation_enabled: false;
  real_order_submission_enabled?: false;
  live_order_cancel_enabled?: false;
  leverage_mutation_enabled?: false;
  margin_mode_mutation_enabled?: false;
  live_gate_mutation_enabled?: false;
  contains_exchange_credentials?: false;
  missing_fields?: string[];
  warnings?: string[];
}

export interface OrderPreviewData {
  allowed: boolean;
  mode: ApiV2Mode;
  reason: string;
  friendly_reason: string;
  estimated_notional: number | null;
  estimated_fee: number | null;
  estimated_margin: number | null;
  available_paper_balance: number | null;
  trader_id?: string | null;
  paper_account_id?: string | null;
  account_scope?: 'public_read_only' | 'authenticated_trader';
  paper_execution_policy?: PaperExecutionPolicy;
  risk_checks: Array<{ name: string; passed: boolean }>;
}

export interface PaperOrderActionData {
  accepted: boolean;
  order: Record<string, unknown> | null;
  execution?: Record<string, unknown> | null;
  reason: string;
  friendly_reason: string;
  trader_id?: string | null;
  paper_account_id?: string | null;
  paper_execution_policy?: PaperExecutionPolicy;
}
