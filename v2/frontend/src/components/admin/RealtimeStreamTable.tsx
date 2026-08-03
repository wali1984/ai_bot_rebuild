interface StreamRow {
  id: string;
  timestamp: string;
  level: 'info' | 'warn' | 'error' | 'debug';
  source: string;
  message: string;
  meta?: Record<string, unknown>;
}

const LEVEL_COLOR: Record<StreamRow['level'], string> = {
  info:  'var(--ok)',
  warn:  'var(--warn)',
  error: 'var(--error)',
  debug: 'var(--text-muted)',
};

interface Props {
  rows: StreamRow[];
  loading?: boolean;
  maxRows?: number;
  title?: string;
}

export function RealtimeStreamTable({ rows, loading = false, maxRows = 50, title }: Props): JSX.Element {
  const visible = rows.slice(0, maxRows);

  return (
    <div data-testid="realtime-stream-table" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {title && (
        <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--text-primary)', display: 'flex', alignItems: 'center', gap: 6 }}>
          {title}
          {!loading && (
            <span style={{ fontSize: 11, color: 'var(--text-muted)', fontWeight: 400 }}>
              ({visible.length}{rows.length > maxRows ? `/${rows.length}` : ''})
            </span>
          )}
        </div>
      )}

      {loading ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading stream…</div>
      ) : visible.length === 0 ? (
        <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>No stream data.</div>
      ) : (
        <div style={{ display: 'flex', flexDirection: 'column', gap: 3, maxHeight: 360, overflowY: 'auto' }}>
          {visible.map((row) => {
            const color = LEVEL_COLOR[row.level];
            return (
              <div
                key={row.id}
                data-testid={`stream-row-${row.id}`}
                style={{
                  display: 'grid',
                  gridTemplateColumns: '160px 60px 120px 1fr',
                  alignItems: 'baseline',
                  gap: 10,
                  padding: '5px 10px',
                  background: 'var(--bg-elevated)',
                  borderRadius: 4,
                  fontSize: 11,
                  fontFamily: 'var(--font-mono)',
                }}
              >
                <span style={{ color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {row.timestamp}
                </span>
                <span style={{ color, fontWeight: 700, textTransform: 'uppercase' }}>
                  {row.level}
                </span>
                <span style={{ color: 'var(--text-secondary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {row.source}
                </span>
                <span style={{ color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                  {row.message}
                </span>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export type { StreamRow };
