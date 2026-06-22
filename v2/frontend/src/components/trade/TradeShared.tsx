import type { ReactNode } from 'react';
import { AlertTriangle } from 'lucide-react';
import { StatusPill } from '../trading/TradingPrimitives';

export function TradePanel({
  title,
  kicker,
  actions,
  children,
  testId,
}: {
  title: string;
  kicker?: ReactNode;
  actions?: ReactNode;
  children: ReactNode;
  testId?: string;
}): JSX.Element {
  return (
    <section className="trade-panel" data-testid={testId}>
      <header className="trade-panel__head">
        <div>
          {kicker ? <span>{kicker}</span> : null}
          <h2>{title}</h2>
        </div>
        {actions ? <div className="trade-panel__actions">{actions}</div> : null}
      </header>
      <div className="trade-panel__body">{children}</div>
    </section>
  );
}

export function MissingDataState({
  title,
  detail,
  endpoint,
  compact = false,
  showEndpoint = false,
}: {
  title: string;
  detail: string;
  endpoint?: string;
  compact?: boolean;
  showEndpoint?: boolean;
}): JSX.Element {
  return (
    <div className={compact ? 'trade-missing trade-missing--compact' : 'trade-missing'} data-testid="trade-missing-data-state">
      <AlertTriangle size={16} aria-hidden="true" />
      <div>
        <StatusPill tone="warn">Connecting stream</StatusPill>
        <strong>{title}</strong>
        <p>{detail}</p>
        {showEndpoint && endpoint ? <code>{endpoint}</code> : null}
      </div>
    </div>
  );
}

export function ModeBadge(): JSX.Element {
  return <span className="trade-mode-badge" data-testid="live-platform-badge">Live Platform</span>;
}
