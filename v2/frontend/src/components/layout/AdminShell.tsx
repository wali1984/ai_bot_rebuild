import { useEffect, useState } from 'react';
import { Navigate, Outlet, useLocation, NavLink } from 'react-router-dom';
import { canSee, canSeePage, normalizeRole, type RoleLike } from '../../auth/rbac';
import { useAuth } from '../../hooks/useAuth';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { PAGES } from '../../pages/registry';
import {
  SYSTEM_NAV_ORDER,
  SYSTEM_NAV_LABELS,
  SYSTEM_NAV_SECONDARY,
  SYSTEM_NAV_SUPERADMIN_ONLY,
} from '../../pages/productNavigation';
import type { AdminOverviewPayload } from '../../types/adminData';
import { RuntimeTruthStrip } from './RuntimeTruthStrip';

// ── Canonical admin paths keyed by SYSTEM_NAV_ORDER id ───────────────────────
const ADMIN_NAV_PATHS: Record<string, string> = {
  overview:       '/admin',
  data:           '/admin/data',
  intelligence:   '/admin/intelligence',
  orchestration:  '/admin/orchestration',
  risk:           '/admin/risk',
  execution:      '/admin/execution',
  exchanges:      '/admin/exchanges',
  config:         '/admin/config',
  users:          '/admin/users',
  reports:        '/admin/reports',
  logs:           '/admin/logs',
  audit:          '/admin/audit',
  tools:          '/admin/tools',
};

// ── Simple icon codenames (no external deps) ─────────────────────────────────
const NAV_ICONS: Record<string, string> = {
  overview:       '⬡',
  data:           '⬣',
  intelligence:   '◈',
  orchestration:  '⬡',
  risk:           '◆',
  execution:      '▶',
  exchanges:      '⇆',
  config:         '⚙',
  users:          '◎',
  reports:        '▤',
  logs:           '≡',
  audit:          '▣',
  tools:          '⊕',
};

function roleLabel(role: RoleLike): string {
  return normalizeRole(role) === 'live_approver' ? 'SUPERADMIN' : String(role).toUpperCase();
}

function relativeAge(tsMs: number): string {
  const sec = Math.floor((Date.now() - tsMs) / 1000);
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  return `${Math.floor(sec / 3600)}h`;
}

interface HealthCounts { ok: number; warn: number; error: number }

function parseHealth(data: AdminOverviewPayload | null | undefined): HealthCounts {
  if (!data?.services) return { ok: 0, warn: 0, error: 0 };
  const counts = { ok: 0, warn: 0, error: 0 };
  for (const svc of data.services) {
    if (svc.status === 'ok') counts.ok++;
    else if (svc.status === 'warn') counts.warn++;
    else counts.error++;
  }
  return counts;
}

function isInsufficientRoleError(message: string): boolean {
  return /insufficient_role|forbidden|\b403\b/i.test(message);
}

function GlobalHealthStrip({ counts, freshMs, restricted }: { counts: HealthCounts; freshMs: number | null; restricted?: boolean }): JSX.Element {
  const hasIssues = counts.warn + counts.error > 0;
  return (
    <div
      data-testid="admin-health-strip"
      data-live-gate-status="blocked_human_only"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 10,
        padding: '4px 16px',
        width: '100%',
        maxWidth: '100vw',
        boxSizing: 'border-box',
        overflowX: 'hidden',
        background: hasIssues
          ? 'color-mix(in oklch, var(--error) 8%, var(--bg-elevated))'
          : 'color-mix(in oklch, var(--ok) 5%, var(--bg-elevated))',
        borderBottom: `1px solid ${hasIssues ? 'color-mix(in oklch, var(--error) 25%, transparent)' : 'var(--line-soft)'}`,
        fontSize: 11,
        fontFamily: 'var(--font-mono)',
        minHeight: 26,
      }}
    >
      {counts.ok + counts.warn + counts.error === 0 ? (
        <span style={{ color: 'var(--text-muted)' }}>
          {restricted ? 'Health summary requires admin role — page data unaffected' : 'Health data loading…'}
        </span>
      ) : (
        <>
          <span style={{ color: 'var(--ok)' }}>
            {counts.ok} ok
          </span>
          {counts.warn > 0 && (
            <span style={{ color: 'var(--warn)' }}>{counts.warn} warn</span>
          )}
          {counts.error > 0 && (
            <span style={{ color: 'var(--error)' }}>{counts.error} error</span>
          )}
        </>
      )}
      <span style={{ color: 'var(--line-strong)', marginLeft: 4 }}>|</span>
      <span
        data-testid="live-block-banner"
        style={{ color: 'var(--error)', fontWeight: 700 }}
      >
        EXECUTION BLOCKED · LIVE TRADING: BLOCKED · blocked_human_only
      </span>
      <span style={{ color: 'var(--line-strong)' }}>|</span>
      <span style={{ color: 'var(--text-muted)' }}>source admin-overview</span>
      {freshMs !== null && (
        <>
          <span style={{ color: 'var(--line-strong)' }}>|</span>
          <span style={{ color: 'var(--text-muted)' }}>updated {relativeAge(freshMs)}</span>
        </>
      )}
    </div>
  );
}

function NavItem({
  navId,
  label,
  icon,
  path,
  isActive,
  incidentCount,
}: {
  navId: string;
  label: string;
  icon: string;
  path: string;
  isActive: boolean;
  incidentCount?: number;
}): JSX.Element {
  return (
    <NavLink
      to={path}
      data-testid={`admin-nav-${navId}`}
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 8,
        padding: '7px 12px',
        borderRadius: 6,
        textDecoration: 'none',
        color: isActive ? 'var(--text-primary)' : 'var(--text-secondary)',
        background: isActive ? 'color-mix(in oklch, var(--admin-accent) 12%, var(--bg-elevated))' : 'transparent',
        borderLeft: `2px solid ${isActive ? 'var(--admin-accent)' : 'transparent'}`,
        fontSize: 13,
        fontWeight: isActive ? 600 : 400,
        transition: 'all 0.12s ease',
        position: 'relative',
      }}
    >
      <span style={{ fontSize: 11, opacity: 0.7, width: 14, textAlign: 'center', flexShrink: 0 }}>{icon}</span>
      <span style={{ flex: 1, minWidth: 0, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
        {label}
      </span>
      {incidentCount && incidentCount > 0 ? (
        <span
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            justifyContent: 'center',
            minWidth: 16,
            height: 16,
            borderRadius: 8,
            background: 'var(--error)',
            color: '#fff',
            fontSize: 10,
            fontWeight: 700,
            padding: '0 4px',
            flexShrink: 0,
          }}
        >
          {incidentCount > 99 ? '99+' : incidentCount}
        </span>
      ) : null}
    </NavLink>
  );
}

function AdminLeftNav({
  role,
  pathname,
  incidentCounts,
}: {
  role: RoleLike;
  pathname: string;
  incidentCounts: Record<string, number>;
}): JSX.Element {
  const primary = SYSTEM_NAV_ORDER.filter((id) => !SYSTEM_NAV_SECONDARY.has(id));
  const secondary = SYSTEM_NAV_ORDER.filter((id) => SYSTEM_NAV_SECONDARY.has(id));
  // Audit, logs, and developer tools expose governance evidence and remain
  // restricted to the explicit live-approver/superadmin role. The navigation
  // must match the route gate so an admin cannot discover a URL it may not use.
  const canReachRestrictedNav = canSee(role, 'live_approver');

  const renderItem = (navId: string) => {
    if (SYSTEM_NAV_SUPERADMIN_ONLY.has(navId) && !canReachRestrictedNav) return null;
    const path = ADMIN_NAV_PATHS[navId] ?? `/admin/${navId}`;
    const label = SYSTEM_NAV_LABELS[navId] ?? navId;
    const icon = NAV_ICONS[navId] ?? '·';
    const isActive = navId === 'overview'
      ? pathname === '/admin'
      : pathname.startsWith(path);
    return (
      <NavItem
        key={navId}
        navId={navId}
        label={label}
        icon={icon}
        path={path}
        isActive={isActive}
        incidentCount={incidentCounts[navId]}
      />
    );
  };

  return (
    <div data-testid="admin-nav" style={{ display: 'contents' }}>
      <nav
        className="admin-left-nav"
        aria-label="Admin navigation"
        data-testid="admin-left-nav"
        style={{
          width: 220,
          flexShrink: 0,
          background: 'color-mix(in oklch, var(--bg-panel) 92%, transparent)',
          borderRight: '1px solid var(--admin-border)',
          padding: '12px 8px',
          display: 'flex',
          flexDirection: 'column',
          gap: 2,
          overflowY: 'auto',
          position: 'sticky',
          top: 0,
          height: '100vh',
          boxSizing: 'border-box',
        }}
      >
        {primary.map(renderItem)}

        <div
          style={{
            margin: '10px 4px 8px',
            borderTop: '1px solid var(--line-soft)',
            paddingTop: 8,
          }}
        >
          <span
            style={{
              display: 'block',
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              color: 'var(--text-muted)',
              paddingLeft: 12,
              marginBottom: 4,
              textTransform: 'uppercase',
              letterSpacing: '0.06em',
            }}
          >
            {canSee(role, 'live_approver') ? 'Superadmin' : 'System'}
          </span>
          {secondary.map(renderItem)}
        </div>
      </nav>
    </div>
  );
}

function Breadcrumb({ pathname }: { pathname: string }): JSX.Element {
  const page = PAGES.find(
    (p) => (p.meta.surface === 'admin' || p.meta.surface === 'system') && p.route.path === pathname,
  );
  const title = page?.meta.title ?? 'Admin';
  const description = page?.meta.description;
  return (
    <div data-testid="admin-breadcrumb" style={{ minWidth: 0, flex: 1 }}>
      <div style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', marginBottom: 1 }}>
        NERVYX ADMIN /
        {' '}
        {title.toUpperCase()}
      </div>
      {description && (
        <div style={{ fontSize: 11, color: 'var(--text-muted)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {description}
        </div>
      )}
    </div>
  );
}

export function AdminShell(): JSX.Element {
  const { user, loading, logout } = useAuth();
  const location = useLocation();
  const effectiveRole: RoleLike = user?.role ? normalizeRole(user.role) : 'public';

  // /api/v2/admin/overview is admin-gated, but AdminShell also hosts
  // viewer/reviewer-min pages reachable by a trader. On 403 insufficient_role,
  // stop repolling and let the health strip degrade honestly instead of
  // showing "Health data loading…" forever.
  const [overviewRestricted, setOverviewRestricted] = useState(false);
  const { envelope } = useRealtimeResource<AdminOverviewPayload>({
    url: '/api/v2/admin/overview',
    source: 'admin-overview',
    pollIntervalMs: 30_000,
    enabled: !!user && !overviewRestricted,
    initialFetchWhenStreaming: true,
  });
  const overviewErrors = envelope.errors;
  useEffect(() => {
    if (overviewErrors.some(isInsufficientRoleError)) {
      setOverviewRestricted(true);
    }
  }, [overviewErrors]);

  const overviewData = envelope.data;
  const healthCounts = parseHealth(overviewData);
  const freshMs = envelope.received_at ?? null;

  const incidentCounts: Record<string, number> = {};
  const totalIncidents = overviewData?.active_incidents?.length ?? 0;

  if (loading) {
    return (
      <div data-testid="admin-auth-loading" style={{ minHeight: '100vh', display: 'grid', placeItems: 'center', fontFamily: 'var(--font-mono)', fontSize: 13 }}>
        Checking backend session…
      </div>
    );
  }

  if (!user) {
    return <Navigate to="/login" replace />;
  }

  const page = PAGES.find(
    (p) =>
      p.route.path === location.pathname &&
      (p.meta.surface === 'admin' || p.meta.surface === 'system'),
  );
  const minRole: RoleLike = page?.rbac.minRole ?? 'reviewer';

  if (!canSeePage(effectiveRole, minRole)) {
    return (
      <div
        data-nervyx-theme="ops-terminal"
        data-testid="access-denied"
        style={{
          display: 'flex',
          flexDirection: 'column',
          alignItems: 'center',
          justifyContent: 'center',
          minHeight: '100vh',
          gap: 12,
          color: 'var(--text-secondary)',
          textAlign: 'center',
          padding: 32,
          fontFamily: 'var(--font-sans)',
        }}
      >
        <div style={{ fontSize: 32 }}>🔒</div>
        <h2 style={{ margin: 0, color: 'var(--text-primary)', fontSize: 20 }}>Access Restricted</h2>
        <p style={{ margin: 0, fontSize: 13 }}>
          Minimum role required:{' '}
          <strong style={{ color: 'var(--admin-accent)' }}>{roleLabel(minRole)}</strong>
        </p>
        <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
          Your role: {roleLabel(effectiveRole)}
        </p>
      </div>
    );
  }

  return (
    <div
      className="admin-shell"
      data-testid="admin-shell"
      data-nervyx-theme="ops-terminal"
      style={{
        display: 'flex',
        flexDirection: 'column',
        minHeight: '100vh',
        fontFamily: 'var(--font-sans)',
      }}
    >
      {/* ── Top header ─────────────────────────────────────────────────── */}
      <header
        className="admin-shell__header"
        style={{
          display: 'flex',
          alignItems: 'center',
          flexWrap: 'wrap',
          gap: 12,
          padding: '8px 16px',
          borderBottom: '1px solid var(--admin-border)',
          background: 'color-mix(in oklch, var(--bg-elevated) 92%, var(--admin-bg))',
          minHeight: 56,
          width: '100%',
          maxWidth: '100vw',
          boxSizing: 'border-box',
          overflowX: 'hidden',
          flexShrink: 0,
          zIndex: 'var(--z-header)' as React.CSSProperties['zIndex'],
          position: 'sticky',
          top: 0,
        }}
      >
        <img
          src="/brand/nervyx-one-logo-horizontal-on-midnight.svg"
          alt="NERVYX ONE"
          style={{ display: 'block', height: 30, width: 'auto', flexShrink: 0 }}
        />

        <span
          data-nervyx-module="guard"
          style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: 4,
            background: 'color-mix(in oklch, var(--admin-accent) 14%, transparent)',
            border: '1px solid color-mix(in oklch, var(--admin-accent) 40%, transparent)',
            color: 'var(--admin-accent)',
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            flexShrink: 0,
          }}
        >
          OPS TERMINAL
        </span>
        <span
          data-nervyx-module="observe"
          style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: 4,
            background: 'color-mix(in oklch, var(--admin-accent) 8%, transparent)',
            border: '1px solid color-mix(in oklch, var(--admin-accent) 24%, transparent)',
            color: 'var(--text-secondary)',
            fontSize: 10,
            fontFamily: 'var(--font-mono)',
            fontWeight: 700,
            letterSpacing: '0.08em',
            flexShrink: 0,
          }}
        >
          NERVYX OBSERVE
        </span>

        <Breadcrumb pathname={location.pathname} />

        {/* Role badge */}
        <div
          data-testid="admin-role-badge"
          style={{
            display: 'inline-flex',
            alignItems: 'center',
            gap: 5,
            padding: '3px 10px',
            borderRadius: 4,
            border: '1px solid var(--admin-border)',
            background: 'var(--bg-elevated)',
            fontSize: 11,
            fontFamily: 'var(--font-mono)',
            color: 'var(--text-secondary)',
            flexShrink: 0,
          }}
        >
          <span style={{ opacity: 0.6 }}>ROLE</span>
          <strong style={{ color: 'var(--text-primary)' }}>{roleLabel(effectiveRole)}</strong>
        </div>

        {/* Incident count badge */}
        {totalIncidents > 0 && (
          <div
            data-testid="admin-incident-count"
            style={{
              display: 'inline-flex',
              alignItems: 'center',
              gap: 5,
              padding: '3px 10px',
              borderRadius: 4,
              border: '1px solid color-mix(in oklch, var(--error) 40%, transparent)',
              background: 'color-mix(in oklch, var(--error) 8%, var(--bg-elevated))',
              fontSize: 11,
              fontFamily: 'var(--font-mono)',
              color: 'var(--error)',
              flexShrink: 0,
            }}
          >
            ⚠ {totalIncidents} incident{totalIncidents !== 1 ? 's' : ''}
          </div>
        )}

        {/* User + sign out */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginLeft: 'auto', flexShrink: 0 }}>
          {user.email && (
            <span style={{ fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
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
              padding: '5px 10px',
            }}
          >
            Sign out
          </button>
        </div>
      </header>

      {/* ── Global health strip ─────────────────────────────────────────── */}
      <GlobalHealthStrip counts={healthCounts} freshMs={freshMs} restricted={overviewRestricted} />
      <RuntimeTruthStrip surface="admin" />

      {/* ── Body: left nav + main ───────────────────────────────────────── */}
      <div style={{ display: 'flex', flex: 1, minHeight: 0, overflow: 'hidden' }}>
        <AdminLeftNav
          role={effectiveRole}
          pathname={location.pathname}
          incidentCounts={incidentCounts}
        />
        <main
          className="admin-shell__main"
          data-testid="admin-main"
          style={{
            flex: 1,
            minWidth: 0,
            padding: 20,
            overflowY: 'auto',
          }}
        >
          <Outlet />
        </main>
      </div>
    </div>
  );
}
