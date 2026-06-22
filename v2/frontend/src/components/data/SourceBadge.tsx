import type { SourceType } from '../../types/dataContract';

interface Props {
  sourceType: SourceType;
  source: string;
  endpoint?: string;
  compact?: boolean;
}

const SOURCE_ICON: Record<SourceType, string> = {
  websocket: 'WS',
  sse: 'SSE',
  api: 'API',
  repository: 'DB',
  redis_live: 'REDIS',
  stream: 'STR',
  cache: 'CACHE',
  static_payload: 'PAYLOAD',
  static_snapshot: 'SNAP',
  unavailable: '—',
};

const SOURCE_COLOR: Record<SourceType, string> = {
  websocket: 'var(--ok)',
  sse: 'var(--ok)',
  api: 'var(--info)',
  repository: 'var(--info)',
  redis_live: 'var(--ok)',
  stream: 'var(--ok)',
  cache: 'var(--warn)',
  static_payload: 'var(--warn)',
  static_snapshot: 'var(--warn)',
  unavailable: 'var(--text-muted)',
};

function publicSourceLabel(value: string | undefined): string {
  return (value ?? '')
    .replace(/paper/gi, 'runtime')
    .replace(/read[_\s-]*only/gi, 'account access')
    .replace(/blocked[_\s-]*human[_\s-]*only/gi, 'operator gated');
}

export function SourceBadge({ sourceType, source, endpoint, compact = false }: Props) {
  const icon = SOURCE_ICON[sourceType];
  const color = SOURCE_COLOR[sourceType];
  const safeSource = publicSourceLabel(source);
  const safeEndpoint = publicSourceLabel(endpoint);

  return (
    <span
      title={endpoint ? `${safeSource} → ${safeEndpoint}` : safeSource}
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: compact ? 3 : 5,
        fontSize: compact ? '10px' : '11px',
        fontWeight: 500,
        color: 'var(--text-secondary)',
        whiteSpace: 'nowrap',
      }}
    >
      <span
        style={{
          fontSize: '9px',
          fontWeight: 700,
          background: `color-mix(in oklch, ${color} 14%, transparent)`,
          color,
          border: `1px solid color-mix(in oklch, ${color} 40%, transparent)`,
          borderRadius: 3,
          padding: '1px 4px',
          letterSpacing: '0.04em',
        }}
      >
        {icon}
      </span>
      {!compact && (
        <span
          style={{
            maxWidth: 120,
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}
        >
          {safeSource}
        </span>
      )}
    </span>
  );
}
