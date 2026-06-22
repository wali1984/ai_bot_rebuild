import { Navigate, NavLink, Outlet, useLocation } from 'react-router-dom';
import { useRoles, canSee, normalizeRole } from '../../auth/rbac';
import { useAuth } from '../../hooks/useAuth';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { TopBar } from './TopBar';

interface ShellTickerRow {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
}

interface ShellMarketOverview {
  tickers?: ShellTickerRow[];
}

function formatTickerPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  if (value >= 10_000) return `$${value.toLocaleString('en-US', { maximumFractionDigits: 0 })}`;
  if (value >= 1) return `$${value.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
  return `$${value.toFixed(6)}`;
}

function formatTickerChange(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return '—';
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

/** Secondary nav tab strip shown under specific top-level sections */
function SecondaryNav(): JSX.Element | null {
  const { pathname } = useLocation();

  // Determine which secondary nav to show based on current path
  let tabs: Array<{ label: string; to: string }> | null = null;

  if (pathname.startsWith('/portfolio')) {
    tabs = [
      { label: 'Overview', to: '/portfolio' },
      { label: 'Executions', to: '/portfolio/executions' },
      { label: 'History', to: '/portfolio/history' },
    ];
  } else if (pathname.startsWith('/research')) {
    tabs = [
      { label: 'Overview', to: '/research' },
    ];
  } else if (pathname.startsWith('/backtests')) {
    tabs = [
      { label: 'Backtests', to: '/backtests' },
      { label: 'Replay', to: '/backtests/replay' },
    ];
  } else if (pathname.startsWith('/admin')) {
    tabs = [
      { label: 'NERVYX OBSERVE', to: '/admin' },
      { label: 'System', to: '/admin/system' },
      { label: 'NERVYX SHIFT', to: '/admin/orchestrator' },
      { label: 'NERVYX GUARD', to: '/admin/risk' },
      { label: 'Traders', to: '/admin/trader' },
      { label: 'Config', to: '/admin/config' },
    ];
  }

  if (!tabs) return null;

  return (
    <nav
      aria-label="Secondary navigation"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 0,
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-panel)',
        padding: '0 16px',
        overflowX: 'auto',
        scrollbarWidth: 'none',
      }}
    >
      {tabs.map((tab) => (
        <NavLink
          key={tab.to}
          to={tab.to}
          end
          style={({ isActive }) => ({
            padding: '8px 14px',
            fontSize: 13,
            fontWeight: isActive ? 600 : 400,
            color: isActive ? 'var(--text-primary)' : 'var(--text-muted)',
            textDecoration: 'none',
            borderBottom: isActive ? '2px solid var(--accent)' : '2px solid transparent',
            marginBottom: -1,
            whiteSpace: 'nowrap',
            transition: 'color var(--ease-fast)',
          })}
        >
          {tab.label}
        </NavLink>
      ))}
    </nav>
  );
}

/** MarketTickerStrip — simple scrolling ticker for top-level market prices */
function MarketTickerStrip(): JSX.Element {
  const { envelope } = useRealtimeResource<ShellMarketOverview>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });
  const tickers = envelope.data?.tickers ?? [];
  const preferred = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT'];
  const rows = preferred
    .map((symbol) => tickers.find((ticker) => ticker.symbol === symbol))
    .filter((ticker): ticker is ShellTickerRow => Boolean(ticker));

  return (
    <div
      data-testid="market-ticker-strip"
      style={{
        height: 32,
        borderBottom: '1px solid var(--border)',
        background: 'var(--bg-elevated)',
        display: 'flex',
        alignItems: 'center',
        gap: 24,
        padding: '0 16px',
        overflowX: 'auto',
        scrollbarWidth: 'none',
        fontSize: 11,
        fontFamily: 'var(--font-mono)',
        color: 'var(--text-muted)',
      }}
    >
      {rows.length > 0 ? rows.map((row) => {
        const pct = row.change_24h == null ? null : (Math.abs(row.change_24h) <= 1 ? row.change_24h * 100 : row.change_24h);
        const tone = pct == null ? 'var(--text-muted)' : pct >= 0 ? 'var(--buy, #10b981)' : 'var(--sell, #ef4444)';
        return (
          <span key={row.symbol} style={{ display: 'inline-flex', alignItems: 'center', gap: 7, whiteSpace: 'nowrap' }}>
            <strong style={{ color: 'var(--text-primary)' }}>{row.symbol.replace('USDT', '')}</strong>
            <span>{formatTickerPrice(row.last_price)}</span>
            <span style={{ color: tone }}>{formatTickerChange(row.change_24h)}</span>
          </span>
        );
      }) : (
        <span style={{ color: 'var(--text-secondary)', fontWeight: 500 }}>
          Market stream connecting · {envelope.source_type === 'websocket' ? 'WebSocket' : 'API fallback'}
        </span>
      )}
    </div>
  );
}

export function TraderShell(): JSX.Element {
  const sessionRole = useRoles();
  const { user, loading } = useAuth();
  const location = useLocation();

  const effectiveRole = user?.role ? normalizeRole(user.role) : sessionRole;

  if (loading) {
    return (
      <div
        style={{
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: 'var(--bg-base)',
          color: 'var(--text-muted)',
          fontFamily: 'var(--font-mono)',
          fontSize: 13,
        }}
      >
        Loading…
      </div>
    );
  }

  if (!user && effectiveRole === 'public') {
    return <Navigate to={`/login?returnTo=${encodeURIComponent(location.pathname)}`} replace />;
  }

  // Viewer role: only allow specific routes
  const viewerHiddenPaths = ['/trade', '/portfolio', '/alerts'];
  if (
    effectiveRole === 'viewer' &&
    viewerHiddenPaths.some((p) => location.pathname === p || location.pathname.startsWith(p + '/'))
  ) {
    return (
      <div
        data-testid="access-denied"
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          background: 'var(--bg-base)',
          color: 'var(--text-secondary)',
          textAlign: 'center',
          padding: 32,
        }}
      >
        <span style={{ fontSize: 32 }}>🔒</span>
        <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>Viewer Access Only</h2>
        <p style={{ margin: 0 }}>
          This section requires <strong style={{ color: 'var(--accent)' }}>trader</strong> role or higher.
        </p>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
          You have <strong>viewer</strong> access — you can view Markets, Signals, and AI Predictions.
        </p>
      </div>
    );
  }

  // Admin-only pages for non-admin roles
  if (
    location.pathname.startsWith('/admin') &&
    !canSee(effectiveRole, 'admin')
  ) {
    return (
      <div
        data-testid="access-denied"
        style={{
          minHeight: '100vh',
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          gap: 12,
          background: 'var(--bg-base)',
          color: 'var(--text-secondary)',
          textAlign: 'center',
          padding: 32,
        }}
      >
        <span style={{ fontSize: 32 }}>🔒</span>
        <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>Access Restricted</h2>
        <p style={{ margin: 0 }}>
          Minimum role: <strong style={{ color: 'var(--accent)' }}>admin</strong>
        </p>
      </div>
    );
  }

  return (
    <div
      className="platform-shell"
      data-testid="trader-shell"
      style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}
    >
      <TopBar surface="app" showSymbolSearch />
      <MarketTickerStrip />
      <SecondaryNav />
      <main
        data-testid="trader-main"
        style={{
          minWidth: 0,
          minHeight: 'calc(100vh - 120px)',
          background: 'var(--bg-base)',
        }}
      >
        <Outlet />
      </main>
    </div>
  );
}
