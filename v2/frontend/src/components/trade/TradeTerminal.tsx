import { useState } from 'react';
import { BarChart3, BookOpen, Activity, ListChecks, FileText, Wifi } from 'lucide-react';
import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import { formatMoney, formatPercent, formatPrice } from '../../lib/tradeFormatters';
import { tradeCopy } from '../../lib/tradeCopy';
import { MarketDepthPanel } from './MarketDepthPanel';
import { OrderBookPanel } from './OrderBookPanel';
import { PaperOrderTicket } from './PaperOrderTicket';
import { RecentTradesTape } from './RecentTradesTape';
import { SymbolHeader } from './SymbolHeader';
import { TradeBottomTabs } from './TradeBottomTabs';
import { TradeIntelligenceBar } from './TradeIntelligenceBar';
import { TradingChartPanel } from './TradingChartPanel';
import { AdaptiveCapitalTelemetryPanel } from '../trading/AdaptiveCapitalTelemetryPanel';
import { useAdaptiveCapitalDashboard } from '../../data/adaptiveCapitalProductivity';

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
  const adaptiveCapital = useAdaptiveCapitalDashboard(30_000);
  const [mobileModule, setMobileModule] = useState<MobileModule>('chart');

  const paper = state.paper.activity.summary as PaperSummary | undefined;
  const realizedPnl = paper?.realized_pnl_usd != null ? paper.realized_pnl_usd : null;
  const unrealizedPnl = paper?.unrealized_pnl_usd != null ? paper.unrealized_pnl_usd : state.account.unrealizedPnl;
  const openNotional = paper?.total_open_notional != null ? paper.total_open_notional : null;
  const openPositionCount = paper?.open_position_count != null ? paper.open_position_count : null;

  const paperBalance = state.account.availablePaperBalance ?? state.account.equity ?? (
    state.account.totalPnl != null ? 10_000 + state.account.totalPnl : null
  );

  const hasLiveSignal = state.signal.direction !== 'Signal connecting';
  const signalDirection = hasLiveSignal
    ? String(state.signal.direction).toUpperCase()
    : '—';
  const signalColor = hasLiveSignal
    ? signalDirection.includes('SHORT') ? 'var(--sell)' : 'var(--buy)'
    : undefined;

  const riskRaw = state.signal.paperFillAllowed
    ? 'Execution Fill Open'
    : tradeCopy(state.signal.riskDecision);
  const riskLabel = riskRaw;
  const riskColor = riskLabel.toLowerCase().includes('allow') || riskLabel === 'Execution Fill Open'
    ? 'var(--buy)'
    : riskLabel !== 'Risk result connecting' ? 'var(--sell)' : undefined;

  const dataLoading = state.paper.loading && !paper;
  const pollPulse = state.paper.connected || state.paper.source === 'http_fallback';

  const pnlColor = (v: number | null) =>
    v != null ? (v >= 0 ? 'var(--buy)' : 'var(--sell)') : undefined;

  return (
    <article className="trade-terminal" data-testid="page-trader" data-mobile-active={mobileModule}>
      <SymbolHeader state={state} />

      {/* Live data status banner */}
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
          ? 'Live data loading… connecting to execution engine'
          : `Live data · execution engine · ${state.paper.connected ? 'WebSocket stream' : 'HTTP fallback'} · ${state.symbols.length} symbols`}
        <span style={{ marginLeft: 'auto', color: 'var(--text-muted)' }}>
          {state.market.lastPrice ? `${state.symbol} $${state.market.lastPrice.toFixed(2)}` : state.symbol}
        </span>
      </div>

      {/* Account KPI strip — reads from Redis paper heartbeat */}
      <section className="trade-account-strip" aria-label="Account status">
        <div>
          <span>Account Balance</span>
          <strong style={{ color: paperBalance != null ? 'var(--buy)' : undefined }}>
            {paperBalance != null ? formatMoney(paperBalance) : '—'}
          </strong>
        </div>
        <div>
          <span>Realized PnL</span>
          <strong style={{ color: pnlColor(realizedPnl) }}>
            {realizedPnl !== null ? formatMoney(realizedPnl) : '—'}
          </strong>
        </div>
        <div>
          <span>Unrealized PnL</span>
          <strong style={{ color: pnlColor(unrealizedPnl) }}>
            {unrealizedPnl !== null ? formatMoney(unrealizedPnl) : '—'}
          </strong>
        </div>
        <div>
          <span>Open Notional</span>
          <strong>{openNotional !== null ? `$${openNotional.toFixed(0)}` : '—'}</strong>
        </div>
        <div>
          <span>Open Positions</span>
          <strong>{openPositionCount !== null ? String(openPositionCount) : '—'}</strong>
        </div>
        <div>
          <span>AI Signal</span>
          <strong style={{ color: signalColor }}>{signalDirection}</strong>
        </div>
        <div>
          <span>Confidence</span>
          <strong>{state.signal.confidence !== null ? formatPercent(state.signal.confidence) : '—'}</strong>
        </div>
        <div>
          <span>Risk Gate</span>
          <strong style={{ color: riskColor }}>{riskLabel}</strong>
        </div>
        <div>
          <span>Last Price</span>
          <strong>{formatPrice(state.market.lastPrice)}</strong>
        </div>
        <div>
          <span>Funding</span>
          <strong>{formatPercent(state.market.fundingRate)}</strong>
        </div>
        <div>
          <span>Mode</span>
          <strong>{tradeCopy(state.mode.traderState, 'Live platform')}</strong>
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
