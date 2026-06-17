import { useState } from 'react';
import { BarChart3, BookOpen, Activity, ListChecks, FileText } from 'lucide-react';
import { useTradeTerminal } from '../../hooks/useTradeTerminal';
import { useRealtimeResource } from '../../hooks/useRealtimeResource';
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
interface PaperStatusData { summary?: PaperSummary }

export function TradeTerminal(): JSX.Element {
  const state = useTradeTerminal();
  const [mobileModule, setMobileModule] = useState<MobileModule>('chart');

  const { envelope: paperEnv } = useRealtimeResource<PaperStatusData>({
    url: '/api/v2/paper/status',
    source: '/api/v2/paper/status',
    pollIntervalMs: 10_000,
    staleThresholdMs: 30_000,
    mode: 'paper',
  });

  const paper = paperEnv.data?.summary;
  const realizedPnl = paper?.realized_pnl_usd ?? null;
  const unrealizedPnl = paper?.unrealized_pnl_usd ?? state.account.unrealizedPnl;
  const openNotional = paper?.total_open_notional ?? null;
  const openPositionCount = paper?.open_position_count ?? null;

  // Paper equity = realized + unrealized (simple P&L-based view)
  const paperEquity = realizedPnl !== null && unrealizedPnl !== null
    ? realizedPnl + unrealizedPnl
    : state.account.equity;

  const signalDirection = state.signal.direction !== 'Signal unavailable'
    ? String(state.signal.direction).toUpperCase()
    : '—';
  const signalColor = state.signal.direction !== 'Signal unavailable'
    ? signalDirection.includes('SHORT') ? 'var(--sell)' : 'var(--buy)'
    : undefined;

  const riskLabel = String(state.signal.riskDecision).replace(/_/g, ' ');
  const riskColor = riskLabel.toLowerCase().includes('allow')
    ? 'var(--buy)'
    : riskLabel !== 'Risk result unavailable' ? 'var(--sell)' : undefined;

  const pnlColor = (v: number | null) =>
    v != null ? (v >= 0 ? 'var(--buy)' : 'var(--sell)') : undefined;

  return (
    <article className="trade-terminal" data-testid="page-trader" data-mobile-active={mobileModule}>
      <SymbolHeader state={state} />

      {/* Account KPI strip — reads from Redis paper heartbeat */}
      <section className="trade-account-strip" aria-label="Account status">
        <div>
          <span>Net PnL</span>
          <strong style={{ color: pnlColor(paperEquity) }}>
            {paperEquity !== null ? formatMoney(paperEquity) : '—'}
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
          <strong>{tradeCopy(state.mode.traderState, 'Paper read-only')}</strong>
        </div>
        <div>
          <span>Account</span>
          <strong>{state.trader.accountLabel}</strong>
        </div>
      </section>

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
