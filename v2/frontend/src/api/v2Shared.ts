import type { ApiV2Envelope, ApiV2Mode } from '../types/apiV2';

export function unavailableV2Response<T>(
  endpoint: string,
  missingFields: string[],
  warning: string,
  options: { symbol?: string; mode?: ApiV2Mode } = {},
): ApiV2Envelope<T> {
  return {
    data: null,
    source: 'unavailable',
    source_type: 'unavailable',
    endpoint,
    timestamp: null,
    received_at: new Date().toISOString(),
    lag_ms: null,
    stale: true,
    missing_fields: missingFields,
    warnings: [warning],
    symbol: options.symbol ?? null,
    exchange: options.symbol ? 'Binance USD-M' : null,
    mode: options.mode ?? 'read_only',
  };
}

function isContractResponse<T>(value: unknown, endpoint: string): value is ApiV2Envelope<T> {
  if (!value || typeof value !== 'object') return false;
  const candidate = value as Partial<ApiV2Envelope<T>>;
  const canonicalEndpoint = endpoint.split('?')[0];
  return (
    (candidate.endpoint === endpoint || candidate.endpoint === canonicalEndpoint)
    && typeof candidate.source === 'string'
    && typeof candidate.source_type === 'string'
    && Array.isArray(candidate.missing_fields)
    && Array.isArray(candidate.warnings)
  );
}

export async function fetchV2Contract<T>(
  endpoint: string,
  missingFields: string[],
  warning: string,
  options: { symbol?: string; mode?: ApiV2Mode; init?: RequestInit } = {},
): Promise<ApiV2Envelope<T>> {
  try {
    const headers = new Headers(options.init?.headers);
    if (!headers.has('Content-Type')) headers.set('Content-Type', 'application/json');
    const response = await fetch(endpoint, {
      ...options.init,
      credentials: options.init?.credentials ?? 'include',
      headers,
    });
    const contentType = response.headers.get('content-type') ?? '';
    if (!response.ok || !contentType.includes('application/json')) {
      return unavailableV2Response<T>(endpoint, missingFields, warning, options);
    }
    const json = await response.json() as unknown;
    return isContractResponse<T>(json, endpoint)
      ? json
      : unavailableV2Response<T>(endpoint, missingFields, warning, options);
  } catch {
    return unavailableV2Response<T>(endpoint, missingFields, warning, options);
  }
}
