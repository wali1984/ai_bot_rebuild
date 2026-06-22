import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatNumber, formatPrice, formatTime } from '../../lib/tradeFormatters';
import { TRADE_ENDPOINTS } from '../../lib/tradeCopy';
import { MissingDataState, TradePanel } from './TradeShared';

export function RecentTradesTape({ state }: { state: TradeTerminalState }): JSX.Element {
  const rows = state.market.recentTrades.slice(0, 18);

  return (
    <div className="trade-mobile-panel" data-mobile-panel="book">
      <TradePanel title="Recent Trades" kicker="Tape" testId="recent-trades-tape">
        <div className="trade-tape-shell">
          <div className="trade-tape-shell__head"><span>Time</span><span>Price</span><span>Size</span><span>Side</span></div>
          {rows.length ? (
            <div className="trade-tape-shell__rows">
              {rows.map((row, index) => (
                <div className={`trade-tape-shell__row trade-tape-shell__row--${row.side}`} key={`${row.time}-${index}`}>
                  <span>{formatTime(row.time)}</span>
                  <span>{formatPrice(row.price)}</span>
                  <span>{formatNumber(row.size)}</span>
                  <span>{row.side === 'buy' ? 'Buy' : 'Sell'}</span>
                </div>
              ))}
            </div>
          ) : (
            <MissingDataState
              title="Recent trades unavailable"
              detail="A trade stream or recent-trades source is required before buy/sell prints can be displayed."
              endpoint={`${TRADE_ENDPOINTS.trades} + ${TRADE_ENDPOINTS.marketStream}`}
            />
          )}
        </div>
      </TradePanel>
    </div>
  );
}
