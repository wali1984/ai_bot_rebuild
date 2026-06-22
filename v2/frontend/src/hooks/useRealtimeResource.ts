import { useCallback, useEffect, useRef, useState } from 'react';
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

function fetchTimeoutMs(pollIntervalMs: number): number {
  return Math.min(4_500, Math.max(3_000, Math.floor(pollIntervalMs * 0.8)));
}

function websocketResourceUrls(url: string, intervalMs: number): string[] {
  if (typeof window === 'undefined') return [];
  const path = url.split('?')[0] ?? url;
  const isApiResource = path.startsWith('/api/v2/') || path.startsWith('/api/v1/');
  const isStaticJsonResource = path.endsWith('.json') && READONLY_STATIC_JSON_PREFIXES.some((prefix) => path.startsWith(prefix));
  if (!isApiResource && !isStaticJsonResource) return [];
  const origin = window.location.origin;
  const protocol = origin.startsWith('https:') ? 'wss:' : 'ws:';
  return ['/api/v2/ws/resource', '/ws/resource'].map((path) => {
    const target = new URL(path, origin);
    target.protocol = protocol;
    target.searchParams.set('path', url);
    target.searchParams.set('interval_ms', String(intervalMs));
    return target.toString();
  });
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

  const [envelope, setEnvelope] = useState<ValidatedDataEnvelope<T>>(
    () => cachedEnvelope<T>(url, mode) ?? makeEmptyEnvelope<T>(source, { source_type, mode }),
  );
  const [loading, setLoading] = useState(() => !cachedEnvelope<T>(url, mode));
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const socketRef = useRef<WebSocket | null>(null);

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
    const nextEnvelope: ValidatedDataEnvelope<T> = {
      data,
      source: backendSource,
      source_type: backendSourceType,
      endpoint: typeof raw.endpoint === 'string' ? raw.endpoint : url,
      symbol: typeof raw.symbol === 'string' ? raw.symbol : undefined,
      exchange: typeof raw.exchange === 'string' ? raw.exchange : undefined,
      trader_context: raw.trader_context,
      account_scope: raw.account_scope,
      timestamp: receivedAt,
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
      const nextUsable = shouldCacheEnvelope(nextEnvelope);
      if (!nextUsable && shouldCacheEnvelope(prev)) {
        return {
          ...prev,
          received_at: receivedAt,
          lag_ms: backendLagMs,
          warnings: [
            ...new Set([
              ...prev.warnings,
              ...backendWarnings,
              'Latest resource frame was stale or incomplete; preserving last current payload',
            ]),
          ],
          errors: backendErrors,
        };
      }
      if (nextUsable) {
        realtimeResourceCache.set(cacheKey(url, backendMode), nextEnvelope);
      }
      return nextEnvelope;
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
    let fallbackTimer: ReturnType<typeof setInterval> | null = null;
    let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
    const urls = websocketResourceUrls(url, pollIntervalMs);

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

    const startFallback = () => {
      if (!httpFallback) {
        markWebSocketUnavailable('resource_websocket_unavailable');
        return;
      }
      if (fallbackTimer) clearInterval(fallbackTimer);
      void fetchData();
      if (pollIntervalMs) {
        fallbackTimer = setInterval(() => void fetchData(), pollIntervalMs);
      }
    };

    const connect = (index = 0) => {
      if (cancelled) return;
      if (!urls.length || index >= urls.length) {
        startFallback();
        return;
      }
      setLoading(true);
      try {
        socketRef.current = new WebSocket(urls[index]);
      } catch {
        connect(index + 1);
        return;
      }
      const socket = socketRef.current;
      socket.onmessage = (event) => {
        if (cancelled) return;
        try {
          const raw = JSON.parse(event.data) as Record<string, unknown>;
          applyRawEnvelope(raw, Date.now(), 0, 'websocket');
          setLoading(false);
        } catch (err) {
          setError((err as Error).message);
          setLoading(false);
        }
      };
      socket.onerror = () => {
        if (!cancelled) setError('resource_websocket_error');
      };
      socket.onclose = () => {
        if (cancelled) return;
        if (index + 1 < urls.length) {
          connect(index + 1);
          return;
        }
        startFallback();
        reconnectTimer = setTimeout(() => connect(0), Math.max(5000, pollIntervalMs));
      };
    };

    connect();
    return () => {
      cancelled = true;
      socketRef.current?.close();
      if (fallbackTimer) clearInterval(fallbackTimer);
      if (reconnectTimer) clearTimeout(reconnectTimer);
      abortRef.current?.abort();
    };
  }, [applyRawEnvelope, enabled, fetchData, httpFallback, initialFetch, pollIntervalMs, url]);

  return { envelope, loading, error, refetch: fetchData };
}
