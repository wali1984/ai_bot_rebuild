import { useMemo } from 'react';
import { useRealtimeResource } from './useRealtimeResource';

export interface RealtimeQueryResult<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  isFetching: boolean;
  refetch: () => void;
}

export interface RealtimeQueryOptions {
  enabled?: boolean;
  refetchIntervalMs?: number;
  staleThresholdMs?: number;
}

function resourceError(error: string | null, errors: string[]): Error | null {
  const message = error ?? errors[0] ?? null;
  return message ? new Error(String(message)) : null;
}

export function useRealtimeQuery<T>(
  url: string,
  opts: RealtimeQueryOptions = {},
): RealtimeQueryResult<T> {
  const intervalMs = opts.refetchIntervalMs ?? 15_000;
  const resource = useRealtimeResource<T>({
    url,
    source: url,
    source_type: 'websocket',
    pollIntervalMs: intervalMs,
    staleThresholdMs: opts.staleThresholdMs ?? Math.max(30_000, intervalMs * 3),
    enabled: opts.enabled ?? true,
    mode: 'read_only',
    unwrapEnvelopeData: 'contract',
  });
  const data = resource.envelope.data;
  return useMemo(
    () => ({
      data,
      error: resourceError(resource.error, resource.envelope.errors),
      isLoading: resource.loading && data === null,
      isFetching: resource.loading && data !== null,
      refetch: resource.refetch,
    }),
    [data, resource.envelope.errors, resource.error, resource.loading, resource.refetch],
  );
}
