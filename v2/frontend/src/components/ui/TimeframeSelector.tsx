import React from 'react';

const DEFAULT_OPTIONS = ['1m', '5m', '15m', '1h', '4h', '1d', '1w'];

interface TimeframeSelectorProps {
  value: string;
  onChange: (tf: string) => void;
  options?: string[];
}

export const TimeframeSelector: React.FC<TimeframeSelectorProps> = ({
  value,
  onChange,
  options = DEFAULT_OPTIONS,
}) => {
  return (
    <div
      data-testid="timeframe-selector"
      role="group"
      aria-label="Timeframe selector"
      style={{
        display: 'inline-flex',
        gap: '2px',
        padding: '3px',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-sm)',
      }}
    >
      {options.map(tf => {
        const active = tf === value;
        return (
          <button
            key={tf}
            onClick={() => onChange(tf)}
            aria-pressed={active}
            style={{
              padding: '4px 10px',
              fontSize: '12px',
              fontWeight: active ? 700 : 500,
              fontFamily: 'var(--font-mono)',
              color: active ? 'var(--text-inverse)' : 'var(--text-secondary)',
              background: active ? 'var(--accent)' : 'transparent',
              border: 'none',
              borderRadius: '6px',
              cursor: 'pointer',
              transition: 'background var(--ease-fast), color var(--ease-fast)',
              lineHeight: '20px',
              whiteSpace: 'nowrap',
            }}
            onMouseEnter={e => {
              if (!active) {
                e.currentTarget.style.color = 'var(--text-primary)';
                e.currentTarget.style.background = 'var(--bg-hover)';
              }
            }}
            onMouseLeave={e => {
              if (!active) {
                e.currentTarget.style.color = 'var(--text-secondary)';
                e.currentTarget.style.background = 'transparent';
              }
            }}
          >
            {tf}
          </button>
        );
      })}
    </div>
  );
};

export default TimeframeSelector;
