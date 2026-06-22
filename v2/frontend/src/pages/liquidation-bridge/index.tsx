import { useState } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { FreshnessBadge } from '../../components/data/FreshnessBadge';
import { SourceBadge } from '../../components/data/SourceBadge';
import { LoadingSkeleton } from '../../components/ui/LoadingSkeleton';
import meta from './meta';
import rbac from './rbac';
import route from './route';

export { default as meta } from './meta';
export { default as rbac } from './rbac';
export { default as route } from './route';

interface DerivRow {
  symbol: string;
  funding_rate: number | null;
  next_funding_time: string | null;
  open_interest: number | null;
  open_interest_value: number | null;
  long_short_ratio: number | null;
  liq_24h_long: number | null;
  liq_24h_short: number | null;
  liq_1h: number | null;
  liquidation_levels_count?: number | null;
  long_liquidation_level?: number | null;
  short_liquidation_level?: number | null;
  long_liquidation_distance_pct?: number | null;
  short_liquidation_distance_pct?: number | null;
}

interface DerivativesData {
  rows: DerivRow[];
  aggregate: {
    total_oi_usd: number | null;
    total_liq_24h: number | null;
    avg_funding: number | null;
    funding_positive_count: number | null;
    funding_negative_count: number | null;
  } | null;
  source: string | null;
  timestamp: string | null;
}

interface RuntimeDerivativesPayload {
  generated_utc?: string;
  modules?: {
    funding?: { rows?: Array<Record<string, unknown>> };
    open_interest?: { rows?: Array<Record<string, unknown>> };
    long_short?: { rows?: Array<Record<string, unknown>> };
    liquidations?: { rows?: Array<Record<string, unknown>> };
  };
  source_keys?: Record<string, unknown>;
}

type TabId = 'funding' | 'open_interest' | 'liquidations' | 'long_short';

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'funding', label: 'Funding Rates' },
  { id: 'open_interest', label: 'Open Interest' },
  { id: 'liquidations', label: 'Liquidations' },
  { id: 'long_short', label: 'Long / Short' },
];

function fmt(n: number | null, d = 2): string {
  if (n == null) return '—';
  return n.toLocaleString('en-US', { minimumFractionDigits: d, maximumFractionDigits: d });
}
function fmtPct(n: number | null, scale = false): string {
  if (n == null) return '—';
  const p = scale ? n * 100 : n;
  return `${p >= 0 ? '+' : ''}${p.toFixed(4)}%`;
}
function fmtUsd(n: number | null): string {
  if (n == null) return '—';
  if (n >= 1e9) return '$' + (n / 1e9).toFixed(2) + 'B';
  if (n >= 1e6) return '$' + (n / 1e6).toFixed(2) + 'M';
  if (n >= 1e3) return '$' + (n / 1e3).toFixed(1) + 'K';
  return '$' + n.toFixed(2);
}
function fmtTime(s: string | null): string {
  if (!s) return '—';
  return new Date(s).toLocaleTimeString();
}

function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() !== '') {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function str(value: unknown): string | null {
  return typeof value === 'string' && value.trim() !== '' ? value : null;
}

function isoFromMaybeMs(value: unknown): string | null {
  const numeric = num(value);
  if (numeric === null) return str(value);
  return new Date(numeric).toISOString();
}

function rowsBySymbol(rows: Array<Record<string, unknown>> | undefined): Map<string, Record<string, unknown>> {
  const map = new Map<string, Record<string, unknown>>();
  for (const row of rows ?? []) {
    const symbol = str(row.symbol)?.toUpperCase();
    if (symbol) map.set(symbol, row);
  }
  return map;
}

function normalizeRuntimeDerivatives(raw: unknown): DerivativesData {
  const payload = raw as RuntimeDerivativesPayload;
  const fundingRows = rowsBySymbol(payload.modules?.funding?.rows);
  const oiRows = rowsBySymbol(payload.modules?.open_interest?.rows);
  const longShortRows = rowsBySymbol(payload.modules?.long_short?.rows);
  const liquidationRows = rowsBySymbol(payload.modules?.liquidations?.rows);
  const symbols = [...new Set([
    ...fundingRows.keys(),
    ...oiRows.keys(),
    ...longShortRows.keys(),
    ...liquidationRows.keys(),
  ])].sort();

  const rows = symbols.map((symbol) => {
    const funding = fundingRows.get(symbol);
    const oi = oiRows.get(symbol);
    const longShort = longShortRows.get(symbol);
    const liquidation = liquidationRows.get(symbol);
    const markPrice = num(funding?.mark_price);
    const openInterest = num(oi?.open_interest);
    return {
      symbol,
      funding_rate: num(funding?.funding_rate),
      next_funding_time: isoFromMaybeMs(funding?.next_funding_time),
      open_interest: openInterest,
      open_interest_value: openInterest != null && markPrice != null ? openInterest * markPrice : null,
      long_short_ratio: num(longShort?.long_short_ratio),
      liq_24h_long: null,
      liq_24h_short: null,
      liq_1h: null,
      liquidation_levels_count: num(liquidation?.levels_count),
      long_liquidation_level: num(liquidation?.long_level),
      short_liquidation_level: num(liquidation?.short_level),
      long_liquidation_distance_pct: num(liquidation?.long_distance_pct),
      short_liquidation_distance_pct: num(liquidation?.short_distance_pct),
    };
  });

  const fundingRates = rows.map((row) => row.funding_rate).filter((value): value is number => value != null);
  const totalOi = rows.reduce((sum, row) => sum + (row.open_interest_value ?? 0), 0);
  return {
    rows,
    aggregate: {
      total_oi_usd: totalOi || null,
      total_liq_24h: null,
      avg_funding: fundingRates.length ? fundingRates.reduce((sum, value) => sum + value, 0) / fundingRates.length : null,
      funding_positive_count: fundingRates.filter((value) => value > 0).length,
      funding_negative_count: fundingRates.filter((value) => value < 0).length,
    },
    source: 'operator_runtime/v2_derivatives/latest/derivatives_payload.json',
    timestamp: payload.generated_utc ?? null,
  };
}

function KPICard({ label, value, sub, color }: { label: string; value: string; sub?: string; color?: string }): JSX.Element {
  return (
    <div style={{
      background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)',
      padding: '16px 18px', display: 'flex', flexDirection: 'column', gap: 4,
    }}>
      <span style={{ fontSize: 11, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>{label}</span>
      <span style={{ fontSize: 22, fontWeight: 700, fontFamily: 'var(--font-mono)', color: color ?? 'var(--text-primary)' }}>{value}</span>
      {sub && <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{sub}</span>}
    </div>
  );
}

function NotConnected({ feature }: { feature: string }): JSX.Element {
  return (
    <div style={{
      border: '1px dashed var(--border)', borderRadius: 'var(--radius)', padding: '32px',
      textAlign: 'center', background: 'var(--bg-panel)', margin: '0 24px 24px',
    }}>
      <p style={{ margin: '0 0 8px', fontSize: 14, fontWeight: 600, color: 'var(--text-secondary)' }}>{feature}</p>
      <p style={{ margin: 0, fontSize: 12, color: 'var(--text-muted)' }}>
        Not connected — this feature requires a realtime derivatives data feed.
        Data will appear automatically when the source is connected.
      </p>
    </div>
  );
}

function FundingTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const sorted = [...rows].sort((a, b) => {
    const av = a.funding_rate ?? 0;
    const bv = b.funding_rate ?? 0;
    return Math.abs(bv) - Math.abs(av);
  });
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Funding Rate', 'Next Funding', 'Annualized'].map((h) => (
              <th key={h} style={{ padding: '10px 16px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const fr = r.funding_rate;
            const color = fr == null ? 'var(--text-muted)' : fr > 0 ? 'var(--buy)' : fr < 0 ? 'var(--sell)' : 'var(--text-secondary)';
            const ann = fr != null ? fr * 3 * 365 : null;
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px', color, fontWeight: 700 }}>{fmtPct(fr, true)}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-muted)' }}>{fmtTime(r.next_funding_time)}</td>
                <td style={{ padding: '10px 16px', color }}>{ann != null ? fmtPct(ann * 100, false) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function OITable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const sorted = [...rows].sort((a, b) => (b.open_interest_value ?? 0) - (a.open_interest_value ?? 0));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'OI (Contracts)', 'OI (USD)', 'Share'].map((h) => (
              <th key={h} style={{ padding: '10px 16px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const totalOI = rows.reduce((s, x) => s + (x.open_interest_value ?? 0), 0);
            const share = r.open_interest_value != null && totalOI > 0 ? (r.open_interest_value / totalOI) * 100 : null;
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px' }}>{fmt(r.open_interest, 0)}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-primary)' }}>{fmtUsd(r.open_interest_value)}</td>
                <td style={{ padding: '10px 16px' }}>
                  {share != null ? (
                    <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                      <div style={{ flex: 1, height: 4, background: 'var(--bg-elevated)', borderRadius: 2, maxWidth: 80 }}>
                        <div style={{ height: '100%', borderRadius: 2, background: 'var(--accent)', width: `${Math.min(share, 100)}%` }} />
                      </div>
                      <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>{share.toFixed(1)}%</span>
                    </div>
                  ) : '—'}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LiqTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const sorted = [...rows].sort((a, b) => {
    const at = a.liquidation_levels_count ?? 0;
    const bt = b.liquidation_levels_count ?? 0;
    return bt - at;
  });
  const hasData = rows.some((r) => r.liquidation_levels_count != null || r.long_liquidation_level != null || r.short_liquidation_level != null);
  if (!hasData) return <NotConnected feature="Liquidation data" />;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Levels', 'Long Level', 'Long Distance', 'Short Level', 'Short Distance'].map((h) => (
              <th key={h} style={{ padding: '10px 16px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => (
            <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
              <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
              <td style={{ padding: '10px 16px', fontWeight: 700 }}>{fmt(r.liquidation_levels_count ?? null, 0)}</td>
              <td style={{ padding: '10px 16px', color: 'var(--sell)' }}>{fmtUsd(r.long_liquidation_level ?? null)}</td>
              <td style={{ padding: '10px 16px', color: 'var(--sell)' }}>{r.long_liquidation_distance_pct != null ? `${r.long_liquidation_distance_pct.toFixed(3)}%` : '—'}</td>
              <td style={{ padding: '10px 16px', color: 'var(--buy)' }}>{fmtUsd(r.short_liquidation_level ?? null)}</td>
              <td style={{ padding: '10px 16px', color: 'var(--buy)' }}>{r.short_liquidation_distance_pct != null ? `${r.short_liquidation_distance_pct.toFixed(3)}%` : '—'}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function LSTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const sorted = [...rows].sort((a, b) => {
    const av = a.long_short_ratio ?? 1;
    const bv = b.long_short_ratio ?? 1;
    return bv - av;
  });
  const hasData = rows.some((r) => r.long_short_ratio != null);
  if (!hasData) return <NotConnected feature="Long / Short ratio data" />;
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'L/S Ratio', 'Longs %', 'Shorts %', 'Bias'].map((h) => (
              <th key={h} style={{ padding: '10px 16px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase', letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)' }}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const ratio = r.long_short_ratio ?? 1;
            const longPct = (ratio / (ratio + 1)) * 100;
            const shortPct = 100 - longPct;
            const bias = ratio > 1.5 ? 'Long-heavy' : ratio < 0.67 ? 'Short-heavy' : 'Balanced';
            const biasColor = ratio > 1.5 ? 'var(--buy)' : ratio < 0.67 ? 'var(--sell)' : 'var(--text-secondary)';
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px', fontWeight: 700 }}>{r.long_short_ratio?.toFixed(2) ?? '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--buy)' }}>{longPct.toFixed(1)}%</td>
                <td style={{ padding: '10px 16px', color: 'var(--sell)' }}>{shortPct.toFixed(1)}%</td>
                <td style={{ padding: '10px 16px', color: biasColor, fontWeight: 600 }}>{bias}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

export default function DerivativesPage(): JSX.Element {
  const [tab, setTab] = useState<TabId>('funding');

  const { envelope, loading, error, refetch } = useRealtimeResource<DerivativesData>({
    url: '/operator_runtime/v2_derivatives/latest/derivatives_payload.json',
    source: '/operator_runtime/v2_derivatives/latest/derivatives_payload.json',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
    initialFetch: true,
    httpFallback: true,
    transform: normalizeRuntimeDerivatives,
  });

  const data = envelope.data;
  const agg = data?.aggregate;
  const rows = data?.rows ?? [];

  return (
    <div
      data-testid="page-derivatives"
      data-page-id={meta.id}
      data-page-path={route.path}
      data-page-min-role={rbac.minRole}
      style={{ background: 'var(--bg-base)', paddingBottom: 48 }}
    >
      {/* Header */}
      <div style={{ padding: '20px 24px 16px', background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12, marginBottom: 16 }}>
          <div>
            <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>Derivatives</h1>
            <p style={{ margin: '4px 0 0', fontSize: 13, color: 'var(--text-muted)' }}>
              Funding rates · Open interest · Liquidations · Long/Short ratios · {rows.length} symbols
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} endpoint={envelope.endpoint} />
            <button
              onClick={refetch}
              style={{ padding: '5px 12px', borderRadius: 'var(--radius-sm)', border: '1px solid var(--border)', background: 'transparent', color: 'var(--text-secondary)', fontSize: 12, cursor: 'pointer' }}
            >
              Refresh
            </button>
          </div>
        </div>

        {/* Aggregate KPIs */}
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(160px, 1fr))', gap: 12 }}>
          <KPICard
            label="Total OI"
            value={loading && !agg ? '…' : fmtUsd(agg?.total_oi_usd ?? null)}
            sub="Aggregate open interest"
          />
          <KPICard
            label="24h Liquidations"
            value={loading && !agg ? '…' : fmtUsd(agg?.total_liq_24h ?? null)}
            sub="Long + short liquidated"
          />
          <KPICard
            label="Avg Funding"
            value={loading && !agg ? '…' : fmtPct(agg?.avg_funding != null ? agg.avg_funding * 100 : null)}
            color={agg?.avg_funding != null ? (agg.avg_funding > 0 ? 'var(--buy)' : 'var(--sell)') : undefined}
            sub="Across universe"
          />
          <KPICard
            label="Positive Funding"
            value={loading && !agg ? '…' : String(agg?.funding_positive_count ?? '—')}
            color="var(--buy)"
            sub="Symbols paying longs"
          />
          <KPICard
            label="Negative Funding"
            value={loading && !agg ? '…' : String(agg?.funding_negative_count ?? '—')}
            color="var(--sell)"
            sub="Symbols paying shorts"
          />
        </div>
      </div>

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)' }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '10px 18px', border: 'none', borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
              background: 'transparent', color: tab === t.id ? 'var(--accent)' : 'var(--text-secondary)',
              fontSize: 13, fontWeight: tab === t.id ? 700 : 400, cursor: 'pointer',
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* Body */}
      <div style={{ marginTop: 0 }}>
        {loading && !data && <div style={{ padding: 24 }}><LoadingSkeleton rows={10} /></div>}
        {!loading && error && !data && (
          <div style={{ padding: 32, textAlign: 'center' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
              Derivatives stream reconnecting — {error}. Values remain withheld until the current feed responds.
            </p>
          </div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
              Derivatives stream is connecting. The endpoint has not returned current rows yet.
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <>
            {tab === 'funding' && <FundingTable rows={rows} />}
            {tab === 'open_interest' && <OITable rows={rows} />}
            {tab === 'liquidations' && <LiqTable rows={rows} />}
            {tab === 'long_short' && <LSTable rows={rows} />}
          </>
        )}
        {!loading && !error && rows.length === 0 && tab !== 'funding' && (
          <NotConnected feature={TABS.find((t) => t.id === tab)?.label ?? tab} />
        )}
      </div>

      {envelope.warnings.length > 0 && (
        <div style={{ padding: '8px 24px' }}>
          {envelope.warnings.map((w, i) => (
            <p key={i} style={{ margin: 0, fontSize: 11, color: 'var(--text-muted)' }}>⚠ {w}</p>
          ))}
        </div>
      )}
    </div>
  );
}
