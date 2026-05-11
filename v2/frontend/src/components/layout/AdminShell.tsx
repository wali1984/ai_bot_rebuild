import { Navigate, Outlet, useLocation } from 'react-router-dom';
import { useRoles, canSeePage } from '../../auth/rbac';
import { LiveBlockBanner } from '../banners/LiveBlockBanner';
import { Nav } from './Nav';
import { PAGES } from '../../pages/registry';

export function AdminShell(): JSX.Element {
  const role = useRoles();
  const location = useLocation();

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
        <h1>AI BOT V2 — Admin</h1>
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
