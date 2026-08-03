import { useMemo } from 'react';
import { safeV2MarketSymbol } from '../api/v2Market';
import { unavailableV2Response } from '../api/v2Shared';
import { useRealtimeResource } from './useRealtimeResource';
import type { ApiV2Envelope, MarketTickerData } from '../types/apiV2';

export interface UseSymbolDataResult {
  detail: ApiV2Envelope<MarketTickerData>;
  loading: boolean;
}

export function useSymbolData(symbol: string): UseSymbolDataResult {
  const safeSymbol = safeV2MarketSymbol(symbol);
  const url = safeSymbol ? `/api/v2/market/${safeSymbol}` : '/api/v2/market/{symbol}';
  const resource = useRealtimeResource<MarketTickerData>({
    url,
    source: url,
    source_type: 'websocket',
    pollIntervalMs: 3_000,
    staleThresholdMs: 9_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
    initialFetch: true,
    httpFallback: true,
  });

  const resourceDetail = useMemo(() => {
    const timestamp = resource.envelope.timestamp != null
    ? new Date(resource.envelope.timestamp).toISOString()
    : null;
    const receivedAt = resource.envelope.received_at != null
    ? new Date(resource.envelope.received_at).toISOString()
    : new Date().toISOString();
    return {
      data: resource.envelope.data,
      source: resource.envelope.source,
      source_type: resource.envelope.source_type,
      endpoint: resource.envelope.endpoint,
      timestamp,
      received_at: receivedAt,
      lag_ms: resource.envelope.lag_ms,
      stale: resource.envelope.freshness_status === 'stale',
      missing_fields: resource.envelope.missing_fields,
      warnings: resource.envelope.warnings,
      mode: resource.envelope.mode,
    } as ApiV2Envelope<MarketTickerData>;
  }, [resource.envelope]);

  if (!safeSymbol) {
    return {
      detail: unavailableV2Response(
        '/api/v2/market/{symbol}',
        ['symbol', 'last_price', 'funding_rate', 'open_interest', 'spread'],
        'Enter a valid market symbol.',
      ),
      loading: false,
    };
  }

  const hasRealtimeData = resourceDetail.data?.symbol?.toUpperCase() === safeSymbol;
  return {
    detail: resourceDetail,
    loading: resource.loading && !hasRealtimeData,
  };
}
