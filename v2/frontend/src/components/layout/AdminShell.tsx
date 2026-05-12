import { useEffect } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useRoles, canSeePage, type Role } from '../../auth/rbac';
import { sessionStore } from '../../auth/session';
import { LiveBlockBanner } from '../banners/LiveBlockBanner';
import { Nav } from './Nav';
import { PAGES } from '../../pages/registry';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload, useTonightReadinessPayload } from '../../pages/operatorTruthData';

const VALID_ROLES = new Set<Role>(['public', 'viewer', 'operator', 'reviewer', 'admin', 'live_approver']);

function roleFromSearch(search: string): Role | null {
  const role = new URLSearchParams(search).get('role') as Role | null;
  return role && VALID_ROLES.has(role) ? role : null;
}

export function AdminShell(): JSX.Element {
  const sessionRole = useRoles();
  const location = useLocation();
  const { payload } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload(15_000);
  const { payload: tonightReadiness } = useTonightReadinessPayload(15_000);
  const queryRole = roleFromSearch(location.search);
  const role = queryRole ?? sessionRole;
  const paperLineageIds = paperRuntime?.current_signal_lineage?.lineage_ids as Record<string, unknown> | undefined;
  const currentRiskDecision = paperRuntime?.current_risk_decision as Record<string, unknown> | undefined;

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
          <p className="eyebrow">Production operator cockpit / paper-shadow twin</p>
          <h1>AI BOT V2 Shadow Desk</h1>
        </div>
        <div className="admin-command-rail" aria-label="Global operator runtime state">
          <span className="chip solid-block">LIVE: {payload?.live_gate_status ?? 'blocked_human_only'}</span>
          <span className={paperRuntime?.runtime_state === 'PAPER_RUNTIME_ONLINE_ACTIVE' ? 'chip solid-ok' : 'chip solid-warn'}>
            Paper: {paperRuntime?.runtime_state ?? 'loading'}
          </span>
          <span className={tonightReadiness?.legacy_bridge_status === 'CURRENT' ? 'chip solid-ok' : 'chip solid-warn'}>
            Bridge: {tonightReadiness?.legacy_bridge_status ?? 'loading'}
          </span>
          <span className="chip">BTCUSDT: {paperRuntime?.market_feed?.price ?? 'loading'}</span>
          <span className={payload?.supervisor_status.stale_or_conflicting ? 'chip solid-warn' : 'chip solid-ok'}>
            Supervisor: {payload?.supervisor_status.stale_or_conflicting ? 'stale/conflicting' : 'current'}
          </span>
          <span className="chip">Routes: {tonightReadiness ? `${tonightReadiness.public_route_failed_count ?? 'n/a'} public fails` : 'loading'}</span>
          <span className="chip">Next: {payload?.current_next_task ?? 'missing'}</span>
          <span className={payload?.trainer_monitor_status.status === 'V2_PAPER_TRAINER_WRAPPER_CURRENT' ? 'chip solid-ok' : 'chip solid-warn'}>
            Trainer: {payload?.trainer_monitor_status.status ?? 'loading'}
          </span>
        </div>
      </header>
      <section className="admin-shell__ticker" aria-label="Current trading desk ticker">
        <span>Mode: paper_shadow_live_blocked</span>
        <strong>{String(paperLineageIds?.signal_id ?? 'signal loading')}</strong>
        <span>Risk: {String(currentRiskDecision?.risk_result ?? 'loading')}</span>
        <span>Paper equity: {paperRuntime?.paper_account?.equity ?? 'loading'}</span>
        <span>Canary: approval required, not created</span>
      </section>
      <div className="admin-shell__body">
        <Nav />
        <main className="admin-shell__main" data-testid="admin-main">
          <Outlet />
        </main>
      </div>
    </div>
  );
}
