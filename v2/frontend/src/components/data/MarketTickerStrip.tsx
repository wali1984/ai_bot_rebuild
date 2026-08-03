import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface TickerItem {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
}

interface MarketTickerData {
  tickers?: TickerItem[];
  symbols?: string[];
  count?: number;
}

function fmt(n: number | null): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { maximumFractionDigits: n > 100 ? 2 : 4 });
}

function pctColor(change: number | null): string {
  if (change == null) return 'flat';
  return change > 0 ? 'up' : change < 0 ? 'down' : 'flat';
}

function pctText(change: number | null): string {
  if (change == null) return '—';
  const pct = Math.abs(change) <= 1 ? change * 100 : change;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

const PINNED = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT', 'AVAXUSDT', 'DOGEUSDT'];

export function MarketTickerStrip(): JSX.Element {
  const { envelope } = useRealtimeResource<MarketTickerData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    pollIntervalMs: 15_000,
    staleThresholdMs: 45_000,
    mode: 'read_only',
  });

  const items = useMemo<TickerItem[]>(() => {
    const data = envelope.data;
    if (data?.tickers?.length) {
      const sorted = [...data.tickers].sort((a, b) => {
        const ap = PINNED.indexOf(a.symbol);
        const bp = PINNED.indexOf(b.symbol);
        if (ap !== -1 && bp !== -1) return ap - bp;
        if (ap !== -1) return -1;
        if (bp !== -1) return 1;
        return Math.abs(b.change_24h ?? 0) - Math.abs(a.change_24h ?? 0);
      });
      return sorted.slice(0, 30);
    }
    if (data?.symbols?.length) {
      return data.symbols.slice(0, 30).map((symbol) => ({ symbol, last_price: null, change_24h: null }));
    }
    return [];
  }, [envelope.data]);

  if (!items.length) return <></>;

  return (
    <div className="market-ticker-strip" role="marquee" aria-label="Market ticker strip">
      {items.map((item) => (
        <Link
          key={item.symbol}
          to={`/market/${item.symbol}`}
          className="market-ticker-strip__item"
          style={{ textDecoration: 'none' }}
        >
          <span className="market-ticker-strip__symbol">{item.symbol.replace('USDT', '')}</span>
          {item.last_price != null && (
            <span className="market-ticker-strip__price">{fmt(item.last_price)}</span>
          )}
          {item.change_24h != null && (
            <span className={`market-ticker-strip__change market-ticker-strip__change--${pctColor(item.change_24h)}`}>
              {pctText(item.change_24h)}
            </span>
          )}
        </Link>
      ))}
    </div>
  );
}
