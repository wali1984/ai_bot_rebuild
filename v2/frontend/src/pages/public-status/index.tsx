import { useEffect, useState } from 'react';
import meta from './meta';

interface PublicStatusData {
  live_gate_status?: string;
  runtime_state?: string;
  public_route_failed_count?: number | null;
  supervisor_health?: string;
}

interface MarketHealth {
  source_type?: string;
  stale?: boolean;
  data?: { count?: number; symbols?: string[] };
}

function safeGateLabel(raw: string | undefined): { label: string; ok: boolean } {
  if (!raw || raw === 'MISSING_EVIDENCE') return { label: 'Checking…', ok: false };
  if (raw.toLowerCase().includes('block') || raw.toLowerCase().includes('disabled')) {
    return { label: 'Disabled', ok: true };
  }
  return { label: raw.replaceAll('_', ' '), ok: false };
}

function Chip({ label, tone }: { label: string; tone: 'ok' | 'warn' | 'block' | 'neutral' }): JSX.Element {
  const colors: Record<string, { bg: string; color: string; border: string }> = {
    ok: { bg: 'var(--buy-bg)', color: 'var(--ok)', border: 'var(--buy-border)' },
    warn: { bg: 'color-mix(in oklch, var(--warn) 12%, transparent)', color: 'var(--warn)', border: 'color-mix(in oklch, var(--warn) 40%, transparent)' },
    block: { bg: 'var(--sell-bg)', color: 'var(--error)', border: 'var(--sell-border)' },
    neutral: { bg: 'var(--bg-elevated)', color: 'var(--text-secondary)', border: 'var(--border)' },
  };
  const c = colors[tone];
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '4px 12px',
        borderRadius: 999,
        border: `1px solid ${c.border}`,
        background: c.bg,
        color: c.color,
        fontSize: 12,
        fontWeight: 600,
        fontFamily: 'var(--font-mono)',
      }}
    >
      {label}
    </span>
  );
}

function StatusRow({ label, value, tone, detail }: { label: string; value: string; tone: 'ok' | 'warn' | 'block' | 'neutral'; detail?: string }): JSX.Element {
  return (
    <div
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr auto',
        alignItems: 'center',
        gap: 16,
        padding: '12px 0',
        borderBottom: '1px solid var(--line-soft)',
      }}
    >
      <span style={{ fontSize: 13, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{label}</span>
      {detail ? (
        <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{detail}</span>
      ) : <span />}
      <Chip label={value} tone={tone} />
    </div>
  );
}

export default function PublicStatusPage(): JSX.Element {
  const [statusData, setStatusData] = useState<PublicStatusData | null>(null);
  const [marketHealth, setMarketHealth] = useState<MarketHealth | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      try {
        const [sRes, mRes] = await Promise.allSettled([
          fetch('/api/v2/public/status'),
          fetch('/api/v2/market/overview'),
        ]);
        if (cancelled) return;
        if (sRes.status === 'fulfilled' && sRes.value.ok) {
          const j = await sRes.value.json() as PublicStatusData;
          setStatusData(j);
        }
        if (mRes.status === 'fulfilled' && mRes.value.ok) {
          const j = await mRes.value.json() as MarketHealth;
          setMarketHealth(j);
        }
      } catch { /* silent */ } finally {
        if (!cancelled) setLoading(false);
      }
    };
    void load();
    const id = window.setInterval(load, 30_000);
    return () => { cancelled = true; window.clearInterval(id); };
  }, []);

  const gateInfo = safeGateLabel(statusData?.live_gate_status);
  const marketFresh = marketHealth?.source_type === 'api' && !marketHealth?.stale;
  const symbolCount = marketHealth?.data?.count ?? marketHealth?.data?.symbols?.length ?? null;
  const apiUp = marketHealth?.source_type && marketHealth.source_type !== 'unavailable';

  return (
    <main
      data-testid="page-public-status"
      data-page-id={meta.id}
      style={{
        minHeight: '100vh',
        background: 'var(--bg-base)',
        color: 'var(--text-primary)',
        fontFamily: 'var(--font-sans)',
        padding: '0 0 64px',
      }}
    >
      {/* Header */}
      <div
        style={{
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-panel)',
          padding: '32px 24px 24px',
          maxWidth: 900,
          margin: '0 auto',
        }}
      >
        <p style={{ margin: '0 0 8px', fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', letterSpacing: '0.06em', textTransform: 'uppercase' }}>
          Platform Status
        </p>
        <h1 style={{ margin: '0 0 8px', fontSize: 28, fontWeight: 700, color: 'var(--text-primary)' }}>
          NERVYX ONE Status
        </h1>
        <p style={{ margin: 0, fontSize: 14, color: 'var(--text-muted)' }}>
          Public-facing platform health summary. No internal diagnostics, logs, or stack traces are shown here.
        </p>
      </div>

      {/* Overall status banner */}
      <div
        style={{
          maxWidth: 900,
          margin: '0 auto',
          padding: '16px 24px',
        }}
      >
        <div
          style={{
            padding: '16px 20px',
            borderRadius: 'var(--radius)',
            border: `1px solid ${apiUp ? 'var(--buy-border)' : 'var(--sell-border)'}`,
            background: apiUp ? 'var(--buy-bg)' : 'var(--sell-bg)',
            display: 'flex',
            alignItems: 'center',
            gap: 12,
            marginBottom: 24,
          }}
        >
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: apiUp ? 'var(--ok)' : 'var(--error)',
              flexShrink: 0,
            }}
          />
          <span style={{ fontSize: 14, fontWeight: 600, color: apiUp ? 'var(--ok)' : 'var(--error)' }}>
            {loading ? 'Checking platform status…' : apiUp ? 'All systems operational' : 'Checking system availability'}
          </span>
        </div>

        {/* Status rows */}
        <div
          style={{
            background: 'var(--bg-panel)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)',
            padding: '0 20px',
            marginBottom: 24,
          }}
        >
          <StatusRow
            label="Platform"
            value={loading ? 'Checking…' : apiUp ? 'Operational' : 'Degraded'}
            tone={loading ? 'neutral' : apiUp ? 'ok' : 'warn'}
            detail="Core API and frontend"
          />
          <StatusRow
            label="Market Data"
            value={loading ? 'Checking…' : marketFresh ? 'Live' : apiUp ? 'Partial' : 'Unavailable'}
            tone={loading ? 'neutral' : marketFresh ? 'ok' : apiUp ? 'warn' : 'warn'}
            detail={symbolCount != null ? `${symbolCount} symbols in universe` : 'USD-M perpetual futures'}
          />
          <StatusRow
            label="Signal Feed"
            value="Live Platform"
            tone="neutral"
            detail="Evidence-based signal stream"
          />
          <StatusRow
            label="Execution Mode"
            value="Risk-gated"
            tone="warn"
            detail="Operator-governed execution paths"
          />
          <StatusRow
            label="Live Trading"
            value="Disabled"
            tone="block"
            detail="Requires separate live-gate approval"
          />
          <StatusRow
            label="Data Freshness"
            value={marketFresh ? 'Monitored' : 'Degraded'}
            tone={marketFresh ? 'ok' : 'warn'}
            detail="Source, received_at, and lag tracked per envelope"
          />
        </div>

        {/* Scheduled maintenance */}
        <div
          style={{
            background: 'var(--bg-panel)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)',
            padding: '20px',
            marginBottom: 24,
          }}
        >
          <h2 style={{ margin: '0 0 12px', fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
            Scheduled Maintenance
          </h2>
          <p style={{ margin: 0, fontSize: 13, color: 'var(--text-muted)' }}>
            No scheduled maintenance is currently planned.
          </p>
        </div>

        {/* Platform capabilities */}
        <div
          style={{
            background: 'var(--bg-panel)',
            borderRadius: 'var(--radius)',
            border: '1px solid var(--border)',
            padding: '20px',
            marginBottom: 24,
          }}
        >
          <h2 style={{ margin: '0 0 16px', fontSize: 16, fontWeight: 600, color: 'var(--text-primary)' }}>
            Platform Capabilities
          </h2>
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(220px, 1fr))', gap: 12 }}>
            {[
              { label: 'Market screener', status: 'Available', ok: true },
              { label: 'Symbol detail', status: 'Available', ok: true },
              { label: 'Derivatives data', status: 'Available', ok: true },
              { label: 'Signal preview', status: 'Available', ok: true },
              { label: 'Portfolio', status: 'Available (auth required)', ok: true },
              { label: 'Alerts', status: 'Available (auth required)', ok: true },
              { label: 'Backtests', status: 'Coming soon', ok: false },
              { label: 'Live trading', status: 'Disabled', ok: false },
            ].map((item) => (
              <div
                key={item.label}
                style={{
                  padding: '12px 14px',
                  borderRadius: 'var(--radius-sm)',
                  border: '1px solid var(--border)',
                  background: 'var(--bg-elevated)',
                  display: 'flex',
                  alignItems: 'center',
                  justifyContent: 'space-between',
                  gap: 8,
                }}
              >
                <span style={{ fontSize: 12.5, color: 'var(--text-secondary)' }}>{item.label}</span>
                <span
                  style={{
                    fontSize: 11,
                    fontWeight: 600,
                    color: item.ok ? 'var(--ok)' : 'var(--text-muted)',
                    fontFamily: 'var(--font-mono)',
                  }}
                >
                  {item.status}
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Footer note */}
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)', textAlign: 'center' }}>
          Status is refreshed every 30 seconds. No internal IDs, logs, or diagnostics are exposed on this public page.
          For platform sign-in, visit <a href="/login" style={{ color: 'var(--accent)' }}>/login</a>.
        </p>
      </div>
    </main>
  );
}
