import type { FreshnessStatus } from '../../types/dataContract';
import { freshnessColor, lagLabel } from '../../types/dataContract';

interface Props {
  status: FreshnessStatus;
  lagMs?: number | null;
  showLag?: boolean;
  compact?: boolean;
}

const LABEL: Record<FreshnessStatus, string> = {
  fresh: 'Live',
  delayed: 'Delayed',
  stale: 'Stale',
  offline: 'Offline',
  unavailable: 'Awaiting feed',
};

export function FreshnessBadge({ status, lagMs, showLag = true, compact = false }: Props) {
  const color = freshnessColor(status);
  const label = LABEL[status];
  const lag = showLag && lagMs != null ? ` · ${lagLabel(lagMs)}` : '';

  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '4px',
        fontSize: compact ? '10px' : '11px',
        fontWeight: 500,
        color,
        letterSpacing: '0.02em',
        whiteSpace: 'nowrap',
      }}
      title={`Freshness: ${label}${lag}`}
    >
      <span
        style={{
          width: compact ? 6 : 7,
          height: compact ? 6 : 7,
          borderRadius: '50%',
          background: color,
          flexShrink: 0,
          ...(status === 'fresh'
            ? { boxShadow: `0 0 4px ${color}` }
            : {}),
        }}
      />
      {!compact && label}
      {lag}
    </span>
  );
}
