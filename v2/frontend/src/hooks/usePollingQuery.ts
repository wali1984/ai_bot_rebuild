import { useCallback, useEffect, useRef, useState } from 'react';

export interface PollingQueryOptions {
  enabled?: boolean;
  refetchIntervalMs?: number;
}

export interface PollingQueryResult<T> {
  data: T | null;
  error: Error | null;
  isLoading: boolean;
  isFetching: boolean;
  refetch: () => void;
}

/**
 * usePollingQuery — minimal React-Query-shape hook so the agent-supervisor
 * panels can ship without adding @tanstack/react-query as a new dependency.
 *
 * Contract:
 * - first call shows isLoading=true until the first fetch resolves or rejects;
 * - any subsequent fetch shows isFetching=true (isLoading stays false);
 * - cancellation: post-unmount setState is suppressed via a ref;
 * - refetchIntervalMs <= 0 disables polling.
 */
export function usePollingQuery<T>(
  key: string,
  fetcher: (signal: AbortSignal) => Promise<T>,
  opts: PollingQueryOptions = {},
): PollingQueryResult<T> {
  const enabled = opts.enabled ?? true;
  const intervalMs = opts.refetchIntervalMs ?? 0;

  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [isFetching, setIsFetching] = useState<boolean>(false);

  const aliveRef = useRef<boolean>(true);
  const tickRef = useRef<number>(0);

  const run = useCallback(async () => {
    if (!enabled) return;
    const myTick = ++tickRef.current;
    const controller = new AbortController();
    setIsFetching(true);
    try {
      const next = await fetcher(controller.signal);
      if (!aliveRef.current || myTick !== tickRef.current) return;
      setData(next);
      setError(null);
    } catch (err) {
      if (!aliveRef.current || myTick !== tickRef.current) return;
      setError(err instanceof Error ? err : new Error(String(err)));
    } finally {
      if (aliveRef.current && myTick === tickRef.current) {
        setIsFetching(false);
        setIsLoading(false);
      }
    }
  }, [enabled, fetcher]);

  useEffect(() => {
    aliveRef.current = true;
    if (!enabled) {
      setIsLoading(false);
      return () => {
        aliveRef.current = false;
      };
    }
    void run();
    let timer: ReturnType<typeof setInterval> | null = null;
    if (intervalMs > 0) {
      timer = setInterval(() => {
        void run();
      }, intervalMs);
    }
    return () => {
      aliveRef.current = false;
      if (timer) clearInterval(timer);
    };
    // `key` participates so consumers can force a fresh subscription.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, enabled, intervalMs, run]);

  const refetch = useCallback(() => {
    void run();
  }, [run]);

  return { data, error, isLoading, isFetching, refetch };
}

export async function fetchJson<T>(url: string, signal: AbortSignal): Promise<T> {
  const res = await fetch(url, { signal, headers: { Accept: 'application/json' } });
  if (!res.ok) throw new Error(`HTTP ${res.status} ${res.statusText} for ${url}`);
  return (await res.json()) as T;
}
