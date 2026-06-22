import { useState } from 'react';
import { cancelV2PaperOrder, fillV2PaperOrder } from '../../api/v2Orders';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatNumber, formatPrice, formatTime } from '../../lib/tradeFormatters';
import { TRADE_ENDPOINTS, tradeCopy } from '../../lib/tradeCopy';
import { MissingDataState } from './TradeShared';

function rowText(row: Record<string, unknown>, keys: string[], fallback = 'Data unavailable'): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'string' && value.trim()) return tradeCopy(value);
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return fallback;
}

function rowRawText(row: Record<string, unknown>, keys: string[], fallback = ''): string {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'string' && value.trim()) return value;
    if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  }
  return fallback;
}

function rowNumber(row: Record<string, unknown>, keys: string[]): number | null {
  for (const key of keys) {
    const value = row[key];
    if (typeof value === 'number' && Number.isFinite(value)) return value;
  }
  return null;
}

function rowMatchesActivePaperScope(row: Record<string, unknown>, state: TradeTerminalState): boolean {
  return Boolean(
    state.trader.traderId
    && state.trader.paperAccountId
    && row.trader_id === state.trader.traderId
    && row.paper_account_id === state.trader.paperAccountId,
  );
}

function rowIsPaperOnly(row: Record<string, unknown>): boolean {
  const mode = rowRawText(row, ['mode', 'order_mode', 'execution_mode', 'account_mode']).toLowerCase();
  const source = rowRawText(row, ['source', 'source_status', 'audit_event']).toLowerCase();
  const orderId = rowRawText(row, ['order_id', 'id']);
  const liveRouteEnabled = (
    row.live_order === true
    || row.real_order === true
    || row.exchange_mutation_enabled === true
    || row.live_transport_enabled === true
    || row.live_order_cancel_enabled === true
  );
  return (
    mode === 'paper'
    && orderId.startsWith('paper-')
    && (
      source.includes('paper_order_repository')
      || source.includes('paper_order_staged_local')
      || source.includes('local paper')
      || row.local_paper_repository_order === true
    )
    && !liveRouteEnabled
  );
}

function canUseLocalPaperOrderAction(row: Record<string, unknown>, state: TradeTerminalState, history: boolean): boolean {
  const status = rowText(row, ['status', 'order_status']).toLowerCase();
  return (
    !history
    && status === 'open'
    && state.activity.actionPolicy.localPaperOrdersRepository === true
    && rowMatchesActivePaperScope(row, state)
    && rowIsPaperOnly(row)
  );
}

export const openOrdersTableTestHooks = {
  rowIsPaperOnly,
};

export function OpenOrdersTable({
  state,
  history = false,
}: {
  state: TradeTerminalState;
  history?: boolean;
}): JSX.Element {
  const [cancelingId, setCancelingId] = useState<string | null>(null);
  const [fillingId, setFillingId] = useState<string | null>(null);
  const rows = history ? state.activity.orderHistory : state.activity.openOrders;

  async function cancelOrder(row: Record<string, unknown>): Promise<void> {
    if (!canUseLocalPaperOrderAction(row, state, history)) return;
    const orderId = rowText(row, ['order_id', 'id'], '');
    if (!orderId) return;
    setCancelingId(orderId);
    try {
      await cancelV2PaperOrder(orderId);
    } finally {
      setCancelingId(null);
    }
  }

  async function fillOrder(row: Record<string, unknown>): Promise<void> {
    if (!canUseLocalPaperOrderAction(row, state, history)) return;
    const orderId = rowText(row, ['order_id', 'id'], '');
    if (!orderId) return;
    const price = rowNumber(row, ['price', 'limit_price', 'stop_price']) ?? state.market.lastPrice ?? null;
    setFillingId(orderId);
    try {
      await fillV2PaperOrder(orderId, {
        price,
        reason: 'Manual paper fill from trade terminal',
      });
    } finally {
      setFillingId(null);
    }
  }

  if (!rows.length) {
    return (
      <div className="trade-table-shell" data-testid={history ? 'order-history-table' : 'open-orders-table'}>
        <div className="trade-table trade-table--orders" role="table" aria-label={history ? 'Order history' : 'Open orders'}>
          <div className="trade-table__row trade-table__row--orders trade-table__row--head" role="row">
            <span>Time</span><span>Symbol</span><span>Side</span><span>Type</span><span>Price</span><span>Size</span><span>Filled</span><span>Status</span><span>Mode</span><span>Action</span>
          </div>
        </div>
        <div style={{ padding: '20px 16px', color: 'var(--text-muted)', fontSize: 13, fontFamily: 'var(--font-mono)' }}>
          {history
            ? 'Order history is stored in the trader-scoped execution repository. Sign in to view your order history.'
            : 'No open orders. The execution engine fills intents synchronously — orders are accepted or blocked immediately, so no orders stay pending. Staged limit/stop orders placed via the Order Ticket will appear here.'}
          <br />
          <span style={{ fontSize: 11, marginTop: 4, display: 'block' }}>
            See the <strong>Executions</strong> tab for fills · <strong>Positions</strong> tab for open positions.
          </span>
        </div>
      </div>
    );
  }

  return (
    <div className="trade-table-shell" data-testid={history ? 'order-history-table' : 'open-orders-table'}>
      <div className="trade-table trade-table--orders" role="table" aria-label={history ? 'Order history' : 'Open orders'}>
        <div className="trade-table__row trade-table__row--orders trade-table__row--head" role="row">
          <span>Time</span><span>Symbol</span><span>Side</span><span>Type</span><span>Price</span><span>Size</span><span>Filled</span><span>Status</span><span>Mode</span><span>Action</span>
        </div>
        {rows.map((row, index) => (
          (() => {
            const orderId = rowText(row, ['order_id', 'id'], '');
            const localPaperActionAllowed = canUseLocalPaperOrderAction(row, state, history);
            return (
              <div className="trade-table__row trade-table__row--orders" role="row" key={`${orderId || 'order'}-${index}`}>
                <span data-label="Time">{formatTime(rowText(row, ['time', 'created_at', 'updated_at'], ''))}</span>
                <span data-label="Symbol">{rowRawText(row, ['symbol']).toUpperCase() || 'Data unavailable'}</span>
                <span data-label="Side">{rowText(row, ['side', 'direction'])}</span>
                <span data-label="Type">{rowText(row, ['type', 'order_type'])}</span>
                <span data-label="Price">{formatPrice(rowNumber(row, ['price', 'limit_price', 'stop_price']))}</span>
                <span data-label="Size">{formatNumber(rowNumber(row, ['size', 'quantity', 'qty']))}</span>
                <span data-label="Filled">{formatNumber(rowNumber(row, ['filled', 'filled_size', 'filled_quantity']))}</span>
                <span data-label="Status">{rowText(row, ['status', 'order_status', 'reason'])}</span>
                <span data-label="Mode">Runtime</span>
                <span data-label="Action">
                  {localPaperActionAllowed ? (
                    <span className="trade-order-actions">
                      <button
                        type="button"
                        className="trade-link-button"
                        disabled={fillingId === orderId}
                        title="Manual local fill only; no exchange order is placed"
                        onClick={() => void fillOrder(row)}
                      >
                        {fillingId === orderId ? 'Filling' : 'Fill'}
                      </button>
                      <button
                        type="button"
                        className="trade-link-button"
                        disabled={cancelingId === orderId}
                        title="Local cancel only; no exchange cancel is sent"
                        onClick={() => void cancelOrder(row)}
                      >
                        {cancelingId === orderId ? 'Canceling' : 'Cancel'}
                      </button>
                    </span>
                  ) : 'Action unavailable'}
                </span>
              </div>
            );
          })()
        ))}
      </div>
    </div>
  );
}
