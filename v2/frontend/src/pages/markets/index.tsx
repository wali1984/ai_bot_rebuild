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

// ── Watchlist persistence ────────────────────────────────────────────────────
// Stars survive reload via localStorage. An explicitly-stored empty list is
// honored (user unstarred everything); defaults apply only when nothing has
// ever been stored or the stored value is unreadable.
const WATCHLIST_STORAGE_KEY = 'ai_bot_v2.market_watchlist.v1';

function loadStoredFavorites(): Set<string> {
  if (typeof window === 'undefined') return marketFavoriteSymbolSet([]);
  try {
    const raw = window.localStorage.getItem(WATCHLIST_STORAGE_KEY);
    if (raw !== null) {
      const parsed = JSON.parse(raw) as unknown;
      if (Array.isArray(parsed)) {
        const valid = parsed
          .filter((s): s is string => typeof s === 'string')
          .map((s) => s.toUpperCase().trim())
          .filter((s) => /^[A-Z0-9]{3,20}$/.test(s));
        return new Set(valid);
      }
    }
  } catch {
    // Unreadable storage falls back to defaults below.
  }
  return marketFavoriteSymbolSet([]);
}

function persistFavorites(favorites: Set<string>): void {
  if (typeof window === 'undefined') return;
  try {
    window.localStorage.setItem(WATCHLIST_STORAGE_KEY, JSON.stringify([...favorites].sort()));
  } catch {
    // Storage may be unavailable (private mode/quota); stars still work for the session.
  }
}

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
  // Enriched per-symbol fields (backend Redis enrichment, 2026-07)
  change_1h?: number | null;
  change_7d?: number | null;
  market_cap_rank?: number | null;
  market_cap_usd?: number | null;
  basis_bps?: number | null;
  next_funding_time?: string | null;
  long_account_ratio?: number | null;
  short_account_ratio?: number | null;
  spread_bps?: number | null;
  orderbook_imbalance?: number | null;
  liquidation_cascade_risk?: number | null;
  liq_notional_1h?: number | null;
  liq_direction_bias_1h?: number | null;
  rsi_1m?: number | null;
  atr_1m?: number | null;
  adx_1m?: number | null;
  htf_trend?: string | null;
  rsi_zone?: string | null;
  macd_direction?: string | null;
  altdata_symbol_score?: number | null;
  altdata_symbol_rank?: number | null;
  coinank_derivatives_score?: number | null;
  open_interest_delta_1h_usd?: number | null;
  coinglass_open_interest_usd?: number | null;
  taker_buy_ratio?: number | null;
  volume_24h_quote_usd?: number | null;
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
type SortKey =
  | 'symbol'
  | 'last_price'
  | 'change_1h'
  | 'change_24h'
  | 'turnover_24h'
  | 'funding_rate'
  | 'open_interest'
  | 'altdata_symbol_score';

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
  // Codex honesty reclassification: optional enrichment sources (e.g. CoinAPI)
  // render a calm optional state, never an alarming hard failure.
  optional_source?: boolean | null;
  requirement_class?: string | null;
  core_data_plane_required?: boolean | null;
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
            const isOptional = row.optional_source === true;
            const calmOptional = isOptional && String(row.status ?? '').toLowerCase() !== 'live';
            const color = calmOptional ? 'var(--text-muted)' : ingestorColor(row.status);
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
                  <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color, whiteSpace: 'nowrap' }}>
                    {String(row.status ?? 'unknown').toUpperCase()}{isOptional ? ' · OPTIONAL' : ''}
                  </span>
                </div>
                <div style={{ display: 'grid', gap: 3, fontSize: 10.5, color: 'var(--text-muted)' }}>
                  <span>keys <b>{fmtSmallCount(row.key_count)}</b> · fresh <b>{fmtAge(row.newest_event_age_seconds)}</b></span>
                  <span style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', fontFamily: 'var(--font-mono)' }}>
                    {row.redis_pattern || '—'}
                  </span>
                  {isOptional ? (
                    <span>
                      {(row.requirement_class ?? 'OPTIONAL_ENRICHMENT').replace(/_/g, ' ').toLowerCase()} · not required for core data plane
                    </span>
                  ) : null}
                  {row.provider_unusable_reason ? (
                    <span
                      title={row.provider_unusable_reason}
                      style={{ color: calmOptional ? 'var(--text-muted)' : 'var(--warn, #f59e0b)', overflowWrap: 'anywhere', wordBreak: 'break-word', minWidth: 0 }}
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

function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '—';
  const digits = n >= 100 ? 2 : n >= 1 ? 3 : 4;
  return n.toLocaleString('en-US', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtFunding(rate: number | null | undefined): string {
  if (rate == null) return '—';
  return `${(rate * 100).toFixed(4)}%`;
}

function fmtOpenInterest(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return (n / 1e3).toFixed(1) + 'K';
  return n.toLocaleString('en-US', { maximumFractionDigits: 0 });
}

function changeColor(chg: number | null | undefined): string {
  if (chg == null) return 'var(--text-muted)';
  if (chg > 0) return 'var(--buy, #10b981)';
  if (chg < 0) return 'var(--sell, #ef4444)';
  return 'var(--text-secondary)';
}

function fundingColor(rate: number | null | undefined): string {
  if (rate == null) return 'var(--text-muted)';
  return rate >= 0 ? 'var(--buy, #10b981)' : 'var(--sell, #ef4444)';
}

function scoreColor(score: number | null | undefined): string {
  if (score == null) return 'var(--text-muted)';
  if (score >= 0.6) return 'var(--buy, #10b981)';
  if (score >= 0.4) return 'var(--text-secondary)';
  return 'var(--warn, #f59e0b)';
}

/** Compact TA trend chip: HTF trend direction + RSI(1m), colored by trend. */
function TrendChip({ row }: { row: TickerRow }): JSX.Element {
  const trend = String(row.htf_trend ?? '').toUpperCase();
  const up = trend === 'UP';
  const down = trend === 'DOWN';
  const color = up ? 'var(--buy, #10b981)' : down ? 'var(--sell, #ef4444)' : 'var(--text-muted)';
  const arrow = up ? '▲' : down ? '▼' : '—';
  const rsi = row.rsi_1m != null ? Math.round(row.rsi_1m) : null;
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 5,
        padding: '2px 8px',
        borderRadius: 999,
        border: `1px solid color-mix(in oklch, ${color} 40%, transparent)`,
        background: `color-mix(in oklch, ${color} 10%, transparent)`,
        color,
        fontSize: 10.5,
        fontFamily: 'var(--font-mono)',
        whiteSpace: 'nowrap',
        lineHeight: 1.5,
      }}
    >
      <span>{arrow} {trend || 'N/A'}</span>
      {rsi != null && <span style={{ color: 'var(--text-secondary)' }}>RSI {rsi}</span>}
    </span>
  );
}

/** Rich glass card used by the Gainers / Losers / Watchlist tabs. */
function MarketCard({
  row,
  isFav,
  onToggleFav,
  onOpen,
}: {
  row: TickerRow;
  isFav: boolean;
  onToggleFav: () => void;
  onOpen: () => void;
}): JSX.Element {
  const chg = row.change_24h;
  const chgColor = changeColor(chg);
  const accent = chg == null || chg === 0 ? 'var(--border)' : chgColor;
  return (
    <div
      data-testid={`market-card-${row.symbol}`}
      onClick={onOpen}
      style={{
        cursor: 'pointer',
        padding: '12px 14px',
        borderRadius: 'var(--radius-md, 12px)',
        border: `1px solid color-mix(in oklch, ${accent} 35%, var(--border))`,
        background: 'color-mix(in oklch, var(--bg-panel) 78%, transparent)',
        backdropFilter: 'blur(8px)',
        display: 'flex',
        flexDirection: 'column',
        gap: 9,
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
        <span
          onClick={(e) => {
            e.stopPropagation();
            onToggleFav();
          }}
          style={{ fontSize: 15, lineHeight: 1, color: isFav ? 'var(--warn, #f59e0b)' : 'var(--text-muted)', cursor: 'pointer' }}
        >
          {isFav ? '★' : '☆'}
        </span>
        <span style={{ fontWeight: 700, fontSize: 14, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
          {row.symbol.replace('USDT', '')}
          <span style={{ color: 'var(--text-muted)', fontWeight: 400, fontSize: 11 }}>/USDT</span>
        </span>
        {row.market_cap_rank != null && (
          <span style={{ fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>#{row.market_cap_rank}</span>
        )}
        <span style={{ marginLeft: 'auto', fontWeight: 700, fontSize: 15, color: chgColor, fontFamily: 'var(--font-mono)' }}>
          {fmtPct(chg)}
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, fontFamily: 'var(--font-mono)' }}>
        <span style={{ fontSize: 17, fontWeight: 700, color: 'var(--text-primary)' }}>{fmtPrice(row.last_price)}</span>
        {row.change_1h != null && (
          <span style={{ fontSize: 11, color: changeColor(row.change_1h) }}>1h {fmtPct(row.change_1h)}</span>
        )}
      </div>
      <div
        style={{
          display: 'grid',
          gridTemplateColumns: '1fr 1fr',
          gap: '4px 12px',
          fontSize: 11,
          fontFamily: 'var(--font-mono)',
          color: 'var(--text-secondary)',
        }}
      >
        <span style={{ color: 'var(--text-muted)' }}>
          Funding <b style={{ color: fundingColor(row.funding_rate) }}>{fmtFunding(row.funding_rate)}</b>
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          Turnover <b style={{ color: 'var(--text-secondary)' }}>{fmtCompact(row.turnover_24h)}</b>
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          OI <b style={{ color: 'var(--text-secondary)' }}>{fmtOpenInterest(row.open_interest)}</b>
        </span>
        <span style={{ color: 'var(--text-muted)' }}>
          Score{' '}
          <b style={{ color: scoreColor(row.altdata_symbol_score) }}>
            {row.altdata_symbol_score != null ? row.altdata_symbol_score.toFixed(2) : '—'}
            {row.altdata_symbol_rank != null ? ` (#${row.altdata_symbol_rank})` : ''}
          </b>
        </span>
      </div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
        <TrendChip row={row} />
        {row.liquidation_cascade_risk != null && row.liquidation_cascade_risk >= 0.8 && (
          <span
            title="Liquidation cascade risk (1m levels engine)"
            style={{
              fontSize: 10,
              fontFamily: 'var(--font-mono)',
              color: 'var(--warn, #f59e0b)',
              border: '1px solid color-mix(in oklch, var(--warn, #f59e0b) 40%, transparent)',
              borderRadius: 999,
              padding: '2px 8px',
              whiteSpace: 'nowrap',
            }}
          >
            LIQ RISK {(row.liquidation_cascade_risk * 100).toFixed(0)}%
          </span>
        )}
      </div>
    </div>
  );
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
  const [favorites, setFavorites] = useState<Set<string>>(loadStoredFavorites);

  function handleSort(key: SortKey): void {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'));
    } else {
      setSortKey(key);
      setSortDir('desc');
    }
  }

  function toggleFavorite(symbol: string): void {
    const next = new Set(favorites);
    if (next.has(symbol)) next.delete(symbol);
    else next.add(symbol);
    persistFavorites(next);
    setFavorites(next);
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
  const hasChange1h = allTickers.some((r) => r.change_1h != null);
  const hasScoreData = allTickers.some((r) => r.altdata_symbol_score != null);
  const hasTrendData = allTickers.some((r) => r.htf_trend != null || r.rsi_1m != null);

  // Gainers / Losers / Watchlist render as rich cards with a fixed, honest sort:
  // gainers by 24h change desc, losers asc (worst first), watchlist by turnover.
  const cardRows = useMemo((): TickerRow[] => {
    if (tab === 'gainers') return [...filteredTickers].sort((a, b) => (b.change_24h ?? 0) - (a.change_24h ?? 0));
    if (tab === 'losers') return [...filteredTickers].sort((a, b) => (a.change_24h ?? 0) - (b.change_24h ?? 0));
    return [...filteredTickers].sort((a, b) => (b.turnover_24h ?? 0) - (a.turnover_24h ?? 0));
  }, [filteredTickers, tab]);
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
    <div data-testid="page-markets" style={{ background: 'var(--bg-base)', paddingBottom: 48, position: 'relative', overflow: 'hidden' }}>
      {/* Ambient depth — gives the frosted header/cards colour to refract. */}
      <div
        aria-hidden="true"
        style={{
          position: 'absolute',
          inset: 0,
          pointerEvents: 'none',
          zIndex: 0,
          background:
            'radial-gradient(44% 28% at 15% 0%, rgba(59,130,246,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(45,212,191,0.08), transparent 72%)',
        }}
      />
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
          position: 'relative',
          zIndex: 1,
          padding: '20px 24px 16px',
          borderBottom: '1px solid var(--border)',
          background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)',
          backdropFilter: 'blur(8px)',
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
          // Wrap on narrow viewports: the nowrap tab labels + fixed-width
          // search must never overlap at 390px.
          flexWrap: 'wrap',
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
              ? 'No watchlist symbols yet — tap the ☆ star on any Overview row to pin it here.'
              : tab === 'gainers'
              ? 'No gaining symbols right now'
              : tab === 'losers'
              ? 'No losing symbols right now'
              : 'Market stream connecting'}
          </div>
        )}
        {tab !== 'overview' && cardRows.length > 0 && (
          <div
            data-testid={`market-cards-${tab}`}
            style={{
              display: 'grid',
              gridTemplateColumns: 'repeat(auto-fill, minmax(250px, 1fr))',
              gap: 10,
              padding: '16px 24px',
            }}
          >
            {cardRows.map((row) => (
              <MarketCard
                key={row.symbol}
                row={row}
                isFav={favorites.has(row.symbol)}
                onToggleFav={() => toggleFavorite(row.symbol)}
                onOpen={() => navigate(`/market/${row.symbol}`)}
              />
            ))}
          </div>
        )}
        {tab === 'overview' && filteredTickers.length > 0 && (
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
                {hasChange1h && (
                  <ColHeader
                    label="1h %"
                    sortKey="change_1h"
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
                {hasDerivativesData && (
                  <ColHeader
                    label="Funding"
                    sortKey="funding_rate"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasDerivativesData && (
                  <ColHeader
                    label="Open Int."
                    sortKey="open_interest"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasScoreData && (
                  <ColHeader
                    label="Score"
                    sortKey="altdata_symbol_score"
                    currentKey={sortKey}
                    dir={sortDir}
                    onSort={handleSort}
                  />
                )}
                {hasTrendData && (
                  <th style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', whiteSpace: 'nowrap', background: 'var(--bg-elevated)', position: 'sticky', top: 0, zIndex: 1, borderBottom: '1px solid var(--border)' }}>
                    Trend
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
                    <td style={{ padding: '10px 12px', whiteSpace: 'nowrap' }}>
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
                      {row.market_cap_rank != null && (
                        <span style={{ marginLeft: 6, fontSize: 10, color: 'var(--text-muted)' }}>#{row.market_cap_rank}</span>
                      )}
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
                        {fmtPrice(row.last_price)}
                      </td>
                    )}
                    {hasChange1h && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          fontSize: 11.5,
                          color: changeColor(row.change_1h),
                        }}
                      >
                        {fmtPct(row.change_1h)}
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
                    {hasDerivativesData && (
                      <td
                        style={{
                          padding: '10px 12px',
                          textAlign: 'right',
                          fontSize: 11.5,
                          color: fundingColor(row.funding_rate),
                        }}
                      >
                        {fmtFunding(row.funding_rate)}
                      </td>
                    )}
                    {hasDerivativesData && (
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11.5, color: 'var(--text-secondary)' }}>
                        {fmtOpenInterest(row.open_interest)}
                      </td>
                    )}
                    {hasScoreData && (
                      <td style={{ padding: '10px 12px', textAlign: 'right', fontSize: 11.5, color: scoreColor(row.altdata_symbol_score) }}>
                        {row.altdata_symbol_score != null ? row.altdata_symbol_score.toFixed(2) : '—'}
                        {row.altdata_symbol_rank != null && (
                          <span style={{ color: 'var(--text-muted)', marginLeft: 4, fontSize: 10 }}>#{row.altdata_symbol_rank}</span>
                        )}
                      </td>
                    )}
                    {hasTrendData && (
                      <td style={{ padding: '8px 12px', textAlign: 'right', whiteSpace: 'nowrap' }}>
                        <TrendChip row={row} />
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
