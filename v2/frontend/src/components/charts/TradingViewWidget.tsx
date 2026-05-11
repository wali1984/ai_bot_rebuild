import { useEffect, useRef, useState, type ReactNode } from 'react';

interface TradingViewWidgetProps {
  symbol?: string;
  fallback?: ReactNode;
}

const WIDGET_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';

export function TradingViewWidget({ symbol = 'BINANCE:BTCUSDT', fallback }: TradingViewWidgetProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const initializedRef = useRef(false);
  const symbolRef = useRef(symbol);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    if (initializedRef.current && symbolRef.current === symbol) return undefined;

    let active = true;
    let loaded = false;
    initializedRef.current = true;
    symbolRef.current = symbol;
    const timeout = window.setTimeout(() => {
      if (active && !loaded) setFailed(true);
    }, 7000);

    setFailed(false);
    container.replaceChildren();

    const widgetTarget = document.createElement('div');
    widgetTarget.className = 'tradingview-widget-container__widget';

    const script = document.createElement('script');
    script.src = WIDGET_SRC;
    script.async = true;
    script.type = 'text/javascript';
    script.onload = () => {
      loaded = true;
    };
    script.onerror = () => {
      if (active) setFailed(true);
    };
    script.innerHTML = JSON.stringify({
      autosize: true,
      symbol,
      interval: '15',
      timezone: 'Etc/UTC',
      theme: 'dark',
      style: '1',
      locale: 'en',
      allow_symbol_change: true,
      calendar: false,
      support_host: 'https://www.tradingview.com',
    });

    container.append(widgetTarget, script);

    return undefined;
  }, [symbol]);

  return (
    <div
      className="tradingview-widget-shell"
      data-testid="tradingview-widget"
      data-symbol={symbol}
      data-failed={failed ? 'true' : 'false'}
    >
      <div
        className="tradingview-widget-container"
        ref={containerRef}
        aria-hidden={failed ? 'true' : undefined}
      />
      {failed
        ? fallback ?? (
            <div className="tradingview-widget-fallback" role="status">
              Chart unavailable. TradingView widget failed to load.
            </div>
          )
        : null}
    </div>
  );
}
