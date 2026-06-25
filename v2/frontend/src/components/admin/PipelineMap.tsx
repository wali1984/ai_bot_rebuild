import type { AdminSource, SourceStatus } from '../../types/adminData';

const STATUS_COLOR: Record<SourceStatus, string> = {
  ok: 'var(--ok)',
  warn: 'var(--warn)',
  error: 'var(--error)',
  gap: 'var(--error)',
  unknown: 'var(--text-muted)',
};

function lagDisplay(ms: number | null | undefined): string {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

function relativeAge(iso: string | null | undefined): string {
  if (!iso) return '—';
  const ms = Date.now() - Date.parse(iso);
  const sec = Math.floor(ms / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
}

interface Props {
  sources: AdminSource[];
  loading?: boolean;
}

export function PipelineMap({ sources, loading = false }: Props): JSX.Element {
  if (loading) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Loading pipeline…</div>
    );
  }

  if (!sources.length) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>
        No pipeline source data available.
      </div>
    );
  }

  return (
    <div data-testid="pipeline-map" style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      {sources.map((src) => {
        const color = STATUS_COLOR[src.status] ?? 'var(--text-muted)';
        return (
          <div
            key={src.id}
            data-testid={`pipeline-source-${src.id}`}
            style={{
              display: 'grid',
              gridTemplateColumns: '160px 70px 80px 80px 1fr',
              alignItems: 'center',
              gap: 10,
              padding: '7px 12px',
              background: 'var(--bg-elevated)',
              border: `1px solid ${color}33`,
              borderLeft: `3px solid ${color}`,
              borderRadius: 6,
              fontSize: 12,
            }}
          >
            <span style={{ fontWeight: 600, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', color: 'var(--text-primary)' }}>
              {src.dataset}
            </span>
            <span style={{ color, fontFamily: 'var(--font-mono)', fontSize: 11, fontWeight: 700 }}>
              {src.status.toUpperCase()}
            </span>
            <span style={{ color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              lag {lagDisplay(src.lag_ms)}
            </span>
            <span style={{ color: src.gap_count > 0 ? 'var(--error)' : 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              {src.gap_count} gap{src.gap_count !== 1 ? 's' : ''}
            </span>
            <span style={{ color: 'var(--text-muted)', fontSize: 11, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              {src.last_record_at ? relativeAge(src.last_record_at) + ' ago' : 'never'}
              {' · '}
              {src.downstream_consumers.length} consumer{src.downstream_consumers.length !== 1 ? 's' : ''}
            </span>
          </div>
        );
      })}
    </div>
  );
}
