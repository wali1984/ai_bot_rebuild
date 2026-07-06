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

const panelStyle: React.CSSProperties = {
  background: 'var(--bg-panel)',
  border: '1px solid var(--border)',
  borderRadius: 'var(--radius-md, 10px)',
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
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
      <div style={panelStyle}>
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

      <div style={panelStyle}>
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

      <div style={panelStyle}>
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
      <div style={{ ...panelStyle, textAlign: 'center', color: 'var(--text-muted)', fontSize: 13 }}>
        Waiting for live data stream…
      </div>
    );
  }

  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(340px, 1fr))', gap: 16 }}>
      <div style={panelStyle}>
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

      <div style={panelStyle}>
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
        <div style={{ ...panelStyle, gridColumn: '1 / -1' }}>
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
        <div style={{ ...panelStyle, gridColumn: '1 / -1' }}>
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
        <div style={{ ...panelStyle, gridColumn: '1 / -1' }}>
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
  const rows = useMemo(() => status.envelope.data?.ingestors ?? [], [status.envelope.data]);
  const active = name && rows.find((row) => row.name === name);

  return (
    <div data-testid="page-markets-ingestors" style={{ background: 'var(--bg-base)', minHeight: '100%', paddingBottom: 48 }}>
      <div style={{ padding: '20px 24px 12px', borderBottom: '1px solid var(--border)', background: 'var(--bg-panel)' }}>
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
        {name ? (
          <IngestorDetail name={name} />
        ) : (
          <IngestorsHub rows={rows} />
        )}
      </div>
    </div>
  );
}
