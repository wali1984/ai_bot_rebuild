import { useMemo, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useOptionalAuth } from '../../hooks/useAuth';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { CanonicalMetricCard } from '../../components/data/CanonicalMetric';
import type { CanonicalMetric } from '../../selectors/accountSelectors';
import { selectMarketBySymbol, selectMarketMetric } from '../../selectors/marketSelectors';
import { marketFavoriteSymbolSet } from '../../lib/traderPageHelpers';

export { marketFavoriteSymbolSet };

interface TickerRow {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
  high_24h?: number | null;
  low_24h?: number | null;
  volume_24h?: number | null;
  turnover_24h?: number | null;
  trade_count_24h?: number | null;
  funding_rate?: number | null;
  open_interest?: number | null;
  long_short_ratio?: number | null;
  mark_price?: number | null;
  index_price?: number | null;
}

interface MarketOverviewData {
  symbols?: string[];
  count?: number;
  tickers?: TickerRow[];
}

interface ProviderCard {
  provider: string;
  display_name?: string;
  status?: string | null;
  dashboard_color?: string | null;
  actual_payload_count?: number | null;
  feature_count?: number | null;
  consumer_roles?: string[] | null;
  heartbeat_only?: boolean | null;
  actual_payload_present?: boolean | null;
}

interface ProviderStatusData {
  providers?: ProviderCard[];
  live_gate?: string;
  places_real_order?: boolean;
  routes_to_live?: boolean;
}

type TabId = 'overview' | 'gainers' | 'losers' | 'watchlist';
type SortKey = 'symbol' | 'last_price' | 'change_24h' | 'turnover_24h' | 'volume_24h';

const MARKET_PROVIDER_ORDER = [
  ['binance', 'Binance'],
  ['kucoin', 'KuCoin'],
  ['coinank', 'CoinAnk'],
  ['coinglass', 'CoinGlass'],
  ['moralis', 'Moralis'],
  ['ta', 'TA Engine'],
  ['feature_snapshot_builder', 'Feature Snapshots'],
  ['microstructure', 'Microstructure'],
  ['liquidations', 'Liquidations'],
  ['orderbook', 'Orderbook'],
  ['trainer_feed', 'Trainer Feed'],
] as const;

interface IngestorRow {
  name: string;
  title?: string | null;
  redis_pattern?: string | null;
  key_count?: number | null;
  sampled_payloads?: number | null;
  newest_event_age_seconds?: number | null;
  status?: string | null;
  provider_current?: boolean | null;
  provider_unusable_reason?: string | null;
}

interface IngestorsStatusData {
  ingestors?: IngestorRow[];
}

function ingestorColor(status: string | null | undefined): string {
  const value = String(status ?? '').toLowerCase();
  if (value === 'live') return 'var(--buy, #10b981)';
  if (value === 'stale') return 'var(--warn, #f59e0b)';
  if (value === 'upstream_error' || value === 'down') return 'var(--sell, #ef4444)';
  return 'var(--text-muted)';
}

function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return '—';
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function MarketIngestorCoverage({ data }: { data: IngestorsStatusData | null | undefined }): JSX.Element {
  const rows = data?.ingestors ?? [];
  return (
    <section
      data-testid="market-ingestor-coverage"
      style={{
        marginTop: 14,
        padding: '12px 14px',
        borderRadius: 'var(--radius-md, 10px)',
        border: '1px solid var(--border)',
        background: 'var(--bg-elevated)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <strong style={{ fontSize: 12, color: 'var(--text-primary)' }}>Ingestor coverage</strong>
          <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            /api/v2/ingestors/status
          </span>
        </div>
        <Link to="/markets/ingestors" style={{ fontSize: 12, color: 'var(--accent, #3b82f6)', textDecoration: 'none' }}>
          Ingestor detail
        </Link>
      </div>
      {rows.length === 0 ? (
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>Loading ingestor registry…</p>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
          {rows.map((row) => {
            const color = ingestorColor(row.status);
            return (
              <div
                key={row.name}
                data-testid={`market-ingestor-${row.name}`}
                style={{
                  border: `1px solid ${color}`,
                  borderRadius: 'var(--radius-sm, 8px)',
                  padding: '8px 10px',
                  minWidth: 0,
                }}
              >
                <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 5 }}>
                  <strong style={{ fontSize: 12, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {row.title || row.name}
                  </strong>
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color }}>
                    {String(row.status ?? 'unknown').toUpperCase()}
                  </span>
                </div>
                <div style={{ display: 'grid', gap: 3, fontSize: 10.5, color: 'var(--text-muted)' }}>
                  <span>keys <b>{fmtSmallCount(row.key_count)}</b> · fresh <b>{fmtAge(row.newest_event_age_seconds)}</b></span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)' }}>
                    {row.redis_pattern || '—'}
                  </span>
                  {row.provider_unusable_reason ? (
                    <span
                      title={row.provider_unusable_reason}
                      style={{ color: 'var(--warn, #f59e0b)', overflowWrap: 'anywhere', wordBreak: 'break-word', minWidth: 0 }}
                    >
                      {row.provider_unusable_reason}
                    </span>
                  ) : null}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
}

function fmt(n: number | null | undefined, digits = 2): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}
function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  const pct = Math.abs(n) <= 1 ? n * 100 : n;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}
function fmtCompact(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
  return '$' + n.toFixed(2);
}

function fmtSmallCount(value: number | null | undefined): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US');
}

function providerMap(providers: ProviderCard[] | undefined): Map<string, ProviderCard> {
  const map = new Map<string, ProviderCard>();
  for (const provider of providers ?? []) {
    map.set(provider.provider.toLowerCase(), provider);
  }
  return map;
}

function providerColor(provider: ProviderCard | undefined): string {
  const color = String(provider?.dashboard_color ?? '').toLowerCase();
  if (color === 'green') return 'var(--buy, #10b981)';
  if (color === 'yellow') return 'var(--warn, #f59e0b)';
  if (color === 'red') return 'var(--sell, #ef4444)';
  return 'var(--text-muted)';
}

function MarketProviderCoverage({ data }: { data: ProviderStatusData | null | undefined }): JSX.Element {
  const byId = useMemo(() => providerMap(data?.providers), [data?.providers]);
  return (
    <section
      data-testid="market-provider-coverage"
      style={{
        marginTop: 14,
        padding: '12px 14px',
        borderRadius: 'var(--radius-md, 10px)',
        border: '1px solid var(--border)',
        background: 'var(--bg-elevated)',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', gap: 12, alignItems: 'baseline', flexWrap: 'wrap', marginBottom: 10 }}>
        <div>
          <strong style={{ fontSize: 12, color: 'var(--text-primary)' }}>Provider coverage</strong>
          <span style={{ marginLeft: 8, fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
            /api/v2/providers/status
          </span>
        </div>
        <Link to="/providers" style={{ fontSize: 12, color: 'var(--accent, #3b82f6)', textDecoration: 'none' }}>
          Provider truth
        </Link>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 8 }}>
        {MARKET_PROVIDER_ORDER.map(([id, label]) => {
          const provider = byId.get(id);
          const color = providerColor(provider);
          return (
            <div
              key={id}
              data-testid={`market-provider-${id}`}
              style={{
                border: `1px solid ${color}`,
                borderRadius: 'var(--radius-sm, 8px)',
                padding: '8px 10px',
                minWidth: 0,
              }}
            >
              <div style={{ display: 'flex', justifyContent: 'space-between', gap: 8, marginBottom: 5 }}>
                <strong style={{ fontSize: 12, color: 'var(--text-primary)' }}>{label}</strong>
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color }}>
                  {String(provider?.dashboard_color ?? provider?.status ?? 'connecting').toUpperCase()}
                </span>
              </div>
              <div style={{ display: 'grid', gap: 3, fontSize: 10.5, color: 'var(--text-muted)' }}>
                <span>samples <b>{fmtSmallCount(provider?.actual_payload_count)}</b> · features <b>{fmtSmallCount(provider?.feature_count)}</b></span>
                <span>actual data <b>{provider?.actual_payload_present ? 'yes' : 'no'}</b> · heartbeat only <b>{provider?.heartbeat_only ? 'yes' : 'no'}</b></span>
                <span>roles <b>{provider?.consumer_roles?.slice(0, 3).join(', ') || '—'}</b></span>
              </div>
            </div>
          );
        })}
      </div>
      <p style={{ margin: '10px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
        Market rows remain price-first; provider data is confluence and risk context only. Trading remains operator-blocked.
      </p>
    </section>
  );
}

function ColHeader({
  label,
  sortKey,
  currentKey,
  dir,
  onSort,
  align = 'right',
}: {
  label: string;
  sortKey: SortKey;
  currentKey: SortKey;
  dir: 'asc' | 'desc';
  onSort: (k: SortKey) => void;
  align?: 'left' | 'right';
}): JSX.Element {
  const active = sortKey === currentKey;
  return (
    <th
      onClick={() => onSort(sortKey)}
      style={{
        padding: '10px 12px',
        textAlign: align,
        fontSize: 11,
        fontWeight: 600,
        textTransform: 'uppercase',
        letterSpacing: '0.05em',
        color: active ? 'var(--text-primary)' : 'var(--text-muted)',
        cursor: 'pointer',
        whiteSpace: 'nowrap',
        userSelect: 'none',
        background: 'var(--bg-elevated)',
        position: 'sticky',
        top: 0,
        zIndex: 1,
        borderBottom: '1px solid var(--border)',
      }}
    >
      {label}
      {active ? (dir === 'asc' ? ' ↑' : ' ↓') : ''}
    </th>
  );
}

export default function MarketsPage(): JSX.Element {
  const navigate = useNavigate();
  const { user } = useOptionalAuth();
  const traderSnapshot = useTraderSnapshot();
  const marketOverview = useRealtimeResource<MarketOverviewData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
  });
  const providerStatus = useRealtimeResource<ProviderStatusData>({
    url: '/api/v2/providers/status',
    source: '/api/v2/providers/status',
    pollIntervalMs: 15_000,
    staleThresholdMs: 45_000,
    mode: 'read_only',
    unwrapEnvelopeData: 'contract',
  });
  const ingestorsStatus = useRealtimeResource<IngestorsStatusData>({
    url: '/api/v2/ingestors/status',
    source: '/api/v2/ingestors/status',
    pollIntervalMs: 20_000,
    staleThresholdMs: 60_000,
    mode: 'read_only',
    unwrapEnvelopeData: 'contract',
  });
  const data = marketOverview.envelope.data;
  const loading = marketOverview.loading;
  const error = marketOverview.error ?? marketOverview.envelope.errors[0] ?? null;
  const [search, setSearch] = useState('');
  const [sortKey, setSortKey] = useState<SortKey>('turnover_24h');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [tab, setTab] = useState<TabId>('overview');
  const [favorites, setFavorites] = useState<Set<string>>(() => marketFavoriteSymbolSet([]));

  function handleSort(key: SortKey): void {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  function toggleFavorite(symbol: string): void {
    setFavorites((prev) => {
      const next = new Set(prev);
      if (next.has(symbol)) next.delete(symbol);
      else next.add(symbol);
      return next;
    });
  }

  const allTickers = useMemo((): TickerRow[] => {
    const raw = data?.tickers;
    if (Array.isArray(raw) && raw.length > 0) return raw;
    const symbols = data?.symbols ?? [];
    return symbols.map((symbol) => ({
      symbol,
      last_price: null,
      change_24h: null,
      high_24h: null,
      low_24h: null,
      volume_24h: null,
      turnover_24h: null,
      trade_count_24h: null,
    }));
  }, [data]);

  const filteredTickers = useMemo((): TickerRow[] => {
    let rows = allTickers;
    const q = search.trim().toUpperCase();
    if (q) rows = rows.filter((r) => r.symbol.includes(q));
    switch (tab) {
      case 'gainers': rows = rows.filter((r) => (r.change_24h ?? 0) > 0); break;
      case 'losers': rows = rows.filter((r) => (r.change_24h ?? 0) < 0); break;
      case 'watchlist': rows = rows.filter((r) => favorites.has(r.symbol)); break;
      default: break;
    }
    return [...rows].sort((a, b) => {
      if (sortKey === 'symbol') {
        return sortDir === 'asc'
          ? a.symbol.localeCompare(b.symbol)
          : b.symbol.localeCompare(a.symbol);
      }
      const av = a[sortKey] as number | null;
      const bv = b[sortKey] as number | null;
      if (av == null && bv == null) return 0;
      if (av == null) return 1;
      if (bv == null) return -1;
      return sortDir === 'asc' ? av - bv : bv - av;
    });
  }, [allTickers, search, sortKey, sortDir, tab, favorites]);

  const gainers = useMemo(() => allTickers.filter((r) => (r.change_24h ?? 0) > 0).length, [allTickers]);
  const losers = useMemo(() => allTickers.filter((r) => (r.change_24h ?? 0) < 0).length, [allTickers]);
  const totalTurnover = useMemo(() => allTickers.reduce((s, r) => s + (r.turnover_24h ?? 0), 0), [allTickers]);
  const hasPriceData = allTickers.some((r) => r.last_price != null);
  const hasDerivativesData = allTickers.some((r) => r.funding_rate != null || r.open_interest != null);
  const canonicalBtcMarket = selectMarketBySymbol(traderSnapshot, 'BTCUSDT') ?? {};
  const canonicalMarketMetric = (fieldId: string) => selectMarketMetric(traderSnapshot, canonicalBtcMarket, fieldId);

  // The authenticated trader snapshot is 401-gated; for logged-out visitors fall
  // back to the public /api/v2/market/overview BTC row so the canonical price
  // cards still render real, fresh values instead of "Source offline".
  const publicBtcRow = allTickers.find((r) => r.symbol === 'BTCUSDT') ?? null;
  const overviewEnvelope = marketOverview.envelope;
  const marketMetric = (fieldId: string, publicKey: keyof TickerRow): CanonicalMetric => {
    const authed = canonicalMarketMetric(fieldId);
    if (authed.value != null) return authed;
    const publicValue = publicBtcRow ? (publicBtcRow[publicKey] as number | null | undefined) ?? null : null;
    if (publicValue == null) return authed;
    return {
      ...authed,
      value: publicValue,
      source: overviewEnvelope.source ?? '/api/v2/market/overview',
      sourceType: overviewEnvelope.source_type ?? 'static_payload',
      timestamp: overviewEnvelope.timestamp != null ? new Date(overviewEnvelope.timestamp).toISOString() : null,
      ageMs: overviewEnvelope.lag_ms ?? null,
      quality: 'valid',
    };
  };

  const TABS: Array<{ id: TabId; label: string; count?: number }> = [
    { id: 'overview', label: 'Overview', count: allTickers.length },
    { id: 'gainers', label: 'Gainers', count: gainers },
    { id: 'losers', label: 'Losers', count: losers },
    { id: 'watchlist', label: 'Watchlist', count: favorites.size },
  ];

  return (
    <div data-testid="page-markets" style={{ background: 'var(--bg-base)', paddingBottom: 48 }}>
      {/* Unauthenticated banner */}
      {!user && (
        <div
          style={{
            padding: '10px 24px',
            background: 'color-mix(in oklch, var(--accent, #3b82f6) 8%, transparent)',
            borderBottom: '1px solid color-mix(in oklch, var(--accent, #3b82f6) 20%, transparent)',
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            gap: 12,
            flexWrap: 'wrap',
          }}
        >
          <span style={{ fontSize: 13, color: 'var(--text-secondary)' }}>
            Sign in to access full trader features: portfolio, signals, AI predictions, and trade terminal.
          </span>
          <Link
            to="/login?returnTo=/markets"
            style={{
              padding: '5px 14px',
              borderRadius: 'var(--radius-sm, 6px)',
              border: '1px solid var(--accent, #3b82f6)',
              background: 'none',
              color: 'var(--accent, #3b82f6)',
              fontSize: 13,
              fontWeight: 600,
              textDecoration: 'none',
            }}
          >
            Sign in
          </Link>
        </div>
      )}

      {/* Page header */}
      <div
        style={{
          padding: '20px 24px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'var(--bg-panel)',
        }}
      >
        <div
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            flexWrap: 'wrap',
            gap: 12,
            marginBottom: 16,
          }}
        >
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
              Markets
            </h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              USD-M perpetual futures · {data?.count ?? allTickers.length} symbols
            </p>
          </div>
          <button
            onClick={() => marketOverview.refetch()}
            style={{
              padding: '5px 12px',
              borderRadius: 'var(--radius-sm, 6px)',
              border: '1px solid var(--border)',
              background: 'transparent',
              color: 'var(--text-secondary)',
              fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Refresh
          </button>
        </div>

        {/* Summary row */}
        <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
          {[
            { label: 'Total', value: String(allTickers.length) },
            { label: 'Gainers', value: String(gainers), color: 'var(--buy, #10b981)' },
            { label: 'Losers', value: String(losers), color: 'var(--sell, #ef4444)' },
            { label: '24h Turnover', value: fmtCompact(totalTurnover) },
          ].map((item) => (
            <div key={item.label} style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
              <span
                style={{
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                {item.label}
              </span>
              <span
                style={{
                  fontSize: 16,
                  fontWeight: 700,
                  color: item.color ?? 'var(--text-primary)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                {loading && !data ? '…' : item.value}
              </span>
            </div>
          ))}
        </div>

        <div className="trader-metric-grid" style={{ marginTop: 14 }}>
          <CanonicalMetricCard label="BTCUSDT Last Price" metric={marketMetric('market.last_price', 'last_price')} />
          <CanonicalMetricCard label="BTCUSDT Mark Price" metric={marketMetric('market.mark_price', 'mark_price')} />
          <CanonicalMetricCard label="BTCUSDT Index Price" metric={marketMetric('market.index_price', 'index_price')} />
        </div>

        <MarketProviderCoverage data={providerStatus.envelope.data} />
        <MarketIngestorCoverage data={ingestorsStatus.envelope.data} />
      </div>

      {/* Tabs + search */}
      <div
        style={{
          display: 'flex',
          alignItems: 'center',
          background: 'var(--bg-panel)',
          borderBottom: '1px solid var(--border)',
          padding: '0 16px',
        }}
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '10px 14px',
              border: 'none',
              borderBottom: tab === t.id ? '2px solid var(--accent, #3b82f6)' : '2px solid transparent',
              background: 'none',
              color: tab === t.id ? 'var(--text-primary)' : 'var(--text-muted)',
              fontWeight: tab === t.id ? 600 : 400,
              fontSize: 13,
              cursor: 'pointer',
              fontFamily: 'var(--font-sans)',
              whiteSpace: 'nowrap',
              marginBottom: -1,
            }}
          >
            {t.label}
            {t.count != null && (
              <span
                style={{
                  marginLeft: 6,
                  fontSize: 11,
                  color: 'var(--text-muted)',
                  fontFamily: 'var(--font-mono)',
                }}
              >
                {t.count}
              </span>
            )}
          </button>
        ))}
        <Link
          to="/markets/ingestors"
          style={{
            padding: '10px 14px',
            borderBottom: '2px solid transparent',
            color: 'var(--text-muted)',
            fontSize: 13,
            textDecoration: 'none',
            whiteSpace: 'nowrap',
            marginBottom: -1,
          }}
        >
          Ingestors ↗
        </Link>
        <div style={{ flex: 1 }} />
        <input
          type="text"
          placeholder="Search…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          style={{
            margin: '6px 0',
            padding: '5px 10px',
            borderRadius: 'var(--radius-sm, 6px)',
            border: '1px solid var(--border)',
            background: 'var(--bg-elevated)',
            color: 'var(--text-primary)',
            fontFamily: 'var(--font-mono)',
            fontSize: 12,
            width: 160,
            outline: 'none',
          }}
        />
      </div>

      {/* No price data warning */}
      {!loading && allTickers.length > 0 && !hasPriceData && (
        <div
          style={{
            padding: '8px 24px',
            background: 'color-mix(in oklch, var(--warn, #f59e0b) 10%, transparent)',
            borderBottom: '1px solid var(--border)',
          }}
        >
          <span style={{ fontSize: 12, color: 'var(--warn, #f59e0b)' }}>
            Price stream connecting — symbol list remains visible while exchange data reconnects.
          </span>
        </div>
      )}

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        {loading && !data && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            Connecting market stream…
          </div>
        )}
        {!loading && error && !data && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--sell, #ef4444)', fontSize: 13 }}>
            {error}
            <button
              onClick={() => marketOverview.refetch()}
              style={{
                marginLeft: 12,
                padding: '4px 10px',
                fontSize: 12,
                cursor: 'pointer',
                border: '1px solid var(--border)',
                borderRadius: 4,
                background: 'none',
                color: 'var(--text-secondary)',
              }}
            >
              Retry
            </button>
          </div>
        )}
        {!loading && filteredTickers.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
            {search
              ? `No symbols match "${search}"`
              : tab === 'watchlist'
              ? 'No watchlist symbols'
              : tab === 'gainers'
              ? 'No gaining symbols right now'
              : 'Market stream connecting'}
          </div>
        )}
        {filteredTickers.length > 0 && (
          <table
            style={{
              width: '100%',
              borderCollapse: 'collapse',
              fontFamily: 'var(--font-mono)',
              fontSize: 12.5,
            }}
          >
            <thead>
              <tr>
                <th
                  style={{
                    padding: '10px 12px',
                    textAlign: 'center',
                    fontSize: 11,
                    color: 'var(--text-muted)',
                    background: 'var(--bg-elevated)',
                    position: 'sticky',
                    top: 0,
                    zIndex: 1,
                    borderBottom: '1px solid var(--border)',
                    width: 40,
                  }}
                >
                  ★
                </th>
                <ColHeader
                  label="Symbol"
                  sortKey="symbol"
                  currentKey={sortKey}
                  dir={sortDir}
                  onSort={handleSort}
                  align="left"
                />
                {hasPriceData && (
                  <ColHeader
                    label="Price"
                    sortKey="last_price"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasPriceData && (
                  <ColHeader
                    label="24h %"
                    sortKey="change_24h"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasPriceData && (
                  <ColHeader
                    label="Turnover 24h"
                    sortKey="turnover_24h"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasPriceData && (
                  <ColHeader
                    label="Volume 24h"
                    sortKey="volume_24h"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasDerivativesData && (
                  <th style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', whiteSpace: 'nowrap', background: 'var(--bg-elevated)', position: 'sticky', top: 0, zIndex: 1, borderBottom: '1px solid var(--border)' }}>
                    Funding
                  </th>
                )}
                {hasDerivativesData && (
                  <th style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', whiteSpace: 'nowrap', background: 'var(--bg-elevated)', position: 'sticky', top: 0, zIndex: 1, borderBottom: '1px solid var(--border)' }}>
                    Open Int.
                  </th>
                )}
                {hasDerivativesData && (
                  <th style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', whiteSpace: 'nowrap', background: 'var(--bg-elevated)', position: 'sticky', top: 0, zIndex: 1, borderBottom: '1px solid var(--border)' }}>
                    L / S
                  </th>
                )}
              </tr>
            </thead>
            <tbody>
              {filteredTickers.map((row, i) => {
                const chg = row.change_24h;
                const chgColor =
                  chg == null
                    ? 'var(--text-muted)'
                    : chg > 0
                    ? 'var(--buy, #10b981)'
                    : chg < 0
                    ? 'var(--sell, #ef4444)'
                    : 'var(--text-secondary)';
                const isFav = favorites.has(row.symbol);
                return (
                  <tr
                    key={row.symbol}
                    onClick={() => navigate(`/market/${row.symbol}`)}
                    style={{
                      cursor: 'pointer',
                      background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)',
                    }}
                    onMouseEnter={(e) => {
                      (e.currentTarget as HTMLTableRowElement).style.background = 'var(--bg-elevated)';
                    }}
                    onMouseLeave={(e) => {
                      (e.currentTarget as HTMLTableRowElement).style.background =
                        i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)';
                    }}
                  >
                    <td
                      style={{ textAlign: 'center', padding: '10px 12px', cursor: 'pointer' }}
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleFavorite(row.symbol);
                      }}
                    >
                      <span
                        style={{
                          fontSize: 14,
                          color: isFav ? 'var(--warn, #f59e0b)' : 'var(--text-muted)',
                          lineHeight: 1,
                        }}
                      >
                        {isFav ? '★' : '☆'}
                      </span>
                    </td>
                    <td style={{ padding: '10px 12px' }}>
                      <span style={{ fontWeight: 600, color: 'var(--text-primary)', fontSize: 13 }}>
                        {row.symbol.replace('USDT', '')}
                        <span
                          style={{
                            color: 'var(--text-muted)',
                            fontWeight: 400,
                            fontSize: 11,
                          }}
                        >
                          /USDT
                        </span>
                      </span>
                    </td>
                    {hasPriceData && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          fontWeight: 600,
                          color: 'var(--text-primary)',
                        }}
                      >
                        {fmt(row.last_price)}
                      </td>
                    )}
                    {hasPriceData && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          fontWeight: 700,
                          color: chgColor,
                        }}
                      >
                        {fmtPct(chg)}
                      </td>
                    )}
                    {hasPriceData && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          color: 'var(--text-secondary)',
                        }}
                      >
                        {fmtCompact(row.turnover_24h)}
                      </td>
                    )}
                    {hasPriceData && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          color: 'var(--text-muted)',
                          fontSize: 11.5,
                        }}
                      >
                        {fmtCompact(row.volume_24h)}
                      </td>
                    )}
                    {hasDerivativesData && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          fontSize: 11.5,
                          color:
                            row.funding_rate == null
                              ? 'var(--text-muted)'
                              : row.funding_rate >= 0
                              ? 'var(--buy, #10b981)'
                              : 'var(--sell, #ef4444)',
                        }}
                      >
                        {row.funding_rate != null ? `${(row.funding_rate * 100).toFixed(4)}%` : '—'}
                      </td>
                    )}
                    {hasDerivativesData && (
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11.5, color: 'var(--text-secondary)' }}>
                        {row.open_interest != null ? row.open_interest.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}
                      </td>
                    )}
                    {hasDerivativesData && (
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11.5, color: 'var(--text-secondary)' }}>
                        {row.long_short_ratio != null ? row.long_short_ratio.toFixed(2) : '—'}
                      </td>
                    )}
                  </tr>
                );
              })}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
