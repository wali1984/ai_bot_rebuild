import { Outlet } from 'react-router-dom';
import { RuntimeTruthStrip } from './RuntimeTruthStrip';
import { TopBar } from './TopBar';

export function PublicShell(): JSX.Element {
  return (
    <div
      className="platform-shell platform-shell--public"
      data-testid="public-shell"
      style={{ background: 'var(--bg-base)', color: 'var(--text-primary)' }}
    >
      <TopBar surface="public" showSymbolSearch={false} />
      <RuntimeTruthStrip surface="public" />
      <main
        className="public-shell__main"
        data-testid="public-main"
        style={{ minWidth: 0 }}
      >
        <Outlet />
      </main>
    </div>
  );
}
