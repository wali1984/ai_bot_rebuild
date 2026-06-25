import { useMemo } from 'react';
import { Link } from 'react-router-dom';
import {
  formatAdaptiveMoney,
  missingAccuracyCellCount,
  pnlWindow,
  useAdaptiveCapitalDashboard,
} from '../../data/adaptiveCapitalProductivity';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
import { AdaptiveCapitalTelemetryPanel } from '../trading/AdaptiveCapitalTelemetryPanel';
import { DataFreshnessBadge, MetricCard, StatusPill } from '../trading/TradingPrimitives';
import type { MarketCandlesData, MarketCandle, MarketTickerData, PortfolioData, PositionsData, SignalData, AccountReadinessData } from '../../types/apiV2';
import type { ValidatedDataEnvelope } from '../../types/dataContract';
import type { MarketOverviewData } from '../../api/v2Market';

const DASHBOARD_SYMBOLS = ['BTCUSDT', 'ETHUSDT', 'SOLUSDT'] as const;

type DashboardEnvelope<T> = ValidatedDataEnvelope<T>;
type TickerEnvelope = DashboardEnvelope<MarketTickerData>;
type SignalEnvelope = DashboardEnvelope<SignalData>;
type PortfolioEnvelope = DashboardEnvelope<PortfolioData>;
type PositionsEnvelope = DashboardEnvelope<PositionsData>;

function formatMoney(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Connecting';
  return `$${value.toLocaleString('en-US', { maximumFractionDigits: value > 100 ? 2 : 4 })}`;
}

function formatSignedMoney(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Connecting';
  return `${value >= 0 ? '+' : '-'}${formatMoney(Math.abs(value))}`;
}

function formatPercent(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Connecting';
  const pct = Math.abs(value) <= 1 ? value * 100 : value;
  return `${pct >= 0 ? '+' : ''}${pct.toFixed(2)}%`;
}

function compactNumber(value: number | null | undefined): string {
  if (typeof value !== 'number' || !Number.isFinite(value)) return 'Connecting';
  return Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 2 }).format(value);
}

function envelopeUsable(envelope: DashboardEnvelope<unknown> | null | undefined): boolean {
  return Boolean(
    envelope?.data
    && envelope.source_type !== 'unavailable'
    && envelope.freshness_status !== 'offline'
    && envelope.freshness_status !== 'unavailable'
    && envelope.freshness_status !== 'stale'
    && envelope.data_quality_status !== 'invalid'
    && envelope.data_quality_status !== 'missing',
  );
}

function freshnessTimestamp(envelope: DashboardEnvelope<unknown> | null | undefined): string | null {
  const value = envelope?.timestamp ?? envelope?.received_at;
  if (typeof value !== 'number' || !Number.isFinite(value)) return null;
  return new Date(value).toISOString();
}

function sourceName(envelope: DashboardEnvelope<unknown> | null | undefined, fallback: string): string {
  if (!envelope) return fallback;
  if (envelope.source_type === 'unavailable') return `${fallback} incident`;
  const source = envelope.source?.toLowerCase() ?? '';
  if (envelope.source_type === 'websocket') return `${fallback} stream`;
  if (source.includes('binance')) return 'Exchange market feed';
  if (source.includes('redis')) return 'Realtime cache';
  if (source.includes('portfolio')) return 'Runtime account service';
  if (source.includes('signal')) return 'Signal service';
  return fallback;
}

function activeSignal(signal: SignalEnvelope | null): Record<string, unknown> | null {
  if (!envelopeUsable(signal)) return null;
  const candidate = signal?.data?.active_signal;
  return candidate && typeof candidate === 'object' && !Array.isArray(candidate) ? candidate : null;
}

function firstText(...values: unknown[]): string | null {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.replaceAll('_', ' ');
  }
  return null;
}

function firstNumber(...values: unknown[]): number | null {
  for (const value of values) {
    if (typeof value === 'number' && Number.isFinite(value)) return value;
    if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  }
  return null;
}

function candleValue(candle: MarketCandle, key: 'open' | 'high' | 'low' | 'close'): number | null {
  const value = candle[key];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

function CandleStrip({ candles }: { candles: MarketCandle[] }): JSX.Element {
  const rows = candles.slice(-44);
  const values = rows.flatMap((candle) => [candleValue(candle, 'high'), candleValue(candle, 'low')]).filter((value): value is number => value !== null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const range = Number.isFinite(max - min) && max > min ? max - min : 1;

  return (
    <div className="trader-dashboard-chart__candles" aria-label="BTC 5m candlestick preview">
      {rows.map((candle, index) => {
        const open = candleValue(candle, 'open') ?? candleValue(candle, 'close') ?? min;
        const close = candleValue(candle, 'close') ?? open;
        const high = candleValue(candle, 'high') ?? Math.max(open, close);
        const low = candleValue(candle, 'low') ?? Math.min(open, close);
        const top = ((max - high) / range) * 100;
        const height = Math.max(6, ((high - low) / range) * 100);
        const bodyTop = ((max - Math.max(open, close)) / range) * 100;
        const bodyHeight = Math.max(4, (Math.abs(close - open) / range) * 100);
        const up = close >= open;
        return (
          <span className={`trader-candle trader-candle--${up ? 'up' : 'down'}`} key={`${candle.time ?? candle.open_time_ms ?? index}-${index}`}>
            <i className="trader-candle__wick" style={{ top: `${top}%`, height: `${height}%` }} />
            <i className="trader-candle__body" style={{ top: `${bodyTop}%`, height: `${bodyHeight}%` }} />
          </span>
        );
      })}
    </div>
  );
}

function MarketPulseCard({ symbol, envelope }: { symbol: string; envelope?: TickerEnvelope }): JSX.Element {
  const data = envelopeUsable(envelope) ? envelope?.data : null;
  const change = data?.change_24h ?? data?.change_4h ?? data?.change_1h;
  const up = typeof change === 'number' ? change >= 0 : true;
  return (
    <Link className={`trader-market-pulse-card trader-market-pulse-card--${up ? 'up' : 'down'}`} to={`/market/${symbol}`}>
      <span>{symbol.replace('USDT', '')}</span>
      <strong>{formatMoney(data?.last_price ?? data?.mark_price)}</strong>
      <small>{formatPercent(change)} · {sourceName(envelope, 'Market feed')}</small>
    </Link>
  );
}

export function TraderDashboard(): JSX.Element {
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const { envelope: overview } = useRealtimeResource<MarketOverviewData>({
    url: '/api/v2/market/overview',
    source: 'dashboard market overview',
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 20_000,
    mode: 'public',
  });
  const { envelope: btcTicker } = useRealtimeResource<MarketTickerData>({
    url: '/api/v2/market/BTCUSDT/ticker',
    source: 'BTCUSDT dashboard ticker',
    source_type: 'websocket',
    pollIntervalMs: 1_000,
    staleThresholdMs: 10_000,
    mode: 'public',
  });
  const { envelope: ethTicker } = useRealtimeResource<MarketTickerData>({
    url: '/api/v2/market/ETHUSDT/ticker',
    source: 'ETHUSDT dashboard ticker',
    source_type: 'websocket',
    pollIntervalMs: 1_000,
    staleThresholdMs: 10_000,
    mode: 'public',
  });
  const { envelope: solTicker } = useRealtimeResource<MarketTickerData>({
    url: '/api/v2/market/SOLUSDT/ticker',
    source: 'SOLUSDT dashboard ticker',
    source_type: 'websocket',
    pollIntervalMs: 1_000,
    staleThresholdMs: 10_000,
    mode: 'public',
  });
  const { envelope: candles } = useRealtimeResource<MarketCandlesData>({
    url: '/api/v2/market/BTCUSDT/candles?timeframe=5m',
    source: 'BTCUSDT dashboard candles',
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 20_000,
    mode: 'public',
  });
  const { envelope: signal } = useRealtimeResource<SignalData>({
    url: '/api/v2/signals?symbol=BTCUSDT',
    source: 'BTCUSDT dashboard signal',
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
  });
  const { envelope: portfolio } = useRealtimeResource<PortfolioData>({
    url: '/api/v2/portfolio',
    source: 'dashboard portfolio stream',
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
  });
  const { envelope: positions } = useRealtimeResource<PositionsData>({
    url: '/api/v2/account/positions',
    source: 'dashboard position stream',
    source_type: 'websocket',
    pollIntervalMs: 2_000,
    staleThresholdMs: 20_000,
    mode: 'paper',
  });
  const { envelope: accountReadiness } = useRealtimeResource<AccountReadinessData>({
    url: '/api/v2/account/readiness',
    source: 'dashboard account readiness stream',
    source_type: 'websocket',
    pollIntervalMs: 5_000,
    staleThresholdMs: 30_000,
    mode: 'paper',
  });
  const tickers: Record<(typeof DASHBOARD_SYMBOLS)[number], TickerEnvelope> = {
    BTCUSDT: btcTicker,
    ETHUSDT: ethTicker,
    SOLUSDT: solTicker,
  };

  const currentSignal = activeSignal(signal);
  const signalDirection = firstText(currentSignal?.direction, currentSignal?.trend, currentSignal?.selected_action, currentSignal?.action) ?? 'Signal stream warming';
  const confidence = firstNumber(currentSignal?.confidence, currentSignal?.model_confidence, currentSignal?.score);
  const marketRegime = firstText(currentSignal?.market_regime, currentSignal?.regime, currentSignal?.trend) ?? 'Market regime monitored';
  const portfolioData = envelopeUsable(portfolio) ? portfolio.data : null;
  const positionRows = envelopeUsable(positions) ? positions.data?.positions ?? [] : [];
  const totalPnl = (portfolioData?.realized_pnl ?? 0) + (portfolioData?.unrealized_pnl ?? 0);
  const capitalStatus = adaptiveCapital.data?.capital_productivity_runtime_status ?? null;
  const pnlHistory = adaptiveCapital.data?.pnl_history_status ?? capitalStatus?.pnl_history ?? null;
  const oneDayPnl = pnlWindow(pnlHistory, '1d');
  const sevenDayPnl = pnlWindow(pnlHistory, '7d');
  const thirtyDayPnl = pnlWindow(pnlHistory, '30d');
  const accuracyStatus = adaptiveCapital.data?.signal_prediction_accuracy_status
    ?? capitalStatus?.signal_prediction_accuracy_status
    ?? null;
  const missingAccuracyCells = missingAccuracyCellCount(accuracyStatus);
  const dataReadyCount = [
    envelopeUsable(overview),
    Object.values(tickers).some((ticker) => envelopeUsable(ticker)),
    envelopeUsable(candles),
    envelopeUsable(signal),
    envelopeUsable(portfolio),
    envelopeUsable(positions),
  ].filter(Boolean).length;

  const chartCandles = useMemo(() => candles?.data?.candles?.filter((candle) => candle.is_final !== false) ?? [], [candles]);

  return (
    <article className="trader-dashboard-page" data-testid="page-dashboard">
      <header className="trader-dashboard-hero">
        <div>
          <p className="eyebrow">Trader command center</p>
          <h1>Trading dashboard</h1>
          <p>
            Portfolio state, active signal context, BTC/ETH/SOL market pulse, and freshness evidence in one trader-facing view.
            Execution is governed by the account risk controls.
          </p>
        </div>
        <div className="trader-dashboard-hero__actions">
          <StatusPill tone="ok">Realtime data</StatusPill>
          <StatusPill tone="warn">Risk governed</StatusPill>
          <DataFreshnessBadge generatedAt={freshnessTimestamp(overview)} source={sourceName(overview, 'Market overview')} staleAfterSeconds={120} />
        </div>
      </header>

      <section className="trader-dashboard-kpis" aria-label="Dashboard KPIs">
        <MetricCard label="Account equity" value={formatMoney(portfolioData?.equity)} detail={sourceName(portfolio, 'Trading account')} tone={portfolioData ? 'ok' : 'warn'} />
        <MetricCard label="Today PnL" value={formatSignedMoney(totalPnl)} detail="Realized plus unrealized account PnL" tone={totalPnl >= 0 ? 'ok' : 'block'} />
        <MetricCard label="1D PnL" value={formatAdaptiveMoney(oneDayPnl?.realized_pnl_usd)} detail={`${oneDayPnl?.closed_trade_count ?? 0} closes`} tone={(oneDayPnl?.realized_pnl_usd ?? 0) >= 0 ? 'ok' : 'block'} />
        <MetricCard label="1W PnL" value={formatAdaptiveMoney(sevenDayPnl?.realized_pnl_usd)} detail={`${sevenDayPnl?.closed_trade_count ?? 0} closes`} tone={(sevenDayPnl?.realized_pnl_usd ?? 0) >= 0 ? 'ok' : 'block'} />
        <MetricCard label="30D PnL" value={formatAdaptiveMoney(thirtyDayPnl?.realized_pnl_usd)} detail={`${thirtyDayPnl?.closed_trade_count ?? 0} closes`} tone={(thirtyDayPnl?.realized_pnl_usd ?? 0) >= 0 ? 'ok' : 'block'} />
        <MetricCard
          label="Capital status"
          value={capitalStatus?.status ?? 'CONNECTING'}
          detail={capitalStatus?.capital_utilization_classification ?? 'Adaptive sizing'}
          tone={(capitalStatus?.status ?? '').toUpperCase() === 'PASSED' ? 'ok' : 'block'}
        />
        <MetricCard label="Active signal" value={signalDirection} detail={sourceName(signal, 'Signal source')} tone={currentSignal ? 'info' : 'warn'} />
        <MetricCard label="AI confidence" value={confidence === null ? 'Calibrating' : `${Math.round(confidence * 100)}%`} detail={marketRegime} tone={confidence === null ? 'warn' : 'ok'} />
        <MetricCard label="Open positions" value={positionRows.length} detail={sourceName(positions, 'Position source')} tone={positionRows.length ? 'info' : 'neutral'} />
        <MetricCard
          label="Accuracy cells"
          value={`${accuracyStatus?.evaluated_symbol_timeframe_cell_count ?? 0}/${accuracyStatus?.symbol_timeframe_cell_count ?? accuracyStatus?.required_symbol_timeframe_cell_count ?? 0}`}
          detail={`${missingAccuracyCells ?? 0} missing evaluated cells`}
          tone={(missingAccuracyCells ?? 0) > 0 ? 'block' : 'ok'}
        />
        <MetricCard label="Data status" value={`${dataReadyCount}/6 live`} detail={accountReadiness?.source_type === 'unavailable' ? 'Account readiness monitored' : 'Account readiness available'} tone={dataReadyCount >= 4 ? 'ok' : 'warn'} />
      </section>

      <AdaptiveCapitalTelemetryPanel
        payload={adaptiveCapital.data}
        title="Capital Productivity + PnL + Accuracy"
        compact
        showMatrix
        maxMatrixHeight={220}
      />

      <section className="trader-dashboard-grid">
        <div className="trader-dashboard-chart panel bracketed">
          <span className="br-bl" aria-hidden="true" />
          <span className="br-br" aria-hidden="true" />
          <div className="panel-head">
            <div>
              <p className="eyebrow">BTCUSDT 5m</p>
              <h2 className="panel-title">Market structure chart</h2>
            </div>
            <DataFreshnessBadge generatedAt={freshnessTimestamp(candles)} source={sourceName(candles, 'Candle service')} staleAfterSeconds={180} />
          </div>
          <CandleStrip candles={chartCandles} />
          <div className="trader-dashboard-chart__footer">
            <span>Closed candles only</span>
            <span>{chartCandles.length ? `${chartCandles.length} candles loaded` : 'Candle stream connecting'}</span>
          </div>
        </div>

        <aside className="trader-dashboard-signal panel">
          <div className="panel-head">
            <div>
              <p className="eyebrow">Current signal</p>
              <h2 className="panel-title">{signalDirection}</h2>
            </div>
            <StatusPill tone={currentSignal ? 'ok' : 'warn'}>{currentSignal ? 'Evidence ready' : 'Connecting'}</StatusPill>
          </div>
          <div className="trader-dashboard-signal__body">
            <div><span>Market regime</span><strong>{marketRegime}</strong></div>
            <div><span>Confidence</span><strong>{confidence === null ? 'Calibrating' : `${Math.round(confidence * 100)}%`}</strong></div>
            <div><span>Risk posture</span><strong>{firstText(currentSignal?.risk_status, currentSignal?.risk_decision, currentSignal?.status) ?? 'Risk monitored'}</strong></div>
            <div><span>Execution</span><strong>Execution staged</strong></div>
          </div>
          <Link className="trader-dashboard-link" to="/signals">Open signal evidence</Link>
        </aside>
      </section>

      <section className="trader-dashboard-lower-grid">
        <div className="panel trader-dashboard-market-pulse">
          <div className="panel-head">
            <h2 className="panel-title">Market pulse</h2>
            <span className="chip solid-loading">{overview?.data?.count ?? overview?.data?.symbols?.length ?? 'Connecting'} symbols</span>
          </div>
          <div className="trader-dashboard-market-pulse__cards">
            {DASHBOARD_SYMBOLS.map((symbol) => <MarketPulseCard key={symbol} symbol={symbol} envelope={tickers[symbol]} />)}
          </div>
        </div>

        <div className="panel trader-dashboard-positions">
          <div className="panel-head">
            <h2 className="panel-title">Live positions</h2>
            <DataFreshnessBadge generatedAt={freshnessTimestamp(positions)} source={sourceName(positions, 'Position source')} staleAfterSeconds={180} />
          </div>
          {positionRows.length ? (
            <div className="trader-dashboard-position-list">
              {positionRows.slice(0, 4).map((row, index) => (
                <div className="trader-dashboard-position" key={index}>
                  <span>{firstText((row as Record<string, unknown>).symbol) ?? `Position ${index + 1}`}</span>
                  <strong>{firstText((row as Record<string, unknown>).side, (row as Record<string, unknown>).direction) ?? 'Position'}</strong>
                  <small>{compactNumber(firstNumber((row as Record<string, unknown>).notional, (row as Record<string, unknown>).size))}</small>
                </div>
              ))}
            </div>
          ) : (
            <div className="trader-dashboard-empty">
              <strong>No open positions</strong>
              <span>Positions will appear here after trader-scoped execution activity is available.</span>
            </div>
          )}
        </div>
      </section>
    </article>
  );
}
