/**
 * Symbol Intelligence section for the market detail page.
 *
 * Renders every per-symbol intelligence surface the V2 ingestors produce —
 * microstructure trust, whale walls, alt-data scores, HTF context, regime
 * gates, liquidation levels, cross-venue comparison, opportunity — from the
 * consolidated /api/v2/market/{symbol}/intel endpoint (WebSocket-streamed).
 * A surface that is truly absent in Redis is shown as missing with its
 * source key, never silently hidden.
 */
import { useMemo } from 'react';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';

const SERIES = ['#219E94', '#8B6EFF', '#CC7D22', '#C95F84', '#4E92DE', '#41AC7C'] as const;
const UP = 'var(--buy, #21C784)';
const DOWN = 'var(--sell, #FF5D7A)';
const WARN = 'var(--warn, #FFB547)';
const MUTED = 'var(--text-muted, #94A3B8)';

interface IntelSection {
  data: Record<string, unknown> | null;
  source_key: string;
  age_seconds: number | null;
  present: boolean;
}

interface SymbolIntelData {
  symbol: string;
  sections: Record<string, IntelSection>;
  present_count: number;
  section_count: number;
}

function num(value: unknown): number | null {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string') {
    const parsed = Number(value);
    if (Number.isFinite(parsed)) return parsed;
  }
  return null;
}

function bpsToPct(value: unknown): number | null {
  const parsed = num(value);
  return parsed === null ? null : parsed / 100;
}

function fmtAge(seconds: number | null): string {
  if (seconds == null) return 'age unknown';
  if (seconds < 90) return `${Math.round(seconds)}s ago`;
  if (seconds < 5400) return `${Math.round(seconds / 60)}m ago`;
  return `${(seconds / 3600).toFixed(1)}h ago`;
}

function AgeChip({ section }: { section: IntelSection | undefined }): JSX.Element {
  if (!section?.present) {
    return <span style={{ fontSize: 10, color: DOWN, fontFamily: 'var(--font-mono)' }}>no data in Redis</span>;
  }
  const fresh = section.age_seconds != null && section.age_seconds < 300;
  return (
    <span style={{ fontSize: 10, color: fresh ? 'var(--buy)' : WARN, fontFamily: 'var(--font-mono)' }}>
      {fmtAge(section.age_seconds)}
    </span>
  );
}

function IntelCard({
  title,
  section,
  children,
}: {
  title: string;
  section: IntelSection | undefined;
  children?: React.ReactNode;
}): JSX.Element {
  return (
    <div
      style={{
        background: 'var(--bg-panel)',
        border: '1px solid var(--border)',
        borderRadius: 'var(--radius-md, 10px)',
        padding: '13px 15px',
        minWidth: 0,
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 8, gap: 8 }}>
        <span style={{ fontSize: 12, fontWeight: 600, color: 'var(--text-secondary)' }}>{title}</span>
        <AgeChip section={section} />
      </div>
      {section?.present ? (
        children
      ) : (
        <p style={{ margin: 0, fontSize: 11, color: MUTED, fontFamily: 'var(--font-mono)', overflowWrap: 'anywhere' }}>
          {section?.source_key ?? 'source key unknown'}
        </p>
      )}
    </div>
  );
}

function ScoreBar({ label, value, max = 1, color = SERIES[0] }: { label: string; value: number | null; max?: number; color?: string }): JSX.Element {
  const ratio = value != null ? Math.min(Math.max(value / max, 0), 1) : 0;
  return (
    <div style={{ marginBottom: 7 }}>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, marginBottom: 2 }}>
        <span style={{ color: MUTED }}>{label}</span>
        <span style={{ color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
          {value != null ? value.toFixed(3) : '—'}
        </span>
      </div>
      <div style={{ height: 5, borderRadius: 3, background: 'var(--bg-elevated)' }}>
        <div style={{ width: `${ratio * 100}%`, height: 5, borderRadius: 3, background: color }} />
      </div>
    </div>
  );
}

function Chip({ text, tone }: { text: string; tone: 'up' | 'down' | 'warn' | 'muted' }): JSX.Element {
  const color = tone === 'up' ? UP : tone === 'down' ? DOWN : tone === 'warn' ? WARN : MUTED;
  return (
    <span
      style={{
        display: 'inline-block',
        padding: '2px 8px',
        borderRadius: 999,
        border: `1px solid ${color}`,
        color,
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: '0.04em',
      }}
    >
      {text}
    </span>
  );
}

function fmtCompactUsd(value: number): string {
  const abs = Math.abs(value);
  if (abs >= 1_000_000) return `$${(value / 1_000_000).toFixed(2)}M`;
  if (abs >= 1_000) return `$${(value / 1_000).toFixed(1)}K`;
  return `$${value.toLocaleString(undefined, { maximumFractionDigits: 0 })}`;
}

function MiniHorizontalBars({
  rows,
}: {
  rows: Array<{ name: string; value: number; color: string }>;
}): JSX.Element {
  const max = rows.reduce((best, row) => Math.max(best, Math.abs(row.value)), 0);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
      {rows.map((row) => {
        const width = max > 0 ? Math.max(4, Math.min(100, (Math.abs(row.value) / max) * 100)) : 0;
        return (
          <div key={row.name}>
            <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8, marginBottom: 3 }}>
              <span style={{ fontSize: 10, color: MUTED }}>{row.name}</span>
              <span style={{ fontSize: 10, color: 'var(--text-primary)', fontFamily: 'var(--font-mono)' }}>
                {fmtCompactUsd(row.value)}
              </span>
            </div>
            <div style={{ height: 8, borderRadius: 4, background: 'var(--bg-elevated)', overflow: 'hidden' }}>
              <div style={{ width: `${width}%`, height: '100%', borderRadius: 4, background: row.color }} />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function SymbolIntelSection({ symbol }: { symbol: string }): JSX.Element {
  const intel = useRealtimeResource<SymbolIntelData>({
    url: `/api/v2/market/${symbol}/intel`,
    source: `/api/v2/market/${symbol}/intel`,
    source_type: 'websocket',
    pollIntervalMs: 5_000,
    staleThresholdMs: 30_000,
    mode: 'read_only',
    enabled: symbol.length > 0,
  });
  const data = intel.envelope.data;
  const sections = useMemo(() => data?.sections ?? {}, [data]);

  const tape = sections.microstructure_trade_tape;
  const crossVenue = sections.microstructure_cross_venue;
  const feedQuality = sections.microstructure_feed_quality;
  const whale = sections.whale_walls;
  const altScore = sections.altdata_symbol_score;
  const htf = sections.htf_context;
  const opportunity = sections.opportunity;
  const kucoin = sections.kucoin_cross_venue;
  const binance = sections.binance_prices;

  const tapeBars = useMemo(() => {
    const buy = num(tape?.data?.aggressive_buy_volume);
    const sell = num(tape?.data?.aggressive_sell_volume);
    if (buy == null && sell == null) return [];
    return [
      { name: 'Aggressive buy', value: buy ?? 0, color: UP },
      { name: 'Aggressive sell', value: sell ?? 0, color: DOWN },
    ];
  }, [tape]);

  // Zero-vs-missing honesty: when the payload declares its orderbook inputs
  // missing (missing_feature_flags), a "$0 wall" is unread input, not "no walls".
  const whaleMissingFlags = useMemo(
    () => ((whale?.data?.missing_feature_flags as string[] | undefined) ?? []).filter((f) => typeof f === 'string'),
    [whale],
  );

  const wallBars = useMemo(() => {
    const bidWall = whale?.data?.bid_wall_summary as Record<string, unknown> | undefined;
    const askWall = whale?.data?.ask_wall_summary as Record<string, unknown> | undefined;
    const bidMissing = whaleMissingFlags.includes('orderbook_bids_missing');
    const askMissing = whaleMissingFlags.includes('orderbook_asks_missing');
    const rows: Array<{ name: string; value: number; color: string }> = [];
    const bidNotional = num(bidWall?.max_single_wall_notional_usd);
    const askNotional = num(askWall?.max_single_wall_notional_usd);
    if (!bidMissing && bidNotional != null) rows.push({ name: 'Max bid wall $', value: bidNotional, color: UP });
    if (!askMissing && askNotional != null) rows.push({ name: 'Max ask wall $', value: askNotional, color: DOWN });
    const bidMarket = num(bidWall?.market_notional_usd);
    const askMarket = num(askWall?.market_notional_usd);
    if (!bidMissing && bidMarket != null) rows.push({ name: 'Bid book $', value: bidMarket, color: SERIES[0] });
    if (!askMissing && askMarket != null) rows.push({ name: 'Ask book $', value: askMarket, color: SERIES[3] });
    return rows;
  }, [whale, whaleMissingFlags]);

  const altScoreBars = useMemo(() => {
    const payload = altScore?.data ?? {};
    return Object.entries(payload)
      .filter(([key, value]) => /score$/i.test(key) && num(value) != null)
      .map(([key, value]) => ({ name: key.replace(/_score$/i, '').replace(/_/g, ' '), value: num(value) as number }))
      .sort((a, b) => b.value - a.value)
      .slice(0, 10);
  }, [altScore]);

  const binanceLast = useMemo(() => {
    const tickerPayload = binance?.data?.ticker_24hr as Record<string, unknown> | undefined;
    return num(tickerPayload?.lastPrice);
  }, [binance]);
  const kucoinLast = num(kucoin?.data?.last);
  const divergenceBps =
    binanceLast != null && kucoinLast != null && binanceLast > 0
      ? ((kucoinLast - binanceLast) / binanceLast) * 10_000
      : null;

  const htfTrend = String(htf?.data?.htf_4h_trend ?? '');
  const htfRsi = num(htf?.data?.htf_4h_rsi_14);
  const oppClass = String(opportunity?.data?.opportunity_class ?? '');
  const failReasons = (feedQuality?.data?.fail_reasons as string[] | undefined) ?? [];

  return (
    <div className="mdc-panel" data-testid="market-intel-section">
      <div className="mdc-panel__head">
        <span className="mdc-panel__eyebrow">Intelligence</span>
        <h2>Symbol Intelligence</h2>
        <span style={{ fontSize: 11, color: MUTED, fontFamily: 'var(--font-mono)' }}>
          {data ? `${data.present_count}/${data.section_count} surfaces live` : 'connecting…'}
        </span>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(280px, 1fr))', gap: 12 }}>
        <IntelCard title="Trade tape pressure" section={tape}>
          {tapeBars.length > 0 && (
            <MiniHorizontalBars rows={tapeBars} />
          )}
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 6 }}>
            {tape?.data?.basis_confirmation != null && (
              <Chip text={`BASIS ${tape.data.basis_confirmation ? 'OK' : 'DIVERGED'}`} tone={tape.data.basis_confirmation ? 'up' : 'down'} />
            )}
            {tape?.data?.large_trade_cluster != null && (
              <Chip text={`${String(tape.data.large_trade_cluster)} LARGE CLUSTERS`} tone="muted" />
            )}
          </div>
        </IntelCard>

        <IntelCard title="Microstructure trust" section={crossVenue}>
          <ScoreBar label="Cross-venue confirmation" value={num(crossVenue?.data?.cross_venue_confirmation_score)} color={SERIES[0]} />
          <ScoreBar label="Depth disagreement" value={num(crossVenue?.data?.depth_disagreement_score)} color={SERIES[2]} />
          <ScoreBar label="Book/trade divergence" value={num(tape?.data?.book_trade_divergence_score)} color={SERIES[1]} />
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginTop: 4 }}>
            <Chip
              text={String(crossVenue?.data?.lead_lag_classification ?? 'unknown').replace(/_/g, ' ').toUpperCase()}
              tone={crossVenue?.data?.kucoin_present ? 'up' : 'warn'}
            />
            {failReasons.length > 0 ? (
              <Chip text={`FEED: ${failReasons[0].replace(/_/g, ' ')}`} tone="warn" />
            ) : feedQuality?.present ? (
              <Chip text="FEED QUALITY OK" tone="up" />
            ) : null}
          </div>
        </IntelCard>

        <IntelCard title="Whale walls" section={whale}>
          {whaleMissingFlags.length > 0 && (
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: wallBars.length > 0 ? 6 : 0 }}>
              {whaleMissingFlags.map((flag) => (
                <Chip key={flag} text={flag.replace(/_/g, ' ').toUpperCase()} tone="warn" />
              ))}
            </div>
          )}
          {wallBars.length > 0 && (
            <MiniHorizontalBars rows={wallBars} />
          )}
        </IntelCard>

        <IntelCard title="Alt-data scores" section={altScore}>
          {altScoreBars.map((row, index) => (
            <ScoreBar key={row.name} label={row.name} value={row.value} color={SERIES[index % SERIES.length]} />
          ))}
        </IntelCard>

        <IntelCard title="Higher-timeframe context" section={htf}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {htfTrend && <Chip text={`4H TREND ${htfTrend}`} tone={htfTrend === 'UP' ? 'up' : htfTrend === 'DOWN' ? 'down' : 'muted'} />}
            {htf?.data?.htf_4h_rsi_zone != null && <Chip text={String(htf.data.htf_4h_rsi_zone)} tone="muted" />}
          </div>
          <ScoreBar label="RSI(14) 4h" value={htfRsi} max={100} color={htfRsi != null && (htfRsi > 70 || htfRsi < 30) ? WARN : SERIES[4]} />
          <ScoreBar label="EMA50 delta % (4h)" value={num(htf?.data?.htf_4h_ema50_delta_pct)} max={10} color={SERIES[5]} />
        </IntelCard>

        <IntelCard title="Cross-venue price" section={kucoin}>
          <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 8, marginBottom: 8 }}>
            <div>
              <div style={{ fontSize: 10, color: MUTED }}>BINANCE</div>
              <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {binanceLast != null ? binanceLast.toLocaleString() : '—'}
              </div>
            </div>
            <div>
              <div style={{ fontSize: 10, color: MUTED }}>KUCOIN</div>
              <div style={{ fontSize: 16, fontWeight: 700, fontFamily: 'var(--font-mono)', color: 'var(--text-primary)' }}>
                {kucoinLast != null ? kucoinLast.toLocaleString() : '—'}
              </div>
            </div>
          </div>
          <Chip
            text={divergenceBps != null ? `DIVERGENCE ${divergenceBps.toFixed(2)} BPS` : 'DIVERGENCE UNAVAILABLE'}
            tone={divergenceBps != null ? (Math.abs(divergenceBps) < 5 ? 'up' : 'warn') : 'muted'}
          />
        </IntelCard>

        <IntelCard title="Opportunity state" section={opportunity}>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            {oppClass && <Chip text={`CLASS ${oppClass}`} tone={oppClass === 'HIGH' ? 'up' : oppClass === 'LOW' ? 'muted' : 'warn'} />}
            {opportunity?.data?.position_state != null && (
              <Chip text={String(opportunity.data.position_state).replace(/_/g, ' ')} tone="muted" />
            )}
          </div>
          <ScoreBar label="Opportunity score" value={num(opportunity?.data?.score)} color={SERIES[0]} />
          <ScoreBar label="MFE %" value={bpsToPct(opportunity?.data?.mfe_bps)} max={1} color={UP} />
          <ScoreBar label="MAE %" value={bpsToPct(opportunity?.data?.mae_bps)} max={1} color={DOWN} />
        </IntelCard>
      </div>
    </div>
  );
}
