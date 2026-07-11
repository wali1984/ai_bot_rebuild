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
  last_known_good_restored?: boolean;
  last_known_good_cached_at?: string;
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
  staleness_seconds?: number | null;
  freshness_status?: string;
  data_quality_status?: string;
  last_known_good_restored?: boolean;
  last_known_good_cached_at?: string;
}

const BOOTSTRAP_SESSION_CACHE_KEY = 'ai_bot_v2.enterprise_realtime.bootstrap.lkg.v1';
const BOOTSTRAP_SESSION_CACHE_MAX_AGE_MS = 10 * 60 * 1000;

type CachedRealtimeBootstrap = {
  schema_version: 'enterprise_realtime_bootstrap_session_cache_v1';
  stored_at_ms: number;
  payload: EnterpriseRealtimeBootstrap;
};

function sessionStorageOrNull(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    const storage = window.sessionStorage;
    const probe = '__ai_bot_v2_realtime_probe__';
    storage.setItem(probe, '1');
    storage.removeItem(probe);
    return storage;
  } catch {
    return null;
  }
}

function isSafeReadonlyBootstrap(payload: EnterpriseRealtimeBootstrap): boolean {
  return payload.schema_version === 'enterprise_realtime_bootstrap_v1'
    && payload.live_gate === 'blocked_human_only'
    && payload.routes_to_live === false
    && payload.places_real_order === false;
}

function cachedSnapshot<T>(
  snapshot: EnterpriseUiSnapshot<T>,
  storedAtMs: number,
  nowMs: number,
): EnterpriseUiSnapshot<T> {
  const ageSeconds = Math.max(
    Number(snapshot.staleness_seconds ?? 0) || 0,
    Math.round((nowMs - storedAtMs) / 1000),
  );
  return {
    ...snapshot,
    source_type: 'cache',
    staleness_seconds: ageSeconds,
    last_good_payload_used: true,
    missing_sections: [...new Set([...(snapshot.missing_sections ?? []), 'session_last_known_good'])],
    last_known_good_restored: true,
    last_known_good_cached_at: new Date(storedAtMs).toISOString(),
  };
}

function cachedBootstrap(payload: EnterpriseRealtimeBootstrap, storedAtMs: number, nowMs: number): EnterpriseRealtimeBootstrap {
  const ageSeconds = Math.max(
    Number(payload.staleness_seconds ?? 0) || 0,
    Math.round((nowMs - storedAtMs) / 1000),
  );
  const resources = Object.fromEntries(
    Object.entries(payload.resources ?? {}).map(([resource, snapshot]) => [
      resource,
      cachedSnapshot(snapshot as EnterpriseUiSnapshot, storedAtMs, nowMs),
    ]),
  ) as Partial<Record<EnterpriseResourceName, EnterpriseUiSnapshot>>;

  return {
    ...payload,
    source: `${payload.source}:session_last_known_good`,
    resources,
    staleness_seconds: ageSeconds,
    freshness_status: 'stale',
    data_quality_status: payload.data_quality_status ?? 'partial',
    last_known_good_restored: true,
    last_known_good_cached_at: new Date(storedAtMs).toISOString(),
  };
}

export function loadCachedRealtimeBootstrap(nowMs = Date.now()): EnterpriseRealtimeBootstrap | null {
  const storage = sessionStorageOrNull();
  if (!storage) return null;
  try {
    const raw = storage.getItem(BOOTSTRAP_SESSION_CACHE_KEY);
    if (!raw) return null;
    const cached = JSON.parse(raw) as CachedRealtimeBootstrap;
    if (cached.schema_version !== 'enterprise_realtime_bootstrap_session_cache_v1') return null;
    if (!Number.isFinite(cached.stored_at_ms)) return null;
    if (nowMs - cached.stored_at_ms > BOOTSTRAP_SESSION_CACHE_MAX_AGE_MS) {
      storage.removeItem(BOOTSTRAP_SESSION_CACHE_KEY);
      return null;
    }
    if (!isSafeReadonlyBootstrap(cached.payload)) return null;
    return cachedBootstrap(cached.payload, cached.stored_at_ms, nowMs);
  } catch {
    storage.removeItem(BOOTSTRAP_SESSION_CACHE_KEY);
    return null;
  }
}

export function saveCachedRealtimeBootstrap(payload: EnterpriseRealtimeBootstrap, nowMs = Date.now()): void {
  const storage = sessionStorageOrNull();
  if (!storage || !isSafeReadonlyBootstrap(payload)) return;
  const cached: CachedRealtimeBootstrap = {
    schema_version: 'enterprise_realtime_bootstrap_session_cache_v1',
    stored_at_ms: nowMs,
    payload,
  };
  try {
    storage.setItem(BOOTSTRAP_SESSION_CACHE_KEY, JSON.stringify(cached));
  } catch {
    // Browser storage may be unavailable or full; realtime transport still works without cache.
  }
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

export async function fetchRealtimeBootstrap(): Promise<EnterpriseRealtimeBootstrap> {
  const response = await fetch('/api/v2/realtime/bootstrap', {
    credentials: 'include',
    headers: { Accept: 'application/json' },
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
