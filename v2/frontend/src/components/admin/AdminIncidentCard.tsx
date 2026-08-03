import type { AdminIncident, IncidentSeverity } from '../../types/adminData';

const SEVERITY_STYLE: Record<IncidentSeverity, { border: string; bg: string; label: string; color: string }> = {
  critical: {
    border: 'color-mix(in oklch, var(--error) 45%, transparent)',
    bg: 'color-mix(in oklch, var(--error) 8%, var(--bg-panel))',
    label: 'CRITICAL',
    color: 'var(--error)',
  },
  high: {
    border: 'color-mix(in oklch, var(--error) 30%, transparent)',
    bg: 'color-mix(in oklch, var(--error) 5%, var(--bg-panel))',
    label: 'HIGH',
    color: 'var(--error)',
  },
  medium: {
    border: 'color-mix(in oklch, var(--warn) 40%, transparent)',
    bg: 'color-mix(in oklch, var(--warn) 6%, var(--bg-panel))',
    label: 'MEDIUM',
    color: 'var(--warn)',
  },
  low: {
    border: 'var(--border)',
    bg: 'var(--bg-elevated)',
    label: 'LOW',
    color: 'var(--text-secondary)',
  },
};

interface Props {
  incident: AdminIncident;
  compact?: boolean;
}

export function AdminIncidentCard({ incident, compact = false }: Props): JSX.Element {
  const s = SEVERITY_STYLE[incident.severity] ?? SEVERITY_STYLE.medium;

  return (
    <div
      data-testid={`admin-incident-card-${incident.incident_id}`}
      style={{
        border: `1px solid ${s.border}`,
        background: s.bg,
        borderRadius: 8,
        padding: compact ? '8px 12px' : '12px 16px',
        fontSize: 12,
        display: 'flex',
        flexDirection: 'column',
        gap: 6,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          style={{
            padding: '2px 7px',
            borderRadius: 4,
            background: s.color,
            color: '#fff',
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            flexShrink: 0,
          }}
        >
          {s.label}
        </span>
        <span style={{ fontWeight: 600, color: 'var(--text-primary)', flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {incident.missing_source}
        </span>
        <span style={{ fontFamily: 'var(--font-mono)', color: 'var(--text-muted)', fontSize: 10, flexShrink: 0 }}>
          #{incident.incident_id}
        </span>
      </div>

      <div style={{ color: 'var(--text-secondary)' }}>
        <strong>Expected:</strong> {incident.expected_endpoint}
      </div>
      <div style={{ color: 'var(--text-secondary)' }}>
        <strong>Owner:</strong> {incident.owner_service}
      </div>
      <div style={{ color: 'var(--error)' }}>
        <strong>Error:</strong> {incident.current_error}
      </div>

      {!compact && (
        <>
          {incident.affected_pages.length > 0 && (
            <div style={{ color: 'var(--text-muted)' }}>
              <strong>Affects:</strong> {incident.affected_pages.join(', ')}
            </div>
          )}
          <div
            style={{
              padding: '6px 10px',
              background: 'color-mix(in oklch, var(--warn) 6%, var(--bg-elevated))',
              border: '1px solid color-mix(in oklch, var(--warn) 25%, transparent)',
              borderRadius: 6,
              color: 'var(--warn)',
            }}
          >
            <strong>Remediation:</strong> {incident.remediation_action}
          </div>
          {incident.last_success_at && (
            <div style={{ color: 'var(--text-muted)', fontSize: 11, fontFamily: 'var(--font-mono)' }}>
              Last success: {incident.last_success_at}
            </div>
          )}
        </>
      )}
    </div>
  );
}
