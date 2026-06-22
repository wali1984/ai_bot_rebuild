import { useRealtimeResource } from '../hooks/useRealtimeResource';

export const CURRENT_RUNTIME_LINEAGE_PATH = '/operator_runtime/paper_online/latest/current_signal_lineage.json';

export type RuntimeRecord = Record<string, unknown>;

export interface CurrentRuntimeLineagePayload {
  generated_at?: string | null;
  signal?: RuntimeRecord | null;
  trainer_prediction?: RuntimeRecord | null;
  risk_decision?: RuntimeRecord | null;
  orchestrator_decision?: RuntimeRecord | null;
  feature_snapshot?: RuntimeRecord | null;
  lineage_ids?: RuntimeRecord | null;
  classification?: string | null;
}

export function useCurrentRuntimeLineage(pollIntervalMs = 10_000) {
  return useRealtimeResource<CurrentRuntimeLineagePayload>({
    url: CURRENT_RUNTIME_LINEAGE_PATH,
    source: CURRENT_RUNTIME_LINEAGE_PATH,
    source_type: 'static_snapshot',
    pollIntervalMs,
    staleThresholdMs: pollIntervalMs * 3,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });
}

export function runtimeRecord(value: unknown): RuntimeRecord {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as RuntimeRecord
    : {};
}

export function runtimeText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return null;
}

export function runtimeNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value);
      if (Number.isFinite(parsed)) return parsed;
    }
  }
  return null;
}

export function runtimeBoolean(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

export function runtimeAgeSeconds(generatedAt: string | null | undefined): number | null {
  if (!generatedAt) return null;
  const parsed = Date.parse(generatedAt);
  if (!Number.isFinite(parsed)) return null;
  return Math.max(0, Math.round((Date.now() - parsed) / 1000));
}

export function publicRuntimeLabel(value: string | null | undefined): string {
  if (!value?.trim()) return '—';
  return value
    .trim()
    .replace(/\bpaper[_ -]?fill\b/gi, 'execution')
    .replace(/\bpaper[_ -]?only\b/gi, 'operator gated')
    .replace(/\bpaper[_ -]?runtime\b/gi, 'execution runtime')
    .replace(/\bpaper[_ -]?account\b/gi, 'account')
    .replace(/\bpaper\b/gi, 'runtime')
    .replace(/\bblocked_human_only\b/gi, 'operator gated')
    .replace(/\bhuman_only\b/gi, 'operator gated')
    .replace(/_/g, ' ');
}

export function publicRuntimeId(value: string | null | undefined): string | null {
  if (!value?.trim()) return null;
  return value.trim().replace(/paper/gi, 'rt');
}
