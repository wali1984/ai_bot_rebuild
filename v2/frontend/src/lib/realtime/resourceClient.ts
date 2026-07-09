export type EnterpriseResourceName =
  | 'dashboard'
  | 'markets'
  | 'ai_brain'
  | 'risk'
  | 'portfolio'
  | 'providers'
  | 'system_health'
  | 'trader_cockpit';

export interface EnterpriseUiSnapshot<T = unknown> {
  schema_version: 'enterprise_ui_snapshot_v1';
  resource: EnterpriseResourceName;
  generated_utc: string;
  display_time_et: string;
  source_timezone: 'UTC';
  display_timezone: 'America/New_York';
  source: string;
  source_type: string;
  source_keys: string[];
  staleness_seconds: number | null;
  data_quality: 'valid' | 'partial' | 'invalid' | string;
  missing_sections: string[];
  error_sections: string[];
  last_good_payload_used: boolean;
  payload: T;
  live_gate: string;
  paper_only: boolean;
  routes_to_live: boolean;
  places_real_order: boolean;
}

export interface EnterpriseRealtimeBootstrap {
  schema_version: 'enterprise_realtime_bootstrap_v1';
  generated_utc: string;
  display_time_et?: string;
  display_timezone: 'America/New_York';
  source: string;
  auth: Record<string, unknown>;
  portfolio: Record<string, unknown>;
  paper: Record<string, unknown>;
  risk: Record<string, unknown>;
  trainer: Record<string, unknown>;
  signals: Record<string, unknown>;
  providers: Record<string, unknown>;
  ingestors: Record<string, unknown>;
  markets: Record<string, unknown>;
  live_canary: Record<string, unknown>;
  alerts: Record<string, unknown>;
  ui_hints: Record<string, unknown>;
  resources: Partial<Record<EnterpriseResourceName, EnterpriseUiSnapshot>>;
  live_gate: string;
  paper_only: boolean;
  routes_to_live: boolean;
  places_real_order: boolean;
}

export type EnterpriseRealtimeFrame =
  | {
      type: 'bootstrap';
      sequence: number;
      generated_utc: string;
      display_time_et: string;
      payload: EnterpriseRealtimeBootstrap;
    }
  | {
      type: 'resource_delta';
      resource: EnterpriseResourceName;
      sequence: number;
      generated_utc: string;
      display_time_et: string;
      payload: EnterpriseUiSnapshot;
    }
  | {
      type: 'resource_path_delta';
      path: string;
      sequence: number;
      generated_utc: string;
      display_time_et: string;
      payload: Record<string, unknown>;
    };

export async function fetchRealtimeBootstrap(signal?: AbortSignal): Promise<EnterpriseRealtimeBootstrap> {
  const response = await fetch('/api/v2/realtime/bootstrap', {
    credentials: 'include',
    headers: { Accept: 'application/json' },
    signal,
  });
  if (!response.ok) {
    throw new Error(`realtime_bootstrap_http_${response.status}`);
  }
  return response.json() as Promise<EnterpriseRealtimeBootstrap>;
}

export function realtimeWebSocketUrl(
  resources?: EnterpriseResourceName[],
  intervalMs = 2_000,
  readonlyPaths?: string[],
  readonlyPathIntervalMs = 15_000,
): string | null {
  if (typeof window === 'undefined') return null;
  const url = new URL('/api/v2/realtime/ws', window.location.origin);
  url.protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  url.searchParams.set('interval_ms', String(intervalMs));
  if (resources?.length) {
    url.searchParams.set('resources', resources.join(','));
  }
  if (readonlyPaths?.length) {
    for (const path of readonlyPaths) {
      url.searchParams.append('path', path);
    }
    url.searchParams.set('path_interval_ms', String(readonlyPathIntervalMs));
  }
  return url.toString();
}
