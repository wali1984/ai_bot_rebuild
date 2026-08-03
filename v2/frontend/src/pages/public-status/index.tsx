import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useOptionalAuth } from '../../hooks/useAuth';
import meta from './meta';
import './styles.css';

interface PublicStatusData {
  live_gate_status?: string;
  runtime_state?: string;
  public_route_failed_count?: number | null;
  supervisor_health?: string;
  status_dimensions?: TruthfulStatusDimensions;
}

interface MarketHealth {
  count?: number;
  symbols?: string[];
}

type StatusTone = 'ok' | 'warn' | 'block' | 'neutral';
type MarketDataStatus = 'LIVE' | 'DELAYED' | 'STALE' | 'OFFLINE';
type AutomationStatus = 'ACTIVE' | 'PAUSED' | 'DEGRADED' | 'UNKNOWN';
type ExecutionStatus = 'RESTRICTED' | 'PAPER' | 'LIVE_APPROVED' | 'DISABLED';
type AccountStatus = 'CONNECTED' | 'AUTHORIZED' | 'UNAVAILABLE' | 'UNAUTHORIZED';

interface TruthfulStatusDimensions {
  market_data?: MarketDataStatus;
  automation?: AutomationStatus;
  execution?: ExecutionStatus;
  account?: AccountStatus;
  live_trading_enabled?: boolean;
  order_submission_enabled?: boolean;
  places_real_order?: boolean;
  exchange_mutation_enabled?: boolean;
  source?: string;
  updated_at?: string | null;
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
      className="public-status__chip"
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
      className="public-status__row"
      style={{
        display: 'grid',
        gridTemplateColumns: '180px 1fr auto',
        alignItems: 'center',
        gap: 16,
        padding: '12px 0',
        borderBottom: '1px solid var(--line-soft)',
      }}
    >
      <span className="public-status__row-label" style={{ fontSize: 13, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>{label}</span>
      {detail ? (
        <span className="public-status__row-detail" style={{ fontSize: 13, color: 'var(--text-secondary)' }}>{detail}</span>
      ) : <span className="public-status__row-detail" />}
      <Chip label={value} tone={tone} />
    </div>
  );
}

function statusLabel(value: string | null | undefined): string {
  if (!value) return 'Unavailable';
  return value
    .toLowerCase()
    .replace(/_/g, ' ')
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function statusTone(label: string | null | undefined): StatusTone {
  const status = String(label ?? '').toUpperCase();
  if (status === 'LIVE' || status === 'ACTIVE' || status === 'CONNECTED' || status === 'AUTHORIZED') return 'ok';
  if (status === 'OFFLINE' || status === 'DISABLED') return 'block';
  if (status === 'UNAUTHORIZED' || status === 'UNAVAILABLE') return 'neutral';
  return 'warn';
}

export default function PublicStatusPage(): JSX.Element {
  const { user } = useOptionalAuth();
  const statusResource = useRealtimeResource<PublicStatusData>({
    url: '/api/v2/public/status',
    source: '/api/v2/public/status',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });
  const marketResource = useRealtimeResource<MarketHealth>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });

  const statusData = statusResource.envelope.data;
  const marketHealth = marketResource.envelope.data;
  const loading = (statusResource.loading && !statusData) || (marketResource.loading && !marketHealth);
  const statusConnected = Boolean(statusData) && statusResource.envelope.data_quality_status !== 'invalid';
  const marketFresh = Boolean(marketHealth)
    && marketResource.envelope.freshness_status !== 'stale'
    && marketResource.envelope.freshness_status !== 'offline'
    && marketResource.envelope.data_quality_status !== 'invalid';
  const symbolCount = marketHealth?.count ?? marketHealth?.symbols?.length ?? null;
  const apiUp = statusConnected || marketFresh;
  const dimensions = statusData?.status_dimensions ?? {};
  // The public status endpoint can report market_data STALE with a stricter/older
  // threshold than the actual feed; trust the live market resource when it is fresh.
  const marketDataStatus = marketFresh ? 'LIVE' : (dimensions.market_data ?? (apiUp ? 'DELAYED' : 'OFFLINE'));
  const automationStatus = dimensions.automation ?? (statusConnected ? 'ACTIVE' : 'UNKNOWN');
  const executionStatus = dimensions.execution ?? 'RESTRICTED';
  // The public endpoint never reads the session (so it always says UNAUTHORIZED);
  // reflect the real signed-in state when a trader session exists.
  const accountStatus = user ? 'AUTHORIZED' : (dimensions.account ?? 'UNAUTHORIZED');
  const overallHealthy = apiUp && marketDataStatus !== 'OFFLINE';

  return (
    <main
      data-testid="page-public-status"
      data-page-id={meta.id}
      style={{
        minHeight: '100vh',
        background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)',
        color: 'var(--text-primary)',
        fontFamily: 'var(--font-sans)',
        padding: '0 0 64px',
      }}
    >
      {/* Header */}
      <div
        style={{
          borderBottom: '1px solid var(--border)',
          background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)',
          backdropFilter: 'blur(8px)',
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
          Public-facing platform health summary. No internal diagnostics or error details are shown here.
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
            {loading ? 'Checking telemetry…' : overallHealthy ? 'Platform telemetry available' : 'Checking system availability'}
          </span>
        </div>

        {/* Status rows */}
        <div
          className="glass"
          style={{
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
            value={loading ? 'Checking…' : statusLabel(marketDataStatus)}
            tone={loading ? 'neutral' : statusTone(marketDataStatus)}
            detail={symbolCount != null ? `${symbolCount} symbols in universe` : 'USD-M perpetual futures'}
          />
          <StatusRow
            label="Automation"
            value={loading ? 'Checking…' : statusLabel(automationStatus)}
            tone={loading ? 'neutral' : statusTone(automationStatus)}
            detail="Automated analysis state"
          />
          <StatusRow
            label="Execution"
            value={statusLabel(executionStatus)}
            tone={statusTone(executionStatus)}
            detail="Order submission disabled unless backend approval is active"
          />
          <StatusRow
            label="Account"
            value={statusLabel(accountStatus)}
            tone={statusTone(accountStatus)}
            detail="Sign-in required for account-specific status"
          />
          <StatusRow
            label="Data Freshness"
            value={marketFresh ? 'Monitored' : 'Degraded'}
            tone={marketFresh ? 'ok' : 'warn'}
            detail="Status and market feeds update through resource WebSockets"
          />
        </div>

        {/* Scheduled maintenance */}
        <div
          className="glass"
          style={{
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
          className="glass"
          style={{
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
              // /derivatives and /signals redirect logged-out users to /login —
              // the public status page must not imply public access to them.
              { label: 'Derivatives data', status: 'Available (auth required)', ok: true },
              { label: 'Signal preview', status: 'Available (auth required)', ok: true },
              { label: 'Portfolio', status: 'Available (auth required)', ok: true },
              { label: 'Alerts', status: 'Available (auth required)', ok: true },
              { label: 'Backtests', status: 'Coming soon', ok: false },
              { label: 'Order routing', status: 'Guarded', ok: true },
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
          Status updates from live resource streams. No internal IDs or diagnostics are exposed on this public page.
          For platform sign-in, visit <a href="/login" style={{ color: 'var(--accent)' }}>/login</a>.
        </p>
      </div>
    </main>
  );
}
