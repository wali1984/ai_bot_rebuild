import { Link } from 'react-router-dom';
import { useRoles, canSeePage } from '../../auth/rbac';
import { PAGES } from '../../pages/registry';

export function Nav(): JSX.Element {
  const role = useRoles();
  const adminPages = PAGES.filter((p) => p.meta.surface === 'admin');
  const visible = adminPages.filter((p) => canSeePage(role, p.rbac.minRole));
  return (
    <nav className="nav" aria-label="Admin navigation" data-testid="admin-nav" data-actor-role={role}>
      <ul>
        {visible.map((p) => (
          <li key={p.meta.id} data-testid={`nav-item-${p.meta.id}`}>
            <Link to={p.route.path}>{p.meta.title}</Link>
          </li>
        ))}
      </ul>
    </nav>
  );
}
