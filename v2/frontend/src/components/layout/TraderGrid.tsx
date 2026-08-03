import type { CSSProperties, ReactNode } from 'react';
import '../../styles/trader.css';

export function TraderGrid({
  children,
  className,
  style,
}: {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
}): JSX.Element {
  return (
    <div className={className ? `trader-grid ${className}` : 'trader-grid'} style={style}>
      {children}
    </div>
  );
}
