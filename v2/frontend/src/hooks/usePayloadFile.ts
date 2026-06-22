import { useMemo } from 'react';
import { useRealtimeResource } from './useRealtimeResource';

export interface PayloadFileResult<T> {
  data: T | null;
  error: string | null;
  ageSeconds: number | null;
  loading: boolean;
}

export interface PayloadFileOptions {
  enabled?: boolean;
}

const TIMESTAMP_FIELDS = [
  'generated_at',
  'generated_utc',
  'generated_est',
  'timestamp',
  'received_at',
  'heartbeat_at',
  'last_run_ts',
  'finished_at',
  'updated_at',
] as const;

function parseAgeSeconds(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) {
    const ms = value > 10_000_000_000 ? value : value * 1000;
    return Math.max(0, Math.round((Date.now() - ms) / 1000));
  }
  if (typeof value !== 'string' || value.trim() === '') return null;
  const ms = new Date(value).getTime();
  return isNaN(ms) ? null : Math.max(0, Math.round((Date.now() - ms) / 1000));
}

function payloadAgeSeconds(payload: Record<string, unknown>): number | null {
  const freshness = payload.freshness;
  if (freshness && typeof freshness === 'object') {
    const runtimeAge = (freshness as Record<string, unknown>).runtime_age_seconds
      ?? (freshness as Record<string, unknown>).age_seconds;
    if (typeof runtimeAge === 'number' && Number.isFinite(runtimeAge)) {
      return Math.max(0, Math.round(runtimeAge));
    }
    const freshnessGenerated = parseAgeSeconds((freshness as Record<string, unknown>).generated_at);
    if (freshnessGenerated !== null) return freshnessGenerated;
  }

  for (const field of TIMESTAMP_FIELDS) {
    const age = parseAgeSeconds(payload[field]);
    if (age !== null) return age;
  }
  return null;
}

/** Stream any safe static JSON payload, falling back to interval fetch if the socket is unavailable. */
export function usePayloadFile<T>(
  path: string,
  intervalMs = 10_000,
  options: PayloadFileOptions = {},
): PayloadFileResult<T> {
  const enabled = options.enabled !== false;
  const { envelope, loading, error } = useRealtimeResource<T>({
    url: path,
    source: path,
    pollIntervalMs: intervalMs,
    staleThresholdMs: Math.max(intervalMs * 3, 30_000),
    enabled,
    initialFetch: true,
    mode: 'read_only',
  });

  const ageSeconds = useMemo(() => {
    if (!envelope.data || typeof envelope.data !== 'object') return null;
    return payloadAgeSeconds(envelope.data as Record<string, unknown>);
  }, [envelope.data]);

  return {
    data: enabled ? envelope.data : null,
    error: enabled ? (error ?? envelope.errors[0] ?? null) : null,
    ageSeconds: enabled ? ageSeconds : null,
    loading: enabled ? loading : false,
  };
}

/** Format seconds into a human-readable age string. */
export function fmtAge(s: number | null): string {
  if (s === null) return '—';
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

/** Return a CSS class suffix based on age. */
export function ageClass(s: number | null, staleThreshold = 120): 'ok' | 'warn' | 'block' {
  if (s === null) return 'block';
  if (s > staleThreshold * 10) return 'block';
  if (s > staleThreshold) return 'warn';
  return 'ok';
}
