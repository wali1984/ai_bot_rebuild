import { Outlet } from 'react-router-dom';
import { Link } from 'react-router-dom';
import { LiveBlockBanner } from '../banners/LiveBlockBanner';

export function PublicShell(): JSX.Element {
  return (
    <div className="public-shell">
      <LiveBlockBanner />
      <header className="public-shell__header">
        <Link className="public-shell__brand" to="/landing">AI BOT V2</Link>
        <nav className="public-shell__nav" aria-label="Public dashboard navigation">
          <Link to="/landing">Overview</Link>
          <Link to="/status">Status</Link>
          <Link to="/login">Access</Link>
          <Link to="/admin/mission-control?role=admin">Mission Control</Link>
        </nav>
      </header>
      <main className="public-shell__main" data-testid="public-main">
        <Outlet />
      </main>
    </div>
  );
}
