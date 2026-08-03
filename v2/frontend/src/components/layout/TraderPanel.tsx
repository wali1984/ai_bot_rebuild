import type { CSSProperties, ReactNode } from 'react';
import '../../styles/trader.css';

export function TraderPanel({
  title,
  right,
  children,
  className,
  style,
}: {
  title?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}): JSX.Element {
  return (
    <section className={className ? `trader-panel ${className}` : 'trader-panel'} style={style}>
      {title || right ? (
        <header className="trader-panel__header">
          {title ? <h2 className="trader-panel__title">{title}</h2> : <span />}
          {right}
        </header>
      ) : null}
      <div className="trader-panel__body">
        {children}
      </div>
    </section>
  );
}
