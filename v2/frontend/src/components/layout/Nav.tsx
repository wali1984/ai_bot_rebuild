import { NavLink, useLocation } from 'react-router-dom';
import { useRoles, canSeePage, type RoleLike } from '../../auth/rbac';
import { PAGES } from '../../pages/registry';
import { moduleForCategory } from '../../brand/nervyxBrand';
import { NervyxModuleBadge } from './NervyxModuleBadge';

const CATEGORY_LABELS: Record<string, string> = {
  overview: 'Overview',
  data: 'Data',
  intelligence: 'Intelligence',
  orchestration: 'Orchestration',
  risk: 'Risk & Readiness',
  execution: 'Execution',
  exchanges: 'Exchanges',
  config: 'Configuration',
  users: 'Users',
  reports: 'Reports',
  logs: 'Logs',
  tools: 'Developer Tools',
  // Legacy / trader-surface categories (not shown in admin nav but kept for safety)
  observability: 'Monitoring',
  trainer: 'Models',
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
  'data', 'intelligence', 'orchestration', 'exchanges', 'config', 'users', 'reports',
  'logs', 'tools',
];

// Utility groups start collapsed — only superadmin roles can see them
const UTILITY_CATEGORIES = new Set(['logs', 'audit', 'tools']);

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
          <details className="nav__group" key={cat} open={!UTILITY_CATEGORIES.has(cat)}>
            <summary className="nav__group-head">
              <span>{CATEGORY_LABELS[cat] ?? cat}</span>
              <NervyxModuleBadge moduleId={moduleForCategory(cat)} compact />
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
