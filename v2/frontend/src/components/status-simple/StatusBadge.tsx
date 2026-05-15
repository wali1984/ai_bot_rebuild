import type { ReactElement } from 'react';

export interface StatusBadgeProps {
  color: 'green' | 'yellow' | 'red' | string;
  label: string;
}

export function StatusBadge({ color, label }: StatusBadgeProps): ReactElement {
  const bg = color === 'green' ? '#0e6b3a' : color === 'red' ? '#7a1d1d' : '#7a5b15';
  const fg = '#fff';
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 10px',
        borderRadius: 12,
        backgroundColor: bg,
        color: fg,
        fontSize: '0.75rem',
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: 0,
      }}
    >
      {label}
    </span>
  );
}

export interface SimpleCardProps {
  title: string;
  color: 'green' | 'yellow' | 'red' | string;
  summary: string;
  whyItMatters: string;
  whatNeedsToHappenNext: string;
  evidencePaths: string[];
  sourceStatus: string;
}

export function SimpleCard(props: SimpleCardProps): ReactElement {
  const {
    title,
    color,
    summary,
    whyItMatters,
    whatNeedsToHappenNext,
    evidencePaths,
    sourceStatus,
  } = props;
  return (
    <article
      style={{
        border: '1px solid rgba(255,255,255,0.1)',
        borderRadius: 8,
        padding: 16,
        marginBottom: 12,
        backgroundColor: 'rgba(255,255,255,0.02)',
      }}
    >
      <header style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 12 }}>
        <h3 style={{ margin: 0, fontSize: '1rem' }}>{title}</h3>
        <div style={{ display: 'flex', gap: 8 }}>
          <StatusBadge color={color} label={color === 'green' ? 'Safe' : color === 'red' ? 'Not safe yet' : 'Watching'} />
          <StatusBadge color={sourceStatus === 'FRESH' ? 'green' : sourceStatus === 'STALE' ? 'yellow' : 'red'} label={sourceStatus} />
        </div>
      </header>
      <p style={{ margin: '8px 0 4px 0' }}>{summary}</p>
      <p style={{ margin: '4px 0 4px 0', opacity: 0.85 }}>
        <strong>Why this matters:</strong> {whyItMatters}
      </p>
      <p style={{ margin: '4px 0 8px 0', opacity: 0.85 }}>
        <strong>What needs to happen next:</strong> {whatNeedsToHappenNext}
      </p>
      {evidencePaths.length > 0 && (
        <details>
          <summary>Evidence</summary>
          <ul style={{ margin: '8px 0 0 0', paddingLeft: 18 }}>
            {evidencePaths.map((p) => (
              <li key={p}>
                <code>{p}</code>
              </li>
            ))}
          </ul>
        </details>
      )}
    </article>
  );
}
