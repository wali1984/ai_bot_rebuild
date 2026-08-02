import type { JSX } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

/**
 * Auto-generated trainer health banner.
 *
 * Renders the real per-lane trainer health published by
 * `v2_trainer_lane_health_publisher` and exposed on `/api/v2/trainer/status`
 * as `trainer_lane_health` / `trainer_alerts`.
 *
 * Honesty rules:
 *  - Never claims health it cannot prove. If the lane-health publisher itself
 *    is down, the banner says trainer failures cannot currently be detected
 *    rather than rendering a reassuring green bar.
 *  - Every lane is listed with its verdict, so a stopped/stalled trainer is
 *    visible instead of silently producing empty telemetry cells.
 */

export interface TrainerLaneAlert {
  severity?: string | null;
  lane_id?: string | null;
  label?: string | null;
  code?: string | null;
  message?: string | null;
  evidence_pointer?: string | null;
}

export interface TrainerLane {
  lane_id?: string | null;
  label?: string | null;
  unit?: string | null;
  health?: string | null;
  severity?: string | null;
  reason?: string | null;
  last_artifact_age_seconds?: number | null;
  process_elapsed_seconds?: number | null;
  redis_key?: string | null;
  redis_key_present?: boolean | null;
}

export interface TrainerLaneHealth {
  available?: boolean | null;
  generated_utc?: string | null;
  worst_severity?: string | null;
  alert_count?: number | null;
  healthy_lane_count?: number | null;
  total_lane_count?: number | null;
  lanes?: TrainerLane[] | null;
  alerts?: TrainerLaneAlert[] | null;
  reason?: string | null;
}

interface TrainerStatusWithHealth {
  trainer_lane_health?: TrainerLaneHealth | null;
  trainer_alerts?: TrainerLaneAlert[] | null;
}

const TONE = {
  error: { fg: '#ef5350', border: 'rgba(239,83,80,0.45)', bg: 'rgba(239,83,80,0.08)', icon: '⛔' },
  warn: { fg: '#f59e0b', border: 'rgba(245,158,11,0.45)', bg: 'rgba(245,158,11,0.08)', icon: '⚠️' },
  ok: { fg: '#26c281', border: 'rgba(38,194,129,0.35)', bg: 'rgba(38,194,129,0.06)', icon: '✅' },
} as const;

function toneFor(severity: string | null | undefined): (typeof TONE)[keyof typeof TONE] {
  if (severity === 'error') return TONE.error;
  if (severity === 'warn') return TONE.warn;
  return TONE.ok;
}

function healthColor(health: string | null | undefined): string {
  switch ((health ?? '').toUpperCase()) {
    case 'OK':
      return '#26c281';
    case 'HELD':
      return '#8bd6ff';
    case 'NOT_PUBLISHING':
    case 'UNKNOWN':
      return '#f59e0b';
    default:
      return '#ef5350';
  }
}

function ageLabel(seconds: number | null | undefined): string | null {
  if (typeof seconds !== 'number' || !Number.isFinite(seconds)) return null;
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

export function TrainerLaneHealthBanner(): JSX.Element {
  const { envelope } = useRealtimeResource<TrainerStatusWithHealth>({
    url: '/api/v2/trainer/status',
    source: '/api/v2/trainer/status',
    pollIntervalMs: 15_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
  });

  const health = envelope.data?.trainer_lane_health ?? null;
  const alerts = envelope.data?.trainer_alerts ?? health?.alerts ?? [];
  const lanes = health?.lanes ?? [];

  // The publisher is not reachable: refuse to imply the trainers are fine.
  const unavailable = !health || health.available === false;
  const severity = unavailable ? 'warn' : (health?.worst_severity ?? 'ok');
  const tone = toneFor(severity);

  const headline = unavailable
    ? 'Trainer health cannot be verified'
    : severity === 'error'
      ? `Trainer problem detected — ${alerts.filter((a) => a.severity === 'error').length} lane(s) failing`
      : severity === 'warn'
        ? `Trainer degraded — ${alerts.length} lane(s) need attention`
        : `All trainer lanes healthy (${health?.healthy_lane_count ?? 0}/${health?.total_lane_count ?? 0})`;

  return (
    <section
      data-testid="trainer-lane-health-banner"
      data-severity={severity}
      style={{
        marginBottom: 12,
        padding: '10px 12px',
        borderRadius: 10,
        border: `1px solid ${tone.border}`,
        background: tone.bg,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <span aria-hidden="true">{tone.icon}</span>
        <strong style={{ fontSize: 12.5, color: tone.fg }}>{headline}</strong>
        <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
          {health?.healthy_lane_count ?? 0}/{health?.total_lane_count ?? 0} lanes OK
          {health?.generated_utc ? ` · evidence ${String(health.generated_utc).slice(11, 19)}Z` : ''}
        </span>
      </div>

      {unavailable ? (
        <div style={{ marginTop: 6, fontSize: 11, color: 'var(--text-secondary)' }}>
          {health?.reason
            ?? 'The trainer lane-health publisher is not running, so a stopped or crashed trainer would not be detected here.'}
        </div>
      ) : null}

      {alerts.length > 0 ? (
        <ul
          data-testid="trainer-lane-health-alerts"
          style={{ margin: '8px 0 0', paddingLeft: 18, display: 'grid', gap: 4 }}
        >
          {alerts.map((alert, index) => (
            <li
              key={`${alert.lane_id ?? 'lane'}-${alert.code ?? index}`}
              style={{ fontSize: 11, color: alert.severity === 'error' ? '#ef5350' : 'var(--text-secondary)' }}
            >
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 9.5, color: 'var(--text-muted)', marginRight: 6 }}>
                {alert.code}
              </span>
              {alert.message}
              {alert.evidence_pointer ? (
                <span style={{ fontSize: 9.5, fontFamily: 'var(--font-mono)', color: 'var(--text-muted)' }}>
                  {' '}· {alert.evidence_pointer}
                </span>
              ) : null}
            </li>
          ))}
        </ul>
      ) : null}

      {lanes.length > 0 ? (
        <div style={{ marginTop: 8, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {lanes.map((lane) => {
            const age = ageLabel(lane.last_artifact_age_seconds);
            return (
              <span
                key={lane.lane_id ?? lane.label ?? 'lane'}
                data-testid={`trainer-lane-chip-${lane.lane_id}`}
                title={lane.reason ?? undefined}
                style={{
                  fontSize: 9.5,
                  fontFamily: 'var(--font-mono)',
                  padding: '2px 7px',
                  borderRadius: 999,
                  border: `1px solid ${healthColor(lane.health)}55`,
                  color: healthColor(lane.health),
                  background: 'var(--bg-base)',
                }}
              >
                {lane.label ?? lane.lane_id} · {lane.health}
                {age ? ` · ${age}` : ''}
              </span>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

export default TrainerLaneHealthBanner;
