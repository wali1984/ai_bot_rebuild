import type { TraderRealtimeState } from '../stores/traderRealtimeStore';
import type { CanonicalSignalSnapshot } from '../types/canonicalTraderData';
import { selectSectionMetric, type CanonicalMetric } from './accountSelectors';

export function selectSignals(state: TraderRealtimeState): CanonicalSignalSnapshot[] {
  return state.snapshot?.signals.data ?? [];
}

export function selectActiveSignal(state: TraderRealtimeState, symbol?: string): CanonicalSignalSnapshot | null {
  const signals = selectSignals(state);
  if (!symbol) return signals[0] ?? null;
  const normalized = symbol.trim().toUpperCase();
  return signals.find((signal) => signal.symbol === normalized) ?? null;
}

export function selectSignalMetric<T = unknown>(
  state: TraderRealtimeState,
  signal: CanonicalSignalSnapshot | Record<string, unknown>,
  fieldId: string,
): CanonicalMetric<T> {
  const key = fieldId.replace(/^signal\./, '');
  const value = signal[key as keyof typeof signal] as T | undefined;
  return selectSectionMetric<T>(state, 'signals', fieldId, value ?? null);
}
