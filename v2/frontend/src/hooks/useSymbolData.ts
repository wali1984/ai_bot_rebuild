import { useEffect, useMemo, useState } from 'react';
import { getV2MarketDetail, safeV2MarketSymbol } from '../api/v2Market';
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
  const [fallbackDetail, setFallbackDetail] = useState<ApiV2Envelope<MarketTickerData> | null>(null);
  const resource = useRealtimeResource<MarketTickerData>({
    url,
    source: url,
    pollIntervalMs: 3_000,
    staleThresholdMs: 9_000,
    mode: 'read_only',
    enabled: Boolean(safeSymbol),
    initialFetch: true,
    httpFallback: true,
  });

  useEffect(() => {
    if (!safeSymbol) {
      setFallbackDetail(null);
      return undefined;
    }

    let active = true;
    const currentSymbol = safeSymbol;
    async function loadFallback(): Promise<void> {
      const next = await getV2MarketDetail(currentSymbol);
      if (active) setFallbackDetail(next);
    }

    void loadFallback();
    const interval = window.setInterval(loadFallback, 3_000);
    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [safeSymbol]);

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

  const fallbackMatchesSymbol = fallbackDetail?.data?.symbol?.toUpperCase() === safeSymbol;
  const hasRealtimeData = resourceDetail.data?.symbol?.toUpperCase() === safeSymbol;
  const detail = hasRealtimeData ? resourceDetail : fallbackMatchesSymbol ? fallbackDetail : resourceDetail;
  return {
    detail,
    loading: resource.loading && !fallbackMatchesSymbol,
  };
}
