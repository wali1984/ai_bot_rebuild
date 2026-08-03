export interface ContractViolation {
  field: string;
  expected_type: string;
  actual_value: string;
  source: string;
  detected_at: string;
  severity: 'critical' | 'high' | 'medium' | 'low';
}

const SEVERITY_COLOR: Record<ContractViolation['severity'], string> = {
  critical: 'var(--error)',
  high: 'var(--error)',
  medium: 'var(--warn)',
  low: 'var(--text-muted)',
};

interface Props {
  violations: ContractViolation[];
  loading?: boolean;
}

export function DataContractViolationPanel({ violations, loading = false }: Props): JSX.Element {
  if (loading) {
    return (
      <div style={{ fontSize: 12, color: 'var(--text-muted)' }}>Checking data contract…</div>
    );
  }

  if (!violations.length) {
    return (
      <div
        data-testid="contract-violations-ok"
        style={{
          padding: '10px 14px',
          borderRadius: 8,
          background: 'color-mix(in oklch, var(--ok) 8%, var(--bg-elevated))',
          border: '1px solid color-mix(in oklch, var(--ok) 30%, transparent)',
          color: 'var(--ok)',
          fontSize: 13,
          fontWeight: 600,
        }}
      >
        ✓ No data contract violations detected.
      </div>
    );
  }

  return (
    <div data-testid="contract-violations-panel" style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      <div style={{ fontWeight: 600, fontSize: 13, color: 'var(--error)' }}>
        ⚠ {violations.length} contract violation{violations.length !== 1 ? 's' : ''}
      </div>
      {violations.map((v, i) => {
        const color = SEVERITY_COLOR[v.severity];
        return (
          <div
            key={i}
            data-testid={`contract-violation-${v.field}-${i}`}
            style={{
              padding: '10px 14px',
              borderRadius: 8,
              background: 'var(--bg-elevated)',
              border: `1px solid ${color}44`,
              borderLeft: `3px solid ${color}`,
              fontSize: 12,
              display: 'flex',
              flexDirection: 'column',
              gap: 4,
            }}
          >
            <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
              <span style={{ fontWeight: 700, color: 'var(--text-primary)' }}>{v.field}</span>
              <span style={{ fontFamily: 'var(--font-mono)', color, fontSize: 10, fontWeight: 700 }}>
                {v.severity.toUpperCase()}
              </span>
            </div>
            <div style={{ color: 'var(--text-secondary)' }}>
              Expected: <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--ok)' }}>{v.expected_type}</code>
              {' '} | Got: <code style={{ fontFamily: 'var(--font-mono)', color: 'var(--error)' }}>{v.actual_value}</code>
            </div>
            <div style={{ color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', fontSize: 11 }}>
              source: {v.source} — {v.detected_at}
            </div>
          </div>
        );
      })}
    </div>
  );
}
