import { useEffect } from 'react';
import { useRealtimeResource } from './useRealtimeResource';
import {
  applyTraderSnapshotEnvelope,
  markTraderSnapshotDisconnected,
  useTraderRealtimeState,
  type TraderRealtimeState,
} from '../stores/traderRealtimeStore';
import type { TraderSnapshot } from '../types/canonicalTraderData';

function unwrapTraderSnapshot(raw: unknown): TraderSnapshot | Record<string, unknown> | null {
  if (!raw || typeof raw !== 'object') return null;
  const record = raw as Record<string, unknown>;
  return (record.data && typeof record.data === 'object' ? record.data : record) as TraderSnapshot | Record<string, unknown>;
}

export function useTraderSnapshot(): TraderRealtimeState & { loading: boolean; refetch: () => void } {
  const resource = useRealtimeResource<TraderSnapshot | Record<string, unknown> | null>({
    url: '/api/v2/trader/snapshot',
    source: '/api/v2/trader/snapshot',
    source_type: 'api',
    pollIntervalMs: 10_000,
    staleThresholdMs: 20_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
    unwrapEnvelopeData: false,
    transform: unwrapTraderSnapshot,
  });
  const state = useTraderRealtimeState();

  useEffect(() => {
    applyTraderSnapshotEnvelope(resource.envelope);
  }, [resource.envelope]);

  useEffect(() => {
    if (resource.error) markTraderSnapshotDisconnected(resource.error);
  }, [resource.error]);

  return {
    ...state,
    loading: resource.loading,
    refetch: resource.refetch,
  };
}
