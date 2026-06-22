import React from 'react';

interface ErrorStateProps {
  title?: string;
  message: string;
  retry?: () => void;
}

export const ErrorState: React.FC<ErrorStateProps> = ({
  title = 'Error',
  message,
  retry,
}) => {
  return (
    <div
      data-testid="error-state"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'flex-start',
        gap: '10px',
        padding: '20px 24px',
        background: 'var(--bg-panel)',
        border: '1px solid var(--error)',
        borderRadius: 'var(--radius-md)',
        borderLeft: '4px solid var(--error)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
        <svg
          width="18"
          height="18"
          viewBox="0 0 18 18"
          fill="none"
          aria-hidden="true"
          style={{ flexShrink: 0 }}
        >
          <circle cx="9" cy="9" r="8.5" stroke="var(--error)" />
          <path d="M9 5v5" stroke="var(--error)" strokeWidth="1.6" strokeLinecap="round" />
          <circle cx="9" cy="13" r="0.8" fill="var(--error)" />
        </svg>
        <span
          style={{
            fontSize: '14px',
            fontWeight: 700,
            color: 'var(--error)',
            fontFamily: 'var(--font-sans)',
          }}
        >
          {title}
        </span>
      </div>
      <p
        style={{
          margin: 0,
          fontSize: '13px',
          color: 'var(--text-secondary)',
          fontFamily: 'var(--font-sans)',
          lineHeight: 1.55,
        }}
      >
        {message}
      </p>
      {retry && (
        <button
          onClick={retry}
          style={{
            marginTop: '4px',
            padding: '6px 16px',
            background: 'transparent',
            color: 'var(--error)',
            border: '1px solid var(--error)',
            borderRadius: 'var(--radius-sm)',
            fontSize: '12px',
            fontWeight: 600,
            fontFamily: 'var(--font-sans)',
            cursor: 'pointer',
            transition: 'background var(--ease-fast)',
          }}
          onMouseEnter={e => {
            e.currentTarget.style.background = 'color-mix(in oklch, var(--error) 14%, transparent)';
          }}
          onMouseLeave={e => {
            e.currentTarget.style.background = 'transparent';
          }}
        >
          Retry
        </button>
      )}
    </div>
  );
};

export default ErrorState;
