import React from 'react';

type Freshness = 'fresh' | 'delayed' | 'stale' | 'offline';
type Size = 'sm' | 'md' | 'lg';

interface MetricCardProps {
  label: string;
  value: React.ReactNode;
  change?: number;
  changeLabel?: string;
  source?: string;
  freshness?: Freshness;
  className?: string;
  size?: Size;
}

const freshnessColor: Record<Freshness, string> = {
  fresh: 'var(--ok)',
  delayed: 'var(--warn)',
  stale: 'var(--warn)',
  offline: 'var(--error)',
};

const freshnessLabel: Record<Freshness, string> = {
  fresh: '● live',
  delayed: '● delayed',
  stale: '● stale',
  offline: '● offline',
};

const sizeMap: Record<Size, { valueFontSize: string; labelFontSize: string; padding: string }> = {
  sm: { valueFontSize: '20px', labelFontSize: '11px', padding: '14px 16px' },
  md: { valueFontSize: '28px', labelFontSize: '12px', padding: '18px 20px' },
  lg: { valueFontSize: '36px', labelFontSize: '13px', padding: '24px 28px' },
};

export const MetricCard: React.FC<MetricCardProps> = ({
  label,
  value,
  change,
  changeLabel,
  source,
  freshness,
  className,
  size = 'md',
}) => {
  const sz = sizeMap[size];
  const changeColor =
    change === undefined
      ? 'var(--text-muted)'
      : change > 0
      ? 'var(--buy)'
      : change < 0
      ? 'var(--sell)'
      : 'var(--text-muted)';

  const changePrefix = change !== undefined && change > 0 ? '+' : '';

  return (
    <div
      data-testid="metric-card"
      className={className}
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '6px',
        padding: sz.padding,
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        fontFamily: 'var(--font-sans)',
        minWidth: 0,
      }}
    >
      {/* Label row */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          gap: '8px',
        }}
      >
        <span
          style={{
            fontSize: sz.labelFontSize,
            fontWeight: 500,
            color: 'var(--text-muted)',
            textTransform: 'uppercase',
            letterSpacing: '0.06em',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {label}
        </span>
        {freshness && (
          <span
            style={{
              fontSize: '10px',
              fontWeight: 600,
              color: freshnessColor[freshness],
              letterSpacing: '0.04em',
              whiteSpace: 'nowrap',
            }}
          >
            {freshnessLabel[freshness]}
          </span>
        )}
      </div>

      {/* Value */}
      <div
        style={{
          fontSize: sz.valueFontSize,
          fontWeight: 700,
          color: 'var(--text-primary)',
          fontFamily: 'var(--font-mono)',
          lineHeight: 1.15,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {value}
      </div>

      {/* Change + source row */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: '8px' }}>
        {change !== undefined && (
          <span
            style={{
              fontSize: '12px',
              fontWeight: 600,
              color: changeColor,
              fontFamily: 'var(--font-mono)',
            }}
          >
            {changePrefix}
            {change.toFixed(2)}%{changeLabel ? ` ${changeLabel}` : ''}
          </span>
        )}
        {source && (
          <span
            style={{
              fontSize: '10px',
              color: 'var(--text-muted)',
              background: 'var(--bg-elevated)',
              border: '1px solid var(--border)',
              borderRadius: '4px',
              padding: '1px 6px',
              fontFamily: 'var(--font-mono)',
              marginLeft: 'auto',
            }}
          >
            {source}
          </span>
        )}
      </div>
    </div>
  );
};

export default MetricCard;
