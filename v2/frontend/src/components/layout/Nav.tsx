import { Link } from 'react-router-dom';
import { useLocation } from 'react-router-dom';
import { useRoles, canSeePage } from '../../auth/rbac';
import { PAGES } from '../../pages/registry';
import { useOperatorTruthPayload } from '../../pages/operatorTruthData';

const CATEGORY_LABELS: Record<string, string> = {
  overview: 'Mission',
  observability: 'System',
  trainer: 'AI / Signals',
  risk: 'Risk',
  execution: 'Execution',
  market: 'Markets',
  trading: 'Markets',
  admin: 'Admin',
  audit: 'Proof / Audit',
  ai: 'AI Operators',
  mobile: 'Admin',
};

const CATEGORY_ORDER = ['overview', 'market', 'trading', 'trainer', 'execution', 'risk', 'observability', 'ai', 'admin', 'mobile', 'audit'];

function categoryWarningCount(category: string, stalePayloads: number, missingEvidence: number, staleSupervisor: boolean): number {
  if (category === 'overview') return stalePayloads + missingEvidence + (staleSupervisor ? 1 : 0);
  if (category === 'observability') return staleSupervisor ? 1 : 0;
  if (category === 'trainer') return missingEvidence;
  if (category === 'audit') return stalePayloads;
  if (category === 'risk') return 1;
  return 0;
}

export function Nav(): JSX.Element {
  const role = useRoles();
  const location = useLocation();
  const { payload } = useOperatorTruthPayload();
  const adminPages = PAGES.filter((p) => p.meta.surface === 'admin');
  const visible = adminPages.filter((p) => canSeePage(role, p.rbac.minRole));
  const byCategory = new Map<string, typeof visible>();
  for (const page of visible) {
    const category = page.meta.navCategory ?? 'admin';
    const existing = byCategory.get(category) ?? [];
    byCategory.set(category, [...existing, page]);
  }
  const stalePayloads = payload?.dashboard_freshness_status.stale_payload_count ?? 0;
  const missingEvidence = payload?.dashboard_freshness_status.missing_evidence_count ?? 0;
  const staleSupervisor = payload?.supervisor_status.stale_or_conflicting ?? false;
  const categories = [
    ...CATEGORY_ORDER.filter((category) => byCategory.has(category)),
    ...Array.from(byCategory.keys()).filter((category) => !CATEGORY_ORDER.includes(category)).sort(),
  ];
  return (
    <nav className="nav" aria-label="Admin navigation" data-testid="admin-nav" data-actor-role={role}>
      <div className="nav__status">
        <span>Operator role</span>
        <strong>{role}</strong>
        <small>{staleSupervisor ? 'Supervisor stale/conflicting' : 'Supervisor snapshot loaded'}</small>
      </div>
      {categories.map((category) => {
        const pages = byCategory.get(category) ?? [];
        const warningCount = categoryWarningCount(category, stalePayloads, missingEvidence, staleSupervisor);
        return (
          <details className="nav__group" key={category} aria-label={`${CATEGORY_LABELS[category] ?? category} navigation`} open>
            <summary className="nav__group-head">
              <span>{CATEGORY_LABELS[category] ?? category}</span>
              {warningCount ? <strong>{warningCount}</strong> : null}
            </summary>
            <ul>
              {pages.map((p) => {
                const active = p.route.path === location.pathname;
                return (
                  <li key={p.meta.id} data-testid={`nav-item-${p.meta.id}`}>
                    <Link className={active ? 'nav__link nav__link--active' : 'nav__link'} to={p.route.path}>
                      {p.meta.title}
                    </Link>
                  </li>
                );
              })}
            </ul>
          </details>
        );
      })}
    </nav>
  );
}
