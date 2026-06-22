import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatMoney, formatNumber, formatPrice, formatTime, formatPercent } from '../../lib/tradeFormatters';
import { tradeCopy } from '../../lib/tradeCopy';

interface PaperFill {
  execution_id: string | null;
  symbol: string;
  side: string;
  fill_price: number | null;
  entry_price: number | null;
  quantity: number | null;
  notional_usd: number | null;
  fee: number | null;
  slippage: number | null;
  timeframe: string | null;
  strategy_id: string | null;
  model_id: string | null;
  confidence: number | null;
  market_regime: string | null;
  risk_result: string | null;
  filled_at: string | null;
  created_at: string | null;
}

function finiteNumber(value: unknown): number | null {
  const next = typeof value === 'number' ? value : typeof value === 'string' ? Number(value) : NaN;
  return Number.isFinite(next) ? next : null;
}

function textValue(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null;
}

function fallbackExecutionFill(row: Record<string, unknown>): PaperFill {
  return {
    execution_id: textValue(row.execution_id) ?? textValue(row.id),
    symbol: textValue(row.symbol)?.toUpperCase() ?? '',
    side: textValue(row.side)?.toUpperCase() ?? textValue(row.direction)?.toUpperCase() ?? '',
    fill_price: finiteNumber(row.fill_price) ?? finiteNumber(row.price) ?? finiteNumber(row.entry_price),
    entry_price: finiteNumber(row.entry_price),
    quantity: finiteNumber(row.quantity) ?? finiteNumber(row.qty) ?? finiteNumber(row.size),
    notional_usd: finiteNumber(row.notional_usd) ?? finiteNumber(row.notional),
    fee: finiteNumber(row.fee),
    slippage: finiteNumber(row.slippage) ?? finiteNumber(row.slippage_bps),
    timeframe: textValue(row.timeframe),
    strategy_id: textValue(row.strategy_id) ?? textValue(row.strategy),
    model_id: textValue(row.model_id) ?? textValue(row.model_version),
    confidence: finiteNumber(row.confidence) ?? finiteNumber(row.confidence_calibrated),
    market_regime: textValue(row.market_regime) ?? textValue(row.regime),
    risk_result: textValue(row.risk_result),
    filled_at: textValue(row.filled_at) ?? textValue(row.time) ?? textValue(row.created_at),
    created_at: textValue(row.created_at),
  };
}

export function ExecutionsTable({ state }: { state: TradeTerminalState }): JSX.Element {
  const paperFills = (state.paper.activity.fills ?? []) as unknown as PaperFill[];
  const typedFills = (state.activity.executions ?? []).map((row) => fallbackExecutionFill(row as Record<string, unknown>));
  const fills = paperFills.length ? paperFills : typedFills;

  if (state.paper.loading && !fills.length) {
    return (
      <div className="trade-table-shell" data-testid="executions-table">
        <div style={{ padding: '24px 16px', color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
          Loading execution history…
        </div>
      </div>
    );
  }

  if (!fills.length) {
    return (
      <div className="trade-table-shell" data-testid="executions-table">
        <div className="trade-table trade-table--executions" role="table" aria-label="Executions">
          <div className="trade-table__row trade-table__row--executions trade-table__row--head" role="row">
            <span>Time</span><span>Symbol</span><span>Side</span><span>Price</span><span>Qty</span><span>Notional</span><span>Confidence</span><span>Strategy</span><span>Regime</span><span>Source</span>
          </div>
        </div>
        <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
          No execution fills recorded yet. Fills appear here as the execution engine accepts intents.
          <br />
          <span style={{ fontSize: 11, color: 'var(--text-muted)', marginTop: 4, display: 'block' }}>
            Source: execution activity stream
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="trade-table-shell" data-testid="executions-table">
      <div className="trade-table trade-table--executions" role="table" aria-label={`Execution history — ${fills.length} fills`}>
        <div className="trade-table__row trade-table__row--executions trade-table__row--head" role="row">
          <span>Time</span><span>Symbol</span><span>Side</span><span>Price</span><span>Qty</span><span>Notional</span><span>Confidence</span><span>Strategy</span><span>Regime</span><span>Source</span>
        </div>
        {fills.map((fill, index) => {
          const sideColor = fill.side === 'SHORT' ? 'var(--sell)' : fill.side === 'LONG' ? 'var(--buy)' : undefined;
          return (
            <div className="trade-table__row trade-table__row--executions" role="row" key={`${fill.execution_id ?? 'fill'}-${index}`}>
              <span data-label="Time">{formatTime(fill.filled_at ?? fill.created_at ?? '')}</span>
              <span data-label="Symbol" style={{ fontWeight: 600 }}>{fill.symbol || '—'}</span>
              <span data-label="Side" style={{ color: sideColor, fontWeight: 600 }}>{fill.side || '—'}</span>
              <span data-label="Price">{formatPrice(fill.fill_price)}</span>
              <span data-label="Qty">{formatNumber(fill.quantity)}</span>
              <span data-label="Notional">{formatMoney(fill.notional_usd)}</span>
              <span data-label="Confidence">{fill.confidence != null ? formatPercent(fill.confidence) : '—'}</span>
              <span data-label="Strategy">{tradeCopy(fill.strategy_id ?? '') || '—'}</span>
              <span data-label="Regime">{fill.market_regime ? tradeCopy(fill.market_regime) : '—'}</span>
              <span data-label="Source" style={{ color: 'var(--buy)', fontSize: 11 }}>Execution stream</span>
            </div>
          );
        })}
      </div>
      <div style={{ padding: '6px 12px', fontSize: 10, color: 'var(--text-muted)', fontFamily: 'var(--font-mono)' }}>
        {fills.length} execution fills · {state.paper.connected ? 'WebSocket stream' : 'HTTP fallback'}
      </div>
    </div>
  );
}
