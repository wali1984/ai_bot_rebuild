import { useMemo, useState } from 'react';
import { useAuth } from '../../hooks/useAuth';
import { useRoles } from '../../auth/rbac';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import type { MarketOverviewData } from '../../api/v2Market';
import './proChartInternals.css';

interface WatchlistSymbol {
  symbol: string;
  price: number | null;
  signal: string | null;
  source_age_s: number | null;
}

interface ChartSymbolsData {
  symbols?: WatchlistSymbol[];
}

// Public fallback favorites. Signed-in traders use their saved watchlist first.
const DEFAULT_FAVORITES = [
  'BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT',
  'LINKUSDT', 'LTCUSDT', 'AVAXUSDT', 'ADAUSDT',
];
const LOCAL_TRADER_PREVIEW_WATCHLIST = ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'];

export interface ProChartSymbolPanelProps {
  activeSymbol: string;
  onSymbolSelect: (symbol: string) => void;
}

function normalizeSymbol(value: unknown): string | null {
  if (typeof value !== 'string') return null;
  const symbol = value.trim().toUpperCase();
  return /^[A-Z0-9]+$/.test(symbol) ? symbol : null;
}

function mergeSymbols(primary: WatchlistSymbol[], supplemental: WatchlistSymbol[]): WatchlistSymbol[] {
  const rows = new Map<string, WatchlistSymbol>();
  for (const row of primary) {
    const symbol = normalizeSymbol(row.symbol);
    if (symbol) rows.set(symbol, { ...row, symbol });
  }
  for (const row of supplemental) {
    const symbol = normalizeSymbol(row.symbol);
    if (!symbol) continue;
    rows.set(symbol, { ...(rows.get(symbol) ?? { symbol, price: null, signal: null, source_age_s: null }), ...row, symbol });
  }
  return [...rows.values()].sort((a, b) => a.symbol.localeCompare(b.symbol));
}

function freshnessLabel(sourceAgeSeconds: number | null | undefined): { label: string; stale: boolean; title: string } {
  if (sourceAgeSeconds == null || !Number.isFinite(sourceAgeSeconds)) {
    return {
      label: 'Connecting stream',
      stale: true,
      title: 'No current source age is available for this symbol.',
    };
  }
  const seconds = Math.max(0, Math.round(sourceAgeSeconds));
  if (seconds > 120) {
    return {
      label: 'Stale data',
      stale: true,
      title: `Last symbol snapshot is ${seconds}s old.`,
    };
  }
  return {
    label: `${seconds}s`,
    stale: false,
    title: `Last symbol snapshot is ${seconds}s old.`,
  };
}

export function ProChartSymbolPanel({ activeSymbol, onSymbolSelect }: ProChartSymbolPanelProps): JSX.Element {
  const [search, setSearch] = useState('');
  const [tab, setTab] = useState<'fav' | 'all'>('fav');
  const { user } = useAuth();
  const sessionRole = useRoles();
  const overview = useRealtimeResource<MarketOverviewData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
  });
  const supplemental = useRealtimeResource<ChartSymbolsData>({
    url: '/api/v1/chart/symbols',
    source: '/api/v1/chart/symbols',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const symbols = useMemo(() => {
    const sourceAgeSeconds = overview.envelope.lag_ms == null
      ? null
      : Math.max(0, overview.envelope.lag_ms / 1000);
    const tickerBySymbol = new Map(
      (overview.envelope.data?.tickers ?? [])
        .map((row) => {
          const symbol = normalizeSymbol(row.symbol);
          return symbol ? [symbol, row] as const : null;
        })
        .filter((row): row is readonly [string, NonNullable<MarketOverviewData['tickers']>[number]] => row !== null),
    );
    const typedSymbols = (overview.envelope.data?.symbols ?? [])
      .map((symbol) => normalizeSymbol(symbol))
      .filter((symbol): symbol is string => symbol !== null)
      .map((symbol) => ({
        symbol,
        price: tickerBySymbol.get(symbol)?.last_price ?? null,
        signal: null,
        source_age_s: sourceAgeSeconds,
      }));
    const supplementalSymbols = Array.isArray(supplemental.envelope.data?.symbols)
      ? supplemental.envelope.data.symbols
      : [];
    return mergeSymbols(supplementalSymbols, typedSymbols);
  }, [overview.envelope.data, overview.envelope.lag_ms, supplemental.envelope.data]);

  const bySymbol = new Map(symbols.map(s => [s.symbol, s]));
  const previewWatchlist = !user && sessionRole === 'trader' ? LOCAL_TRADER_PREVIEW_WATCHLIST : DEFAULT_FAVORITES;
  const configuredFavorites = (user?.watchlist?.length ? user.watchlist : previewWatchlist)
    .map((value) => value.trim().toUpperCase())
    .filter((value, index, list) => /^[A-Z0-9]+$/.test(value) && list.indexOf(value) === index);
  const favorites = configuredFavorites.length ? configuredFavorites : DEFAULT_FAVORITES;

  const filtered = (
    tab === 'fav'
      ? favorites.map(s => bySymbol.get(s) ?? { symbol: s, price: null, signal: null, source_age_s: null })
      : symbols
  ).filter(s => s.symbol.toLowerCase().includes(search.toLowerCase()));

  return (
    <div className="symbol-panel">
      <div className="symbol-panel__tabs">
        <button className={tab === 'fav' ? 'active' : ''} onClick={() => setTab('fav')}>
          Favorites
        </button>
        <button className={tab === 'all' ? 'active' : ''} onClick={() => setTab('all')}>
          Markets
        </button>
      </div>

      <div className="symbol-panel__search">
        <input
          type="text"
          placeholder="Search symbol..."
          value={search}
          onChange={e => setSearch(e.target.value)}
          aria-label="Search symbols"
        />
      </div>

      <div className="symbol-panel__list" role="listbox" aria-label="Symbol watchlist">
        {filtered.map(s => {
          const isActive = s.symbol === activeSymbol;
          // The signal vocabulary is long/short/hold (not BUY/SELL), so the old
          // 'BUY'/'SELL' substring test never matched and no arrow ever rendered.
          const dir = /long|buy/i.test(s.signal ?? '') ? 'buy' : /short|sell/i.test(s.signal ?? '') ? 'sell' : null;
          const displayName = s.symbol.replace('USDT', '');
          const priceStr = s.price != null
            ? `$${s.price.toLocaleString('en-US', { maximumFractionDigits: 4 })}`
            : 'Connecting stream';
          const freshness = freshnessLabel(s.source_age_s);
          return (
            <button
              key={s.symbol}
              role="option"
              aria-selected={isActive}
              className={`symbol-row ${isActive ? 'symbol-row--active' : ''}`}
              onClick={() => onSymbolSelect(s.symbol)}
              title={s.symbol}
            >
              <span className="symbol-row__name">{displayName}</span>
              <div className="symbol-row__right">
                <span className="symbol-row__price">{priceStr}</span>
                <span
                  className={`symbol-row__freshness${freshness.stale ? ' symbol-row__freshness--stale' : ''}`}
                  title={freshness.title}
                >
                  {freshness.label}
                </span>
                {dir && (
                  <span
                    className={`symbol-row__sig symbol-row__sig--${dir}`}
                    aria-label={dir === 'buy' ? 'Buy signal' : 'Sell signal'}
                  >
                    {dir === 'buy' ? '▲' : '▼'}
                  </span>
                )}
              </div>
            </button>
          );
        })}
        {filtered.length === 0 && (
          <p className="symbol-panel__empty">No symbols match "{search}"</p>
        )}
      </div>
    </div>
  );
}
