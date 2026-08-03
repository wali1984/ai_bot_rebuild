import React from 'react';

interface EmptyStateProps {
  icon?: string;
  title: string;
  message?: string;
  action?: { label: string; onClick: () => void };
}

export const EmptyState: React.FC<EmptyStateProps> = ({ icon, title, message, action }) => {
  return (
    <div
      data-testid="empty-state"
      style={{
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        justifyContent: 'center',
        padding: '48px 24px',
        textAlign: 'center',
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        gap: '12px',
      }}
    >
      {icon && (
        <span
          style={{
            fontSize: '40px',
            lineHeight: 1,
            marginBottom: '4px',
            opacity: 0.7,
          }}
          aria-hidden="true"
        >
          {icon}
        </span>
      )}
      <h3
        style={{
          margin: 0,
          fontSize: '16px',
          fontWeight: 600,
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-sans)',
        }}
      >
        {title}
      </h3>
      {message && (
        <p
          style={{
            margin: 0,
            fontSize: '14px',
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-sans)',
            maxWidth: '320px',
            lineHeight: 1.5,
          }}
        >
          {message}
        </p>
      )}
      {action && (
        <button
          onClick={action.onClick}
          style={{
            marginTop: '8px',
            padding: '8px 20px',
            background: 'var(--accent)',
            color: 'var(--text-inverse)',
            border: 'none',
            borderRadius: 'var(--radius-sm)',
            fontSize: '13px',
            fontWeight: 600,
            fontFamily: 'var(--font-sans)',
            cursor: 'pointer',
            transition: 'opacity var(--ease-fast)',
          }}
          onMouseEnter={e => (e.currentTarget.style.opacity = '0.85')}
          onMouseLeave={e => (e.currentTarget.style.opacity = '1')}
        >
          {action.label}
        </button>
      )}
    </div>
  );
};

export default EmptyState;
