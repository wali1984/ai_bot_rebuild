import { useEffect, useState } from 'react';

export interface Freshness {
  data_source: string;
  generated_at: string;
  last_event_at: string;
  age_seconds: number;
  freshness_state: 'fresh' | 'warn' | 'stale' | 'missing';
  source_pointer: string;
  evidence_link: string;
  mode: 'STATIC_PROOF_FIXTURE' | 'CONTINUOUS_NON_LIVE' | 'EVIDENCE_GAP';
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

const cockpitPayloadPath = '/enterprise_trading_cockpit/latest/operator_cockpit_payload.json';
const quarantinePayloadPath = '/external_manual_position_quarantine/latest/operator_dashboard_payload.json';

async function fetchJson<T>(path: string): Promise<T> {
  const response = await fetch(path, { cache: 'no-store' });
  if (!response.ok) throw new Error(`${path}: ${response.status}`);
  return response.json() as Promise<T>;
}

export function useCockpitPayload(): {
  payload: CockpitPayload | null;
  quarantine: QuarantinePayload | null;
  error: string | null;
} {
  const [payload, setPayload] = useState<CockpitPayload | null>(null);
  const [quarantine, setQuarantine] = useState<QuarantinePayload | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetchJson<CockpitPayload>(cockpitPayloadPath)
      .then((next) => {
        if (active) setPayload(next);
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
    return () => {
      active = false;
    };
  }, []);

  return { payload, quarantine, error };
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
