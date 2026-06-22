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
  const [ready, setReady] = useState(false);

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return undefined;
    if (initializedRef.current && symbolRef.current === symbol) return undefined;

    let active = true;
    let observer: MutationObserver | null = null;
    initializedRef.current = true;
    symbolRef.current = symbol;
    const timeout = window.setTimeout(() => {
      if (active && !container.querySelector('iframe')) setFailed(true);
    }, 5000);
    const poll = window.setInterval(() => {
      if (active && container.querySelector('iframe')) {
        setReady(true);
        setFailed(false);
      }
    }, 250);

    setFailed(false);
    setReady(false);
    container.replaceChildren();
    observer = new MutationObserver(() => {
      if (active && container.querySelector('iframe')) {
        setReady(true);
        setFailed(false);
      }
    });
    observer.observe(container, { childList: true, subtree: true });

    const widgetTarget = document.createElement('div');
    widgetTarget.className = 'tradingview-widget-container__widget';

    const script = document.createElement('script');
    script.src = WIDGET_SRC;
    script.async = true;
    script.type = 'text/javascript';
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

    return () => {
      active = false;
      window.clearTimeout(timeout);
      window.clearInterval(poll);
      observer?.disconnect();
    };
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
      {!ready && fallback ? fallback : null}
      {!ready ? (
        <div className="tradingview-widget-loading" role="status">
          {failed
            ? `TradingView external widget did not connect for ${symbol}. Local live-market chart remains active.`
            : `TradingView connecting for ${symbol}. Local live-market chart is active.`}
        </div>
      ) : null}
      {failed && !fallback ? (
        <div className="tradingview-widget-fallback" role="status">
          TradingView external widget did not connect.
        </div>
      ) : null}
    </div>
  );
}
