import { useMemo, useState } from 'react';
import { PnLBars, Donut, DonutLegend, ChartFrame } from '../../components/charts/NervyxCharts';
import { CATEGORICAL } from '../../components/charts/nervyxChartTheme';
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

interface LiqZone {
  price: number;
  strength: number | null;
}

interface DerivRow {
  symbol: string;
  // funding
  funding_rate: number | null;
  next_funding_time: string | null;
  coinglass_funding_rate: number | null;
  coinglass_funding_rate_zscore: number | null;
  coinglass_next_funding_minutes: number | null;
  // open interest
  open_interest: number | null;
  open_interest_value: number | null;
  open_interest_change_pct: number | null;
  // basis
  basis_bps: number | null;
  mark_price: number | null;
  index_price: number | null;
  // long / short
  long_short_ratio: number | null;
  coinank_derivatives_score: number | null;
  // liquidations
  liquidation_levels_count: number | null;
  long_liquidation_level: number | null;
  short_liquidation_level: number | null;
  long_liquidation_distance_pct: number | null;
  short_liquidation_distance_pct: number | null;
  cascade_risk: number | null;
  cascade_probability: number | null;
  market_stress: number | null;
  pressure_direction: string | number | null;
  predicted_long_zone: number | null;
  predicted_short_zone: number | null;
  long_turnover_usd: number | null;
  short_turnover_usd: number | null;
  turnover_imbalance_usd: number | null;
  long_zones: LiqZone[];
  short_zones: LiqZone[];
  // cross exchange
  price_spread_pct: number | null;
  funding_spread_bps: number | null;
  binance_funding_pct: number | null;
  kucoin_funding_pct: number | null;
  spread_differential: number | null;
  better_liquidity_exchange: string | null;
}

interface RegimeData {
  total_open_interest_usd: number | null;
  total_volume_usd: number | null;
  total_liquidations_usd: number | null;
  aggregate_long_short_ratio: number | null;
  avg_funding_rate: number | null;
  market_sentiment: number | null;
  fear_greed: number | null;
  alt_season_index: number | null;
  btc_dominance: number | null;
  eth_dominance: number | null;
  volatility_index: number | null;
  present_member_count: number | null;
  age_seconds: number | null;
  data_status: string | null;
}

interface DerivativesData {
  rows: DerivRow[];
  aggregate: {
    total_oi_usd: number | null;
    total_liq_24h: number | null;
    avg_funding: number | null;
    aggregate_long_short_ratio: number | null;
    funding_positive_count: number | null;
    funding_negative_count: number | null;
  } | null;
  regime: RegimeData | null;
  source: string | null;
  timestamp: string | null;
}

interface RuntimeDerivativesPayload {
  generated_utc?: string;
  aggregate?: Record<string, unknown>;
  global_regime?: Record<string, unknown>;
  modules?: {
    funding?: { rows?: Array<Record<string, unknown>> };
    open_interest?: { rows?: Array<Record<string, unknown>> };
    long_short?: { rows?: Array<Record<string, unknown>> };
    basis?: { rows?: Array<Record<string, unknown>> };
    liquidations?: { rows?: Array<Record<string, unknown>> };
    cross_exchange?: { rows?: Array<Record<string, unknown>> };
  };
  source_keys?: Record<string, unknown>;
}

type TabId = 'funding' | 'open_interest' | 'basis' | 'long_short' | 'liquidations' | 'cross_exchange';

const TABS: Array<{ id: TabId; label: string }> = [
  { id: 'funding', label: 'Funding Rates' },
  { id: 'open_interest', label: 'Open Interest' },
  { id: 'basis', label: 'Basis' },
  { id: 'long_short', label: 'Long / Short' },
  { id: 'liquidations', label: 'Liquidations' },
  { id: 'cross_exchange', label: 'Cross-Exchange' },
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
  const abs = Math.abs(n);
  const sign = n < 0 ? '-' : '';
  if (abs >= 1e9) return `${sign}$${(abs / 1e9).toFixed(2)}B`;
  if (abs >= 1e6) return `${sign}$${(abs / 1e6).toFixed(2)}M`;
  if (abs >= 1e3) return `${sign}$${(abs / 1e3).toFixed(1)}K`;
  return `${sign}$${abs.toFixed(2)}`;
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

function zones(value: unknown): LiqZone[] {
  if (!Array.isArray(value)) return [];
  const out: LiqZone[] = [];
  for (const item of value) {
    if (item && typeof item === 'object') {
      const price = num((item as Record<string, unknown>).price);
      if (price != null) out.push({ price, strength: num((item as Record<string, unknown>).strength) });
    }
  }
  return out;
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
  // Accept both the raw published file (modules at root) and the /api/v2/derivatives
  // contract envelope (payload under `data`).
  const root = raw as { data?: unknown; modules?: unknown };
  const payload = (root && typeof root === 'object' && 'data' in root && root.data && !root.modules
    ? (root.data as RuntimeDerivativesPayload)
    : (raw as RuntimeDerivativesPayload));
  const fundingRows = rowsBySymbol(payload.modules?.funding?.rows);
  const oiRows = rowsBySymbol(payload.modules?.open_interest?.rows);
  const longShortRows = rowsBySymbol(payload.modules?.long_short?.rows);
  const basisRows = rowsBySymbol(payload.modules?.basis?.rows);
  const liquidationRows = rowsBySymbol(payload.modules?.liquidations?.rows);
  const crossRows = rowsBySymbol(payload.modules?.cross_exchange?.rows);
  const symbols = [...new Set([
    ...fundingRows.keys(),
    ...oiRows.keys(),
    ...longShortRows.keys(),
    ...liquidationRows.keys(),
    ...crossRows.keys(),
  ])].sort();

  const rows: DerivRow[] = symbols.map((symbol) => {
    const funding = fundingRows.get(symbol);
    const oi = oiRows.get(symbol);
    const longShort = longShortRows.get(symbol);
    const basis = basisRows.get(symbol);
    const liquidation = liquidationRows.get(symbol);
    const cross = crossRows.get(symbol);
    const markPrice = num(funding?.mark_price) ?? num(basis?.mark_price);
    const openInterest = num(oi?.open_interest);
    const pressureRaw = liquidation?.pressure_direction;
    return {
      symbol,
      funding_rate: num(funding?.funding_rate),
      next_funding_time: isoFromMaybeMs(funding?.next_funding_time),
      coinglass_funding_rate: num(funding?.coinglass_funding_rate),
      coinglass_funding_rate_zscore: num(funding?.coinglass_funding_rate_zscore),
      coinglass_next_funding_minutes: num(funding?.coinglass_next_funding_minutes),
      open_interest: openInterest,
      open_interest_value: openInterest != null && markPrice != null ? openInterest * markPrice : null,
      open_interest_change_pct: num(oi?.open_interest_change_pct),
      basis_bps: num(basis?.basis_bps) ?? num(funding?.basis_bps),
      mark_price: markPrice,
      index_price: num(basis?.index_price) ?? num(funding?.index_price),
      long_short_ratio: num(longShort?.long_short_ratio),
      coinank_derivatives_score: num(longShort?.coinank_derivatives_score),
      liquidation_levels_count: num(liquidation?.levels_count),
      long_liquidation_level: num(liquidation?.long_level),
      short_liquidation_level: num(liquidation?.short_level),
      long_liquidation_distance_pct: num(liquidation?.long_distance_pct),
      short_liquidation_distance_pct: num(liquidation?.short_distance_pct),
      cascade_risk: num(liquidation?.cascade_risk),
      cascade_probability: num(liquidation?.cascade_probability),
      market_stress: num(liquidation?.market_stress),
      pressure_direction: typeof pressureRaw === 'string' ? pressureRaw : num(pressureRaw),
      predicted_long_zone: num(liquidation?.predicted_long_zone),
      predicted_short_zone: num(liquidation?.predicted_short_zone),
      long_turnover_usd: num(liquidation?.long_turnover_usd),
      short_turnover_usd: num(liquidation?.short_turnover_usd),
      turnover_imbalance_usd: num(liquidation?.turnover_imbalance_usd),
      long_zones: zones(liquidation?.long_zones),
      short_zones: zones(liquidation?.short_zones),
      price_spread_pct: num(cross?.price_spread_pct),
      funding_spread_bps: num(cross?.funding_spread_bps),
      binance_funding_pct: num(cross?.binance_funding_pct),
      kucoin_funding_pct: num(cross?.kucoin_funding_pct),
      spread_differential: num(cross?.spread_differential),
      better_liquidity_exchange: str(cross?.better_liquidity_exchange),
    };
  });

  const g = payload.global_regime ?? {};
  const regime: RegimeData = {
    total_open_interest_usd: num(g.total_open_interest_usd),
    total_volume_usd: num(g.total_volume_usd),
    total_liquidations_usd: num(g.total_liquidations_usd),
    aggregate_long_short_ratio: num(g.aggregate_long_short_ratio),
    avg_funding_rate: num(g.avg_funding_rate),
    market_sentiment: num(g.market_sentiment),
    fear_greed: num(g.fear_greed),
    alt_season_index: num(g.alt_season_index),
    btc_dominance: num(g.btc_dominance),
    eth_dominance: num(g.eth_dominance),
    volatility_index: num(g.volatility_index),
    present_member_count: num(g.present_member_count),
    age_seconds: num(g.age_seconds),
    data_status: str(g.data_status),
  };

  const a = payload.aggregate ?? {};
  const fundingRates = rows.map((row) => row.funding_rate).filter((value): value is number => value != null);
  const aggregate = {
    total_oi_usd: num(a.total_oi_usd) ?? regime.total_open_interest_usd,
    total_liq_24h: num(a.total_liq_24h) ?? regime.total_liquidations_usd,
    avg_funding: num(a.avg_funding) ?? (fundingRates.length ? fundingRates.reduce((s, v) => s + v, 0) / fundingRates.length : null),
    aggregate_long_short_ratio: num(a.aggregate_long_short_ratio) ?? regime.aggregate_long_short_ratio,
    funding_positive_count: num(a.funding_positive_count) ?? fundingRates.filter((v) => v > 0).length,
    funding_negative_count: num(a.funding_negative_count) ?? fundingRates.filter((v) => v < 0).length,
  };

  return {
    rows,
    aggregate,
    regime: regime.data_status && regime.data_status !== 'NO_CURRENT_GLOBAL_REGIME_SOURCE' ? regime : null,
    source: 'Derivatives runtime',
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

const TH_STYLE: React.CSSProperties = {
  padding: '10px 16px', fontSize: 11, fontWeight: 600, textTransform: 'uppercase',
  letterSpacing: '0.05em', color: 'var(--text-muted)', textAlign: 'left', borderBottom: '1px solid var(--border)',
};

function sentimentLabel(v: number | null): { text: string; color: string } {
  if (v == null) return { text: '—', color: 'var(--text-muted)' };
  if (v >= 0.2) return { text: 'Bullish', color: 'var(--buy)' };
  if (v <= -0.2) return { text: 'Bearish', color: 'var(--sell)' };
  return { text: 'Neutral', color: 'var(--text-secondary)' };
}

function RegimePanel({ regime }: { regime: RegimeData }): JSX.Element | null {
  const sent = sentimentLabel(regime.market_sentiment);
  const items: Array<{ label: string; value: string; color?: string }> = [];
  if (regime.market_sentiment != null) items.push({ label: 'Market Sentiment', value: `${sent.text} (${regime.market_sentiment.toFixed(2)})`, color: sent.color });
  if (regime.aggregate_long_short_ratio != null) items.push({ label: 'Aggregate L/S', value: regime.aggregate_long_short_ratio.toFixed(2), color: regime.aggregate_long_short_ratio > 1 ? 'var(--buy)' : 'var(--sell)' });
  if (regime.fear_greed != null) items.push({ label: 'Fear / Greed', value: regime.fear_greed.toFixed(0), color: regime.fear_greed >= 55 ? 'var(--buy)' : regime.fear_greed <= 45 ? 'var(--sell)' : 'var(--text-secondary)' });
  if (regime.btc_dominance != null) items.push({ label: 'BTC Dominance', value: `${regime.btc_dominance.toFixed(2)}%` });
  if (regime.eth_dominance != null) items.push({ label: 'ETH Dominance', value: `${regime.eth_dominance.toFixed(2)}%` });
  if (regime.alt_season_index != null) items.push({ label: 'Alt-Season Index', value: regime.alt_season_index.toFixed(0) });
  if (regime.volatility_index != null) items.push({ label: 'Volatility Index', value: regime.volatility_index.toFixed(2) });
  if (regime.total_volume_usd != null) items.push({ label: '24h Volume', value: fmtUsd(regime.total_volume_usd) });
  if (items.length === 0) return null;
  return (
    <div style={{ margin: '16px 24px 0' }}>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Global Market Regime
        </span>
        <span style={{ fontSize: 10.5, color: 'var(--text-muted)' }}>
          CoinAnk aggregate · {regime.present_member_count ?? 0} metrics
          {regime.age_seconds != null ? ` · ${Math.round(regime.age_seconds)}s ago` : ''}
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 10 }}>
        {items.map((it) => (
          <div key={it.label} style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius-sm)', padding: '10px 12px' }}>
            <div style={{ fontSize: 10.5, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.04em' }}>{it.label}</div>
            <div style={{ fontSize: 15, fontWeight: 700, fontFamily: 'var(--font-mono)', color: it.color ?? 'var(--text-primary)', marginTop: 2 }}>{it.value}</div>
          </div>
        ))}
      </div>
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
        No current source rows — this module has no fresh data in the derivatives runtime feed yet.
      </p>
    </div>
  );
}

function FundingTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const sorted = [...rows].sort((a, b) => Math.abs(b.funding_rate ?? 0) - Math.abs(a.funding_rate ?? 0));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Funding Rate', 'Annualized', 'Next Funding', 'CoinGlass Rate', 'CG Z-Score', 'CG Next (min)'].map((h) => (
              <th key={h} style={TH_STYLE}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const fr = r.funding_rate;
            const color = fr == null ? 'var(--text-muted)' : fr > 0 ? 'var(--buy)' : fr < 0 ? 'var(--sell)' : 'var(--text-secondary)';
            const ann = fr != null ? fr * 3 * 365 : null;
            const z = r.coinglass_funding_rate_zscore;
            const zColor = z == null ? 'var(--text-muted)' : Math.abs(z) >= 2 ? 'var(--accent)' : 'var(--text-secondary)';
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px', color, fontWeight: 700 }}>{fmtPct(fr, true)}</td>
                <td style={{ padding: '10px 16px', color }}>{ann != null ? fmtPct(ann * 100, false) : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-muted)' }}>{fmtTime(r.next_funding_time)}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-secondary)' }}>{r.coinglass_funding_rate != null ? `${r.coinglass_funding_rate.toFixed(4)}%` : '—'}</td>
                <td style={{ padding: '10px 16px', color: zColor }}>{z != null ? z.toFixed(2) : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-muted)' }}>{r.coinglass_next_funding_minutes != null ? r.coinglass_next_funding_minutes.toFixed(0) : '—'}</td>
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
  const totalOI = rows.reduce((s, x) => s + (x.open_interest_value ?? 0), 0);
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'OI (Contracts)', 'OI (USD)', 'Δ Change', 'Share'].map((h) => (
              <th key={h} style={TH_STYLE}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const share = r.open_interest_value != null && totalOI > 0 ? (r.open_interest_value / totalOI) * 100 : null;
            const chg = r.open_interest_change_pct;
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px' }}>{fmt(r.open_interest, 0)}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-primary)' }}>{fmtUsd(r.open_interest_value)}</td>
                <td style={{ padding: '10px 16px', color: chg == null ? 'var(--text-muted)' : chg >= 0 ? 'var(--buy)' : 'var(--sell)' }}>{chg != null ? `${chg >= 0 ? '+' : ''}${chg.toFixed(2)}%` : '—'}</td>
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

function BasisTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const withBasis = rows.filter((r) => r.basis_bps != null);
  if (withBasis.length === 0) return <NotConnected feature="Basis (mark vs index)" />;
  const sorted = [...withBasis].sort((a, b) => Math.abs(b.basis_bps ?? 0) - Math.abs(a.basis_bps ?? 0));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Basis (bps)', 'Mark Price', 'Index Price', 'Structure'].map((h) => (
              <th key={h} style={TH_STYLE}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const b = r.basis_bps ?? 0;
            const color = b > 0 ? 'var(--buy)' : b < 0 ? 'var(--sell)' : 'var(--text-secondary)';
            const structure = b > 2 ? 'Contango' : b < -2 ? 'Backwardation' : 'Flat';
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px', color, fontWeight: 700 }}>{`${b >= 0 ? '+' : ''}${b.toFixed(2)}`}</td>
                <td style={{ padding: '10px 16px' }}>{r.mark_price != null ? fmt(r.mark_price, r.mark_price < 10 ? 4 : 2) : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-muted)' }}>{r.index_price != null ? fmt(r.index_price, r.index_price < 10 ? 4 : 2) : '—'}</td>
                <td style={{ padding: '10px 16px', color, fontWeight: 600 }}>{structure}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function LSTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const hasData = rows.some((r) => r.long_short_ratio != null);
  if (!hasData) return <NotConnected feature="Long / Short ratio data" />;
  const sorted = [...rows].sort((a, b) => (b.long_short_ratio ?? 1) - (a.long_short_ratio ?? 1));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'L/S Ratio', 'Longs %', 'Shorts %', 'Bias', 'CoinAnk Deriv Score'].map((h) => (
              <th key={h} style={TH_STYLE}>{h}</th>
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
            const score = r.coinank_derivatives_score;
            const scoreColor = score == null ? 'var(--text-muted)' : score >= 0.6 ? 'var(--buy)' : score <= 0.4 ? 'var(--sell)' : 'var(--text-secondary)';
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px', fontWeight: 700 }}>{r.long_short_ratio?.toFixed(2) ?? '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--buy)' }}>{r.long_short_ratio != null ? `${longPct.toFixed(1)}%` : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--sell)' }}>{r.long_short_ratio != null ? `${shortPct.toFixed(1)}%` : '—'}</td>
                <td style={{ padding: '10px 16px', color: biasColor, fontWeight: 600 }}>{r.long_short_ratio != null ? bias : '—'}</td>
                <td style={{ padding: '10px 16px', color: scoreColor, fontWeight: 600 }}>{score != null ? score.toFixed(3) : '—'}</td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function pressureText(p: string | number | null): { text: string; color: string } {
  if (p == null) return { text: '—', color: 'var(--text-muted)' };
  if (typeof p === 'string') {
    const low = p.toLowerCase();
    if (low.includes('long')) return { text: 'Long', color: 'var(--buy)' };
    if (low.includes('short')) return { text: 'Short', color: 'var(--sell)' };
    return { text: p, color: 'var(--text-secondary)' };
  }
  if (p > 0.05) return { text: `Long ${p.toFixed(2)}`, color: 'var(--buy)' };
  if (p < -0.05) return { text: `Short ${p.toFixed(2)}`, color: 'var(--sell)' };
  return { text: `Neutral ${p.toFixed(2)}`, color: 'var(--text-secondary)' };
}

function riskColor(v: number | null): string {
  if (v == null) return 'var(--text-muted)';
  if (v >= 0.66) return 'var(--sell)';
  if (v >= 0.33) return 'var(--warning, #d19a00)';
  return 'var(--buy)';
}

function LiqHeatmap({ row }: { row: DerivRow }): JSX.Element | null {
  const longs = [...row.long_zones].sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0)).slice(0, 6);
  const shorts = [...row.short_zones].sort((a, b) => (b.strength ?? 0) - (a.strength ?? 0)).slice(0, 6);
  if (longs.length === 0 && shorts.length === 0) return null;
  const maxStrength = Math.max(1, ...longs.map((z) => z.strength ?? 0), ...shorts.map((z) => z.strength ?? 0));
  const Bar = ({ z, color }: { z: LiqZone; color: string }): JSX.Element => (
    <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 11.5, fontFamily: 'var(--font-mono)' }}>
      <span style={{ width: 92, color: 'var(--text-secondary)' }}>{fmt(z.price, z.price < 10 ? 4 : 2)}</span>
      <div style={{ flex: 1, height: 8, background: 'var(--bg-elevated)', borderRadius: 3, overflow: 'hidden' }}>
        <div style={{ height: '100%', width: `${Math.max(4, ((z.strength ?? 0) / maxStrength) * 100)}%`, background: color, borderRadius: 3 }} />
      </div>
      <span style={{ width: 64, textAlign: 'right', color: 'var(--text-muted)' }}>{z.strength != null ? fmt(z.strength, 0) : '—'}</span>
    </div>
  );
  return (
    <div style={{ margin: '4px 24px 20px', background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 'var(--radius)', padding: 16 }}>
      <div style={{ fontSize: 12, fontWeight: 700, color: 'var(--text-secondary)', marginBottom: 12 }}>
        Liquidation Heatmap — {row.symbol.replace('USDT', '')}/USDT
        <span style={{ fontSize: 10.5, fontWeight: 400, color: 'var(--text-muted)', marginLeft: 8 }}>highest cascade risk · price ladder × strength</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24 }}>
        <div>
          <div style={{ fontSize: 11, color: 'var(--buy)', fontWeight: 600, marginBottom: 6 }}>Long liquidation zones (below)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {longs.length ? longs.map((z, i) => <Bar key={i} z={z} color="var(--buy)" />) : <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>—</span>}
          </div>
        </div>
        <div>
          <div style={{ fontSize: 11, color: 'var(--sell)', fontWeight: 600, marginBottom: 6 }}>Short liquidation zones (above)</div>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 5 }}>
            {shorts.length ? shorts.map((z, i) => <Bar key={i} z={z} color="var(--sell)" />) : <span style={{ fontSize: 11, color: 'var(--text-muted)' }}>—</span>}
          </div>
        </div>
      </div>
    </div>
  );
}

function LiqTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const hasData = rows.some((r) => r.liquidation_levels_count != null || r.cascade_risk != null || r.turnover_imbalance_usd != null);
  if (!hasData) return <NotConnected feature="Liquidation data" />;
  const sorted = [...rows].sort((a, b) => (b.cascade_risk ?? 0) - (a.cascade_risk ?? 0) || (b.liquidation_levels_count ?? 0) - (a.liquidation_levels_count ?? 0));
  const heatmapRow = sorted.find((r) => r.long_zones.length > 0 || r.short_zones.length > 0);
  return (
    <>
      <div style={{ overflowX: 'auto' }}>
        <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
          <thead>
            <tr style={{ background: 'var(--bg-elevated)' }}>
              {['Symbol', 'Cascade Risk', 'Cascade Prob', 'Market Stress', 'Pressure', 'Levels', 'Long Turnover', 'Short Turnover', 'Imbalance'].map((h) => (
                <th key={h} style={TH_STYLE}>{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {sorted.map((r, i) => {
              const press = pressureText(r.pressure_direction);
              const imb = r.turnover_imbalance_usd;
              return (
                <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                  <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                  <td style={{ padding: '10px 16px', color: riskColor(r.cascade_risk), fontWeight: 700 }}>{r.cascade_risk != null ? r.cascade_risk.toFixed(3) : '—'}</td>
                  <td style={{ padding: '10px 16px', color: riskColor(r.cascade_probability) }}>{r.cascade_probability != null ? r.cascade_probability.toFixed(3) : '—'}</td>
                  <td style={{ padding: '10px 16px', color: riskColor(r.market_stress) }}>{r.market_stress != null ? r.market_stress.toFixed(3) : '—'}</td>
                  <td style={{ padding: '10px 16px', color: press.color, fontWeight: 600 }}>{press.text}</td>
                  <td style={{ padding: '10px 16px' }}>{fmt(r.liquidation_levels_count ?? null, 0)}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--buy)' }}>{fmtUsd(r.long_turnover_usd)}</td>
                  <td style={{ padding: '10px 16px', color: 'var(--sell)' }}>{fmtUsd(r.short_turnover_usd)}</td>
                  <td style={{ padding: '10px 16px', color: imb == null ? 'var(--text-muted)' : imb >= 0 ? 'var(--buy)' : 'var(--sell)', fontWeight: 600 }}>{fmtUsd(imb)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      {heatmapRow && <LiqHeatmap row={heatmapRow} />}
    </>
  );
}

function CrossExchangeTable({ rows }: { rows: DerivRow[] }): JSX.Element {
  const withData = rows.filter((r) => r.price_spread_pct != null || r.funding_spread_bps != null);
  if (withData.length === 0) return <NotConnected feature="Cross-exchange arbitrage (Binance vs KuCoin)" />;
  const sorted = [...withData].sort((a, b) => Math.abs(b.funding_spread_bps ?? 0) - Math.abs(a.funding_spread_bps ?? 0));
  return (
    <div style={{ overflowX: 'auto' }}>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontFamily: 'var(--font-mono)', fontSize: 12.5 }}>
        <thead>
          <tr style={{ background: 'var(--bg-elevated)' }}>
            {['Symbol', 'Price Spread', 'Funding Spread (bps)', 'Binance Funding', 'KuCoin Funding', 'Spread Diff (bps)', 'Better Liquidity'].map((h) => (
              <th key={h} style={TH_STYLE}>{h}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {sorted.map((r, i) => {
            const fs = r.funding_spread_bps;
            return (
              <tr key={r.symbol} style={{ background: i % 2 === 0 ? 'var(--bg-base)' : 'var(--bg-panel)' }}>
                <td style={{ padding: '10px 16px', fontWeight: 600 }}>{r.symbol.replace('USDT', '')}/USDT</td>
                <td style={{ padding: '10px 16px' }}>{r.price_spread_pct != null ? `${r.price_spread_pct >= 0 ? '+' : ''}${r.price_spread_pct.toFixed(4)}%` : '—'}</td>
                <td style={{ padding: '10px 16px', color: fs == null ? 'var(--text-muted)' : Math.abs(fs) >= 5 ? 'var(--accent)' : 'var(--text-secondary)', fontWeight: 700 }}>{fs != null ? fs.toFixed(2) : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-secondary)' }}>{r.binance_funding_pct != null ? `${r.binance_funding_pct.toFixed(4)}%` : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-secondary)' }}>{r.kucoin_funding_pct != null ? `${r.kucoin_funding_pct.toFixed(4)}%` : '—'}</td>
                <td style={{ padding: '10px 16px', color: 'var(--text-muted)' }}>{r.spread_differential != null ? r.spread_differential.toFixed(2) : '—'}</td>
                <td style={{ padding: '10px 16px', fontWeight: 600, textTransform: 'capitalize' }}>{r.better_liquidity_exchange ?? '—'}</td>
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
    url: '/api/v2/derivatives',
    source: 'Derivatives runtime',
    source_type: 'websocket',
    pollIntervalMs: 30_000,
    staleThresholdMs: 90_000,
    mode: 'read_only',
    initialFetch: true,
    httpFallback: true,
    unwrapEnvelopeData: 'contract',
    transform: normalizeRuntimeDerivatives,
  });

  const data = envelope.data;
  const agg = data?.aggregate;
  const regime = data?.regime ?? null;
  const rows = data?.rows ?? [];

  // ── Chart derivations: top funding (bps, diverging) + OI share ───────────
  const topFunding = useMemo(() => [...rows]
    .filter((r) => r.funding_rate != null)
    .sort((a, b) => Math.abs(b.funding_rate ?? 0) - Math.abs(a.funding_rate ?? 0))
    .slice(0, 10)
    .map((r) => ({ label: r.symbol.replace('USDT', ''), value: (r.funding_rate ?? 0) * 10000 })), [rows]);
  const oiShare = useMemo(() => {
    const withOi = [...rows].filter((r) => (r.open_interest_value ?? 0) > 0).sort((a, b) => (b.open_interest_value ?? 0) - (a.open_interest_value ?? 0));
    const top = withOi.slice(0, 6).map((r, i) => ({ name: r.symbol.replace('USDT', ''), value: r.open_interest_value ?? 0, color: CATEGORICAL[i % CATEGORICAL.length] }));
    const rest = withOi.slice(6).reduce((s, r) => s + (r.open_interest_value ?? 0), 0);
    return rest > 0 ? [...top, { name: 'Others', value: rest, color: '#64748b' }] : top;
  }, [rows]);

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
              Funding · Open interest · Basis · Long/Short · Liquidations · Cross-exchange · {rows.length} symbols
            </p>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <FreshnessBadge status={envelope.freshness_status} lagMs={envelope.lag_ms} />
            <SourceBadge sourceType={envelope.source_type} source={envelope.source} />
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
          <KPICard label="Total OI" value={loading && !agg ? '…' : fmtUsd(agg?.total_oi_usd ?? null)} sub="Whole-market open interest" />
          <KPICard label="24h Liquidations" value={loading && !agg ? '…' : fmtUsd(agg?.total_liq_24h ?? null)} sub="Long + short liquidated" color="var(--sell)" />
          <KPICard label="Avg Funding" value={loading && !agg ? '…' : fmtPct(agg?.avg_funding != null ? agg.avg_funding * 100 : null)} color={agg?.avg_funding != null ? (agg.avg_funding > 0 ? 'var(--buy)' : 'var(--sell)') : undefined} sub="Across universe" />
          <KPICard label="Aggregate L/S" value={loading && !agg ? '…' : (agg?.aggregate_long_short_ratio != null ? agg.aggregate_long_short_ratio.toFixed(2) : '—')} color={agg?.aggregate_long_short_ratio != null ? (agg.aggregate_long_short_ratio > 1 ? 'var(--buy)' : 'var(--sell)') : undefined} sub="Whole-market positioning" />
          <KPICard label="Funding Split" value={loading && !agg ? '…' : `${agg?.funding_positive_count ?? '—'} / ${agg?.funding_negative_count ?? '—'}`} sub="Positive / negative symbols" />
        </div>
      </div>

      {/* Global regime */}
      {regime && <RegimePanel regime={regime} />}

      {/* Derivatives analytics charts — top funding rates + OI distribution */}
      {rows.length > 0 && (
        <div style={{ margin: '16px 24px 0', display: 'grid', gridTemplateColumns: 'minmax(0, 1.6fr) minmax(0, 1fr)', gap: 14 }}>
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
            <ChartFrame title="Top funding rates" subtitle="basis points · longs pay shorts when positive" height={180}>
              {topFunding.length
                ? <PnLBars data={topFunding} height={180} usd={false} />
                : <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12 }}>No funding data</div>}
            </ChartFrame>
          </div>
          <div style={{ background: 'var(--bg-panel)', border: '1px solid var(--border)', borderRadius: 10, padding: '10px 12px' }}>
            <ChartFrame title="Open-interest share" subtitle="top symbols by notional" height={180}>
              {oiShare.length
                ? <><Donut data={oiShare} height={160} centerLabel="symbols" centerValue={String(oiShare.length)} /><DonutLegend data={oiShare} /></>
                : <div style={{ height: 180, display: 'flex', alignItems: 'center', justifyContent: 'center', color: 'var(--text-muted)', fontSize: 12 }}>No OI data</div>}
            </ChartFrame>
          </div>
        </div>
      )}

      {/* Tabs */}
      <div style={{ display: 'flex', gap: 0, background: 'var(--bg-panel)', borderBottom: '1px solid var(--border)', marginTop: 16, overflowX: 'auto' }}>
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            style={{
              padding: '10px 18px', border: 'none', borderBottom: tab === t.id ? '2px solid var(--accent)' : '2px solid transparent',
              background: 'transparent', color: tab === t.id ? 'var(--accent)' : 'var(--text-secondary)',
              fontSize: 13, fontWeight: tab === t.id ? 700 : 400, cursor: 'pointer', whiteSpace: 'nowrap',
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
              Derivatives runtime reconnecting — {error}. Values remain withheld until the current feed responds.
            </p>
          </div>
        )}
        {!loading && !error && rows.length === 0 && (
          <div style={{ padding: 32, textAlign: 'center' }}>
            <p style={{ color: 'var(--text-muted)', fontSize: 13 }}>
              Derivatives runtime is connecting. The publisher has not returned current rows yet.
            </p>
          </div>
        )}
        {rows.length > 0 && (
          <>
            {tab === 'funding' && <FundingTable rows={rows} />}
            {tab === 'open_interest' && <OITable rows={rows} />}
            {tab === 'basis' && <BasisTable rows={rows} />}
            {tab === 'long_short' && <LSTable rows={rows} />}
            {tab === 'liquidations' && <LiqTable rows={rows} />}
            {tab === 'cross_exchange' && <CrossExchangeTable rows={rows} />}
          </>
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
