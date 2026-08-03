import type { TraderRealtimeState } from '../stores/traderRealtimeStore';
import type { CanonicalFieldDefinition } from '../types/canonicalTraderData';
import { CANONICAL_TRADER_FIELD_REGISTRY } from '../data/canonicalFieldRegistry';

export interface CanonicalMetric<T = unknown> {
  fieldId: string;
  definition: CanonicalFieldDefinition | null;
  value: T | null;
  source: string;
  sourceType: string;
  timestamp: string | null;
  ageMs: number | null;
  quality: string;
}

export function selectSectionMetric<T>(
  state: TraderRealtimeState,
  sectionName: keyof NonNullable<TraderRealtimeState['snapshot']>,
  fieldId: string,
  value: T | null,
): CanonicalMetric<T> {
  const section = state.snapshot?.[sectionName];
  const meta = section?.meta;
  return {
    fieldId,
    definition: CANONICAL_TRADER_FIELD_REGISTRY[fieldId] ?? null,
    value,
    source: meta?.source ?? state.source,
    sourceType: meta?.source_type ?? state.sourceType,
    timestamp: meta?.timestamp ?? null,
    ageMs: meta?.lag_ms ?? null,
    quality: meta?.quality ?? state.quality,
  };
}

export function selectAccountMetric<T = unknown>(state: TraderRealtimeState, fieldId: string): CanonicalMetric<T> {
  const key = fieldId.replace(/^account\./, '');
  const value = state.snapshot?.account.data?.[key as keyof typeof state.snapshot.account.data] as T | undefined;
  return selectSectionMetric<T>(state, 'account', fieldId, value ?? null);
}

export function selectAccountMetrics(state: TraderRealtimeState): CanonicalMetric[] {
  return Object.keys(CANONICAL_TRADER_FIELD_REGISTRY)
    .filter((fieldId) => fieldId.startsWith('account.'))
    .map((fieldId) => selectAccountMetric(state, fieldId));
}

export function metricDataAttributes(metric: CanonicalMetric): Record<string, string> {
  return {
    'data-field-id': metric.fieldId,
    'data-source': metric.source,
    'data-source-type': metric.sourceType,
    'data-timestamp': metric.timestamp ?? '',
    'data-age-ms': metric.ageMs == null ? '' : String(metric.ageMs),
    'data-quality': metric.quality,
  };
}
