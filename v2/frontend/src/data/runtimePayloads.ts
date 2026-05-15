import { useEffect, useState } from 'react';

export interface FrontendTruthPageCard {
  id: string;
  title: string;
  color: 'green' | 'yellow' | 'red' | string;
  summary: string;
  why_it_matters: string;
  what_needs_to_happen_next: string;
  evidence_paths: string[];
  source_status: string;
}

export interface FrontendTruthBlockerTechnical {
  id?: string | null;
  category?: string | null;
  remediation_task_id?: string | null;
  source?: string | null;
  evidence?: string | null;
}

export interface FrontendTruthPayload {
  schema_version: string;
  generated_utc: string;
  live_gate: string;
  live_symbols: string[];
  approves_live: boolean;
  approves_canary: boolean;
  approves_legacy_shutdown: boolean;
  approves_redis_trim: boolean;
  plain_english_summary: string;
  current_goal: string;
  shutdown_recommendation: string;
  paper_edge_status: string;
  trainer_parity_status: string;
  decision_quality_status: string;
  active_claude_task: string;
  active_codex_task: string;
  last_completed_fix: string;
  next_fix: string;
  blockers_simple: string[];
  blockers_technical: FrontendTruthBlockerTechnical[];
  page_cards: FrontendTruthPageCard[];
  stale_payloads: string[];
  missing_payloads: string[];
  source_status: Record<string, string>;
  evidence_paths: Record<string, string>;
}

const FRONTEND_TRUTH_PATH = '/operator_runtime/frontend_truth/latest/frontend_truth_payload.json';

interface UseFrontendTruth {
  payload: FrontendTruthPayload | null;
  error: string | null;
  loading: boolean;
}

export function useFrontendTruthPayload(pollMs = 30_000): UseFrontendTruth {
  const [payload, setPayload] = useState<FrontendTruthPayload | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState<boolean>(true);

  useEffect(() => {
    let cancelled = false;
    async function load() {
      try {
        const r = await fetch(FRONTEND_TRUTH_PATH, { cache: 'no-store' });
        if (!r.ok) throw new Error(`${FRONTEND_TRUTH_PATH}: ${r.status}`);
        const data = (await r.json()) as FrontendTruthPayload;
        if (cancelled) return;
        setPayload(data);
        setError(null);
      } catch (e) {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    }
    load();
    const handle = window.setInterval(load, pollMs);
    return () => {
      cancelled = true;
      window.clearInterval(handle);
    };
  }, [pollMs]);

  return { payload, error, loading };
}

export function isStalePayload(payload: FrontendTruthPayload | null, sourceKey: string): boolean {
  if (!payload) return false;
  return payload.stale_payloads.includes(sourceKey);
}

export function isMissingPayload(payload: FrontendTruthPayload | null, sourceKey: string): boolean {
  if (!payload) return false;
  return payload.missing_payloads.includes(sourceKey);
}
