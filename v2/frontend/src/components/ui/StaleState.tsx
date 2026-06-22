import React from 'react';

interface StaleStateProps {
  message?: string;
  lastUpdated?: string;
}

export const StaleState: React.FC<StaleStateProps> = ({
  message = 'Data may be stale or delayed.',
  lastUpdated,
}) => {
  return (
    <div
      data-testid="stale-state"
      style={{
        display: 'flex',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '14px 18px',
        background: 'color-mix(in oklch, var(--warn) 10%, transparent)',
        border: '1px solid var(--warn)',
        borderRadius: 'var(--radius-md)',
        borderLeft: '4px solid var(--warn)',
      }}
    >
      <svg
        width="18"
        height="18"
        viewBox="0 0 18 18"
        fill="none"
        aria-hidden="true"
        style={{ flexShrink: 0, marginTop: '1px' }}
      >
        <path
          d="M9 2L16.5 15H1.5L9 2Z"
          stroke="var(--warn)"
          strokeWidth="1.5"
          strokeLinejoin="round"
        />
        <path d="M9 7v4" stroke="var(--warn)" strokeWidth="1.6" strokeLinecap="round" />
        <circle cx="9" cy="12.5" r="0.8" fill="var(--warn)" />
      </svg>
      <div style={{ display: 'flex', flexDirection: 'column', gap: '4px' }}>
        <span
          style={{
            fontSize: '13px',
            fontWeight: 600,
            color: 'var(--warn)',
            fontFamily: 'var(--font-sans)',
          }}
        >
          Stale / Delayed Data
        </span>
        <span
          style={{
            fontSize: '12px',
            color: 'var(--text-secondary)',
            fontFamily: 'var(--font-sans)',
            lineHeight: 1.5,
          }}
        >
          {message}
        </span>
        {lastUpdated && (
          <span
            style={{
              fontSize: '11px',
              color: 'var(--text-muted)',
              fontFamily: 'var(--font-mono)',
              marginTop: '2px',
            }}
          >
            Last updated: {lastUpdated}
          </span>
        )}
      </div>
    </div>
  );
};

export default StaleState;
