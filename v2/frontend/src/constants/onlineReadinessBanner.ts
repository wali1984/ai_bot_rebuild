export type OnlineReadinessLaneStatus = 'matched' | 'missing' | 'divergent' | 'error';

export type OnlineReadinessLiveGateStatus = 'blocked_human_only';

export interface OnlineReadinessLane {
  lane_id: string;
  description?: string | null;
  required_marker: string;
  actual_marker: string | null;
  marker_path: string;
  found: boolean;
  matched: boolean;
  is_required_for_online: boolean;
  error: string | null;
}

export interface OnlineReadinessBannerPayload {
  rollup_version: string;
  generated_at: string;
  go_no_go_marker: string;
  all_required_matched: boolean;
  blocking_lanes: string[];
  lanes: OnlineReadinessLane[];
  forbidden_operations: string[];
  live_gate_status: OnlineReadinessLiveGateStatus;
}

export const DEFAULT_ONLINE_READINESS_BANNER: OnlineReadinessBannerPayload = {
  rollup_version: 'v1',
  generated_at: '',
  go_no_go_marker: '',
  all_required_matched: false,
  blocking_lanes: [],
  lanes: [],
  forbidden_operations: [],
  live_gate_status: 'blocked_human_only',
};

export function deriveLaneStatus(lane: OnlineReadinessLane): OnlineReadinessLaneStatus {
  if (lane.error === 'missing' || !lane.found) return 'missing';
  if (lane.error) return 'error';
  if (!lane.matched) return 'divergent';
  return 'matched';
}
