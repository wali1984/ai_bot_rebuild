import { useCallback, useEffect, useRef, useState } from 'react';
import { useOptionalEnterpriseRealtime } from '../lib/realtime/RealtimeProvider';
import type { ValidatedDataEnvelope, SourceType, DataQualityStatus } from '../types/dataContract';
import { makeEmptyEnvelope } from '../types/dataContract';

export interface RealtimeResourceOptions<T> {
  url: string;
  source: string;
  source_type?: SourceType;
  pollIntervalMs?: number;
  staleThresholdMs?: number;
  transform?: (raw: unknown) => T;
  enabled?: boolean;
  initialFetch?: boolean;
  initialFetchWhenStreaming?: boolean;
  httpFallback?: boolean;
  requestTimeoutMs?: number;
  mode?: ValidatedDataEnvelope<T>['mode'];
  unwrapEnvelopeData?: boolean | 'contract';
}

export interface RealtimeResourceResult<T> {
  envelope: ValidatedDataEnvelope<T>;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

const realtimeResourceCache = new Map<string, ValidatedDataEnvelope<unknown>>();
const RESOURCE_SESSION_CACHE_PREFIX = 'ai_bot_v2.realtime_resource.lkg.v1:';
const RESOURCE_SESSION_CACHE_MAX_AGE_MS = 10 * 60 * 1000;
const READONLY_STATIC_JSON_PREFIXES = [
  '/operator_runtime/',
  '/operator_truth/',
  '/operator_gui_real_data_and_explainability/',
  '/v2_',
  '/tonight_live_like_paper_shadow/',
  '/enterprise_trading_cockpit/',
  '/external_manual_position_quarantine/',
  '/readonly_market_exchange_data_plane/',
  '/system_atlas_runtime_coverage/',
  '/system_atlas_gap_remediation/',
  '/phase3c_runtime_monitor_verification/',
  '/redis_memory_pressure_remediation/',
  '/redis_memory_human_approval/',
  '/redis_export_capacity_remediation/',
  '/redis_liquidations_full_export/',
  '/historical_30d_replay_and_paper_proof/',
  '/redis_safe_trim_packet/',
  '/autonomous_governor/',
] as const;

type UnwrapShape = 'raw' | 'data';

function unwrapShapeOf(policy: boolean | 'contract' | undefined): UnwrapShape {
  // The cached envelope's data SHAPE depends on the unwrap policy:
  // policy false stores the whole contract envelope as data, while
  // true/'contract' store the unwrapped inner payload. Sharing one cache
  // entry across both policies poisons consumers with the wrong shape
  // (fields read undefined => permanently empty panels), so the shape is
  // part of the cache identity.
  return policy === false ? 'raw' : 'data';
}

function cacheKey(url: string, mode: ValidatedDataEnvelope<unknown>['mode'], shape: UnwrapShape): string {
  return `${mode}:${shape}:${url}`;
}

function sessionStorageOrNull(): Storage | null {
  if (typeof window === 'undefined') return null;
  try {
    const storage = window.sessionStorage;
    const probe = '__ai_bot_v2_resource_probe__';
    storage.setItem(probe, '1');
    storage.removeItem(probe);
    return storage;
  } catch {
    return null;
  }
}

function hashCacheKey(value: string): string {
  let hash = 0;
  for (let index = 0; index < value.length; index += 1) {
    hash = ((hash << 5) - hash + value.charCodeAt(index)) | 0;
  }
  return Math.abs(hash).toString(36);
}

function sessionCacheKey(url: string, mode: ValidatedDataEnvelope<unknown>['mode'], shape: UnwrapShape): string {
  return `${RESOURCE_SESSION_CACHE_PREFIX}${mode}:${shape}:${hashCacheKey(url)}:${encodeURIComponent(url).slice(0, 96)}`;
}

function displayableLastKnownEnvelope<T>(envelope: ValidatedDataEnvelope<T>): boolean {
  return envelope.data !== null
    && envelope.data !== undefined
    && envelope.source_type !== 'unavailable'
    && envelope.data_quality_status !== 'missing'
    && envelope.data_quality_status !== 'invalid';
}

function cachedForSessionRestore<T>(envelope: ValidatedDataEnvelope<T>, storedAt: number, now: number): ValidatedDataEnvelope<T> {
  return {
    ...envelope,
    source_type: 'cache',
    received_at: now,
    lag_ms: now - storedAt,
    freshness_status: 'stale',
    warnings: uniqueResourceWarnings(
      envelope.warnings,
      ['Session last-known-good payload restored while realtime transport reconnects'],
    ),
    errors: [],
  };
}

function restoreLastKnownResourceEnvelope<T>(
  url: string,
  mode: ValidatedDataEnvelope<T>['mode'],
  shape: UnwrapShape,
  now = Date.now(),
): ValidatedDataEnvelope<T> | null {
  const storage = sessionStorageOrNull();
  if (!storage) return null;
  const key = sessionCacheKey(url, mode, shape);
  try {
    const raw = storage.getItem(key);
    if (!raw) return null;
    const cached = JSON.parse(raw) as {
      schema_version?: string;
      stored_at_ms?: number;
      envelope?: ValidatedDataEnvelope<T>;
    };
    if (cached.schema_version !== 'realtime_resource_session_cache_v1') return null;
    const storedAtMs = cached.stored_at_ms;
    if (typeof storedAtMs !== 'number' || !Number.isFinite(storedAtMs)) return null;
    if (!cached.envelope || !displayableLastKnownEnvelope(cached.envelope)) return null;
    if (now - storedAtMs > RESOURCE_SESSION_CACHE_MAX_AGE_MS) {
      storage.removeItem(key);
      return null;
    }
    return cachedForSessionRestore(cached.envelope, storedAtMs, now);
  } catch {
    storage.removeItem(key);
    return null;
  }
}

function persistLastKnownResourceEnvelope<T>(
  url: string,
  mode: ValidatedDataEnvelope<T>['mode'],
  shape: UnwrapShape,
  envelope: ValidatedDataEnvelope<T>,
  now = Date.now(),
): void {
  if (!shouldCacheEnvelope(envelope)) return;
  const storage = sessionStorageOrNull();
  if (!storage) return;
  try {
    storage.setItem(sessionCacheKey(url, mode, shape), JSON.stringify({
      schema_version: 'realtime_resource_session_cache_v1',
      stored_at_ms: now,
      envelope,
    }));
  } catch {
    // Session cache is an operator UX optimization; resource fetches continue without it.
  }
}

function cachedEnvelope<T>(
  url: string,
  mode: ValidatedDataEnvelope<T>['mode'],
  shape: UnwrapShape,
): ValidatedDataEnvelope<T> | null {
  const memory = realtimeResourceCache.get(cacheKey(url, mode, shape)) as ValidatedDataEnvelope<T> | undefined;
  if (memory) return memory;
  const restored = restoreLastKnownResourceEnvelope<T>(url, mode, shape);
  if (restored) {
    realtimeResourceCache.set(cacheKey(url, mode, shape), restored);
  }
  return restored;
}

function shouldCacheEnvelope<T>(envelope: ValidatedDataEnvelope<T>): boolean {
  return envelope.data !== null
    && envelope.data !== undefined
    && envelope.source_type !== 'unavailable'
    && envelope.source_type !== 'static_payload'
    && envelope.source_type !== 'static_snapshot'
    && envelope.freshness_status !== 'stale'
    && envelope.freshness_status !== 'offline'
    && envelope.freshness_status !== 'unavailable'
    && envelope.data_quality_status !== 'missing'
    && envelope.data_quality_status !== 'invalid';
}

function uniqueResourceWarnings(...groups: string[][]): string[] {
  return [...new Set(groups.flat().filter(Boolean))];
}

function timestampToMs(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value) && value > 0) {
    return value < 1_000_000_000_000 ? Math.round(value * 1000) : Math.round(value);
  }
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function resourceFrameTimestampMs(raw: Record<string, unknown>, receivedAt: number): number {
  const candidates = [
    raw.timestamp,
    raw.received_at,
    raw.generated_at,
    raw.generated_utc,
    raw.updated_at,
  ];
  for (const value of candidates) {
    const parsed = timestampToMs(value);
    if (parsed !== null) return parsed;
  }
  return receivedAt;
}

export function mergeRealtimeResourceEnvelope<T>(
  previous: ValidatedDataEnvelope<T>,
  next: ValidatedDataEnvelope<T>,
): { envelope: ValidatedDataEnvelope<T>; shouldCache: boolean; preservedReason: 'stale_or_incomplete' | 'out_of_order' | null } {
  const previousUsable = shouldCacheEnvelope(previous);
  const nextUsable = shouldCacheEnvelope(next);
  const previousDisplayable = displayableLastKnownEnvelope(previous);
  const previousTimestamp = typeof previous.timestamp === 'number' ? previous.timestamp : null;
  const nextTimestamp = typeof next.timestamp === 'number' ? next.timestamp : null;

  if (
    previousUsable
    && nextUsable
    && previousTimestamp !== null
    && nextTimestamp !== null
    && nextTimestamp < previousTimestamp
  ) {
    return {
      envelope: {
        ...previous,
        received_at: next.received_at,
        lag_ms: next.lag_ms,
        warnings: uniqueResourceWarnings(
          previous.warnings,
          next.warnings,
          ['Latest resource frame was older than the current payload; preserving last current payload'],
        ),
        errors: next.errors,
      },
      shouldCache: false,
      preservedReason: 'out_of_order',
    };
  }

  if (!nextUsable && previousDisplayable) {
    return {
      envelope: {
        ...previous,
        received_at: next.received_at,
        lag_ms: next.lag_ms,
        warnings: uniqueResourceWarnings(
          previous.warnings,
          next.warnings,
          ['Latest resource frame was stale or incomplete; preserving last current payload'],
        ),
        errors: next.errors,
      },
      shouldCache: false,
      preservedReason: 'stale_or_incomplete',
    };
  }

  return { envelope: next, shouldCache: nextUsable, preservedReason: null };
}

function fetchTimeoutMs(pollIntervalMs: number, requestTimeoutMs?: number): number {
  if (typeof requestTimeoutMs === 'number' && Number.isFinite(requestTimeoutMs)) {
    return Math.min(60_000, Math.max(1_000, Math.floor(requestTimeoutMs)));
  }
  return Math.min(10_000, Math.max(4_000, Math.floor(pollIntervalMs * 0.8)));
}

function sharedStreamFallbackDelayMs(url: string, pollIntervalMs: number): number {
  let hash = 0;
  for (let i = 0; i < url.length; i += 1) {
    hash = (hash * 31 + url.charCodeAt(i)) % 997;
  }
  const base = Math.min(900, Math.max(250, Math.floor(pollIntervalMs * 0.04)));
  return base + (hash % 700);
}

function canUseReadonlyResourceStream(url: string): boolean {
  if (typeof window === 'undefined') return false;
  const path = url.split('?')[0] ?? url;
  const isApiResource = path.startsWith('/api/v2/') || path.startsWith('/api/v1/');
  const isStaticJsonResource = path.endsWith('.json') && READONLY_STATIC_JSON_PREFIXES.some((prefix) => path.startsWith(prefix));
  return isApiResource || isStaticJsonResource;
}

function computeFreshness(receivedAt: number, staleThresholdMs: number): ValidatedDataEnvelope<unknown>['freshness_status'] {
  const age = Date.now() - receivedAt;
  if (age < staleThresholdMs * 0.5) return 'fresh';
  if (age < staleThresholdMs) return 'delayed';
  return 'stale';
}

function computeQuality(data: unknown, missing: string[]): DataQualityStatus {
  if (data === null || data === undefined) return 'missing';
  if (missing.length > 0) return 'partial';
  return 'valid';
}

function hasContractEnvelopeMetadata(raw: Record<string, unknown>): boolean {
  return typeof raw.source_type === 'string'
    || typeof raw.source === 'string'
    || typeof raw.endpoint === 'string'
    || typeof raw.mode === 'string'
    || Array.isArray(raw.missing_fields)
    || Array.isArray(raw.warnings)
    || raw.transport === 'websocket'
    || typeof raw.resource_path === 'string';
}

function shouldUnwrapEnvelopeData(raw: Record<string, unknown>, policy: boolean | 'contract'): boolean {
  if (!('data' in raw) || raw.data === undefined) return false;
  if (policy === true) return true;
  if (policy === false) return false;
  return hasContractEnvelopeMetadata(raw);
}

export function useRealtimeResource<T>(
  opts: RealtimeResourceOptions<T>,
): RealtimeResourceResult<T> {
  const {
    url,
    source,
    source_type = 'api',
    pollIntervalMs = 15_000,
    staleThresholdMs = 30_000,
    transform,
    enabled = true,
    initialFetch = true,
    initialFetchWhenStreaming = false,
    httpFallback = true,
    requestTimeoutMs,
    mode = 'read_only',
    unwrapEnvelopeData = true,
  } = opts;
  const sharedRealtime = useOptionalEnterpriseRealtime();
  const subscribeResourcePath = sharedRealtime?.subscribeResourcePath;
  const unwrapShape = unwrapShapeOf(unwrapEnvelopeData);

  const [envelope, setEnvelope] = useState<ValidatedDataEnvelope<T>>(
    () => cachedEnvelope<T>(url, mode, unwrapShape) ?? makeEmptyEnvelope<T>(source, { source_type, mode }),
  );
  const [loading, setLoading] = useState(() => !cachedEnvelope<T>(url, mode, unwrapShape));
  const [error, setError] = useState<string | null>(null);
  const mountedRef = useRef(false);
  const resourceKeyRef = useRef(cacheKey(url, mode, unwrapShape));
  const inFlightRef = useRef<Set<AbortController>>(new Set());

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      inFlightRef.current.forEach(controller => controller.abort());
      inFlightRef.current.clear();
    };
  }, []);

  const applyRawEnvelope = useCallback((raw: Record<string, unknown>, receivedAt: number, lagMs: number, deliveredSourceType?: SourceType) => {
    const innerData = shouldUnwrapEnvelopeData(raw, unwrapEnvelopeData) ? raw.data as T : raw as unknown as T;
    const data: T = transform ? transform(innerData) : innerData;
    const backendMissing = Array.isArray(raw.missing_fields) ? raw.missing_fields as string[] : [];
    const backendWarnings = Array.isArray(raw.warnings) ? raw.warnings as string[] : [];
    const backendErrors = Array.isArray(raw.errors) ? raw.errors.map(String) : [];
    const backendSourceType = deliveredSourceType ?? (typeof raw.source_type === 'string' ? raw.source_type : source_type) as typeof source_type;
    const backendSource = typeof raw.source === 'string' ? raw.source : source;
    const backendMode = (typeof raw.mode === 'string' ? raw.mode : mode) as typeof mode;
    const backendLagMs = typeof raw.lag_ms === 'number' ? raw.lag_ms : lagMs;
    const isStale = raw.stale === true;
    const freshness = isStale ? 'stale' as const : computeFreshness(receivedAt, staleThresholdMs);
    const quality = computeQuality(data, backendMissing);
    const frameTimestampMs = resourceFrameTimestampMs(raw, receivedAt);
    const nextEnvelope: ValidatedDataEnvelope<T> = {
      data,
      source: backendSource,
      source_type: backendSourceType,
      endpoint: typeof raw.endpoint === 'string' ? raw.endpoint : url,
      symbol: typeof raw.symbol === 'string' ? raw.symbol : undefined,
      exchange: typeof raw.exchange === 'string' ? raw.exchange : undefined,
      trader_context: raw.trader_context,
      account_scope: raw.account_scope,
      timestamp: frameTimestampMs,
      received_at: receivedAt,
      lag_ms: backendLagMs,
      freshness_status: freshness,
      data_quality_status: backendErrors.length ? 'invalid' : quality,
      missing_fields: backendMissing,
      warnings: backendWarnings,
      errors: backendErrors,
      mode: backendMode,
    };
    setError(backendErrors[0] ?? null);
    setEnvelope(prev => {
      const merged = mergeRealtimeResourceEnvelope(prev, nextEnvelope);
      if (merged.shouldCache) {
        realtimeResourceCache.set(cacheKey(url, backendMode, unwrapShape), merged.envelope);
        persistLastKnownResourceEnvelope(url, backendMode, unwrapShape, merged.envelope);
      }
      return merged.envelope;
    });
  }, [mode, source, source_type, staleThresholdMs, transform, unwrapEnvelopeData, unwrapShape, url]);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    const requestKey = cacheKey(url, mode, unwrapShape);
    let timeoutId: number | null = null;
    inFlightRef.current.forEach(controller => controller.abort());
    inFlightRef.current.clear();
    const controller = new AbortController();
    inFlightRef.current.add(controller);
    const timeoutPromise = new Promise<null>((resolve) => {
      timeoutId = window.setTimeout(() => {
        controller.abort();
        resolve(null);
      }, fetchTimeoutMs(pollIntervalMs, requestTimeoutMs));
    });
    if (mountedRef.current && resourceKeyRef.current === requestKey) {
      setLoading(true);
    }
    const fetchStart = Date.now();
    try {
      const resp = await Promise.race([
        fetch(url, { credentials: 'include', signal: controller.signal }),
        timeoutPromise,
      ]);
      const receivedAt = Date.now();
      const lagMs = receivedAt - fetchStart;
      if (!mountedRef.current || resourceKeyRef.current !== requestKey) return;
      if (!resp) {
        setError('request_timeout');
        setEnvelope(prev => ({
          ...prev,
          freshness_status: 'offline',
          data_quality_status: 'invalid',
          errors: ['request_timeout'],
          lag_ms: lagMs,
          received_at: receivedAt,
        }));
        return;
      }
      if (!resp.ok) {
        const errText = await resp.text().catch(() => resp.statusText);
        setError(errText);
        setEnvelope(prev => ({
          ...prev,
          freshness_status: 'offline',
          data_quality_status: 'invalid',
          errors: [errText],
          lag_ms: lagMs,
          received_at: receivedAt,
        }));
        return;
      }
      const raw = await resp.json() as Record<string, unknown>;
      if (!mountedRef.current || resourceKeyRef.current !== requestKey) return;
      applyRawEnvelope(raw, receivedAt, lagMs);
    } catch (err) {
      if (!mountedRef.current || resourceKeyRef.current !== requestKey) return;
      const msg = (err as Error).message ?? 'fetch_error';
      setError(msg);
      setEnvelope(prev => ({
        ...prev,
        freshness_status: 'offline',
        data_quality_status: 'invalid',
        errors: [msg],
        received_at: Date.now(),
      }));
    } finally {
      if (timeoutId !== null) window.clearTimeout(timeoutId);
      inFlightRef.current.delete(controller);
      if (mountedRef.current && resourceKeyRef.current === requestKey) {
        setLoading(false);
      }
    }
  }, [url, mode, enabled, pollIntervalMs, requestTimeoutMs, unwrapShape, applyRawEnvelope]);

  useEffect(() => {
    resourceKeyRef.current = cacheKey(url, mode, unwrapShape);
    const cached = cachedEnvelope<T>(url, mode, unwrapShape);
    setEnvelope(cached ?? makeEmptyEnvelope<T>(source, { source_type, mode }));
    setLoading(enabled && !cached);
    setError(null);
  }, [enabled, mode, source, source_type, unwrapShape, url]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
    const streamable = canUseReadonlyResourceStream(url);
    const usingSharedStream = Boolean(streamable && subscribeResourcePath);

    if (initialFetch && (!usingSharedStream || initialFetchWhenStreaming)) {
      void fetchData();
    }

    const markWebSocketUnavailable = (reason: string) => {
      const receivedAt = Date.now();
      setLoading(false);
      setError(reason);
      setEnvelope(prev => ({
        ...prev,
        source_type: 'websocket',
        freshness_status: 'offline',
        data_quality_status: prev.data === null ? 'missing' : prev.data_quality_status,
        errors: [reason],
        warnings: [...new Set([...prev.warnings, 'WebSocket stream unavailable; HTTP fallback disabled for this view'])],
        received_at: receivedAt,
      }));
    };

    const clearFallback = () => {
      if (fallbackTimer) {
        clearTimeout(fallbackTimer);
        fallbackTimer = null;
      }
    };

    const startFallback = (delayMs = 0) => {
      if (!httpFallback) {
        markWebSocketUnavailable('resource_websocket_unavailable');
        return;
      }
      clearFallback();
      const run = () => {
        if (cancelled) return;
        void fetchData().finally(() => {
          if (!cancelled && pollIntervalMs) {
            fallbackTimer = setTimeout(run, pollIntervalMs);
          }
        });
      };
      fallbackTimer = setTimeout(run, delayMs);
    };

    if (streamable && subscribeResourcePath) {
      const unsubscribe = subscribeResourcePath(url, (raw) => {
        if (cancelled) return;
        try {
          applyRawEnvelope(raw, Date.now(), 0, 'websocket');
          setLoading(false);
        } catch (err) {
          setError((err as Error).message);
          setLoading(false);
        }
      });
      const cachedAtSubscribe = cachedEnvelope<T>(url, mode, unwrapShape);
      // Fetch once even when a cached envelope exists but is stale or a
      // session-restored snapshot; otherwise a page whose resource path is
      // not streamed over the shared WebSocket stays on stale data forever.
      if (
        httpFallback
        && initialFetch
        && !initialFetchWhenStreaming
        && (!cachedAtSubscribe || !shouldCacheEnvelope(cachedAtSubscribe))
      ) {
        fallbackTimer = setTimeout(() => {
          if (!cancelled) void fetchData();
        }, sharedStreamFallbackDelayMs(url, pollIntervalMs));
      }
      return () => {
        cancelled = true;
        unsubscribe();
        clearFallback();
        inFlightRef.current.forEach(controller => controller.abort());
        inFlightRef.current.clear();
      };
    }

    startFallback();
    return () => {
      cancelled = true;
      clearFallback();
      inFlightRef.current.forEach(controller => controller.abort());
      inFlightRef.current.clear();
    };
  }, [applyRawEnvelope, enabled, fetchData, httpFallback, initialFetch, initialFetchWhenStreaming, mode, pollIntervalMs, subscribeResourcePath, unwrapShape, url]);

  return { envelope, loading, error, refetch: fetchData };
}

export const realtimeResourceTestHooks = {
  resourceFrameTimestampMs,
  mergeRealtimeResourceEnvelope,
};
