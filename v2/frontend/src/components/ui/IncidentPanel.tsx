import React from 'react';

type Severity = 'critical' | 'warning' | 'info';

interface IncidentPanelProps {
  title: string;
  severity: Severity;
  source?: string;
  owner?: string;
  lastSeen?: string;
  message: string;
  remediation?: string;
}

const severityConfig: Record<Severity, { color: string; bg: string; label: string; icon: string }> = {
  critical: {
    color: 'var(--error)',
    bg: 'color-mix(in oklch, var(--error) 10%, transparent)',
    label: 'CRITICAL',
    icon: '✕',
  },
  warning: {
    color: 'var(--warn)',
    bg: 'color-mix(in oklch, var(--warn) 10%, transparent)',
    label: 'WARNING',
    icon: '⚠',
  },
  info: {
    color: 'var(--info)',
    bg: 'color-mix(in oklch, var(--info) 10%, transparent)',
    label: 'INFO',
    icon: 'ℹ',
  },
};

export const IncidentPanel: React.FC<IncidentPanelProps> = ({
  title,
  severity,
  source,
  owner,
  lastSeen,
  message,
  remediation,
}) => {
  const cfg = severityConfig[severity];

  return (
    <div
      data-testid="incident-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '10px',
        padding: '16px 20px',
        background: cfg.bg,
        border: `1px solid ${cfg.color}`,
        borderLeft: `4px solid ${cfg.color}`,
        borderRadius: 'var(--radius-md)',
        fontFamily: 'var(--font-sans)',
      }}
    >
      {/* Header row */}
      <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              width: '20px',
              height: '20px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: '50%',
              border: `1.5px solid ${cfg.color}`,
              color: cfg.color,
              fontSize: '11px',
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {cfg.icon}
          </span>
          <span
            style={{
              fontSize: '14px',
              fontWeight: 700,
              color: cfg.color,
            }}
          >
            {title}
          </span>
        </div>
        <span
          style={{
            fontSize: '10px',
            fontWeight: 700,
            letterSpacing: '0.08em',
            color: cfg.color,
            background: 'transparent',
            border: `1px solid ${cfg.color}`,
            borderRadius: '4px',
            padding: '2px 7px',
            whiteSpace: 'nowrap',
          }}
        >
          {cfg.label}
        </span>
      </div>

      {/* Meta row */}
      {(source || owner || lastSeen) && (
        <div style={{ display: 'flex', gap: '16px', flexWrap: 'wrap' }}>
          {source && (
            <MetaItem label="Source" value={source} />
          )}
          {owner && (
            <MetaItem label="Owner" value={owner} />
          )}
          {lastSeen && (
            <MetaItem label="Last Seen" value={lastSeen} mono />
          )}
        </div>
      )}

      {/* Message */}
      <p
        style={{
          margin: 0,
          fontSize: '13px',
          color: 'var(--text-secondary)',
          lineHeight: 1.6,
        }}
      >
        {message}
      </p>

      {/* Remediation */}
      {remediation && (
        <div
          style={{
            padding: '10px 14px',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--text-primary)', display: 'block', marginBottom: '4px' }}>
            Remediation
          </span>
          {remediation}
        </div>
      )}
    </div>
  );
};

function MetaItem({ label, value, mono }: { label: string; value: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '1px' }}>
      <span style={{ fontSize: '10px', fontWeight: 600, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
        {label}
      </span>
      <span
        style={{
          fontSize: '12px',
          color: 'var(--text-secondary)',
          fontFamily: mono ? 'var(--font-mono)' : 'var(--font-sans)',
        }}
      >
        {value}
      </span>
    </div>
  );
}

export default IncidentPanel;
