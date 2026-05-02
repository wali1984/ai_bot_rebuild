import { Outlet } from 'react-router-dom';
import { LiveBlockBanner } from '../banners/LiveBlockBanner';

export function PublicShell(): JSX.Element {
  return (
    <div className="public-shell">
      <LiveBlockBanner />
      <header className="public-shell__header">
        <span className="public-shell__brand">AI BOT V2</span>
      </header>
      <main className="public-shell__main" data-testid="public-main">
        <Outlet />
      </main>
    </div>
  );
}
