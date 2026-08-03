import React from 'react';

type CoverageStatus = 'live' | 'partial' | 'snapshot' | 'missing' | 'broken';

interface CoverageItem {
  label: string;
  status: CoverageStatus;
  source?: string;
  endpoint?: string;
  lastSeen?: string;
}

interface DataCoveragePanelProps {
  items: CoverageItem[];
}

const statusConfig: Record<CoverageStatus, { color: string; bg: string; label: string }> = {
  live: {
    color: 'var(--ok)',
    bg: 'color-mix(in oklch, var(--ok) 16%, transparent)',
    label: 'LIVE',
  },
  partial: {
    color: 'var(--warn)',
    bg: 'color-mix(in oklch, var(--warn) 16%, transparent)',
    label: 'PARTIAL',
  },
  snapshot: {
    color: 'var(--info)',
    bg: 'color-mix(in oklch, var(--info) 16%, transparent)',
    label: 'SNAPSHOT',
  },
  missing: {
    color: 'var(--text-muted)',
    bg: 'color-mix(in oklch, var(--text-muted) 10%, transparent)',
    label: 'MISSING',
  },
  broken: {
    color: 'var(--error)',
    bg: 'color-mix(in oklch, var(--error) 16%, transparent)',
    label: 'BROKEN',
  },
};

export const DataCoveragePanel: React.FC<DataCoveragePanelProps> = ({ items }) => {
  return (
    <div
      data-testid="data-coverage-panel"
      style={{
        display: 'flex',
        flexDirection: 'column',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md)',
        overflow: 'hidden',
        fontFamily: 'var(--font-sans)',
        background: 'var(--bg-panel)',
      }}
    >
      {/* Panel header */}
      <div
        style={{
          padding: '10px 16px',
          borderBottom: '1px solid var(--border)',
          fontSize: '11px',
          fontWeight: 700,
          color: 'var(--text-muted)',
          textTransform: 'uppercase',
          letterSpacing: '0.08em',
          background: 'var(--bg-elevated)',
          display: 'flex',
          justifyContent: 'space-between',
          alignItems: 'center',
        }}
      >
        <span>Data Coverage</span>
        <span style={{ fontWeight: 400, color: 'var(--text-muted)' }}>{items.length} sources</span>
      </div>

      {/* Items */}
      {items.length === 0 ? (
        <div
          style={{
            padding: '32px 16px',
            textAlign: 'center',
            color: 'var(--text-muted)',
            fontSize: '13px',
          }}
        >
          No coverage items.
        </div>
      ) : (
        <ul style={{ margin: 0, padding: 0, listStyle: 'none' }}>
          {items.map((item, i) => {
            const cfg = statusConfig[item.status];
            return (
              <li
                key={i}
                style={{
                  display: 'flex',
                  alignItems: 'flex-start',
                  justifyContent: 'space-between',
                  gap: '12px',
                  padding: '10px 16px',
                  borderBottom: i < items.length - 1 ? '1px solid var(--border)' : 'none',
                  transition: 'background var(--ease-fast)',
                }}
                onMouseEnter={e => (e.currentTarget.style.background = 'var(--bg-hover)')}
                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
              >
                {/* Left: label + meta */}
                <div style={{ display: 'flex', flexDirection: 'column', gap: '3px', minWidth: 0 }}>
                  <span
                    style={{
                      fontSize: '13px',
                      fontWeight: 600,
                      color: 'var(--text-primary)',
                      overflow: 'hidden',
                      textOverflow: 'ellipsis',
                      whiteSpace: 'nowrap',
                    }}
                  >
                    {item.label}
                  </span>
                  <div style={{ display: 'flex', gap: '10px', flexWrap: 'wrap' }}>
                    {item.source && (
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {item.source}
                      </span>
                    )}
                    {item.endpoint && (
                      <span
                        style={{
                          fontSize: '11px',
                          color: 'var(--text-muted)',
                          fontFamily: 'var(--font-mono)',
                          overflow: 'hidden',
                          textOverflow: 'ellipsis',
                          whiteSpace: 'nowrap',
                          maxWidth: '260px',
                        }}
                      >
                        {item.endpoint}
                      </span>
                    )}
                    {item.lastSeen && (
                      <span style={{ fontSize: '11px', color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
                        {item.lastSeen}
                      </span>
                    )}
                  </div>
                </div>

                {/* Right: status badge */}
                <span
                  style={{
                    flexShrink: 0,
                    fontSize: '10px',
                    fontWeight: 700,
                    letterSpacing: '0.07em',
                    color: cfg.color,
                    background: cfg.bg,
                    border: `1px solid ${cfg.color}`,
                    borderRadius: '4px',
                    padding: '2px 8px',
                    alignSelf: 'center',
                  }}
                >
                  {cfg.label}
                </span>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
};

export default DataCoveragePanel;
