import { useEffect, useRef, useState } from 'react';

interface TradingViewWidgetProps {
  symbol?: string;
}

const WIDGET_SRC = 'https://s3.tradingview.com/external-embedding/embed-widget-advanced-chart.js';

export function TradingViewWidget({ symbol = 'BINANCE:BTCUSDT' }: TradingViewWidgetProps): JSX.Element {
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;

    let active = true;
    let loaded = false;
    const timeout = window.setTimeout(() => {
      if (active && !loaded) setFailed(true);
    }, 7000);

    setFailed(false);
    container.replaceChildren();

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

    container.appendChild(script);

    return () => {
      active = false;
      window.clearTimeout(timeout);
      container.replaceChildren();
    };
  }, [symbol]);

  return (
    <div className="tradingview-widget-shell" data-testid="tradingview-widget" data-symbol={symbol}>
      <div className="tradingview-widget-container" ref={containerRef} />
      {failed ? (
        <div className="tradingview-widget-fallback" role="status">
          Chart unavailable. TradingView widget failed to load.
        </div>
      ) : null}
    </div>
  );
}
