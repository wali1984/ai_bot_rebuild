interface Props {
  page: string;
  component: string;
  source: string;
  owner?: string;
  remediation?: string;
  adminOnly?: boolean;
}

export function MissingSourceIncident({
  page,
  component,
  source,
  owner,
  remediation,
  adminOnly = false,
}: Props) {
  if (adminOnly) {
    return (
      <div
        style={{
          padding: '12px 16px',
          background: 'color-mix(in oklch, var(--error) 8%, var(--bg-panel))',
          border: '1px solid color-mix(in oklch, var(--error) 30%, transparent)',
          borderRadius: 8,
          fontSize: 12,
        }}
      >
        <div style={{ fontWeight: 600, color: 'var(--error)', marginBottom: 4 }}>
          Source Unavailable
        </div>
        <div style={{ color: 'var(--text-secondary)' }}>
          <strong>Page:</strong> {page} &nbsp;|&nbsp;
          <strong>Component:</strong> {component}
        </div>
        <div style={{ color: 'var(--text-secondary)', marginTop: 4 }}>
          <strong>Source:</strong> {source}
        </div>
        {owner && (
          <div style={{ color: 'var(--text-secondary)', marginTop: 2 }}>
            <strong>Owner:</strong> {owner}
          </div>
        )}
        {remediation && (
          <div style={{ color: 'var(--warn)', marginTop: 4 }}>
            <strong>Remediation:</strong> {remediation}
          </div>
        )}
      </div>
    );
  }

  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '8px 12px',
        background: 'var(--bg-elevated)',
        border: '1px solid var(--border)',
        borderRadius: 6,
        fontSize: 12,
        color: 'var(--text-muted)',
      }}
    >
      <span>Data source not connected</span>
    </div>
  );
}
