import { useState, useMemo } from 'react';
import { Link } from 'react-router-dom';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import { AdaptiveCapitalTelemetryPanel } from '../../components/trading/AdaptiveCapitalTelemetryPanel';
import { useAdaptiveCapitalDashboard } from '../../data/adaptiveCapitalProductivity';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

// ─── Types ────────────────────────────────────────────────────────────────

interface TickerRow {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
  high_24h: number | null;
  low_24h: number | null;
  volume_24h: number | null;
  turnover_24h: number | null;
  trade_count_24h?: number | null;
  weighted_avg_price?: number | null;
  // derivatives (may come from separate endpoint)
  funding_rate?: number | null;
  open_interest?: number | null;
  mark_price?: number | null;
}

interface OverviewData {
  symbols: string[];
  count: number;
  timeframes: string[];
  tickers: TickerRow[];
}

type SortKey = 'symbol' | 'last_price' | 'change_24h' | 'volume_24h' | 'turnover_24h' | 'high_24h' | 'low_24h';
type TabId = 'overview' | 'gainers' | 'losers' | 'volume' | 'watchlist';

const DEFAULT_WATCHLIST = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT', 'BNBUSDT', 'XRPUSDT'];

// ─── Helpers ──────────────────────────────────────────────────────────────

function fmt(n: number | null | undefined, d = 2): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `$${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `$${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `$${(n / 1_000).toFixed(2)}K`;
  return `$${n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d })}`;
}
function fmtPrice(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 10000) return `$${n.toLocaleString('en-US', { minimumFractionDigits: 0 })}`;
  if (n >= 1) return `$${n.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 4 })}`;
  return `$${n.toFixed(6)}`;
}
function fmtVol(n: number | null | undefined): string {
  if (n == null) return '—';
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(2)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return n.toFixed(2);
}
function fmtPct(n: number | null | undefined): string {
  if (n == null) return '—';
  const p = Math.abs(n) <= 1 ? n * 100 : n;
  return `${p >= 0 ? '+' : ''}${p.toFixed(2)}%`;
}
function changeColor(n: number | null | undefined): string {
  if (n == null) return 'var(--text-muted)';
  const p = Math.abs(n) <= 1 ? n * 100 : n;
  if (p > 0) return '#26c281';
  if (p < 0) return '#ef5350';
  return 'var(--text-muted)';
}
function shortSymbol(s: string): string {
  return s.replace('USDT', '').replace('BUSD', '').replace('USDC', '');
}

// ─── Mini sparkline bar ─────────────────────────────────────────────────────

function ChangeBar({ pct }: { pct: number | null | undefined }): JSX.Element {
  if (pct == null) return <span style={{ color: 'var(--text-muted)' }}>—</span>;
  const p = Math.abs(pct) <= 1 ? pct * 100 : pct;
  const w = Math.min(100, Math.abs(p) * 3);
  const color = p >= 0 ? '#26c281' : '#ef5350';
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
      <div style={{ width: 40, height: 4, background: 'rgba(255,255,255,0.06)', borderRadius: 2, overflow: 'hidden', flexShrink: 0 }}>
        <div style={{ height: '100%', width: `${w}%`, background: color, borderRadius: 2, float: p < 0 ? 'right' : 'left' }} />
      </div>
      <span style={{ fontSize: 12, fontFamily: 'var(--font-mono)', color, fontWeight: 600, minWidth: 64, textAlign: 'right' }}>
        {fmtPct(pct)}
      </span>
    </div>
  );
}

// ─── Stat card ─────────────────────────────────────────────────────────────

function StatCard({ label, value, color, sub, icon }: { label: string; value: string; color?: string; sub?: string; icon?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 10, padding: '14px 16px' }}>
      <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginBottom: 6 }}>
        {icon && <span style={{ fontSize: 14 }}>{icon}</span>}
        <span style={{ fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{label}</span>
      </div>
      <div style={{ fontSize: 17, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)', marginBottom: sub ? 3 : 0 }}>{value}</div>
      {sub && <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{sub}</div>}
    </div>
  );
}

// ─── Ticker row ─────────────────────────────────────────────────────────────

function TickerTableRow({ row, rank }: { row: TickerRow; rank: number }): JSX.Element {
  const changePct = row.change_24h != null ? (Math.abs(row.change_24h) <= 1 ? row.change_24h * 100 : row.change_24h) : null;
  const isUp = changePct != null && changePct > 0;
  const isDown = changePct != null && changePct < 0;
  return (
    <tr style={{ borderBottom: '1px solid rgba(255,255,255,0.04)', transition: 'background 0.1s' }}
      onMouseEnter={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'rgba(255,255,255,0.02)'; }}
      onMouseLeave={(e) => { (e.currentTarget as HTMLTableRowElement).style.background = 'transparent'; }}
    >
      <td style={{ padding: '9px 12px', fontSize: 12, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', width: 36 }}>{rank}</td>
      <td style={{ padding: '9px 12px' }}>
        <Link to={`/market/${row.symbol}`} style={{ textDecoration: 'none' }}>
          <div style={{ fontSize: 13, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>{shortSymbol(row.symbol)}</div>
          <div style={{ fontSize: 10, color: 'var(--text-muted)' }}>{row.symbol}</div>
        </Link>
      </td>
      <td style={{ padding: '9px 12px', fontSize: 13, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)', fontWeight: 600, textAlign: 'right' }}>
        {fmtPrice(row.last_price)}
      </td>
      <td style={{ padding: '9px 14px', textAlign: 'right' }}>
        <ChangeBar pct={row.change_24h} />
      </td>
      <td style={{ padding: '9px 12px', fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', textAlign: 'right' }}>
        {fmtVol(row.volume_24h)}
      </td>
      <td style={{ padding: '9px 12px', fontSize: 12, fontFamily: 'var(--font-mono)', color: 'var(--text-secondary)', textAlign: 'right' }}>
        {row.turnover_24h != null ? fmt(row.turnover_24h) : '—'}
      </td>
      <td style={{ padding: '9px 12px', fontSize: 12, fontFamily: 'var(--font-mono)', textAlign: 'right' }}>
        <span style={{ color: '#26c281' }}>{fmtPrice(row.high_24h)}</span>
        <span style={{ color: 'var(--text-muted)', margin: '0 3px' }}>/</span>
        <span style={{ color: '#ef5350' }}>{fmtPrice(row.low_24h)}</span>
      </td>
      <td style={{ padding: '9px 12px', textAlign: 'right' }}>
        <Link
          to={`/market/${row.symbol}`}
          style={{ padding: '3px 10px', borderRadius: 6, fontSize: 11, border: '1px solid var(--border)', color: 'var(--text-muted)', textDecoration: 'none', background: 'transparent' }}
        >
          Chart
        </Link>
      </td>
    </tr>
  );
}

// ─── Market overview summary ──────────────────────────────────────────────

function MarketSummaryBanner({ tickers }: { tickers: TickerRow[] }): JSX.Element {
  if (tickers.length === 0) return <></>;
  const advancing = tickers.filter((t) => (t.change_24h ?? 0) > 0).length;
  const declining = tickers.filter((t) => (t.change_24h ?? 0) < 0).length;
  const unchanged = tickers.length - advancing - declining;
  const totalTurnover = tickers.reduce((s, t) => s + (t.turnover_24h ?? 0), 0);
  const avgChange = tickers.reduce((s, t) => s + (Math.abs(t.change_24h ?? 0) <= 1 ? (t.change_24h ?? 0) * 100 : (t.change_24h ?? 0)), 0) / (tickers.length || 1);
  const btc = tickers.find((t) => t.symbol === 'BTCUSDT');
  const eth = tickers.find((t) => t.symbol === 'ETHUSDT');
  const breadth = tickers.length > 0 ? ((advancing - declining) / tickers.length * 100) : 0;
  const breadthColor = breadth > 20 ? '#26c281' : breadth < -20 ? '#ef5350' : '#f59e0b';

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(155px, 1fr))', gap: 12, marginBottom: 20 }}>
      <StatCard label="BTC Price" value={fmtPrice(btc?.last_price)} color={changeColor(btc?.change_24h)}
        sub={btc ? fmtPct(btc.change_24h) + ' 24h' : 'Not loaded'} icon="₿" />
      <StatCard label="ETH Price" value={fmtPrice(eth?.last_price)} color={changeColor(eth?.change_24h)}
        sub={eth ? fmtPct(eth.change_24h) + ' 24h' : 'Not loaded'} icon="⟠" />
      <StatCard label="Market Breadth" value={`${breadth >= 0 ? '+' : ''}${breadth.toFixed(0)}%`}
        color={breadthColor} sub={`${advancing}↑ / ${declining}↓ / ${unchanged}=`} icon="📊" />
      <StatCard label="Total Volume 24h" value={totalTurnover > 0 ? fmt(totalTurnover) : '—'}
        sub="Total USD turnover across all pairs" icon="💹" />
      <StatCard label="Avg Change 24h" value={`${avgChange >= 0 ? '+' : ''}${avgChange.toFixed(2)}%`}
        color={avgChange >= 0 ? '#26c281' : '#ef5350'} sub="Mean price change across all pairs" icon="📈" />
      <StatCard label="Active Symbols" value={String(tickers.length)} color="var(--text-primary)"
        sub="USD-M futures pairs" icon="🔢" />
    </div>
  );
}

// ─── Main page ─────────────────────────────────────────────────────────────

export default function ResearchPage(): JSX.Element {
  const [activeTab, setActiveTab] = useState<TabId>('overview');
  const [sortKey, setSortKey] = useState<SortKey>('turnover_24h');
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc');
  const [search, setSearch] = useState('');
  const [watchlist] = useState<Set<string>>(new Set(DEFAULT_WATCHLIST));
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);

  const { envelope, loading } = useRealtimeResource<OverviewData>({
    url: '/api/v2/market/overview',
    source: '/api/v2/market/overview',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });

  const { envelope: signalsEnv } = useRealtimeResource<{ active_signal: Record<string, unknown> | null }>({
    url: '/api/v2/signals?symbol=BTCUSDT',
    source: '/api/v2/signals',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 60_000,
    initialFetch: true,
    httpFallback: true,
    mode: 'read_only',
  });

  const tickers = envelope.data?.tickers ?? [];

  function toggleSort(key: SortKey): void {
    if (sortKey === key) setSortDir((d) => d === 'desc' ? 'asc' : 'desc');
    else { setSortKey(key); setSortDir('desc'); }
  }

  const filteredSorted = useMemo(() => {
    let rows = [...tickers];
    if (search.trim()) {
      const q = search.trim().toUpperCase();
      rows = rows.filter((r) => r.symbol.includes(q));
    }
    if (activeTab === 'gainers') rows = rows.filter((r) => (r.change_24h ?? 0) > 0).sort((a, b) => ((b.change_24h ?? 0) - (a.change_24h ?? 0)));
    else if (activeTab === 'losers') rows = rows.filter((r) => (r.change_24h ?? 0) < 0).sort((a, b) => ((a.change_24h ?? 0) - (b.change_24h ?? 0)));
    else if (activeTab === 'volume') rows = [...rows].sort((a, b) => ((b.turnover_24h ?? 0) - (a.turnover_24h ?? 0)));
    else if (activeTab === 'watchlist') rows = rows.filter((r) => watchlist.has(r.symbol));
    else {
      rows.sort((a, b) => {
        const av = a[sortKey] ?? 0;
        const bv = b[sortKey] ?? 0;
        if (typeof av === 'string' && typeof bv === 'string') {
          return sortDir === 'asc' ? av.localeCompare(bv) : bv.localeCompare(av);
        }
        return sortDir === 'asc' ? (av as number) - (bv as number) : (bv as number) - (av as number);
      });
    }
    return rows;
  }, [tickers, search, sortKey, sortDir, activeTab, watchlist]);

  const TABS: Array<{ id: TabId; label: string; count?: number }> = [
    { id: 'overview', label: 'All Pairs', count: tickers.length },
    { id: 'gainers', label: '▲ Gainers', count: tickers.filter((t) => (t.change_24h ?? 0) > 0).length },
    { id: 'losers', label: '▼ Losers', count: tickers.filter((t) => (t.change_24h ?? 0) < 0).length },
    { id: 'volume', label: 'Top Volume' },
    { id: 'watchlist', label: 'Watchlist', count: watchlist.size },
  ];

  const SortTh = ({ label, k }: { label: string; k: SortKey }) => (
    <th
      onClick={() => toggleSort(k)}
      style={{
        padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
        letterSpacing: '0.05em', color: sortKey === k ? 'var(--accent)' : 'var(--text-muted)',
        textAlign: 'right', borderBottom: '1px solid var(--border)', cursor: 'pointer',
        whiteSpace: 'nowrap', userSelect: 'none',
      }}
    >
      {label} {sortKey === k ? (sortDir === 'desc' ? '↓' : '↑') : ''}
    </th>
  );

  // active_signal uses actual backend fields: side, proposed_action, symbol
  const activeSignal = signalsEnv.data?.active_signal as Record<string, unknown> | null;

  return (
    <div
      data-testid="page-market-intelligence"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', minHeight: '100vh', paddingBottom: 48 }}
    >
      {/* ── Header ── */}
      <div style={{ padding: '20px 24px 0', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 12 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Research</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Live Binance USD-M screener · {tickers.length} pairs · WebSocket market data
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
          </div>
        </div>

        {/* Tabs */}
        <div style={{ display: 'flex', gap: 0, borderTop: '1px solid var(--border)' }}>
          {TABS.map((t) => (
            <button
              key={t.id}
              onClick={() => setActiveTab(t.id)}
              style={{
                padding: '10px 16px', border: 'none',
                borderBottom: activeTab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
                background: 'transparent',
                color: activeTab === t.id
                  ? t.id === 'gainers' ? '#26c281' : t.id === 'losers' ? '#ef5350' : 'var(--accent)'
                  : 'var(--text-secondary)',
                fontSize: 12.5, fontWeight: activeTab === t.id ? 700 : 400,
                cursor: 'pointer', whiteSpace: 'nowrap', display: 'flex', alignItems: 'center', gap: 6,
              }}
            >
              {t.label}
              {t.count != null && (
                <span style={{ fontSize: 10, fontFamily: 'var(--font-mono)', color: activeTab === t.id ? 'inherit' : 'var(--text-muted)', opacity: 0.8 }}>
                  {t.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      <div style={{ padding: 24 }}>
        {loading && tickers.length === 0 && <LoadingSkeleton rows={10} />}

        <div style={{ marginBottom: 20 }}>
          <AdaptiveCapitalTelemetryPanel
            payload={adaptiveCapital.data}
            title="Signal Accuracy + Capital Productivity"
            compact
            showMatrix
            maxMatrixHeight={220}
          />
        </div>

        {/* Market summary KPIs */}
        {tickers.length > 0 && <MarketSummaryBanner tickers={tickers} />}

        {/* Active Signal Banner */}
        {activeSignal && (
          <div style={{
            marginBottom: 16, padding: '14px 18px', borderRadius: 10,
            background: 'linear-gradient(90deg, rgba(59,130,246,0.06), transparent)',
            border: '1px solid rgba(59,130,246,0.2)',
            display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap',
          }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
              <div style={{ width: 8, height: 8, borderRadius: '50%', background: '#3b82f6', boxShadow: '0 0 8px #3b82f640' }} />
              <div>
                <span style={{ fontSize: 12, color: 'var(--text-muted)', marginRight: 8 }}>Active Signal</span>
                <span style={{ fontSize: 13, fontWeight: 700, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                  {String(activeSignal.symbol ?? 'BTCUSDT')} ·&nbsp;
                  <span style={{ color: ((activeSignal.side ?? activeSignal.direction ?? '') as string).toLowerCase().includes('short') ? '#ef5350' : '#26c281' }}>
                    {String(activeSignal.side ?? activeSignal.proposed_action ?? activeSignal.direction ?? activeSignal.selected_action ?? '—').toUpperCase()}
                  </span>
                </span>
              </div>
            </div>
            <Link to="/signals" style={{ fontSize: 12, color: 'var(--accent)', textDecoration: 'none', fontWeight: 600 }}>
              View Signal →
            </Link>
          </div>
        )}

        {/* Search bar */}
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 12 }}>
          <input
            type="search"
            placeholder="Filter symbols…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            style={{
              width: 220, padding: '7px 12px', borderRadius: 8, border: '1px solid var(--border)',
              background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontSize: 13,
              outline: 'none', fontFamily: 'var(--font-mono)',
            }}
          />
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            {filteredSorted.length} of {tickers.length} pairs
          </span>
        </div>

        {/* Market table */}
        {tickers.length > 0 && (
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12, overflow: 'hidden' }}>
            <div style={{ overflowX: 'auto' }}>
              <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: 12.5 }}>
                <thead>
                  <tr style={{ background: 'var(--bg-elevated)' }}>
                    <th style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)', width: 36 }}>#</th>
                    <th
                      onClick={() => toggleSort('symbol')}
                      style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: sortKey === 'symbol' ? 'var(--accent)' : 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)', cursor: 'pointer', userSelect: 'none' }}
                    >
                      Symbol {sortKey === 'symbol' ? (sortDir === 'desc' ? '↓' : '↑') : ''}
                    </th>
                    <SortTh label="Price" k="last_price" />
                    <SortTh label="24h Change" k="change_24h" />
                    <SortTh label="Volume" k="volume_24h" />
                    <SortTh label="Turnover" k="turnover_24h" />
                    <th style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'right', borderBottom: '1px solid var(--border)' }}>High / Low</th>
                    <th style={{ padding: '10px 12px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'right', borderBottom: '1px solid var(--border)' }}>Detail</th>
                  </tr>
                </thead>
                <tbody>
                  {filteredSorted.slice(0, 150).map((row, i) => (
                    <TickerTableRow key={row.symbol} row={row} rank={i + 1} />
                  ))}
                </tbody>
              </table>
            </div>
            {filteredSorted.length === 0 && (
              <div style={{ padding: '32px', textAlign: 'center', color: 'var(--text-muted)' }}>
                No matching symbols found for "{search}"
              </div>
            )}
          </div>
        )}

        {/* No data state */}
        {!loading && tickers.length === 0 && (
          <div style={{ padding: 40, textAlign: 'center', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 12 }}>
            <div style={{ fontSize: 36, marginBottom: 12 }}>📡</div>
            <h3 style={{ margin: '0 0 8px', fontSize: 15, fontWeight: 700, color: 'var(--text-primary)' }}>Market Stream Connecting</h3>
            <p style={{ margin: '0 0 16px', fontSize: 13, color: 'var(--text-muted)', maxWidth: 400, marginLeft: 'auto', marginRight: 'auto', lineHeight: 1.6 }}>
              The live market overview stream is connecting to the USD-M futures feed.
              API fallback activates automatically if the stream is unavailable.
            </p>
          </div>
        )}

        {/* Warnings */}
        {envelope.warnings.length > 0 && (
          <div style={{ marginTop: 16, display: 'flex', flexDirection: 'column', gap: 3 }}>
            {envelope.warnings.slice(0, 3).map((w, i) => (
              <p key={i} style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>⚠ {w}</p>
            ))}
          </div>
        )}
      </div>

      {/* Footer */}
      <div style={{ padding: '12px 24px', borderTop: '1px solid var(--border)' }}>
        <p style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>
          Market data: Binance USD-M Futures WebSocket stream with API fallback · {envelope.source ?? '/api/v2/market/overview'} · Live market platform.
          {tickers.length} active pairs.
        </p>
      </div>
    </div>
  );
}
