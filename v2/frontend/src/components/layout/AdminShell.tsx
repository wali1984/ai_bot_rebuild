import { Navigate, Outlet, useLocation, NavLink } from 'react-router-dom';
import { canSeePage, normalizeRole, useRoles, type RoleLike } from '../../auth/rbac';
import { useAuth } from '../../hooks/useAuth';
import { LiveBlockBanner } from '../banners/LiveBlockBanner';
import { Nav } from './Nav';
import { PAGES } from '../../pages/registry';
const ADMIN_NAV_SECTIONS: Array<{ label: string; paths: string[] }> = [
  {
    label: 'System',
    paths: ['/admin/system', '/admin', '/admin/monitor-center', '/admin/ingestors', '/admin/logs'],
  },
  {
    label: 'Data',
    paths: ['/admin/coverage', '/admin/scripts', '/admin/signal-explainability'],
  },
  {
    label: 'AI / Trainer',
    paths: ['/admin/trainer', '/system/build-code-review', '/admin/ai-tools'],
  },
  {
    label: 'Risk',
    paths: ['/admin/risk', '/admin/readiness', '/admin/external-manual-position-quarantine'],
  },
  {
    label: 'Config',
    paths: ['/admin/config', '/admin/traders', '/admin/orchestrator', '/admin/execution', '/admin/exchanges'],
  },
  {
    label: 'Audit',
    paths: ['/admin/audit', '/admin/build-validation', '/admin/evidence', '/system/executive-summary', '/admin/migrations'],
  },
  {
    label: 'Reports',
    paths: ['/admin/reports', '/admin/readiness/mobile'],
  },
];

function StatusChip({ label, value, ok }: { label: string; value: string; ok?: boolean }): JSX.Element {
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '3px 9px',
        borderRadius: 6,
        border: `1px solid ${ok === true ? 'var(--ok)' : ok === false ? 'var(--error)' : 'var(--border)'}`,
        background: ok === true ? 'var(--buy-bg)' : ok === false ? 'var(--sell-bg)' : 'var(--bg-elevated)',
        color: ok === true ? 'var(--ok)' : ok === false ? 'var(--error)' : 'var(--text-secondary)',
        fontSize: 11,
        fontFamily: 'var(--font-mono)',
        whiteSpace: 'nowrap',
      }}
    >
      <span style={{ opacity: 0.7 }}>{label}</span>
      <strong style={{ fontWeight: 700 }}>{value}</strong>
    </span>
  );
}

function roleLabel(role: RoleLike): string {
  return normalizeRole(role) === 'live_approver' ? 'superadmin' : String(role);
}

export function AdminShell(): JSX.Element {
  const sessionRole = useRoles();
  const { user, loading, logout } = useAuth();
  const location = useLocation();
  const effectiveRole: RoleLike = user?.role ? normalizeRole(user.role) : sessionRole;
  const routeLookupPath = location.pathname;

  if (loading) {
    return (
      <div data-testid="admin-auth-loading" style={{ minHeight: '60vh', display: 'grid', placeItems: 'center' }}>
        Checking backend session...
      </div>
    );
  }

  if (!user && effectiveRole === 'public') {
    return <Navigate to="/login" replace />;
  }

  const page = PAGES.find(
    (p) => p.route.path === routeLookupPath && (p.meta.surface === 'admin' || p.meta.surface === 'system'),
  );
  if (page && !canSeePage(effectiveRole, page.rbac.minRole)) {
    return (
      <div
        data-testid="access-denied"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '60vh',
          gap: 12,
          color: 'var(--text-secondary)',
          textAlign: 'center',
          padding: 32,
        }}
      >
        <span style={{ fontSize: 32 }}>🔒</span>
        <h2 style={{ margin: 0, color: 'var(--text-primary)' }}>Access Restricted</h2>
        <p style={{ margin: 0 }}>
          Minimum role required: <strong style={{ color: 'var(--admin-accent)' }}>{roleLabel(page.rbac.minRole)}</strong>
        </p>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
          Your role: {String(effectiveRole)}
        </p>
      </div>
    );
  }

  return (
    <div
      className="platform-shell"
      data-testid="admin-shell"
      style={{ fontFamily: 'var(--font-sans)' }}
    >
      <LiveBlockBanner />

      {/* Top bar */}
      <header className="admin-shell__header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <span
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              justifyContent: 'center',
              width: 32,
              height: 32,
              borderRadius: 8,
              background: 'var(--admin-bg)',
              border: '1px solid var(--admin-border)',
              color: 'var(--admin-accent)',
              fontWeight: 700,
              fontSize: 14,
              fontFamily: 'var(--font-mono)',
            }}
          >
            A
          </span>
          <div>
            <div style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)' }}>
              AlphaForge V2
            </div>
            <div style={{ fontSize: 11, color: 'var(--admin-accent)', fontFamily: 'var(--font-mono)' }}>
              Control Portal
            </div>
          </div>
        </div>

        <div className="admin-shell__top-chips">
          <StatusChip label="MODE" value="PAPER/READ-ONLY" />
          <StatusChip label="LIVE" value="BLOCKED" ok={false} />
          <StatusChip label="ROLE" value={String(effectiveRole).toUpperCase()} />
        </div>

        <div className="admin-shell__topright">
          {user && (
            <span style={{ fontSize: 12, color: 'var(--text-secondary)', fontFamily: 'var(--font-mono)' }}>
              {user.email}
            </span>
          )}
          <button
            type="button"
            onClick={() => { void logout(); }}
            style={{
              border: '1px solid var(--border)',
              borderRadius: 6,
              background: 'var(--bg-elevated)',
              color: 'var(--text-secondary)',
              cursor: 'pointer',
              fontSize: 12,
              padding: '6px 10px',
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      {/* Horizontal secondary nav */}
      <nav className="admin-shell__topnav" aria-label="Admin section navigation">
        {ADMIN_NAV_SECTIONS.map((section) => {
          const isActive = section.paths.some((p) => location.pathname.startsWith(p));
          return (
            <NavLink
              key={section.label}
              to={section.paths[0]}
              className={`admin-shell__topnav-link${isActive ? ' admin-shell__topnav-link--active' : ''}`}
            >
              {section.label}
            </NavLink>
          );
        })}
      </nav>

      {/* Body: sidebar + main */}
      <div className="admin-shell__body">
        <Nav role={effectiveRole} />
        <main
          className="admin-shell__main"
          data-testid="admin-main"
          style={{ padding: 16, minWidth: 0 }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
