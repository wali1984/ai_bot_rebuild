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
  httpFallback?: boolean;
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

function cacheKey(url: string, mode: ValidatedDataEnvelope<unknown>['mode']): string {
  return `${mode}:${url}`;
}

function cachedEnvelope<T>(
  url: string,
  mode: ValidatedDataEnvelope<T>['mode'],
): ValidatedDataEnvelope<T> | null {
  return (realtimeResourceCache.get(cacheKey(url, mode)) as ValidatedDataEnvelope<T> | undefined) ?? null;
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

  if (!nextUsable && previousUsable) {
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

function fetchTimeoutMs(pollIntervalMs: number): number {
  return Math.min(4_500, Math.max(3_000, Math.floor(pollIntervalMs * 0.8)));
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
    httpFallback = true,
    mode = 'read_only',
    unwrapEnvelopeData = true,
  } = opts;
  const sharedRealtime = useOptionalEnterpriseRealtime();
  const subscribeResourcePath = sharedRealtime?.subscribeResourcePath;

  const [envelope, setEnvelope] = useState<ValidatedDataEnvelope<T>>(
    () => cachedEnvelope<T>(url, mode) ?? makeEmptyEnvelope<T>(source, { source_type, mode }),
  );
  const [loading, setLoading] = useState(() => !cachedEnvelope<T>(url, mode));
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

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
        realtimeResourceCache.set(cacheKey(url, backendMode), merged.envelope);
      }
      return merged.envelope;
    });
  }, [mode, source, source_type, staleThresholdMs, transform, unwrapEnvelopeData, url]);

  const fetchData = useCallback(async () => {
    if (!enabled) return;
    if (abortRef.current) abortRef.current.abort();
    const ctrl = new AbortController();
    abortRef.current = ctrl;
    const timeoutId = window.setTimeout(() => ctrl.abort(), fetchTimeoutMs(pollIntervalMs));
    setLoading(true);
    const fetchStart = Date.now();
    try {
      const resp = await fetch(url, { signal: ctrl.signal, credentials: 'include' });
      const receivedAt = Date.now();
      const lagMs = receivedAt - fetchStart;
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
      applyRawEnvelope(raw, receivedAt, lagMs);
    } catch (err) {
      if ((err as Error).name === 'AbortError') return;
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
      window.clearTimeout(timeoutId);
      setLoading(false);
    }
  }, [url, enabled, pollIntervalMs, applyRawEnvelope]);

  useEffect(() => {
    const cached = cachedEnvelope<T>(url, mode);
    setEnvelope(cached ?? makeEmptyEnvelope<T>(source, { source_type, mode }));
    setLoading(enabled && !cached);
    setError(null);
  }, [enabled, mode, source, source_type, url]);

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    let fallbackTimer: ReturnType<typeof setTimeout> | null = null;
    const streamable = canUseReadonlyResourceStream(url);

    if (initialFetch) {
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
      return () => {
        cancelled = true;
        unsubscribe();
        clearFallback();
        abortRef.current?.abort();
      };
    }

    startFallback();
    return () => {
      cancelled = true;
      clearFallback();
      abortRef.current?.abort();
    };
  }, [applyRawEnvelope, enabled, fetchData, httpFallback, initialFetch, pollIntervalMs, subscribeResourcePath, url]);

  return { envelope, loading, error, refetch: fetchData };
}

export const realtimeResourceTestHooks = {
  resourceFrameTimestampMs,
  mergeRealtimeResourceEnvelope,
};
