import type { ReactNode } from 'react';

/**
 * Shared trader-first section divider — an uppercase kicker with a gradient
 * rule that trails off to the right. Used to group every trader page into
 * scannable bands (e.g. "Account · at a glance", "Positions", "Performance")
 * so the layout reads the way a trader thinks, top priority first.
 *
 * `hint` is an optional right-aligned note (counts, freshness, source).
 */
export function SectionLabel({
  children,
  hint,
}: {
  children: ReactNode;
  hint?: ReactNode;
}): JSX.Element {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        margin: '4px 0 12px',
      }}
    >
      <span
        style={{
          flex: '0 0 auto',
          fontSize: 11,
          fontWeight: 800,
          letterSpacing: '0.14em',
          textTransform: 'uppercase',
          color: 'var(--text-secondary)',
          whiteSpace: 'nowrap',
        }}
      >
        {children}
      </span>
      <span
        aria-hidden="true"
        style={{
          flex: '1 1 auto',
          height: 1,
          background:
            'linear-gradient(90deg, rgba(var(--glass-accent, 124, 92, 255), 0.42), transparent)',
        }}
      />
      {hint != null ? (
        <span
          style={{
            flex: '0 0 auto',
            fontSize: 11,
            fontWeight: 600,
            color: 'var(--text-muted)',
            fontFamily: 'var(--font-mono)',
            whiteSpace: 'nowrap',
          }}
        >
          {hint}
        </span>
      ) : null}
    </div>
  );
}

export default SectionLabel;
