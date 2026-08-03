import type { ReactNode } from 'react';
import '../../styles/trader.css';

export function TraderPage({
  kicker,
  title,
  subtitle,
  actions,
  children,
}: {
  kicker?: string;
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  children: ReactNode;
}): JSX.Element {
  return (
    <main className="trader-page">
      <header className="trader-page__header">
        <div>
          {kicker ? <p className="trader-page__kicker">{kicker}</p> : null}
          <h1 className="trader-page__title">{title}</h1>
          {subtitle ? <p className="trader-page__subtitle">{subtitle}</p> : null}
        </div>
        {actions ? <div className="trader-status-strip">{actions}</div> : null}
      </header>
      {children}
    </main>
  );
}
