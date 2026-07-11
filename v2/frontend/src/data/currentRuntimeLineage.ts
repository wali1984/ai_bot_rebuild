import { useRealtimeResource } from '../hooks/useRealtimeResource';

export const CURRENT_RUNTIME_LINEAGE_PATH = '/api/v2/paper/runtime-status';

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

function normalizeRuntimeStatusLineage(raw: unknown): CurrentRuntimeLineagePayload {
  const root = runtimeRecord(raw);
  const lineage = runtimeRecord(root.current_signal_lineage);
  if (Object.keys(lineage).length === 0) {
    return root as CurrentRuntimeLineagePayload;
  }
  const trainer = runtimeRecord(root.trainer_prediction ?? lineage.trainer_prediction);
  const risk = runtimeRecord(root.current_risk_decision ?? lineage.risk_decision);
  const orchestrator = runtimeRecord(lineage.orchestrator_decision);
  const featureSnapshot = runtimeRecord(lineage.feature_snapshot);
  return {
    generated_at: runtimeText(lineage.generated_at, root.generated_at),
    signal: runtimeRecord(lineage.signal),
    trainer_prediction: Object.keys(trainer).length ? trainer : null,
    risk_decision: Object.keys(risk).length ? risk : null,
    orchestrator_decision: Object.keys(orchestrator).length ? orchestrator : null,
    feature_snapshot: Object.keys(featureSnapshot).length ? featureSnapshot : null,
    lineage_ids: runtimeRecord(lineage.lineage_ids),
    classification: runtimeText(lineage.classification, root.heartbeat_classification),
  };
}

export function useCurrentRuntimeLineage(pollIntervalMs = 10_000) {
  return useRealtimeResource<CurrentRuntimeLineagePayload>({
    url: CURRENT_RUNTIME_LINEAGE_PATH,
    source: CURRENT_RUNTIME_LINEAGE_PATH,
    source_type: 'api',
    pollIntervalMs,
    staleThresholdMs: pollIntervalMs * 3,
    transform: normalizeRuntimeStatusLineage,
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
    .replace(/\bpaper[_ -]?only\b/gi, 'approval gated')
    .replace(/\bpaper[_ -]?runtime\b/gi, 'execution runtime')
    .replace(/\bpaper[_ -]?account\b/gi, 'account')
    .replace(/\bpaper\b/gi, 'runtime')
    .replace(/\bblocked_human_only\b/gi, 'approval required')
    .replace(/\bhuman_only\b/gi, 'approval required')
    .replace(/_/g, ' ');
}

export function publicRuntimeId(value: string | null | undefined): string | null {
  if (!value?.trim()) return null;
  return value.trim().replace(/paper/gi, 'rt');
}
