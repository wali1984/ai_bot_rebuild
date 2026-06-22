import { useRealtimeQuery, type RealtimeQueryResult } from './useRealtimeQuery';

export interface RunSummary {
  task_id: string;
  agent: string | null;
  risk_level: string | null;
  status: string;
  start_time: string | null;
  end_time: string | null;
  summary: string | null;
  materialized_files: string[];
  timed_out: boolean;
  attention_reason: string | null;
  last_retry_reason: string | null;
  error: string | null;
}

export interface BuildStatusEnvelope {
  _meta: {
    source: string;
    read_at: string;
    total_runs: number;
    returned: number;
  };
  runs: RunSummary[];
}

export const BUILD_STATUS_URL = '/api/v1/_meta/build-status';

export function useBuildStatus(limit: number = 25): RealtimeQueryResult<BuildStatusEnvelope> {
  return useRealtimeQuery<BuildStatusEnvelope>(`${BUILD_STATUS_URL}?limit=${limit}`, {
    refetchIntervalMs: 30_000,
  });
}
