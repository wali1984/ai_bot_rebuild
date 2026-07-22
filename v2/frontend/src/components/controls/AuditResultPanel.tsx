import React from 'react';

type Result = 'success' | 'failure' | 'pending' | 'unknown';

interface AuditResultPanelProps {
  actor: unknown;
  action: unknown;
  result: Result;
  timestamp: unknown;
  reason?: unknown;
  evidence?: unknown;
}

const displayValue = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (value == null) return '';
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
};

const resultConfig: Record<Result, { color: string; bg: string; label: string; icon: string }> = {
  success: {
    color: 'var(--ok)',
    bg: 'color-mix(in oklch, var(--ok) 10%, transparent)',
    label: 'SUCCESS',
    icon: '✓',
  },
  failure: {
    color: 'var(--error)',
    bg: 'color-mix(in oklch, var(--error) 10%, transparent)',
    label: 'FAILURE',
    icon: '✕',
  },
  pending: {
    color: 'var(--warn)',
    bg: 'color-mix(in oklch, var(--warn) 10%, transparent)',
    label: 'PENDING',
    icon: '…',
  },
  unknown: {
    color: 'var(--warn)',
    bg: 'color-mix(in oklch, var(--warn) 10%, transparent)',
    label: 'UNKNOWN',
    icon: '?',
  },
};

export const AuditResultPanel: React.FC<AuditResultPanelProps> = ({
  actor,
  action,
  result,
  timestamp,
  reason,
  evidence,
}) => {
  // Backend audit records are append-only and may gain new result enums.
  // Preserve the evidence without crashing the whole audit page or implying
  // that an unrecognised result is pending/successful.
  const cfg = resultConfig[result] ?? resultConfig.unknown;
  const displayReason = displayValue(reason);
  const displayEvidence = displayValue(evidence);
  const displayActor = displayValue(actor);
  const displayAction = displayValue(action);
  const displayTimestamp = displayValue(timestamp);

  return (
    <div
      data-testid="audit-result-panel"
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
      {/* Result badge + timestamp row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '12px' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
          <span
            style={{
              width: '22px',
              height: '22px',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              borderRadius: '50%',
              border: `1.5px solid ${cfg.color}`,
              color: cfg.color,
              fontSize: '12px',
              fontWeight: 700,
              flexShrink: 0,
            }}
          >
            {cfg.icon}
          </span>
          <span
            style={{
              fontSize: '10px',
              fontWeight: 700,
              letterSpacing: '0.08em',
              color: cfg.color,
              border: `1px solid ${cfg.color}`,
              borderRadius: '4px',
              padding: '2px 7px',
            }}
          >
            {cfg.label}
          </span>
        </div>
        <span
          style={{
            fontSize: '11px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'nowrap',
          }}
        >
          {displayTimestamp}
        </span>
      </div>

      {/* Actor + action */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'baseline' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
            Actor
          </span>
          <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontWeight: 600, fontFamily: 'var(--font-mono)' }}>
            {displayActor}
          </span>
        </div>
        <div style={{ display: 'flex', gap: '6px', alignItems: 'baseline' }}>
          <span style={{ fontSize: '11px', color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', fontWeight: 600 }}>
            Action
          </span>
          <span style={{ fontSize: '13px', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
            {displayAction}
          </span>
        </div>
      </div>

      {/* Reason */}
      {displayReason && (
        <div
          style={{
            padding: '8px 12px',
            background: 'var(--bg-elevated)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            color: 'var(--text-secondary)',
            lineHeight: 1.55,
          }}
        >
          <span style={{ fontWeight: 600, color: 'var(--text-primary)' }}>Reason: </span>
          {displayReason}
        </div>
      )}

      {/* Evidence */}
      {displayEvidence && (
        <div
          style={{
            padding: '8px 12px',
            background: 'var(--bg-base)',
            border: '1px solid var(--border)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '11px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            lineHeight: 1.6,
            whiteSpace: 'pre-wrap',
            wordBreak: 'break-all',
          }}
        >
          <span style={{ display: 'block', fontWeight: 700, marginBottom: '4px', color: 'var(--text-secondary)', fontFamily: 'var(--font-sans)', fontSize: '10px', textTransform: 'uppercase', letterSpacing: '0.06em' }}>
            Evidence
          </span>
          {displayEvidence}
        </div>
      )}
    </div>
  );
};

export default AuditResultPanel;
