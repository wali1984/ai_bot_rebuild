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

interface Props {
  sources: AdminSource[];
  loading?: boolean;
}

export function SourceCoverageTable({ sources, loading = false }: Props): JSX.Element {
  if (loading) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>
        Loading source coverage…
      </div>
    );
  }

  if (!sources.length) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-muted)', padding: '12px 0' }}>
        No source data available.
      </div>
    );
  }

  return (
    <div data-testid="source-coverage-table" style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12 }}>
        <thead>
          <tr style={{ borderBottom: '1px solid var(--line-soft)' }}>
            {['Dataset', 'Status', 'Lag', 'Throughput', 'Gaps', 'Errors'].map((h) => (
              <th key={h} style={{ padding: '6px 10px', textAlign: 'left', fontWeight: 600, color: 'var(--text-muted)', whiteSpace: 'nowrap' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sources.map((src) => {
            const color = STATUS_COLOR[src.status] ?? 'var(--text-muted)';
            return (
              <tr key={src.id} data-testid={`source-row-${src.id}`} style={{ borderBottom: '1px solid var(--line-soft)' }}>
                <td style={{ padding: '7px 10px', fontWeight: 600, color: 'var(--text-primary)', whiteSpace: 'nowrap' }}>{src.dataset}</td>
                <td style={{ padding: '7px 10px' }}>
                  <span style={{ display: 'inline-block', padding: '2px 7px', borderRadius: 4, background: color, color: '#fff', fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                    {src.status.toUpperCase()}
                  </span>
                </td>
                <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>{lagDisplay(src.lag_ms)}</td>
                <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)' }}>
                  {src.throughput !== null && src.throughput !== undefined ? `${src.throughput}/min` : '—'}
                </td>
                <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: src.gap_count > 0 ? 'var(--error)' : 'var(--text-muted)' }}>{src.gap_count}</td>
                <td style={{ padding: '7px 10px', fontFamily: 'var(--font-mono)', color: src.error_count > 0 ? 'var(--error)' : 'var(--text-muted)' }}>{src.error_count}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
