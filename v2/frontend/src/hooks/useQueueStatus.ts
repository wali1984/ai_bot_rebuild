import { useRealtimeQuery, type RealtimeQueryResult } from './useRealtimeQuery';

export interface QueueCounts {
  pending: number;
  running: number;
  completed: number;
  failed: number;
  blocked: number;
  retry_scheduled: number;
  skipped: number;
  cancelled: number;
  human_attention_required: number;
  [extra: string]: number;
}

export interface BlockedQuota {
  task_id: string;
  agent: string | null;
  resume_after_utc: string | null;
}

export interface HumanAttentionTask {
  task_id: string;
  agent: string | null;
  attention_reason: string | null;
  last_summary?: string | null;
}

export interface QueueStatus {
  generated_at: string;
  next_pending_task: string | null;
  current_running_task: string | null;
  blocked_quota: BlockedQuota | null;
  stale_running_count: number;
  stale_running_tasks: string[];
  no_event_count: number;
  no_event_tasks: string[];
  no_output_growth_count: number;
  no_output_growth_tasks: string[];
  human_attention_required_count: number;
  human_attention_required_tasks: HumanAttentionTask[];
  counts: QueueCounts;
  gate: string;
}

export interface QueueStatusEnvelope {
  _meta: {
    source: string;
    read_at: string;
    error: string | null;
  };
  data: QueueStatus | null;
}

export const QUEUE_STATUS_URL = '/api/v1/_meta/queue-status';

export function useQueueStatus(): RealtimeQueryResult<QueueStatusEnvelope> {
  return useRealtimeQuery<QueueStatusEnvelope>(QUEUE_STATUS_URL, {
    refetchIntervalMs: 10_000,
  });
}
