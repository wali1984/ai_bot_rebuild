import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatNumber } from '../../lib/tradeFormatters';
import { TRADE_ENDPOINTS, sourceLabel } from '../../lib/tradeCopy';
import { MissingDataState, TradePanel } from './TradeShared';

export function MarketDepthPanel({ state }: { state: TradeTerminalState }): JSX.Element {
  const bidTotal = state.market.depthLevels.bids.reduce((sum, row) => sum + Number(row[1] ?? 0), 0);
  const askTotal = state.market.depthLevels.asks.reduce((sum, row) => sum + Number(row[1] ?? 0), 0);
  const bidSize = bidTotal > 0 ? bidTotal : state.market.bookBidSize ?? 0;
  const askSize = askTotal > 0 ? askTotal : state.market.bookAskSize ?? 0;
  const max = Math.max(bidSize, askSize, 1);
  const hasDepthSummary = bidSize > 0 || askSize > 0;
  const hasTypedDepth = state.market.depthLevels.bids.length > 0 && state.market.depthLevels.asks.length > 0;

  return (
    <div className="trade-mobile-panel" data-mobile-panel="book">
      <TradePanel title="Market Depth" kicker="Liquidity summary" testId="market-depth-panel">
        {!hasDepthSummary ? (
          <MissingDataState
            title="Market depth unavailable"
            detail="Depth curves and liquidity walls require cumulative bid/ask levels."
            endpoint={TRADE_ENDPOINTS.depth}
          />
        ) : (
          <div className="trade-depth" title={sourceLabel(state.market.sources.depth)}>
            <div className="trade-depth__axis">
              <span>Bid depth</span>
              <span>Ask depth</span>
            </div>
            <div className="trade-depth__bars" aria-label="Bid and ask cumulative depth">
              <span className="trade-depth__bid" style={{ width: `${Math.max(8, (bidSize / max) * 100)}%` }} />
              <span className="trade-depth__ask" style={{ width: `${Math.max(8, (askSize / max) * 100)}%` }} />
            </div>
            <div className="trade-depth__values">
              <strong>{formatNumber(bidSize)}</strong>
              <em>Spread</em>
              <strong>{formatNumber(askSize)}</strong>
            </div>
          </div>
        )}
        {!hasTypedDepth ? (
          <MissingDataState
            title="Depth chart source incomplete"
            detail="A full cumulative curve and liquidity wall markers need the depth endpoint."
            endpoint={TRADE_ENDPOINTS.depth}
            compact
          />
        ) : null}
      </TradePanel>
    </div>
  );
}
