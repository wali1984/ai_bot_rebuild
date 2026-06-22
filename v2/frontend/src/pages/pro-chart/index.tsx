import { useEffect, useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { ProChart } from '../../components/charts/ProChart';
import { ProChartSymbolPanel } from '../../components/charts/ProChartSymbolPanel';
import { useTraderContext } from '../../hooks/useTraderContext';
import meta from './meta';

const TIMEFRAMES = ['1m', '3m', '5m', '15m', '1h', '4h', '1d', '1w'] as const;
type TF = typeof TIMEFRAMES[number];

function normalizeProChartSymbol(value: string | undefined): string | null {
  if (!value) return null;
  const symbol = value.trim().toUpperCase();
  return /^[A-Z0-9]{3,24}$/.test(symbol) ? symbol : null;
}

function chartCanvasHeight(): number {
  if (typeof window === 'undefined') return 600;
  const compact = window.innerWidth <= 760;
  const reservedChrome = compact ? 238 : 274;
  return Math.max(320, Math.min(920, window.innerHeight - reservedChrome));
}

export default function ProChartPage(): JSX.Element {
  const { symbol: routeSymbol } = useParams<{ symbol?: string }>();
  const navigate = useNavigate();
  const [symbol, setSymbol] = useState(normalizeProChartSymbol(routeSymbol) ?? 'BTCUSDT');
  const [timeframe, setTimeframe] = useState<TF>('5m');
  const [chartHeight, setChartHeight] = useState(chartCanvasHeight);
  const traderContext = useTraderContext();

  useEffect(() => {
    const normalized = normalizeProChartSymbol(routeSymbol) ?? 'BTCUSDT';
    setSymbol(normalized);
    if (routeSymbol && routeSymbol.toUpperCase() !== normalized) {
      navigate(`/chart/${normalized}`, { replace: true });
    }
  }, [routeSymbol, navigate]);

  useEffect(() => {
    const updateHeight = (): void => setChartHeight(chartCanvasHeight());
    updateHeight();
    window.addEventListener('resize', updateHeight);
    window.visualViewport?.addEventListener('resize', updateHeight);
    return () => {
      window.removeEventListener('resize', updateHeight);
      window.visualViewport?.removeEventListener('resize', updateHeight);
    };
  }, []);

  const handleSelect = (sym: string): void => {
    const normalized = normalizeProChartSymbol(sym) ?? 'BTCUSDT';
    setSymbol(normalized);
    navigate(`/chart/${normalized}`, { replace: true });
  };

  const accountPosture = traderContext.accountBindingVerified
    ? `${traderContext.exchangeLabel} connected`
    : traderContext.accountBindingStatus;

  return (
    <div className="pro-chart-page" data-testid="page-pro-chart" data-page-id={meta.id}>
      <div className="pro-chart-header">
        <div className="pro-chart-header__symbol">
          <h1 className="pro-chart-header__name">{symbol}</h1>
          <span className="pro-chart-header__exchange">
            Public market data · {traderContext.accountScopeLabel} · {traderContext.accountBindingStatus}
          </span>
        </div>
        <div className="pro-chart-header__timeframes" role="tablist" aria-label="Timeframe selection">
          {TIMEFRAMES.map(tf => (
            <button
              key={tf}
              role="tab"
              aria-selected={timeframe === tf}
              className={`tf-btn ${timeframe === tf ? 'tf-btn--active' : ''}`}
              onClick={() => setTimeframe(tf)}
            >
              {tf}
            </button>
          ))}
        </div>
        <div className="pro-chart-header__right">
          <span className="status-pill" style={{ fontSize: 11 }}>
            Live chart
          </span>
          <span className="status-pill" style={{ fontSize: 11 }}>
            {traderContext.accountLabel}
          </span>
          <span className="status-pill" style={{ fontSize: 11 }}>
            {accountPosture}
          </span>
        </div>
      </div>

      <div className="pro-chart-status-strip" aria-label="Chart source and account status">
        <span className="pro-chart-status-strip__item pro-chart-status-strip__item--safe">
          Live market data
        </span>
        <span className="pro-chart-status-strip__item">
          Realtime source: Binance public stream when frames arrive; public REST candle backfill when needed
        </span>
        <span className="pro-chart-status-strip__item">
          Trader scope: {traderContext.accountScopeLabel}
        </span>
        <span className="pro-chart-status-strip__item pro-chart-status-strip__item--blocked">
          Live order placement off
        </span>
      </div>

      <div className="pro-chart-layout">
        <div className="pro-chart-main">
          <ProChart
            symbol={symbol}
            timeframe={timeframe}
            height={chartHeight}
          />
        </div>
        <div className="pro-chart-sidebar">
          <ProChartSymbolPanel
            activeSymbol={symbol}
            onSymbolSelect={handleSelect}
          />
        </div>
      </div>
    </div>
  );
}
