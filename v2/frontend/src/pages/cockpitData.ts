import { useEffect, useState } from 'react';

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

const cockpitPayloadPath = '/enterprise_trading_cockpit/latest/operator_cockpit_payload.json';
const quarantinePayloadPath = '/external_manual_position_quarantine/latest/operator_dashboard_payload.json';
const readonlyDataPlanePayloadPath = '/readonly_market_exchange_data_plane/latest/operator_dashboard_payload.json';
const systemAtlasPayloadPath = '/system_atlas_runtime_coverage/latest/operator_dashboard_payload.json';
const systemAtlasGapRemediationPayloadPath = '/system_atlas_gap_remediation/latest/operator_dashboard_payload.json';

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

export function useCockpitPayload(): {
  payload: CockpitPayload | null;
  quarantine: QuarantinePayload | null;
  systemAtlas: SystemAtlasPayload | null;
  systemAtlasGapRemediation: SystemAtlasGapRemediationPayload | null;
  error: string | null;
} {
  const [payload, setPayload] = useState<CockpitPayload | null>(null);
  const [quarantine, setQuarantine] = useState<QuarantinePayload | null>(null);
  const [systemAtlas, setSystemAtlas] = useState<SystemAtlasPayload | null>(null);
  const [systemAtlasGapRemediation, setSystemAtlasGapRemediation] = useState<SystemAtlasGapRemediationPayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchJson<CockpitPayload>(cockpitPayloadPath)
      .then(async (next) => {
        const readonlyPayload = await fetchJson<ReadonlyDataPlanePayload>(readonlyDataPlanePayloadPath).catch(() => null);
        if (active) setPayload(readonlyPayload ? mergeReadonlyDataPlane(next, readonlyPayload) : next);
      })
      .catch((err: unknown) => {
        if (active) setError(err instanceof Error ? err.message : 'cockpit payload unavailable');
      });
    fetchJson<QuarantinePayload>(quarantinePayloadPath)
      .then((next) => {
        if (active) setQuarantine(next);
      })
      .catch(() => {
        if (active) setQuarantine(null);
      });
    fetchJson<SystemAtlasPayload>(systemAtlasPayloadPath)
      .then((next) => {
        if (active) setSystemAtlas(next);
      })
      .catch(() => {
        if (active) setSystemAtlas(null);
      });
    fetchJson<SystemAtlasGapRemediationPayload>(systemAtlasGapRemediationPayloadPath)
      .then((next) => {
        if (active) setSystemAtlasGapRemediation(next);
      })
      .catch(() => {
        if (active) setSystemAtlasGapRemediation(null);
      });
    return () => {
      active = false;
    };
  }, []);

  return { payload, quarantine, systemAtlas, systemAtlasGapRemediation, error };
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
        value: readonlyPayload.feed_health.source_type,
        detail: readonlyPayload.feed_health.errors.length ? readonlyPayload.feed_health.errors.join(', ') : 'Read-only feed path active or fixture fallback explicit',
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
  return String(value);
}

export function statusClass(value: unknown): string {
  const normalized = String(value).toLowerCase();
  if (normalized.includes('fresh') || normalized.includes('ready') || normalized.includes('allow') || normalized === 'true') return 'cockpit-pill cockpit-pill--ok';
  if (normalized.includes('blocked') || normalized.includes('deny') || normalized.includes('stale') || normalized.includes('missing')) return 'cockpit-pill cockpit-pill--bad';
  if (normalized.includes('warn') || normalized.includes('human') || normalized.includes('static')) return 'cockpit-pill cockpit-pill--warn';
  return 'cockpit-pill';
}
