import React, { useState, useMemo } from 'react';
import { LoadingSkeleton } from './LoadingSkeleton';

export interface Column<T> {
  key: string;
  header: string;
  render: (row: T, i: number) => React.ReactNode;
  width?: string;
  align?: 'left' | 'center' | 'right';
  sortable?: boolean;
}

interface ProTableProps<T> {
  columns: Column<T>[];
  data: T[];
  rowKey: (row: T, i: number) => string;
  loading?: boolean;
  empty?: React.ReactNode;
  className?: string;
  compact?: boolean;
  stickyHeader?: boolean;
}

type SortDir = 'asc' | 'desc' | null;

export function ProTable<T>({
  columns,
  data,
  rowKey,
  loading = false,
  empty,
  className,
  compact = false,
  stickyHeader = false,
}: ProTableProps<T>) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>(null);

  const rowHeight = compact
    ? 'var(--table-row-height-compact)'
    : 'var(--table-row-height)';

  function handleSort(col: Column<T>) {
    if (!col.sortable) return;
    if (sortKey === col.key) {
      setSortDir(prev => (prev === 'asc' ? 'desc' : prev === 'desc' ? null : 'asc'));
      if (sortDir === 'desc') setSortKey(null);
    } else {
      setSortKey(col.key);
      setSortDir('asc');
    }
  }

  // Client-side sort: we sort by render output if string, otherwise stable by index
  const sortedData = useMemo(() => {
    if (!sortKey || !sortDir) return data;
    const col = columns.find(c => c.key === sortKey);
    if (!col) return data;
    return [...data].sort((a, b) => {
      const av = col.render(a, 0);
      const bv = col.render(b, 0);
      const as = String(av ?? '');
      const bs = String(bv ?? '');
      const cmp = as.localeCompare(bs, undefined, { numeric: true, sensitivity: 'base' });
      return sortDir === 'asc' ? cmp : -cmp;
    });
  }, [data, sortKey, sortDir, columns]);

  const headerBg = stickyHeader
    ? { position: 'sticky' as const, top: 0, zIndex: 2, background: 'var(--bg-panel)' }
    : {};

  return (
    <div
      data-testid="pro-table"
      className={className}
      style={{
        width: '100%',
        overflowX: 'auto',
        overflowY: stickyHeader ? 'auto' : undefined,
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--bg-panel)',
        fontFamily: 'var(--font-sans)',
      }}
    >
      <table
        style={{
          width: '100%',
          borderCollapse: 'collapse',
          tableLayout: 'auto',
        }}
      >
        <thead>
          <tr
            style={{
              ...headerBg,
              borderBottom: '1px solid var(--border-strong)',
            }}
          >
            {columns.map(col => (
              <th
                key={col.key}
                onClick={() => handleSort(col)}
                style={{
                  padding: compact ? '6px 12px' : '10px 14px',
                  textAlign: col.align ?? 'left',
                  fontSize: '11px',
                  fontWeight: 600,
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.06em',
                  width: col.width,
                  cursor: col.sortable ? 'pointer' : 'default',
                  userSelect: 'none',
                  whiteSpace: 'nowrap',
                }}
              >
                <span style={{ display: 'inline-flex', alignItems: 'center', gap: '4px' }}>
                  {col.header}
                  {col.sortable && (
                    <span
                      style={{
                        fontSize: '10px',
                        color:
                          sortKey === col.key ? 'var(--accent)' : 'var(--text-muted)',
                        opacity: sortKey === col.key ? 1 : 0.5,
                      }}
                    >
                      {sortKey === col.key && sortDir === 'asc'
                        ? '▲'
                        : sortKey === col.key && sortDir === 'desc'
                        ? '▼'
                        : '⇅'}
                    </span>
                  )}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading ? (
            <tr>
              <td colSpan={columns.length} style={{ padding: '20px 14px' }}>
                <LoadingSkeleton rows={compact ? 3 : 5} height={compact ? '20px' : '28px'} />
              </td>
            </tr>
          ) : sortedData.length === 0 ? (
            <tr>
              <td
                colSpan={columns.length}
                style={{
                  padding: '40px 14px',
                  textAlign: 'center',
                  color: 'var(--text-muted)',
                  fontSize: '13px',
                }}
              >
                {empty ?? 'Awaiting feed.'}
              </td>
            </tr>
          ) : (
            sortedData.map((row, i) => (
              <tr
                key={rowKey(row, i)}
                style={{
                  borderBottom: i < sortedData.length - 1 ? '1px solid var(--border)' : 'none',
                  height: rowHeight,
                  transition: 'background var(--ease-fast)',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                {columns.map(col => (
                  <td
                    key={col.key}
                    style={{
                      padding: compact ? '4px 12px' : '8px 14px',
                      textAlign: col.align ?? 'left',
                      fontSize: compact ? '12px' : '13px',
                      color: 'var(--text-primary)',
                      verticalAlign: 'middle',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {col.render(row, i)}
                  </td>
                ))}
              </tr>
            ))
          )}
        </tbody>
      </table>
    </div>
  );
}

export default ProTable;
