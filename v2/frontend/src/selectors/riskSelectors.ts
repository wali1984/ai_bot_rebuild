import type { TraderRealtimeState } from '../stores/traderRealtimeStore';

export function selectRiskStatus(state: TraderRealtimeState): string | null {
  const risk = state.snapshot?.risk.data;
  const status = risk?.status ?? risk?.classification ?? risk?.risk_status;
  return typeof status === 'string' ? status : null;
}

export function selectExecutionStatus(state: TraderRealtimeState): string {
  const executionStatus = state.snapshot?.execution_status;
  if (!executionStatus) return 'UNKNOWN';
  if (executionStatus.meta.quality === 'missing') return 'DISABLED';
  return 'RESTRICTED';
}
