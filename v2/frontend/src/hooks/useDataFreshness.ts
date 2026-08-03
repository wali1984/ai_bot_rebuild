import { useMemo } from 'react';
import type { FreshnessStatus, ValidatedDataEnvelope } from '../types/dataContract';

export interface FreshnessResult {
  status: FreshnessStatus;
  lagMs: number | null;
  isStale: boolean;
  isFresh: boolean;
  isOffline: boolean;
  isUnavailable: boolean;
  ageSeconds: number | null;
}

export function useDataFreshness(
  envelope: ValidatedDataEnvelope<unknown> | null | undefined,
  staleThresholdMs = 30_000,
): FreshnessResult {
  return useMemo(() => {
    if (!envelope) {
      return {
        status: 'unavailable',
        lagMs: null,
        isStale: false,
        isFresh: false,
        isOffline: false,
        isUnavailable: true,
        ageSeconds: null,
      };
    }
    const now = Date.now();
    const lagMs = envelope.lag_ms;
    const receivedAt = envelope.received_at;
    const ageMs = receivedAt ? now - receivedAt : null;
    const ageSeconds = ageMs !== null ? ageMs / 1000 : null;
    let status: FreshnessStatus = envelope.freshness_status;
    if (ageMs !== null && ageMs > staleThresholdMs && status === 'fresh') {
      status = 'stale';
    }
    return {
      status,
      lagMs,
      isStale: status === 'stale',
      isFresh: status === 'fresh',
      isOffline: status === 'offline',
      isUnavailable: status === 'unavailable',
      ageSeconds,
    };
  }, [envelope, staleThresholdMs]);
}
