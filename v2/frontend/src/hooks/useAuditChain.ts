import { useRealtimeQuery, type RealtimeQueryResult } from './useRealtimeQuery';

export interface AuditEvent {
  event?: string;
  task_id?: string;
  ts?: string;
  [extra: string]: unknown;
}

export interface AuditChainBreak {
  index: number;
  previous_ts: string;
  current_ts: string;
  event?: string;
  task_id?: string;
}

export interface AuditChainEnvelope {
  _meta: {
    source: string;
    read_at: string;
    exists: boolean;
    returned: number;
    limit: number;
  };
  events: AuditEvent[];
  chain_intact: boolean;
  chain_breaks: AuditChainBreak[];
}

export const AUDIT_CHAIN_URL = '/api/v1/_meta/audit-chain';

export function useAuditChain(limit: number = 100): RealtimeQueryResult<AuditChainEnvelope> {
  return useRealtimeQuery<AuditChainEnvelope>(`${AUDIT_CHAIN_URL}?limit=${limit}`, {
    refetchIntervalMs: 30_000,
  });
}
