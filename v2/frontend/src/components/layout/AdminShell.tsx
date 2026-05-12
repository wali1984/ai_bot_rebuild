import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useRoles, canSeePage, type Role } from '../../auth/rbac';
import { sessionStore } from '../../auth/session';
import { LiveBlockBanner } from '../banners/LiveBlockBanner';
import { Nav } from './Nav';
import { PAGES } from '../../pages/registry';
import { useOperatorTruthPayload } from '../../pages/operatorTruthData';

const VALID_ROLES = new Set<Role>(['public', 'viewer', 'operator', 'reviewer', 'admin', 'live_approver']);

function roleFromSearch(search: string): Role | null {
  const role = new URLSearchParams(search).get('role') as Role | null;
  return role && VALID_ROLES.has(role) ? role : null;
}

export function AdminShell(): JSX.Element {
  const sessionRole = useRoles();
  const location = useLocation();
  const { payload } = useOperatorTruthPayload();
  const queryRole = roleFromSearch(location.search);
  const role = queryRole ?? sessionRole;

  useEffect(() => {
    if (queryRole && queryRole !== sessionRole) {
      sessionStore.setRole(queryRole);
    }
  }, [queryRole, sessionRole]);

  if (role === 'public') {
    return <Navigate to="/" replace />;
  }

  const page = PAGES.find((p) => p.route.path === location.pathname && p.meta.surface === 'admin');
  if (page && !canSeePage(role, page.rbac.minRole)) {
    return <Navigate to="/" replace />;
  }

  return (
    <div className="admin-shell">
      <LiveBlockBanner />
      <header className="admin-shell__header">
        <div>
          <p className="eyebrow">Production operator cockpit</p>
          <h1>AI BOT V2</h1>
        </div>
        <div className="admin-command-rail" aria-label="Global operator runtime state">
          <span className="chip solid-block">LIVE: {payload?.live_gate_status ?? 'blocked_human_only'}</span>
          <span className={payload?.supervisor_status.stale_or_conflicting ? 'chip solid-warn' : 'chip solid-ok'}>
            Supervisor: {payload?.supervisor_status.stale_or_conflicting ? 'stale/conflicting' : 'current'}
          </span>
          <span className="chip">Current: {payload?.supervisor_status.current_running_task ?? 'none'}</span>
          <span className="chip">Next: {payload?.current_next_task ?? 'missing'}</span>
          <span className="chip solid-warn">Trainer: {payload?.trainer_monitor_status.status ?? 'MISSING_EVIDENCE'}</span>
        </div>
      </header>
      <div className="admin-shell__body">
        <Nav />
        <main className="admin-shell__main" data-testid="admin-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
