import { NavLink, useLocation } from 'react-router-dom';
import { useRoles, canSeePage, type RoleLike } from '../../auth/rbac';
import { PAGES } from '../../pages/registry';

const CATEGORY_LABELS: Record<string, string> = {
  overview: 'Overview',
  observability: 'Monitoring',
  trainer: 'AI & Models',
  risk: 'Risk',
  execution: 'Execution',
  market: 'Markets',
  trading: 'Trading',
  admin: 'Admin',
  audit: 'Audit',
  ai: 'AI Tools',
  mobile: 'Platform',
  signals: 'Signals',
  analytics: 'Analytics',
  account: 'Account',
};

const CATEGORY_ORDER = [
  'overview', 'market', 'trading', 'signals', 'trainer', 'execution',
  'risk', 'observability', 'analytics', 'ai', 'admin', 'mobile', 'audit', 'account',
];

export function Nav({ role: confirmedRole }: { role?: RoleLike } = {}): JSX.Element {
  const sessionRole = useRoles();
  const role = confirmedRole ?? sessionRole;
  const location = useLocation();

  const adminPages = PAGES.filter(
    (p) => p.meta.surface === 'admin' || p.meta.surface === 'system',
  );
  const visible = adminPages.filter((p) => canSeePage(role, p.rbac.minRole));

  const byCategory = new Map<string, typeof visible>();
  for (const page of visible) {
    const cat = page.meta.navCategory ?? 'admin';
    byCategory.set(cat, [...(byCategory.get(cat) ?? []), page]);
  }

  const categories = [
    ...CATEGORY_ORDER.filter((c) => byCategory.has(c)),
    ...Array.from(byCategory.keys())
      .filter((c) => !CATEGORY_ORDER.includes(c))
      .sort(),
  ];

  return (
    <nav
      className="nav platform-nav"
      aria-label="Admin navigation"
      data-testid="admin-nav"
      data-actor-role={role}
    >
      {categories.map((cat) => {
        const pages = byCategory.get(cat) ?? [];
        return (
          <details className="nav__group" key={cat} open>
            <summary className="nav__group-head">
              <span>{CATEGORY_LABELS[cat] ?? cat}</span>
            </summary>
            <ul>
              {pages.map((p) => {
                const active = location.pathname === p.route.path;
                return (
                  <li key={p.meta.id} data-testid={`nav-item-${p.meta.id}`}>
                    <NavLink
                      className={active ? 'nav__link nav__link--active' : 'nav__link'}
                      to={p.route.path}
                    >
                      {p.meta.title}
                    </NavLink>
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
