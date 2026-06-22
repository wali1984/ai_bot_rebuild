import { Search, Star } from 'lucide-react';
import { DataFreshnessBadge, StatusPill } from '../trading/TradingPrimitives';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatCompact, formatPercent, formatPrice, formatTime, signedClass } from '../../lib/tradeFormatters';
import { sourceLabel, tradeCopy } from '../../lib/tradeCopy';
import { ModeBadge } from './TradeShared';

interface HeaderMetric {
  label: string;
  value: string;
  source?: string | null;
  className?: string;
}

export function SymbolHeader({ state }: { state: TradeTerminalState }): JSX.Element {
  const market = state.market;
  const metrics: HeaderMetric[] = [
    { label: 'Last', value: formatPrice(market.lastPrice), source: market.sources.price },
    { label: 'Mark', value: formatPrice(market.markPrice), source: market.sources.ticker ?? 'Mark price endpoint unavailable' },
    { label: 'Index', value: formatPrice(market.indexPrice), source: market.sources.ticker ?? 'Index price endpoint unavailable' },
    { label: '24h', value: formatPercent(market.change24h), source: market.sources.ticker ?? '24h ticker endpoint unavailable', className: signedClass(market.change24h) },
    { label: 'High', value: formatPrice(market.high24h), source: market.sources.ticker ?? '24h ticker endpoint unavailable' },
    { label: 'Low', value: formatPrice(market.low24h), source: market.sources.ticker ?? '24h ticker endpoint unavailable' },
    { label: 'Volume', value: formatCompact(market.volume24h), source: market.sources.volume },
    { label: 'Turnover', value: formatCompact(market.turnover24h), source: market.sources.volume },
    { label: 'Funding', value: formatPercent(market.fundingRate), source: market.sources.funding },
    { label: 'Next funding', value: formatTime(market.nextFunding), source: market.sources.funding ?? 'Funding schedule endpoint unavailable' },
    { label: 'Open interest', value: formatCompact(market.openInterest), source: market.sources.openInterest },
    { label: 'OI change', value: formatPercent(market.openInterestChange), source: market.sources.openInterest, className: signedClass(market.openInterestChange) },
    { label: 'Spread', value: market.spreadAbs === null ? '—' : `${formatPrice(market.spreadAbs)} / ${formatPercent(market.spreadPct)}`, source: market.sources.orderBook },
    { label: 'AI direction', value: tradeCopy(state.signal.direction), source: state.signal.source, className: signedClass(state.signal.confidence) },
    { label: 'Confidence', value: formatPercent(state.signal.confidence), source: state.signal.source },
    { label: 'Risk', value: tradeCopy(state.signal.riskDecision), source: state.signal.source },
  ];

  return (
    <header className="trade-symbol-header">
      <div className="trade-symbol-header__primary">
        <div className="trade-symbol-header__search">
          <Star size={18} aria-hidden="true" />
          <label>
            <Search size={16} aria-hidden="true" />
            <select
              aria-label="Select symbol"
              value={state.symbol}
              onChange={(event) => state.setSelectedSymbol(event.target.value)}
            >
              {state.symbols.map((symbol) => (
                <option value={symbol} key={symbol}>{symbol}</option>
              ))}
            </select>
          </label>
        </div>
        <div>
          <h1>{state.symbol} Perpetual</h1>
          <p>Professional live trading terminal · {state.trader.accountLabel}</p>
        </div>
      </div>

      <div className="trade-symbol-header__badges">
        <ModeBadge />
        <span className="trade-mode-badge" title={state.trader.credentialStatus}>{state.trader.accountBindingStatus}</span>
        <StatusPill tone="ok">{tradeCopy(state.mode.liveGate, 'Live platform')}</StatusPill>
        <DataFreshnessBadge generatedAt={state.account.generatedAt ?? undefined} source="Trade data" />
      </div>

      <div className="trade-symbol-header__metrics" aria-label="Symbol metrics">
        {metrics.map((metric) => (
          <div className="trade-symbol-header__metric" title={sourceLabel(metric.source)} key={metric.label}>
            <span>{metric.label}</span>
            <strong className={metric.className}>{metric.value}</strong>
          </div>
        ))}
      </div>
    </header>
  );
}
