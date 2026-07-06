import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

interface TickerRow {
  symbol: string;
  last_price: number | null;
  change_24h: number | null;
  turnover_24h?: number | null;
  funding_rate?: number | null;
  open_interest?: number | null;
  long_short_ratio?: number | null;
}

interface OverviewData { symbols?: string[]; tickers?: TickerRow[] }

interface UniverseData {
  tracked_symbols: string[];
  tracked_count: number;
  tracked_heartbeat_age_seconds: number | null;
  discovered_symbols: string[];
  discovered_count: number;
  discovery_status: Record<string, unknown>;
}

function KV({ label, value, color }: { label: string; value: string; color?: string }): JSX.Element {
  return (
    <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-md, 10px)', padding: '12px 14px' }}>
      <span style={{ display: 'block', fontSize: 10, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', marginBottom: 4 }}>{label}</span>
      <span style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
    </div>
  );
}

const th: React.CSSProperties = {
  padding: '9px 12px', textAlign: 'right', fontSize: 10, fontWeight: 600, textTransform: 'uppercase',
  letterSpacing: '0.05em', color: 'var(--text-muted)', background: 'var(--bg-elevated)',
  position: 'sticky', top: 0, borderBottom: '1px solid var(--border)', whiteSpace: 'nowrap',
};

export default function SymbolsPage(): JSX.Element {
  const navigate = useNavigate();
  const overview = useRealtimeResource<OverviewData>({
    url: '/api/v2/market/overview', source: '/api/v2/market/overview',
    source_type: 'websocket', pollIntervalMs: 15_000, staleThresholdMs: 60_000, mode: 'read_only',
  });
  const universe = useRealtimeResource<UniverseData>({
    url: '/api/v2/symbols/universe', source: '/api/v2/symbols/universe',
    source_type: 'websocket', pollIntervalMs: 30_000, staleThresholdMs: 120_000, mode: 'read_only',
  });
  const [filter, setFilter] = useState<'all' | 'tracked' | 'discovered'>('all');
  const [search, setSearch] = useState('');

  const tracked = useMemo(() => new Set(universe.envelope.data?.tracked_symbols ?? []), [universe.envelope.data]);
  const discovered = useMemo(() => new Set(universe.envelope.data?.discovered_symbols ?? []), [universe.envelope.data]);
  const rows = useMemo(() => {
    let list = overview.envelope.data?.tickers ?? [];
    if (filter === 'tracked') list = list.filter((r) => tracked.has(r.symbol));
    if (filter === 'discovered') list = list.filter((r) => discovered.has(r.symbol));
    const q = search.trim().toUpperCase();
    if (q) list = list.filter((r) => r.symbol.includes(q));
    return [...list].sort((a, b) => (b.turnover_24h ?? 0) - (a.turnover_24h ?? 0));
  }, [overview.envelope.data, filter, search, tracked, discovered]);

  const uni = universe.envelope.data;
  const disc = uni?.discovery_status ?? {};
  const loading = overview.loading && !overview.envelope.data;

  return (
    <div data-testid="page-symbols" data-page-id={meta.id} data-page-path={route.path} data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Symbols</h1>
        <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
          Adaptive symbol universe · ingestor coverage · dynamic discovery · realtime over WebSocket
        </p>
      </div>

      <div style={{ padding: '16px 24px 0', display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
        <KV label="Universe (USDT-M)" value={String(overview.envelope.data?.tickers?.length ?? '—')} />
        <KV label="Ingestor tracked" value={String(uni?.tracked_count ?? '—')} color="var(--buy)" />
        <KV label="Dynamic discovered" value={String(uni?.discovered_count ?? '—')} color="var(--accent, #22D3C5)" />
        <KV label="Heartbeat age" value={uni?.tracked_heartbeat_age_seconds != null ? `${Math.round(uni.tracked_heartbeat_age_seconds)}s` : '—'}
          color={(uni?.tracked_heartbeat_age_seconds ?? 999) < 180 ? 'var(--buy)' : 'var(--warn)'} />
        {'dynamic_symbol_count' in disc && <KV label="Dynamic universe" value={String(disc.dynamic_symbol_count ?? '—')} />}
        {'binance_usdm_status' in disc && (
          <KV label="Discovery sources" value={['binance_usdm_status', 'coingecko_status', 'coinglass_status', 'surf_status']
            .filter((k) => JSON.stringify(disc[k] ?? '').includes('API_OK')).length + ' / 4 OK'} color="var(--accent, #22D3C5)" />
        )}
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '14px 24px 0', flexWrap: 'wrap' }}>
        {(['all', 'tracked', 'discovered'] as const).map((f) => (
          <button key={f} onClick={() => setFilter(f)}
            style={{
              padding: '5px 14px', borderRadius: 999, fontSize: 12, cursor: 'pointer',
              border: `1px solid ${filter === f ? 'var(--accent, #22D3C5)' : 'var(--border)'}`,
              background: filter === f ? 'color-mix(in oklch, var(--accent, #22D3C5) 12%, transparent)' : 'none',
              color: filter === f ? 'var(--text-primary)' : 'var(--text-muted)', fontWeight: filter === f ? 600 : 400,
            }}>
            {f === 'all' ? `All (${overview.envelope.data?.tickers?.length ?? 0})` : f === 'tracked' ? `Tracked (${uni?.tracked_count ?? 0})` : `Discovered (${uni?.discovered_count ?? 0})`}
          </button>
        ))}
        <div style={{ flex: 1 }} />
        <input type="text" placeholder="Search…" value={search} onChange={(e) => setSearch(e.target.value)}
          style={{ padding: '5px 10px', borderRadius: 6, border: '1px solid var(--border)', background: 'var(--bg-elevated)', color: 'var(--text-primary)', fontFamily: 'var(--font-mono)', fontSize: 12, width: 150, outline: 'none' }} />
      </div>

      <div style={{ overflowX: 'auto', padding: '12px 24px 0' }}>
        {loading ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>Connecting symbol universe stream…</p>
        ) : rows.length === 0 ? (
          <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>No symbols match the current filter.</p>
        ) : (
          <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12 }}>
            <thead>
              <tr>
                <th style={{ ...th, textAlign: 'left' }}>Symbol</th>
                <th style={th}>Price</th>
                <th style={th}>24h %</th>
                <th style={th}>Turnover</th>
                <th style={th}>Funding</th>
                <th style={th}>Open Int.</th>
                <th style={th}>L / S</th>
                <th style={{ ...th, textAlign: 'center' }}>Coverage</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r, i) => {
                const chg = r.change_24h != null ? (Math.abs(r.change_24h) <= 1 ? r.change_24h * 100 : r.change_24h) : null;
                return (
                  <tr key={r.symbol} onClick={() => navigate(`/market/${r.symbol}`)}
                    style={{ cursor: 'pointer', background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                    <td style={{ padding: '8px 12px', fontWeight: 600, color: 'var(--text-primary)' }}>{r.symbol}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: 'var(--text-primary)' }}>{r.last_price?.toLocaleString() ?? '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', fontWeight: 700, color: chg == null ? 'var(--text-muted)' : chg >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
                      {chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '—'}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                      {r.turnover_24h != null ? `$${(r.turnover_24h / 1e6).toFixed(1)}M` : '—'}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: r.funding_rate == null ? 'var(--text-muted)' : r.funding_rate >= 0 ? 'var(--buy)' : 'var(--sell)' }}>
                      {r.funding_rate != null ? `${(r.funding_rate * 100).toFixed(4)}%` : '—'}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)' }}>
                      {r.open_interest != null ? r.open_interest.toLocaleString('en-US', { maximumFractionDigits: 0 }) : '—'}
                    </td>
                    <td style={{ padding: '8px 12px', textAlign: 'right', color: 'var(--text-secondary)' }}>{r.long_short_ratio?.toFixed(2) ?? '—'}</td>
                    <td style={{ padding: '8px 12px', textAlign: 'center' }}>
                      {tracked.has(r.symbol) ? (
                        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--buy)' }}>TRACKED</span>
                      ) : discovered.has(r.symbol) ? (
                        <span style={{ fontSize: 10, fontWeight: 700, color: 'var(--accent, #22D3C5)' }}>DISCOVERED</span>
                      ) : (
                        <span style={{ fontSize: 10, color: 'var(--text-muted)' }}>exchange only</span>
                      )}
                    </td>
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
