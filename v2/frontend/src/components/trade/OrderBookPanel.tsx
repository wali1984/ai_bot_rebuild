import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatNumber, formatPercent, formatPrice } from '../../lib/tradeFormatters';
import { TRADE_ENDPOINTS, sourceLabel } from '../../lib/tradeCopy';
import { MissingDataState, TradePanel } from './TradeShared';

export function OrderBookPanel({ state }: { state: TradeTerminalState }): JSX.Element {
  const { bid, ask, bookBidSize, bookAskSize, spreadAbs, spreadPct, sources, depthLevels } = state.market;
  const bids = depthLevels.bids.filter((row) => row[0] !== null && row[1] !== null).slice(0, 8);
  const asks = depthLevels.asks.filter((row) => row[0] !== null && row[1] !== null).slice(0, 8).reverse();
  const hasTopOfBook = bid !== null && ask !== null;
  const hasLadder = bids.length > 0 && asks.length > 0;
  const maxSize = Math.max(
    ...bids.map((row) => Number(row[1] ?? 0)),
    ...asks.map((row) => Number(row[1] ?? 0)),
    bookBidSize ?? 0,
    bookAskSize ?? 0,
    1,
  );
  const total = (rows: Array<[number | null, number | null]>, index: number) => rows
    .slice(0, index + 1)
    .reduce((sum, row) => sum + Number(row[1] ?? 0), 0);

  return (
    <div className="trade-mobile-panel" data-mobile-panel="book">
      <TradePanel
        title="Order Book"
        kicker="Top of book"
        testId="order-book-panel"
        actions={<select aria-label="Order book grouping" disabled title="Grouping requires the market depth endpoint"><option>0.5</option></select>}
      >
        {!hasTopOfBook && !hasLadder ? (
          <MissingDataState
            title="Order book unavailable"
            detail="A bid/ask ladder requires current depth data before it can be displayed."
            endpoint={TRADE_ENDPOINTS.depth}
          />
        ) : (
          <div className="trade-order-book" title={sourceLabel(sources.orderBook)}>
            <div className="trade-order-book__head"><span>Price</span><span>Size</span><span>Total</span></div>
            {(hasLadder ? asks : [[ask, bookAskSize]]).map((row, index) => (
              <div className="trade-order-book__row trade-order-book__row--ask" key={`ask-${row[0]}-${index}`}>
                <span>{formatPrice(row[0])}</span>
                <span>{formatNumber(row[1])}</span>
                <span>{formatNumber(hasLadder ? total(asks, index) : row[1])}</span>
                <i style={{ width: `${Math.min(100, (Number(row[1] ?? 0) / maxSize) * 100)}%` }} />
              </div>
            ))}
            <div className="trade-order-book__spread">
              <strong>{formatPrice(spreadAbs)}</strong>
              <span>{formatPercent(spreadPct)}</span>
            </div>
            {(hasLadder ? bids : [[bid, bookBidSize]]).map((row, index) => (
              <div className="trade-order-book__row trade-order-book__row--bid" key={`bid-${row[0]}-${index}`}>
                <span>{formatPrice(row[0])}</span>
                <span>{formatNumber(row[1])}</span>
                <span>{formatNumber(hasLadder ? total(bids, index) : row[1])}</span>
                <i style={{ width: `${Math.min(100, (Number(row[1] ?? 0) / maxSize) * 100)}%` }} />
              </div>
            ))}
          </div>
        )}
        {!hasLadder ? (
          <MissingDataState
            title="Full ladder unavailable"
            detail="The current fallback only supports top-of-book context. Full bid/ask levels need the market depth endpoint."
            endpoint={TRADE_ENDPOINTS.depth}
            compact
          />
        ) : null}
      </TradePanel>
    </div>
  );
}
