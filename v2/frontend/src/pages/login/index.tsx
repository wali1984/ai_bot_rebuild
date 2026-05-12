import { Link } from 'react-router-dom';
import meta from './meta';
import { sessionStore } from '../../auth/session';
import { useRoles, type Role } from '../../auth/rbac';
import { Metric, Panel } from '../cockpitComponents';
import { useTonightReadinessPayload } from '../operatorTruthData';

const LOCAL_ROLES: Role[] = ['viewer', 'operator', 'reviewer', 'admin'];

export default function LoginPage(): JSX.Element {
  const role = useRoles();
  const { payload: tonightReadiness } = useTonightReadinessPayload();
  return (
    <article className="production-public-page grid-bg" data-testid="page-login" data-page-id={meta.id}>
      <header className="public-page-header panel bracketed">
        <span className="br-bl" aria-hidden="true" />
        <span className="br-br" aria-hidden="true" />
        <p className="eyebrow">Local access / RBAC preview</p>
        <h1>{meta.title}</h1>
        <p>Local role selection for the operator dashboard. This does not grant live authority and does not expose exchange keys.</p>
      </header>
      <section className="public-market-strip" aria-label="Access state">
        <Metric label="Current role" value={role} />
        <Metric label="Live gate" value={tonightReadiness?.live_gate_status ?? 'blocked_human_only'} />
        <Metric label="Canary preflight" value={tonightReadiness?.canary_preflight_status ?? 'approval required'} />
        <Metric label="Public route failures" value={tonightReadiness?.public_route_failed_count ?? 'loading'} />
      </section>
      <Panel id="local-role-selector" title="Local Role Selector" right={<span className="chip solid-paper">No live authority</span>}>
        <div className="role-button-grid">
          {LOCAL_ROLES.map((nextRole) => (
            <button
              type="button"
              className={role === nextRole ? 'role-button role-button--active' : 'role-button'}
              key={nextRole}
              onClick={() => sessionStore.setRole(nextRole)}
            >
              <strong>{nextRole}</strong>
              <span>{nextRole === 'admin' ? 'Full UI visibility, dangerous controls still disabled.' : 'Read-only or review visibility.'}</span>
            </button>
          ))}
        </div>
        <div className="public-feature-grid">
          <div className="public-feature-card">
            <h3>Access Boundary</h3>
            <p>Role selection is browser-local and only changes visible dashboard surfaces. It cannot place orders or approve live trading.</p>
            <span>Session storage only</span>
          </div>
          <div className="public-feature-card">
            <h3>Next Step</h3>
            <p>Open Mission Control with an admin role to inspect current paper/shadow runtime and remaining blockers.</p>
            <Link to="/admin/mission-control?role=admin">Open Mission Control</Link>
          </div>
        </div>
      </Panel>
    </article>
  );
}
