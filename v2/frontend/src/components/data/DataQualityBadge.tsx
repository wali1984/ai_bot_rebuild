import type { DataQualityStatus } from '../../types/dataContract';
import { qualityColor } from '../../types/dataContract';

interface Props {
  status: DataQualityStatus;
  missingFields?: string[];
  compact?: boolean;
}

const LABEL: Record<DataQualityStatus, string> = {
  valid: 'Valid',
  partial: 'Partial',
  invalid: 'Invalid',
  missing: 'Missing',
  degraded: 'Degraded',
};

export function DataQualityBadge({ status, missingFields = [], compact = false }: Props) {
  const color = qualityColor(status);
  const label = LABEL[status];
  const title =
    missingFields.length > 0
      ? `${label} — missing: ${missingFields.join(', ')}`
      : `Data quality: ${label}`;

  return (
    <span
      title={title}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 4,
        fontSize: compact ? '10px' : '11px',
        fontWeight: 500,
        color,
        letterSpacing: '0.02em',
        whiteSpace: 'nowrap',
      }}
    >
      {!compact && label}
      {missingFields.length > 0 && !compact && (
        <span style={{ color: 'var(--text-muted)', fontWeight: 400 }}>
          ({missingFields.length} missing)
        </span>
      )}
    </span>
  );
}
