import { useState } from 'react';
import { BarChart3, BookOpen, Activity, ListChecks, FileText, Wifi } from 'lucide-react';
import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import { useTraderSnapshot } from '../../hooks/useTraderSnapshot';
import { CanonicalMetricValue } from '../data/CanonicalMetric';
import { LivePnlStrip } from './LivePnlStrip';
import { MarketDepthPanel } from './MarketDepthPanel';
import { OrderBookPanel } from './OrderBookPanel';
import { PaperOrderTicket } from './PaperOrderTicket';
import { RecentTradesTape } from './RecentTradesTape';
import { SymbolHeader } from './SymbolHeader';
import { TradeBottomTabs } from './TradeBottomTabs';
import { TradeExecutionReadinessPanel } from './TradeExecutionReadinessPanel';
import { TradeIntelligenceBar } from './TradeIntelligenceBar';
import { TradingChartPanel } from './TradingChartPanel';
import { AdaptiveCapitalTelemetryPanel } from '../trading/AdaptiveCapitalTelemetryPanel';
import { useAdaptiveCapitalDashboard } from '../../data/adaptiveCapitalProductivity';
import { selectAccountMetric, selectSectionMetric, type CanonicalMetric } from '../../selectors/accountSelectors';
import { selectMarketBySymbol, selectMarketMetric } from '../../selectors/marketSelectors';
import { selectActiveSignal, selectSignalMetric } from '../../selectors/signalSelectors';
import { selectRiskStatus } from '../../selectors/riskSelectors';

const MOBILE_MODULES = [
  { key: 'chart', label: 'Chart', Icon: BarChart3 },
  { key: 'book', label: 'Book', Icon: BookOpen },
  { key: 'ticket', label: 'Ticket', Icon: Activity },
  { key: 'positions', label: 'Positions', Icon: ListChecks },
  { key: 'evidence', label: 'Evidence', Icon: FileText },
] as const;

type MobileModule = (typeof MOBILE_MODULES)[number]['key'];

interface PaperSummary {
  open_position_count?: number;
  realized_pnl_usd?: number | null;
  unrealized_pnl_usd?: number | null;
  total_open_notional?: number | null;
  paper_signals_seen?: number | null;
}

export function TradeTerminal(): JSX.Element {
  const state = useTradeTerminal();
  const traderSnapshot = useTraderSnapshot();
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const [mobileModule, setMobileModule] = useState<MobileModule>('chart');

  const paper = state.paper.activity.summary as PaperSummary | undefined;
  const accountMetric = (fieldId: string) => selectAccountMetric(traderSnapshot, fieldId);
  const selectedMarket = selectMarketBySymbol(traderSnapshot, state.symbol) ?? {};
  const marketMetric = (fieldId: string) => selectMarketMetric(traderSnapshot, selectedMarket, fieldId);
  const canonicalSignal = selectActiveSignal(traderSnapshot, state.symbol);
  // The trader-realtime snapshot only carries the published signal row(s) (BTCUSDT 5m
  // today); any other selected symbol resolves null there. Fall back to the page's own
  // symbol-scoped /api/v2/signals payload (state.signal), which the header above already
  // renders, so the account strip and the header can never disagree.
  const signalFallbackRow: Record<string, unknown> = {
    direction: state.signal.direction !== 'Signal connecting' ? state.signal.direction : null,
    confidence: state.signal.confidence,
  };
  const signalMetric = (fieldId: string) => selectSignalMetric(traderSnapshot, canonicalSignal ?? signalFallbackRow, fieldId);
  // Same never-disagree rule as the signal cells above, applied to prices: the
  // SymbolHeader renders the live market lane (stream merged over /api/v2 market
  // detail), while the trader-snapshot market row is a slower poll lane — the two
  // visibly diverge for the same symbol on the same screen. Prefer the live-lane
  // value in the strip and only fall back to the snapshot row when the live lane
  // has no value, so the strip and the header can never disagree.
  const livePriceMetric = (metric: CanonicalMetric, liveValue: unknown): CanonicalMetric => {
    if (typeof liveValue !== 'number' || !Number.isFinite(liveValue)) return metric;
    return {
      ...metric,
      value: liveValue,
      source: state.market.sources.ticker ?? metric.source,
      sourceType: 'realtime_market_lane',
      timestamp: null,
      ageMs: null,
      quality: 'valid',
    };
  };
  const riskMetric = selectSectionMetric(
    traderSnapshot,
    'risk',
    'position.risk_status',
    selectRiskStatus(traderSnapshot),
  );

  const dataLoading = state.paper.loading && !paper;
  const pollPulse = state.paper.connected || state.paper.source === 'http_fallback';

  const pnlColor = (v: number | null) =>
    v != null ? (v >= 0 ? 'var(--buy)' : 'var(--sell)') : undefined;

  return (
    <article className="trade-terminal" data-testid="page-trader" data-mobile-active={mobileModule}>
      <SymbolHeader state={state} />

      {/* Realtime data status banner */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8,
        padding: '5px 16px',
        background: dataLoading ? 'color-mix(in oklch, var(--warn) 10%, var(--bg-panel))' : 'var(--bg-panel)',
        borderBottom: '1px solid var(--border)',
        fontSize: 11, color: dataLoading ? 'var(--warn)' : 'var(--text-muted)',
        fontFamily: 'var(--font-mono)',
      }}>
        <Wifi size={11} aria-hidden="true" style={{ color: pollPulse ? 'var(--buy)' : dataLoading ? 'var(--warn)' : 'var(--text-muted)' }} />
        {dataLoading
          ? 'Realtime data loading... connecting to execution runtime'
          : `Realtime data · execution runtime · ${state.paper.connected ? 'WebSocket stream' : 'HTTP fallback'} · ${state.symbols.length} symbols`}
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
          {state.market.lastPrice ? `${state.symbol} $${state.market.lastPrice.toFixed(2)}` : state.symbol}
        </span>
      </div>

      {/* Live PnL trend - accumulates from the same paper stream as the strip below */}
      <LivePnlStrip
        totalPnl={
          paper?.realized_pnl_usd != null || paper?.unrealized_pnl_usd != null
            ? (paper?.realized_pnl_usd ?? 0) + (paper?.unrealized_pnl_usd ?? 0)
            : null
        }
        realizedPnl={paper?.realized_pnl_usd ?? null}
        unrealizedPnl={paper?.unrealized_pnl_usd ?? null}
        openNotional={paper?.total_open_notional ?? null}
        connected={state.paper.connected}
      />

      {/* Account KPI strip - canonical trader snapshot source */}
      <section className="trade-account-strip" aria-label="Account status">
        <div>
          <span>Account Balance</span>
          <strong style={{ color: 'var(--buy)' }}>
            <CanonicalMetricValue
              metric={accountMetric('account.available_balance')}
              emptyText="Paper balance unavailable; live signed account not read"
            />
          </strong>
        </div>
        <div>
          <span>Realized PnL</span>
          <strong style={{ color: pnlColor(accountMetric('account.realized_pnl').value as number | null) }}>
            <CanonicalMetricValue metric={accountMetric('account.realized_pnl')} />
          </strong>
        </div>
        <div>
          <span>Unrealized PnL</span>
          <strong style={{ color: pnlColor(accountMetric('account.unrealized_pnl').value as number | null) }}>
            <CanonicalMetricValue metric={accountMetric('account.unrealized_pnl')} />
          </strong>
        </div>
        <div>
          <span>Exposure</span>
          <strong><CanonicalMetricValue metric={accountMetric('account.exposure')} /></strong>
        </div>
        <div>
          <span>Open Positions</span>
          <strong><CanonicalMetricValue metric={accountMetric('account.open_position_count')} /></strong>
        </div>
        <div>
          <span>AI Signal</span>
          <strong><CanonicalMetricValue metric={signalMetric('signal.direction')} /></strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong><CanonicalMetricValue metric={signalMetric('signal.confidence')} /></strong>
        </div>
        <div>
          <span>Risk Gate</span>
          <strong>
            <CanonicalMetricValue
              metric={riskMetric}
              emptyText="Fail-closed: no current risk record"
            />
          </strong>
        </div>
        <div>
          <span>Last Price</span>
          <strong><CanonicalMetricValue metric={livePriceMetric(marketMetric('market.last_price'), state.market.lastPrice)} /></strong>
        </div>
        <div>
          <span>Mark Price</span>
          <strong><CanonicalMetricValue metric={livePriceMetric(marketMetric('market.mark_price'), state.market.markPrice)} /></strong>
        </div>
        <div>
          <span>Index Price</span>
          <strong><CanonicalMetricValue metric={livePriceMetric(marketMetric('market.index_price'), state.market.indexPrice)} /></strong>
        </div>
        <div>
          <span>Mode</span>
          <strong><CanonicalMetricValue metric={accountMetric('account.mode')} /></strong>
        </div>
        <div>
          <span>Account</span>
          <strong>{state.trader.accountLabel}</strong>
        </div>
      </section>

      <div style={{ padding: '0 16px 10px' }}>
        <AdaptiveCapitalTelemetryPanel
          payload={adaptiveCapital.data}
          title="Capital Productivity + PnL + Accuracy"
          compact
          showMatrix
          maxMatrixHeight={160}
        />
      </div>

      {/* Orchestrator / Risk / Trainer intelligence strip */}
      <TradeIntelligenceBar state={state} />
      <TradeExecutionReadinessPanel state={state} />

      <nav className="trade-mobile-switcher" aria-label="Trade modules">
        {MOBILE_MODULES.map(({ key, label, Icon }) => (
          <button
            type="button"
            className={mobileModule === key ? 'is-active' : ''}
            onClick={() => setMobileModule(key)}
            key={key}
          >
            <Icon size={15} aria-hidden="true" />
            {label}
          </button>
        ))}
      </nav>

      <section className="trade-terminal__workspace">
        <div className="trade-terminal__main">
          <TradingChartPanel symbol={state.symbol} />
          <TradeBottomTabs
            state={state}
            mobileFocus={mobileModule === 'evidence' ? 'evidence' : mobileModule === 'positions' ? 'positions' : undefined}
          />
        </div>
        <aside className="trade-terminal__side" aria-label="Trading column">
          <OrderBookPanel state={state} />
          <MarketDepthPanel state={state} />
          <RecentTradesTape state={state} />
          <PaperOrderTicket state={state} />
        </aside>
      </section>
    </article>
  );
}
