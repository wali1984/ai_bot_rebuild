import { useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

// Categorical palette validated with the dataviz six-checks script against the
// NERVYX dark panel (#101522) and light (#FFFFFF) surfaces. Fixed assignment
// order — never cycled.
const SERIES = ['#0E8F85', '#8672EA', '#C06A38', '#22A06B', '#A8841F'] as const;

// Status colors are reserved for state and always paired with a label.
const STATUS_COLOR: Record<string, string> = {
  live: 'var(--buy, #21C784)',
  stale: '#A8841F',
  upstream_error: 'var(--sell, #FF5D7A)',
  offline: 'var(--sell, #FF5D7A)',
  unknown_freshness: 'var(--text-muted, #8296B3)',
  not_started: 'var(--text-muted, #8296B3)',
};

interface IngestorRow {
  name: string;
  title: string;
  redis_pattern: string;
  key_count: number;
  sampled_payloads: number;
  upstream_error_payloads: number;
  newest_event_age_seconds: number | null;
  status: string;
  provider_current?: boolean;
  provider_usable?: boolean;
  provider_unusable_reason?: string | null;
  must_not_label_as_current_source?: boolean;
}

interface IngestorStatusData {
  ingestors: IngestorRow[];
  counts: { total: number; live: number; stale: number; offline: number; not_started: number };
}

interface MetricRow {
  key: string;
  symbol: string;
  age_seconds: number | null;
  last_price?: number | null;
  volume_24h_quote?: number | null;
  price_change_pct?: number | null;
  bid?: number | null;
  ask?: number | null;
  numeric_fields: Record<string, number>;
}

interface IngestorMetricsData {
  ingestor: string;
  title: string;
  redis_pattern: string;
  rows: MetricRow[];
  row_count: number;
}

interface ProviderCard {
  provider: string;
  display_name?: string;
  subscription_tier?: string | null;
  status?: string | null;
  dashboard_color?: string | null;
  dashboard_color_reason?: string | null;
  actual_payload_count?: number | null;
  feature_count?: number | null;
  consumer_count?: number | null;
  consumer_roles?: string[] | null;
  symbols_covered?: string[] | null;
  endpoints_active?: string[] | null;
  endpoints_disabled?: string[] | null;
  last_success_utc?: string | null;
  last_error_utc?: string | null;
  source_lag_seconds?: number | null;
  rate_limit_used?: number | null;
  rate_limit_remaining?: number | null;
  daily_quota_used?: number | null;
  monthly_quota_used?: number | null;
  heartbeat_only?: boolean | null;
  actual_payload_present?: boolean | null;
  raw_key_exposed?: boolean | null;
  routes_to_live?: boolean | null;
  places_real_order?: boolean | null;
  watchlist_count?: number | null;
  smart_wallet_candidate_count?: number | null;
  verified_smart_wallet_count?: number | null;
  token_map_count?: number | null;
  disabled_heatmap_endpoint?: boolean | null;
}

interface ProviderStatusData {
  providers?: ProviderCard[];
  provider_count?: number;
  heartbeat_only_green_count?: number;
  live_gate?: string;
  routes_to_live?: boolean;
  places_real_order?: boolean;
}

const REQUIRED_PROVIDER_ORDER = [
  ['binance', 'Binance WSS/REST'],
  ['kucoin', 'KuCoin WSS/REST'],
  ['coinank', 'CoinAnk'],
  ['coinglass', 'CoinGlass Standard'],
  ['moralis', 'Moralis Starter'],
  ['ta', 'TA pipeline'],
  ['microstructure', 'Microstructure trust'],
  ['liquidations', 'Liquidations'],
  ['orderbook', 'Orderbook recorder'],
  ['feature_snapshot_builder', 'Feature Snapshot Builder'],
  ['trainer_feed', 'Trainer Feed'],
] as const;

// Provider card id -> ingestor registry name (INGESTOR_FEEDS) so clicking a
// provider status card opens its live per-ingestor stream page. Providers with no
// dedicated ingestor feed are left non-clickable.
const PROVIDER_TO_INGESTOR: Record<string, string> = {
  binance: 'live_binance',
  kucoin: 'live_kucoin',
  coinank: 'live_coinank',
  moralis: 'moralis',
  ta: 'live_technical_analysis',
  liquidations: 'liquidation_bridge',
  orderbook: 'realtime_price_provider',
};

const panelStyle: React.CSSProperties = {
  padding: '16px 18px',
};

function PanelTitle({ children }: { children: React.ReactNode }) {
  return (
    <h3 style={{ margin: '0 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
      {children}
    </h3>
  );
}

const tooltipStyle: React.CSSProperties = {
  background: 'var(--bg-elevated, #161D2E)',
  border: '1px solid var(--border)',
  borderRadius: 6,
  fontSize: 12,
  color: 'var(--text-primary)',
};

function fmtAge(seconds: number | null | undefined): string {
  if (seconds == null) return '—';
  if (seconds < 90) return `${Math.round(seconds)}s`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m`;
  return `${(seconds / 3600).toFixed(1)}h`;
}

function fmtCount(value: number | null | undefined): string {
  if (value == null) return '—';
  return value.toLocaleString('en-US');
}

function joinPreview(values: string[] | null | undefined, fallback = '—', limit = 4): string {
  if (!Array.isArray(values) || values.length === 0) return fallback;
  const head = values.slice(0, limit).join(', ');
  return values.length > limit ? `${head} +${values.length - limit}` : head;
}

function providerTone(provider: ProviderCard | undefined): string {
  const color = String(provider?.dashboard_color ?? '').toLowerCase();
  if (color === 'green') return 'var(--buy, #21C784)';
  if (color === 'yellow') return '#A8841F';
  if (color === 'red') return 'var(--sell, #FF5D7A)';
  return 'var(--text-muted)';
}

function providerById(providers: ProviderCard[] | undefined): Map<string, ProviderCard> {
  const map = new Map<string, ProviderCard>();
  for (const provider of providers ?? []) {
    map.set(provider.provider.toLowerCase(), provider);
  }
  return map;
}

function ProviderTruthPanel({ providers }: { providers: ProviderStatusData | null | undefined }) {
  const byId = useMemo(() => providerById(providers?.providers), [providers?.providers]);
  const cards = REQUIRED_PROVIDER_ORDER.map(([id, label]) => ({ id, label, provider: byId.get(id) }));
  return (
    <div data-testid="provider-truth-panel" className="glass" style={{ ...panelStyle, marginBottom: 16 }}>
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 12, flexWrap: 'wrap', marginBottom: 12 }}>
        <PanelTitle>Provider truth · canonical contract</PanelTitle>
        <span style={{ fontSize: 11, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
          /api/v2/providers/status · live_gate {providers?.live_gate ?? 'blocked_human_only'} · read-only
        </span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 10 }}>
        {cards.map(({ id, label, provider }) => {
          const tone = providerTone(provider);
          const missing = !provider;
          const ingestorName = PROVIDER_TO_INGESTOR[id];
          const cardStyle: React.CSSProperties = {
            display: 'block',
            border: `1px solid ${missing ? 'var(--border)' : tone}`,
            borderRadius: 'var(--radius-sm, 8px)',
            padding: '12px 13px',
            background: missing ? 'var(--bg-elevated)' : 'color-mix(in oklch, var(--bg-elevated) 94%, transparent)',
            minWidth: 0,
            textDecoration: 'none',
            cursor: ingestorName ? 'pointer' : 'default',
          };
          const body = (
            <>
              <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 8 }}>
                <strong style={{ fontSize: 13, color: 'var(--text-primary)' }}>{label}</strong>
                <span style={{ color: tone, fontSize: 10, fontFamily: 'var(--font-mono)', fontWeight: 700 }}>
                  {missing ? 'MISSING' : String(provider?.dashboard_color ?? provider?.status ?? 'gray').toUpperCase()}
                </span>
              </div>
              <div style={{ display: 'grid', gap: 5, fontSize: 11, color: 'var(--text-secondary)' }}>
                <span>tier <b>{provider?.subscription_tier ?? 'unknown'}</b> · status <b>{provider?.status ?? 'missing evidence'}</b></span>
                <span>payloads <b>{fmtCount(provider?.actual_payload_count)}</b> · features <b>{fmtCount(provider?.feature_count)}</b> · consumers <b>{fmtCount(provider?.consumer_count)}</b></span>
                <span>actual data <b>{provider?.actual_payload_present ? 'yes' : 'no'}</b> · heartbeat only <b>{provider?.heartbeat_only ? 'yes' : 'no'}</b></span>
                <span>symbols <b>{joinPreview(provider?.symbols_covered)}</b></span>
                <span>active endpoints <b>{joinPreview(provider?.endpoints_active)}</b></span>
                <span>disabled endpoints <b>{joinPreview(provider?.endpoints_disabled, 'none')}</b></span>
                <span>consumer roles <b>{joinPreview(provider?.consumer_roles)}</b></span>
                {id === 'coinglass' ? <span>heatmap disabled <b>{provider?.disabled_heatmap_endpoint === true ? 'yes' : 'no'}</b> · rate remaining <b>{fmtCount(provider?.rate_limit_remaining)}</b></span> : null}
                {id === 'moralis' ? <span>watchlist <b>{fmtCount(provider?.watchlist_count)}</b> · candidates <b>{fmtCount(provider?.smart_wallet_candidate_count)}</b> · token map <b>{fmtCount(provider?.token_map_count)}</b></span> : null}
                <span>last success <b>{provider?.last_success_utc ?? '—'}</b> · age <b>{fmtAge(provider?.source_lag_seconds)}</b></span>
                {ingestorName ? (
                  <span style={{ color: 'var(--accent, #22D3C5)', fontSize: 10, fontWeight: 700, marginTop: 2 }}>
                    View live stream →
                  </span>
                ) : null}
              </div>
            </>
          );
          return ingestorName ? (
            <Link key={id} to={`/markets/ingestors/${ingestorName}`} data-testid={`provider-card-${id}`} style={cardStyle}>
              {body}
            </Link>
          ) : (
            <div key={id} data-testid={`provider-card-${id}`} style={cardStyle}>
              {body}
            </div>
          );
        })}
      </div>
      <p style={{ margin: '12px 0 0', fontSize: 11, color: 'var(--text-muted)' }}>
        Retired non-current sources are not active panels here; this grid only shows canonical runtime providers and required internal pipelines.
      </p>
    </div>
  );
}

function StatusLegend({ rows }: { rows: IngestorRow[] }) {
  const counts = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) map.set(row.status, (map.get(row.status) ?? 0) + 1);
    return [...map.entries()];
  }, [rows]);
  return (
    <div style={{ display: 'flex', gap: 14, flexWrap: 'wrap', marginTop: 10 }}>
      {counts.map(([status, count]) => (
        <span key={status} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
          <span style={{ width: 10, height: 10, borderRadius: 3, background: STATUS_COLOR[status] ?? 'var(--text-muted)' }} />
          {status.replace(/_/g, ' ')} · {count}
        </span>
      ))}
    </div>
  );
}

/** Freshness colour: only live ingestors grade by age; others take their status colour. */
function ageColor(status: string, age: number | null | undefined): string {
  if (status !== 'live') return STATUS_COLOR[status] ?? 'var(--text-muted)';
  if (age == null) return 'var(--text-muted)';
  if (age < 60) return 'var(--buy, #21C784)';
  if (age < 300) return '#A8841F';
  return 'var(--sell, #FF5D7A)';
}

function Stat({ label, value, color, mono }: { label: string; value: React.ReactNode; color?: string; mono?: boolean }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
      <span style={{ fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em', whiteSpace: 'nowrap' }}>{label}</span>
      <span style={{ fontSize: 13, fontWeight: 700, color: color ?? 'var(--text-primary)', fontFamily: mono ? 'var(--font-mono)' : undefined, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{value}</span>
    </div>
  );
}

/** One ingestor as a full-field glass status card — every field from the real payload. */
function IngestorStatusCard({ row }: { row: IngestorRow }) {
  const color = STATUS_COLOR[row.status] ?? 'var(--text-muted)';
  const hasErrors = (row.upstream_error_payloads ?? 0) > 0;
  const providerKnown = row.provider_current !== undefined || row.provider_usable !== undefined;
  return (
    <Link
      to={`/markets/ingestors/${row.name}`}
      data-testid={`ingestor-status-card-${row.name}`}
      className="glass glass-hover"
      style={{ display: 'block', textDecoration: 'none', padding: '14px 16px', borderLeft: `3px solid ${color}` }}
    >
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8, marginBottom: 12 }}>
        <span style={{ minWidth: 0, fontSize: 14, fontWeight: 700, color: 'var(--text-primary)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{row.title}</span>
        <span style={{ flex: '0 0 auto', padding: '2px 9px', borderRadius: 999, fontSize: 10, fontWeight: 800, letterSpacing: '0.04em', color, background: `color-mix(in oklch, ${color} 14%, transparent)`, border: `1px solid color-mix(in oklch, ${color} 40%, transparent)`, textTransform: 'uppercase' }}>{row.status.replace(/_/g, ' ')}</span>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(2, minmax(0, 1fr))', gap: '10px 14px' }}>
        <Stat label="Freshness" value={fmtAge(row.newest_event_age_seconds)} color={ageColor(row.status, row.newest_event_age_seconds)} mono />
        <Stat label="Keys / symbols" value={row.key_count != null ? row.key_count.toLocaleString() : '—'} mono />
        <Stat label="Sampled payloads" value={row.sampled_payloads != null ? row.sampled_payloads.toLocaleString() : '—'} mono />
        <Stat label="Upstream errors" value={row.upstream_error_payloads ?? 0} color={hasErrors ? 'var(--sell, #FF5D7A)' : 'var(--buy, #21C784)'} mono />
        {providerKnown ? (
          <>
            <Stat label="Provider current" value={row.provider_current ? 'yes' : 'no'} color={row.provider_current ? 'var(--buy, #21C784)' : 'var(--text-muted)'} />
            <Stat label="Provider usable" value={row.provider_usable ? 'yes' : 'no'} color={row.provider_usable ? 'var(--buy, #21C784)' : 'var(--sell, #FF5D7A)'} />
          </>
        ) : null}
      </div>
      {row.provider_unusable_reason ? (
        <div style={{ marginTop: 10, fontSize: 11, color: 'var(--sell, #FF5D7A)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.provider_unusable_reason}>⚠ {row.provider_unusable_reason.replace(/_/g, ' ')}</div>
      ) : null}
      <div style={{ marginTop: 10, paddingTop: 10, borderTop: '1px solid var(--glass-border, var(--border))', display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 8 }}>
        <span style={{ minWidth: 0, fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }} title={row.redis_pattern}>{row.redis_pattern}</span>
        <span style={{ flex: '0 0 auto', fontSize: 11, color: 'var(--accent, #22D3C5)', fontWeight: 600 }}>View stream →</span>
      </div>
    </Link>
  );
}

const STATUS_RANK: Record<string, number> = { upstream_error: 0, offline: 1, stale: 2, not_started: 3, live: 4 };

/** Full per-ingestor status grid — problems surfaced first, every real field shown. */
function IngestorCardGrid({ rows }: { rows: IngestorRow[] }) {
  const sorted = useMemo(
    () => [...rows].sort((a, b) => (STATUS_RANK[a.status] ?? 9) - (STATUS_RANK[b.status] ?? 9) || a.title.localeCompare(b.title)),
    [rows],
  );
  const counts = useMemo(() => {
    const c = { total: rows.length, live: 0, stale: 0, offline: 0, upstream_error: 0, not_started: 0 } as Record<string, number>;
    for (const r of rows) c[r.status] = (c[r.status] ?? 0) + 1;
    return c;
  }, [rows]);
  const summary: Array<{ label: string; key: string }> = [
    { label: 'Total', key: 'total' },
    { label: 'Live', key: 'live' },
    { label: 'Stale', key: 'stale' },
    { label: 'Upstream error', key: 'upstream_error' },
    { label: 'Offline', key: 'offline' },
    { label: 'Not started', key: 'not_started' },
  ];
  return (
    <div style={{ marginBottom: 18 }}>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(120px, 1fr))', gap: 10, marginBottom: 14 }}>
        {summary.map((s) => (
          <div key={s.key} className="glass" style={{ padding: '10px 14px' }}>
            <span style={{ display: 'block', fontSize: 9, color: 'var(--text-muted)', textTransform: 'uppercase', letterSpacing: '0.06em' }}>{s.label}</span>
            <span style={{ display: 'block', fontSize: 22, fontWeight: 800, fontFamily: 'var(--font-mono)', color: s.key === 'total' ? 'var(--text-primary)' : (STATUS_COLOR[s.key] ?? 'var(--text-primary)') }}>{counts[s.key] ?? 0}</span>
          </div>
        ))}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 1fr))', gap: 14 }}>
        {sorted.map((row) => <IngestorStatusCard key={row.name} row={row} />)}
      </div>
    </div>
  );
}

/** Hub view: every ingestor as charts — status donut, freshness bars, coverage bars. */
function IngestorsHub({ rows }: { rows: IngestorRow[] }) {
  const donutData = useMemo(() => {
    const map = new Map<string, number>();
    for (const row of rows) map.set(row.status, (map.get(row.status) ?? 0) + 1);
    return [...map.entries()].map(([status, value]) => ({ name: status.replace(/_/g, ' '), status, value }));
  }, [rows]);

  const freshnessData = useMemo(
    () =>
      rows
        .map((row) => ({
          name: row.title,
          status: row.status,
          age: row.newest_event_age_seconds != null ? Math.min(row.newest_event_age_seconds, 3600) : null,
        }))
        .filter((row) => row.age != null),
    [rows],
  );

  const coverageData = useMemo(
    () => rows.map((row) => ({ name: row.title, keys: row.key_count, status: row.status })),
    [rows],
  );

  return (
    <>
      <IngestorCardGrid rows={rows} />
      <h3 style={{ margin: '4px 0 12px', fontSize: 13, fontWeight: 600, color: 'var(--text-secondary)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>Fleet visualisation</h3>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
      <div className="glass" style={panelStyle}>
        <PanelTitle>Ingestor status</PanelTitle>
        <ResponsiveContainer width="100%" height={220}>
          <PieChart>
            <Pie
              data={donutData}
              dataKey="value"
              nameKey="name"
              innerRadius="55%"
              outerRadius="85%"
              stroke="var(--bg-panel)"
              strokeWidth={2}
            >
              {donutData.map((entry) => (
                <Cell key={entry.status} fill={STATUS_COLOR[entry.status] ?? 'var(--text-muted)'} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
        <StatusLegend rows={rows} />
      </div>

      <div className="glass" style={panelStyle}>
        <PanelTitle>Newest event age (lower is fresher)</PanelTitle>
        <ResponsiveContainer width="100%" height={Math.max(220, freshnessData.length * 26)}>
          <BarChart data={freshnessData} layout="vertical" margin={{ left: 8, right: 44 }}>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 4" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} tickFormatter={(v: number) => fmtAge(v)} />
            <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} />
            <Tooltip contentStyle={tooltipStyle} formatter={(value) => fmtAge(Number(value))} cursor={{ fill: 'color-mix(in oklch, var(--text-muted) 8%, transparent)' }} />
            <Bar dataKey="age" barSize={12} radius={[0, 4, 4, 0]} label={{ position: 'right', fontSize: 10, fill: 'var(--text-muted)', formatter: (v: React.ReactNode) => fmtAge(Number(v)) }}>
              {freshnessData.map((entry) => (
                <Cell key={entry.name} fill={STATUS_COLOR[entry.status] ?? SERIES[0]} stroke="var(--bg-panel)" strokeWidth={1} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="glass" style={panelStyle}>
        <PanelTitle>Symbols / keys tracked</PanelTitle>
        <ResponsiveContainer width="100%" height={Math.max(220, coverageData.length * 26)}>
          <BarChart data={coverageData} layout="vertical" margin={{ left: 8, right: 44 }}>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 4" horizontal={false} />
            <XAxis type="number" tick={{ fontSize: 11, fill: 'var(--text-muted)' }} />
            <YAxis type="category" dataKey="name" width={170} tick={{ fontSize: 11, fill: 'var(--text-secondary)' }} />
            <Tooltip contentStyle={tooltipStyle} cursor={{ fill: 'color-mix(in oklch, var(--text-muted) 8%, transparent)' }} />
            <Bar dataKey="keys" barSize={12} radius={[0, 4, 4, 0]} fill={SERIES[0]} label={{ position: 'right', fontSize: 10, fill: 'var(--text-muted)' }} />
          </BarChart>
        </ResponsiveContainer>
      </div>
    </div>
    </>
  );
}

interface TrendPoint {
  at: string;
  medianAge: number | null;
  rowCount: number;
}

/** Detail view for one ingestor: per-symbol freshness, values, live trend. */
function IngestorDetail({ name }: { name: string }) {
  const metrics = useRealtimeResource<IngestorMetricsData>({
    url: `/api/v2/ingestors/${name}/metrics?limit=120`,
    source: `redis ingestor ${name}`,
    pollIntervalMs: 5000,
    unwrapEnvelopeData: 'contract',
  });
  const data = metrics.envelope.data;
  const rows = useMemo(() => data?.rows ?? [], [data]);

  // Accumulate a client-side trend from streamed frames.
  const [trend, setTrend] = useState<TrendPoint[]>([]);
  const lastStampRef = useRef<string>('');
  useEffect(() => {
    if (!data) return;
    const stamp = String(metrics.envelope.timestamp ?? new Date().toISOString());
    if (stamp === lastStampRef.current) return;
    lastStampRef.current = stamp;
    const ages = rows.map((row) => row.age_seconds).filter((age): age is number => age != null).sort((a, b) => a - b);
    const median = ages.length ? ages[Math.floor(ages.length / 2)] : null;
    setTrend((prev) => [
      ...prev.slice(-59),
      { at: stamp.slice(11, 19), medianAge: median, rowCount: rows.length },
    ]);
  }, [data, rows, metrics.envelope.timestamp]);

  const freshnessBySymbol = useMemo(
    () =>
      rows
        .filter((row) => row.age_seconds != null)
        .slice(0, 30)
        .map((row) => ({ symbol: row.symbol.replace(/USDT.*$/, ''), age: row.age_seconds as number })),
    [rows],
  );

  const changeRows = useMemo(
    () =>
      rows
        .filter((row) => row.price_change_pct != null)
        .sort((a, b) => (b.price_change_pct ?? 0) - (a.price_change_pct ?? 0))
        .slice(0, 30)
        .map((row) => ({ symbol: row.symbol.replace(/USDT.*$/, ''), change: row.price_change_pct as number })),
    [rows],
  );

  const volumeRows = useMemo(
    () =>
      rows
        .filter((row) => row.volume_24h_quote != null)
        .sort((a, b) => (b.volume_24h_quote ?? 0) - (a.volume_24h_quote ?? 0))
        .slice(0, 20)
        .map((row) => ({ symbol: row.symbol.replace(/USDT.*$/, ''), volume: (row.volume_24h_quote as number) / 1e6 })),
    [rows],
  );

  const freshSplit = useMemo(() => {
    let fresh = 0;
    let lagging = 0;
    for (const row of rows) {
      if (row.age_seconds == null) continue;
      if (row.age_seconds <= 60) fresh += 1;
      else lagging += 1;
    }
    return [
      { name: 'fresh ≤60s', value: fresh, color: 'var(--buy, #21C784)' },
      { name: 'lagging >60s', value: lagging, color: '#A8841F' },
    ];
  }, [rows]);

  if (metrics.envelope.source_type === 'unavailable' && !data) {
    return (
      <div className="glass" style={{ ...panelStyle, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        Waiting for live data stream…
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
      <div className="glass" style={panelStyle}>
        <PanelTitle>Feed freshness · live stream</PanelTitle>
        <ResponsiveContainer width="100%" height={200}>
          <LineChart data={trend} margin={{ left: 4, right: 12 }}>
            <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 4" vertical={false} />
            <XAxis dataKey="at" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} minTickGap={40} />
            <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickFormatter={(v: number) => fmtAge(v)} width={44} />
            <Tooltip contentStyle={tooltipStyle} formatter={(value) => fmtAge(Number(value))} />
            <Line type="monotone" dataKey="medianAge" name="median age" stroke={SERIES[0]} strokeWidth={2} dot={false} isAnimationActive={false} />
          </LineChart>
        </ResponsiveContainer>
        <div style={{ display: 'flex', alignItems: 'center', gap: 6, marginTop: 8, fontSize: 12, color: 'var(--text-secondary)' }}>
          <span style={{ width: 10, height: 2, background: SERIES[0], display: 'inline-block' }} />
          median payload age · updates in realtime over WebSocket
        </div>
      </div>

      <div className="glass" style={panelStyle}>
        <PanelTitle>Fresh vs lagging symbols</PanelTitle>
        <ResponsiveContainer width="100%" height={200}>
          <PieChart>
            <Pie data={freshSplit} dataKey="value" nameKey="name" innerRadius="55%" outerRadius="85%" stroke="var(--bg-panel)" strokeWidth={2}>
              {freshSplit.map((entry) => (
                <Cell key={entry.name} fill={entry.color} />
              ))}
            </Pie>
            <Tooltip contentStyle={tooltipStyle} />
          </PieChart>
        </ResponsiveContainer>
        <div style={{ display: 'flex', gap: 14, marginTop: 8 }}>
          {freshSplit.map((entry) => (
            <span key={entry.name} style={{ display: 'inline-flex', alignItems: 'center', gap: 6, fontSize: 12, color: 'var(--text-secondary)' }}>
              <span style={{ width: 10, height: 10, borderRadius: 3, background: entry.color }} />
              {entry.name} · {entry.value}
            </span>
          ))}
        </div>
      </div>

      {freshnessBySymbol.length > 0 && (
        <div className="glass" style={{ ...panelStyle, gridColumn: '1 / -1' }}>
          <PanelTitle>Payload age by symbol</PanelTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={freshnessBySymbol} margin={{ left: 4, right: 12 }} barCategoryGap="25%">
              <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="symbol" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} interval={0} angle={-38} height={52} textAnchor="end" />
              <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickFormatter={(v: number) => fmtAge(v)} width={44} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value) => fmtAge(Number(value))} cursor={{ fill: 'color-mix(in oklch, var(--text-muted) 8%, transparent)' }} />
              <Bar dataKey="age" fill={SERIES[0]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {changeRows.length > 0 && (
        <div className="glass" style={{ ...panelStyle, gridColumn: '1 / -1' }}>
          <PanelTitle>24h price change %</PanelTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={changeRows} margin={{ left: 4, right: 12 }} barCategoryGap="25%">
              <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="symbol" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} interval={0} angle={-38} height={52} textAnchor="end" />
              <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} tickFormatter={(v: number) => `${v.toFixed(1)}%`} width={48} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value) => `${Number(value).toFixed(2)}%`} cursor={{ fill: 'color-mix(in oklch, var(--text-muted) 8%, transparent)' }} />
              <Bar dataKey="change" radius={[4, 4, 0, 0]} maxBarSize={22}>
                {changeRows.map((entry) => (
                  <Cell key={entry.symbol} fill={entry.change >= 0 ? 'var(--chart-up, #21C784)' : 'var(--chart-down, #FF5D7A)'} />
                ))}
              </Bar>
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}

      {volumeRows.length > 0 && (
        <div className="glass" style={{ ...panelStyle, gridColumn: '1 / -1' }}>
          <PanelTitle>24h turnover · $M</PanelTitle>
          <ResponsiveContainer width="100%" height={220}>
            <BarChart data={volumeRows} margin={{ left: 4, right: 12 }} barCategoryGap="25%">
              <CartesianGrid stroke="var(--chart-grid)" strokeDasharray="2 4" vertical={false} />
              <XAxis dataKey="symbol" tick={{ fontSize: 10, fill: 'var(--text-muted)' }} interval={0} angle={-38} height={52} textAnchor="end" />
              <YAxis tick={{ fontSize: 10, fill: 'var(--text-muted)' }} width={52} />
              <Tooltip contentStyle={tooltipStyle} formatter={(value) => `$${Number(value).toFixed(1)}M`} cursor={{ fill: 'color-mix(in oklch, var(--text-muted) 8%, transparent)' }} />
              <Bar dataKey="volume" fill={SERIES[1]} radius={[4, 4, 0, 0]} maxBarSize={22} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </div>
  );
}

export default function MarketsIngestorsPage() {
  const { name } = useParams<{ name?: string }>();
  const status = useRealtimeResource<IngestorStatusData>({
    url: '/api/v2/ingestors/status',
    source: 'redis ingestor freshness scan',
    pollIntervalMs: 5000,
    unwrapEnvelopeData: 'contract',
  });
  const providerStatus = useRealtimeResource<ProviderStatusData>({
    url: '/api/v2/providers/status',
    source: 'control center provider truth',
    pollIntervalMs: 10000,
    unwrapEnvelopeData: 'contract',
  });
  const rows = useMemo(() => status.envelope.data?.ingestors ?? [], [status.envelope.data]);
  const active = name && rows.find((row) => row.name === name);

  return (
    <div data-testid="page-markets-ingestors" style={{ background: 'radial-gradient(44% 28% at 15% 0%, rgba(124,92,255,0.12), transparent 70%), radial-gradient(38% 30% at 90% 4%, rgba(59,130,246,0.08), transparent 72%), var(--bg-base)', minHeight: '100%', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 12px', borderBottom: '1px solid var(--border)', background: 'color-mix(in oklch, var(--bg-panel) 82%, transparent)', backdropFilter: 'blur(8px)' }}>
        <div style={{ display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' }}>
          <h1 style={{ margin: 0, fontSize: 20, fontWeight: 700, color: 'var(--text-primary)' }}>
            <Link to="/markets" style={{ color: 'var(--text-muted)', textDecoration: 'none' }}>Markets</Link>
            {' / '}
            <Link to="/markets/ingestors" style={{ color: active ? 'var(--text-muted)' : 'var(--text-primary)', textDecoration: 'none' }}>
              Ingestors
            </Link>
            {active ? ` / ${active.title}` : ''}
          </h1>
          <span style={{ fontSize: 12, color: 'var(--text-muted)' }}>
            realtime over WebSocket · read-only
          </span>
        </div>

        {/* Ingestor sub-menu */}
        <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginTop: 14 }}>
          {rows.map((row) => (
            <Link
              key={row.name}
              to={`/markets/ingestors/${row.name}`}
              style={{
                display: 'inline-flex',
                alignItems: 'center',
                gap: 7,
                padding: '5px 12px',
                borderRadius: 999,
                fontSize: 12,
                textDecoration: 'none',
                border: `1px solid ${name === row.name ? 'var(--accent, #22D3C5)' : 'var(--border)'}`,
                color: name === row.name ? 'var(--accent, #22D3C5)' : 'var(--text-secondary)',
                background: name === row.name ? 'color-mix(in oklch, var(--accent, #22D3C5) 10%, transparent)' : 'transparent',
              }}
            >
              <span
                style={{
                  width: 8,
                  height: 8,
                  borderRadius: '50%',
                  background: STATUS_COLOR[row.status] ?? 'var(--text-muted)',
                }}
              />
              {row.title}
            </Link>
          ))}
        </div>
      </div>

      <div style={{ padding: '18px 24px' }}>
        <ProviderTruthPanel providers={providerStatus.envelope.data} />
        {name ? (
          <>
            {active ? (
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(300px, 340px))', gap: 14, marginBottom: 16 }}>
                <IngestorStatusCard row={active} />
              </div>
            ) : null}
            <IngestorDetail name={name} />
          </>
        ) : (
          <IngestorsHub rows={rows} />
        )}
      </div>
    </div>
  );
}
