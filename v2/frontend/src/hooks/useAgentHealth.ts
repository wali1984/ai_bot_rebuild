import { useCallback } from 'react';
import { fetchJson, usePollingQuery, type PollingQueryResult } from './usePollingQuery';

export interface SupervisorHeartbeat {
  pid: number;
  tmux_session: string | null;
  loop_count: number;
  last_loop_ts: string | null;
  current_task: string | null;
  last_event_ts: string | null;
  started_at: string | null;
  version: string | null;
}

export interface AgentHealthBlob {
  generated_at: string;
  terminal_operator?: string | null;
  active_agents: string[];
  claude?: Record<string, unknown> | null;
  codex?: Record<string, unknown> | null;
  ollama?: Record<string, unknown> | null;
  last_auto_commit_hash?: string | null;
  supervisor_version?: string | null;
}

export interface AgentHealthEnvelope {
  _meta: {
    agent_health_source: string;
    heartbeat_source: string;
    read_at: string;
    agent_health_error: string | null;
    heartbeat_error: string | null;
  };
  agent_health: AgentHealthBlob | null;
  heartbeat: SupervisorHeartbeat | null;
  heartbeat_age_s: number | null;
  heartbeat_stale: boolean;
  heartbeat_missing: boolean;
}

export const AGENT_HEALTH_URL = '/api/v1/_meta/agent-health';

export function useAgentHealth(): PollingQueryResult<AgentHealthEnvelope> {
  const fetcher = useCallback(
    (signal: AbortSignal) => fetchJson<AgentHealthEnvelope>(AGENT_HEALTH_URL, signal),
    [],
  );
  return usePollingQuery<AgentHealthEnvelope>('agent-health', fetcher, {
    refetchIntervalMs: 15_000,
  });
}
