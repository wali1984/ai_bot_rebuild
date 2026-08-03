import type { TraderRealtimeState } from '../stores/traderRealtimeStore';
import type { CanonicalMarketSnapshot } from '../types/canonicalTraderData';
import { selectSectionMetric, type CanonicalMetric } from './accountSelectors';

export function selectMarkets(state: TraderRealtimeState): CanonicalMarketSnapshot[] {
  return state.snapshot?.market_status.data ?? [];
}

export function selectMarketBySymbol(state: TraderRealtimeState, symbol: string): CanonicalMarketSnapshot | null {
  const normalized = symbol.trim().toUpperCase();
  return selectMarkets(state).find((market) => market.symbol === normalized) ?? null;
}

export function selectMarketMetric<T = unknown>(
  state: TraderRealtimeState,
  market: CanonicalMarketSnapshot | Record<string, unknown>,
  fieldId: string,
): CanonicalMetric<T> {
  const key = fieldId.replace(/^market\./, '');
  const value = market[key as keyof typeof market] as T | undefined;
  return selectSectionMetric<T>(state, 'market_status', fieldId, value ?? null);
}
