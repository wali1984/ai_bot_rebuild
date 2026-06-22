import { useMemo } from 'react';
import { ageClass, fmtAge, usePayloadFile } from '../../hooks/usePayloadFile';

interface ChartSample {
  symbol: string;
  source?: string;
  source_type?: string;
  event_ts_ms?: number;
  received_ts_ms?: number;
  timestamp_utc?: string;
  mid_px?: number;
  best_bid_px?: number | null;
  best_ask_px?: number | null;
  spread?: number | null;
  imbalance_5?: number | null;
  book_bid_sum_5?: number | null;
  book_ask_sum_5?: number | null;
}

interface MarketChartPayload {
  status?: string;
  blocker?: string | null;
  generated_est?: string;
  generated_utc?: string;
  symbol?: string;
  timeframe?: string;
  chart_source?: string;
  source_type?: string;
  source_redis_key?: string;
  source_event_age_seconds?: number | null;
  sample_count?: number;
  latest?: ChartSample | null;
  samples?: ChartSample[];
  redis_read_ok?: boolean;
  live_gate?: string;
  live_symbols?: string[];
  execution_live_symbols?: string[];
}

export const V2_MARKET_CHART_BASE_PATH = '/operator_runtime/v2_market_chart/latest';

function finite(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function money(value: unknown): string {
  const n = finite(value);
  if (n === null) return 'Connecting stream';
  if (n >= 1000) return `$${n.toLocaleString('en-US', { maximumFractionDigits: 2 })}`;
  if (n >= 1) return `$${n.toLocaleString('en-US', { maximumFractionDigits: 4 })}`;
  return `$${n.toLocaleString('en-US', { maximumFractionDigits: 8 })}`;
}

function shortTs(ms: unknown): string {
  const n = finite(ms);
  if (n === null) return 'Time unavailable';
  return new Date(n).toLocaleTimeString('en-US', { hour12: false, hour: '2-digit', minute: '2-digit', second: '2-digit' });
}

function chartStatusLabel(value: string | undefined, loading: boolean): string {
  if (loading) return 'Loading';
  if (!value) return 'Connecting stream';
  const text = value.trim().toUpperCase();
  if (text === 'CURRENT') return 'Current';
  if (text.includes('STALE')) return 'Stale data';
  if (text.includes('MISSING') || text.includes('UNAVAILABLE') || text.includes('ERROR')) return 'Connecting stream';
  return value.replace(/[_-]+/g, ' ').replace(/^./u, (char) => char.toUpperCase());
}

function chartSourceLabel(value: unknown): string {
  const text = String(value ?? '').trim().toLowerCase();
  if (!text) return 'Market chart source connecting';
  if (text.includes('websocket') || text.includes('stream')) return 'Live market stream';
  if (text.includes('api') || text.includes('contract')) return 'Current market data source';
  if (text.includes('static') || text.includes('fallback')) return 'Fallback market data';
  return 'Current market chart source';
}

function pathFor(symbol: string, timeframe: string): string {
  return `${V2_MARKET_CHART_BASE_PATH}/${symbol}_${timeframe}_chart.json`;
}

export function V2RealtimeMarketChart({
  symbol = 'BTCUSDT',
  timeframe = '1m',
  height = 300,
}: {
  symbol?: string;
  timeframe?: string;
  height?: number;
}): JSX.Element {
  const path = pathFor(symbol, timeframe);
  const { data, error, ageSeconds, loading } = usePayloadFile<MarketChartPayload>(path, 2_000);
  const samples = useMemo(
    () => (data?.samples ?? []).filter((sample) => finite(sample.mid_px) !== null),
    [data?.samples],
  );
  const latest = data?.latest ?? samples[samples.length - 1] ?? null;
  const prices = samples.map((sample) => finite(sample.mid_px) as number);
  const min = prices.length ? Math.min(...prices) : 0;
  const max = prices.length ? Math.max(...prices) : 1;
  const range = max - min || Math.max(max * 0.001, 1);
  const width = 760;
  const innerTop = 22;
  const innerBottom = height - 32;
  const innerHeight = Math.max(1, innerBottom - innerTop);
  const xStep = samples.length > 1 ? width / (samples.length - 1) : width;
  const points = samples
    .map((sample, index) => {
      const price = finite(sample.mid_px) as number;
      const x = samples.length > 1 ? index * xStep : width / 2;
      const y = innerBottom - ((price - min) / range) * innerHeight;
      return `${x.toFixed(2)},${y.toFixed(2)}`;
    })
    .join(' ');
  const status = data?.status ?? (loading ? 'Connecting' : 'Connecting stream');
  const statusCopy = chartStatusLabel(data?.status, loading);
  const freshClass = ageClass(ageSeconds, 10);
  const isCurrent = status === 'CURRENT' && !error && samples.length > 0;
  const sourceCopy = chartSourceLabel(data?.chart_source);

  return (
    <div
      className="v2-realtime-market-chart"
      data-testid="v2-realtime-market-chart"
      data-symbol={symbol}
      data-source-type={data?.source_type ?? 'EXISTING_WEBSOCKET_RUNTIME_FEED'}
    >
      <div className="v2-realtime-market-chart__head">
        <div>
          <span>{symbol} / {timeframe}</span>
          <strong>{money(latest?.mid_px)}</strong>
          <small>
            {sourceCopy}
          </small>
        </div>
        <div className="v2-realtime-market-chart__chips">
          <span className={`chip solid-${isCurrent ? 'ok' : 'warn'}`}>{statusCopy}</span>
          <span className={`chip solid-${freshClass}`}>{fmtAge(ageSeconds)}</span>
          <span className="chip solid-paper">Live chart</span>
        </div>
      </div>

      {error ? (
        <div className="v2-realtime-market-chart__empty" role="status">
          Market chart stream is connecting.
        </div>
      ) : samples.length > 0 ? (
        <svg
          className="v2-realtime-market-chart__svg"
          viewBox={`0 0 ${width} ${height}`}
          role="img"
          aria-label={`${symbol} realtime V2 market chart`}
        >
          <rect x="0" y="0" width={width} height={height} rx="6" />
          <line x1="0" x2={width} y1={innerTop} y2={innerTop} className="chart-grid-line" />
          <line x1="0" x2={width} y1={(innerTop + innerBottom) / 2} y2={(innerTop + innerBottom) / 2} className="chart-grid-line" />
          <line x1="0" x2={width} y1={innerBottom} y2={innerBottom} className="chart-grid-line" />
          <polyline points={points} className="chart-live-line" />
          {samples.slice(-24).map((sample, offset) => {
            const absoluteIndex = samples.length - Math.min(samples.length, 24) + offset;
            const price = finite(sample.mid_px) as number;
            const x = samples.length > 1 ? absoluteIndex * xStep : width / 2;
            const y = innerBottom - ((price - min) / range) * innerHeight;
            return <circle key={`${sample.received_ts_ms}-${offset}`} cx={x} cy={y} r="2.5" className="chart-live-dot" />;
          })}
          <text x="12" y="20">{money(max)}</text>
          <text x="12" y={height - 10}>{money(min)}</text>
        </svg>
      ) : (
        <div className="v2-realtime-market-chart__empty" role="status">
          Market chart stream connecting: {data?.blocker ? chartStatusLabel(data.blocker, false) : 'current market-price samples are connecting.'}
        </div>
      )}

      <div className="v2-realtime-market-chart__meta">
        <span>samples {data?.sample_count ?? samples.length}</span>
        <span>bid {money(latest?.best_bid_px)}</span>
        <span>ask {money(latest?.best_ask_px)}</span>
        <span>spread {finite(latest?.spread) === null ? 'Connecting stream' : `${(finite(latest?.spread) as number).toFixed(6)}`}</span>
        <span>event {shortTs(latest?.event_ts_ms)}</span>
        <span>source age {data?.source_event_age_seconds == null ? 'Connecting stream' : `${data.source_event_age_seconds}s`}</span>
      </div>
    </div>
  );
}
