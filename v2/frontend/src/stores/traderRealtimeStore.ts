import { useSyncExternalStore } from 'react';
import type { ValidatedDataEnvelope } from '../types/dataContract';
import type { TraderSnapshot, TraderSnapshotSectionMeta } from '../types/canonicalTraderData';

export interface TraderRealtimeState {
  snapshot: TraderSnapshot | null;
  source: string;
  sourceType: string;
  timestamp: number | null;
  receivedAt: number | null;
  sequence: number | null;
  freshness: ValidatedDataEnvelope<unknown>['freshness_status'];
  quality: ValidatedDataEnvelope<unknown>['data_quality_status'];
  lastError: string | null;
  warnings: string[];
  missingFields: string[];
}

const initialState: TraderRealtimeState = {
  snapshot: null,
  source: '/api/v2/trader/snapshot',
  sourceType: 'unavailable',
  timestamp: null,
  receivedAt: null,
  sequence: null,
  freshness: 'unavailable',
  quality: 'missing',
  lastError: null,
  warnings: [],
  missingFields: [],
};

let state = initialState;
const listeners = new Set<() => void>();

function emit(): void {
  for (const listener of listeners) listener();
}

function parseTime(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : null;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value);
}

function sectionMeta(snapshot: TraderSnapshot | null, section: keyof TraderSnapshot): TraderSnapshotSectionMeta | null {
  return snapshot?.[section]?.meta ?? null;
}

function snapshotSequence(snapshot: TraderSnapshot): number | null {
  const dataStatus = sectionMeta(snapshot, 'data_status');
  return typeof dataStatus?.sequence === 'number' ? dataStatus.sequence : null;
}

function snapshotTimestamp(snapshot: TraderSnapshot): number | null {
  const dataStatus = sectionMeta(snapshot, 'data_status');
  return parseTime(dataStatus?.timestamp) ?? parseTime(dataStatus?.received_at);
}

function containsInvalidNumber(value: unknown): boolean {
  if (typeof value === 'number') return !Number.isFinite(value);
  if (Array.isArray(value)) return value.some(containsInvalidNumber);
  if (isRecord(value)) return Object.values(value).some(containsInvalidNumber);
  return false;
}

function sameFrame(current: TraderRealtimeState, nextSequence: number | null, nextTimestamp: number | null): boolean {
  return (
    nextSequence !== null
    && current.sequence !== null
    && nextSequence === current.sequence
    && nextTimestamp !== null
    && current.timestamp !== null
    && nextTimestamp === current.timestamp
  );
}

function isOutOfOrder(current: TraderRealtimeState, nextSequence: number | null, nextTimestamp: number | null): boolean {
  if (current.sequence !== null && nextSequence !== null) return nextSequence < current.sequence;
  if (current.timestamp !== null && nextTimestamp !== null) return nextTimestamp < current.timestamp;
  return false;
}

function coerceSnapshot(value: unknown): TraderSnapshot | null {
  if (!isRecord(value)) return null;
  const maybeWrapped = isRecord(value.data) ? value.data : value;
  const required = [
    'account',
    'portfolio',
    'positions',
    'orders',
    'executions',
    'history',
    'signals',
    'predictions',
    'risk',
    'market_status',
    'automation_status',
    'execution_status',
    'data_status',
  ];
  return required.every((key) => isRecord(maybeWrapped[key])) ? maybeWrapped as unknown as TraderSnapshot : null;
}

export function applyTraderSnapshotEnvelope(envelope: ValidatedDataEnvelope<unknown>): TraderRealtimeState {
  const nextSnapshot = coerceSnapshot(envelope.data);
  if (!nextSnapshot || containsInvalidNumber(nextSnapshot)) {
    state = {
      ...state,
      source: envelope.source,
      sourceType: envelope.source_type,
      receivedAt: envelope.received_at,
      freshness: envelope.freshness_status,
      quality: 'invalid',
      lastError: nextSnapshot ? 'Trader snapshot contains NaN or infinity' : 'Trader snapshot payload is missing required sections',
      warnings: [...state.warnings, ...envelope.warnings],
      missingFields: [...new Set([...state.missingFields, ...envelope.missing_fields])],
    };
    emit();
    return state;
  }

  const nextSequence = snapshotSequence(nextSnapshot);
  const nextTimestamp = snapshotTimestamp(nextSnapshot) ?? envelope.timestamp;
  if (sameFrame(state, nextSequence, nextTimestamp)) return state;
  if (isOutOfOrder(state, nextSequence, nextTimestamp)) {
    state = {
      ...state,
      receivedAt: envelope.received_at,
      warnings: [...new Set([...state.warnings, 'Out-of-order trader snapshot frame ignored'])],
    };
    emit();
    return state;
  }

  state = {
    snapshot: nextSnapshot,
    source: envelope.source,
    sourceType: envelope.source_type,
    timestamp: nextTimestamp,
    receivedAt: envelope.received_at,
    sequence: nextSequence,
    freshness: envelope.freshness_status,
    quality: envelope.data_quality_status,
    lastError: envelope.errors[0] ?? null,
    warnings: envelope.warnings,
    missingFields: envelope.missing_fields,
  };
  emit();
  return state;
}

export function markTraderSnapshotDisconnected(error: string | null): TraderRealtimeState {
  state = {
    ...state,
    freshness: state.snapshot ? 'stale' : 'offline',
    quality: state.snapshot ? state.quality : 'missing',
    lastError: error,
  };
  emit();
  return state;
}

export function getTraderRealtimeState(): TraderRealtimeState {
  return state;
}

export function subscribeTraderRealtimeStore(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

export function useTraderRealtimeState(): TraderRealtimeState {
  return useSyncExternalStore(subscribeTraderRealtimeStore, getTraderRealtimeState, () => initialState);
}

export function resetTraderRealtimeStoreForTests(): void {
  state = initialState;
  emit();
}
