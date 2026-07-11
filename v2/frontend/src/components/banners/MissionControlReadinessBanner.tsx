import {
  DEFAULT_ONLINE_READINESS_BANNER,
  deriveLaneStatus,
  type OnlineReadinessBannerPayload,
  type OnlineReadinessLane,
} from '../../constants/onlineReadinessBanner';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

const BANNER_ENDPOINT = '/api/v1/live-readiness/banner';

function normalizeLane(raw: Partial<OnlineReadinessLane> | null | undefined): OnlineReadinessLane | null {
  if (!raw || typeof raw !== 'object') return null;
  const lane_id = typeof raw.lane_id === 'string' ? raw.lane_id : '';
  if (!lane_id) return null;
  return {
    lane_id,
    description: typeof raw.description === 'string' ? raw.description : null,
    required_marker: typeof raw.required_marker === 'string' ? raw.required_marker : '',
    actual_marker: typeof raw.actual_marker === 'string' ? raw.actual_marker : null,
    marker_path: typeof raw.marker_path === 'string' ? raw.marker_path : '',
    found: Boolean(raw.found),
    matched: Boolean(raw.matched),
    is_required_for_online: raw.is_required_for_online !== false,
    error: typeof raw.error === 'string' ? raw.error : null,
  };
}

function normalizePayload(raw: Partial<OnlineReadinessBannerPayload> | null | undefined): OnlineReadinessBannerPayload {
  if (!raw || typeof raw !== 'object') return DEFAULT_ONLINE_READINESS_BANNER;
  const lanesIn = Array.isArray(raw.lanes) ? raw.lanes : [];
  const lanes = lanesIn
    .map((lane) => normalizeLane(lane as Partial<OnlineReadinessLane>))
    .filter((lane): lane is OnlineReadinessLane => lane !== null);
  return {
    rollup_version: typeof raw.rollup_version === 'string' ? raw.rollup_version : 'v1',
    generated_at: typeof raw.generated_at === 'string' ? raw.generated_at : '',
    go_no_go_marker: typeof raw.go_no_go_marker === 'string' ? raw.go_no_go_marker : '',
    all_required_matched: Boolean(raw.all_required_matched),
    blocking_lanes: Array.isArray(raw.blocking_lanes)
      ? raw.blocking_lanes.filter((entry): entry is string => typeof entry === 'string')
      : [],
    lanes,
    forbidden_operations: Array.isArray(raw.forbidden_operations)
      ? raw.forbidden_operations.filter((entry): entry is string => typeof entry === 'string')
      : [],
    live_gate_status: 'blocked_human_only',
  };
}

function transformOnlineReadinessPayload(raw: unknown): OnlineReadinessBannerPayload {
  return normalizePayload(raw as Partial<OnlineReadinessBannerPayload>);
}

export function MissionControlReadinessBanner(): JSX.Element {
  const { envelope, loading, error } = useRealtimeResource<OnlineReadinessBannerPayload>({
    url: BANNER_ENDPOINT,
    source: BANNER_ENDPOINT,
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    initialFetch: true,
    initialFetchWhenStreaming: true,
    httpFallback: true,
    enabled: true,
    mode: 'read_only',
    transform: transformOnlineReadinessPayload,
  });
  const payload = envelope.data ?? DEFAULT_ONLINE_READINESS_BANNER;
  const loadError = error ?? envelope.errors[0] ?? null;
  const loaded = !loading || envelope.data !== null || Boolean(loadError);

  const ready = payload.all_required_matched;
  const chipLabel = ready ? 'READY' : 'BLOCKED';
  const chipTone = ready
    ? 'mc-readiness-banner__chip--ready'
    : 'mc-readiness-banner__chip--blocked';
  const liveGateLabel = `live_gate_status: ${payload.live_gate_status}`;

  return (
    <section
      role="status"
      aria-live="polite"
      data-testid="mission-control-readiness-banner"
      data-ready={ready ? 'true' : 'false'}
      data-loaded={loaded ? 'true' : 'false'}
      data-blocking-count={String(payload.blocking_lanes.length)}
      className="mc-readiness-banner"
    >
      <header className="mc-readiness-banner__header">
        <span
          data-testid="mc-readiness-chip"
          data-chip-state={ready ? 'ready' : 'blocked'}
          className={`mc-readiness-banner__chip ${chipTone}`}
        >
          {chipLabel}
        </span>
        <span
          data-testid="mc-live-gate-status"
          data-live-gate-status={payload.live_gate_status}
          className="mc-readiness-banner__live-gate"
        >
          {liveGateLabel}
        </span>
        {payload.go_no_go_marker ? (
          <span
            data-testid="mc-readiness-go-no-go-marker"
            className="mc-readiness-banner__marker"
          >
            {payload.go_no_go_marker}
          </span>
        ) : null}
        {loadError ? (
          <span
            data-testid="mc-readiness-error"
            className="mc-readiness-banner__error"
          >
            error: {loadError}
          </span>
        ) : null}
      </header>
      <ul
        data-testid="mc-readiness-lane-list"
        data-lane-count={String(payload.lanes.length)}
        className="mc-readiness-banner__lane-list"
      >
        {payload.lanes.map((lane) => {
          const status = deriveLaneStatus(lane);
          return (
            <li
              key={lane.lane_id}
              data-testid={`mc-readiness-lane-${lane.lane_id}`}
              data-lane-id={lane.lane_id}
              data-lane-status={status}
              data-lane-required={lane.is_required_for_online ? 'true' : 'false'}
              className={`mc-readiness-banner__lane mc-readiness-banner__lane--${status}`}
            >
              <span className="mc-readiness-banner__lane-id">{lane.lane_id}</span>
              <span
                data-testid={`mc-readiness-lane-${lane.lane_id}-status`}
                className="mc-readiness-banner__lane-status"
              >
                {status}
              </span>
              <span
                data-testid={`mc-readiness-lane-${lane.lane_id}-marker-path`}
                className="mc-readiness-banner__lane-marker-path"
              >
                {lane.marker_path}
              </span>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
