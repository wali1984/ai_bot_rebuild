import type { TraderRealtimeState } from '../stores/traderRealtimeStore';
import type { CanonicalPositionSnapshot } from '../types/canonicalTraderData';
import { selectSectionMetric, type CanonicalMetric } from './accountSelectors';

export function selectPositions(state: TraderRealtimeState): CanonicalPositionSnapshot[] {
  return state.snapshot?.positions.data ?? [];
}

export function selectOpenPositionCount(state: TraderRealtimeState): number | null {
  return state.snapshot?.account.data.open_position_count ?? null;
}

export function selectPositionById(state: TraderRealtimeState, id: string): CanonicalPositionSnapshot | null {
  return selectPositions(state).find((position) => position.id === id) ?? null;
}

export function selectPositionMetric<T = unknown>(
  state: TraderRealtimeState,
  position: CanonicalPositionSnapshot | Record<string, unknown>,
  fieldId: string,
): CanonicalMetric<T> {
  const key = fieldId.replace(/^position\./, '');
  const value = position[key as keyof typeof position] as T | undefined;
  return selectSectionMetric<T>(state, 'positions', fieldId, value ?? null);
}
