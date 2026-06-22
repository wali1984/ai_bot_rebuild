import { useEffect, useMemo, useState } from 'react';
import { Lock } from 'lucide-react';
import { previewV2Order, submitV2PaperOrder } from '../../api/v2Orders';
import type { TradeTerminalState } from '../../hooks/useTradeTerminal';
import { formatMoney, formatNumber, formatPrice } from '../../lib/tradeFormatters';
import { TRADE_ENDPOINTS, missingEndpointCopy, tradeCopy } from '../../lib/tradeCopy';
import type { ApiV2Envelope, OrderPreviewData, PaperOrderActionData } from '../../types/apiV2';
import { MissingDataState, TradePanel } from './TradeShared';

const ORDER_TYPES = ['Market', 'Limit', 'Stop', 'TP/SL'] as const;
const PERCENTS = [25, 50, 75, 100] as const;

export function paperPreviewMatchesTraderScope(
  previewData: OrderPreviewData | null | undefined,
  traderId: string | null | undefined,
  paperAccountId: string | null | undefined,
): boolean {
  return Boolean(
    previewData?.allowed
    && traderId
    && paperAccountId
    && previewData.trader_id === traderId
    && previewData.paper_account_id === paperAccountId,
  );
}

export function PaperOrderTicket({ state }: { state: TradeTerminalState }): JSX.Element {
  const [side, setSide] = useState<'Buy' | 'Sell'>('Buy');
  const [orderType, setOrderType] = useState<(typeof ORDER_TYPES)[number]>('Limit');
  const [quantity, setQuantity] = useState('');
  const [price, setPrice] = useState('');
  const numericQuantity = Number(quantity);
  const numericPrice = Number(price || state.market.lastPrice || 0);
  const notional = Number.isFinite(numericQuantity) && Number.isFinite(numericPrice) ? numericQuantity * numericPrice : 0;
  const requiresPrice = orderType === 'Limit' || orderType === 'Stop';
  const previewSupportedOrderType = orderType === 'Market' || orderType === 'Limit' || orderType === 'Stop';
  const [preview, setPreview] = useState<ApiV2Envelope<OrderPreviewData> | null>(null);
  const [submitResult, setSubmitResult] = useState<ApiV2Envelope<PaperOrderActionData> | null>(null);
  const [previewLoading, setPreviewLoading] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const previewScopeMatches = paperPreviewMatchesTraderScope(
    preview?.data,
    state.trader.traderId,
    state.trader.paperAccountId,
  );
  const paperPolicy = submitResult?.data?.paper_execution_policy ?? preview?.data?.paper_execution_policy;
  const productionPaperActionsDisabled = paperPolicy?.production_environment === true && paperPolicy?.production_paper_actions_enabled === false;
  const productionValidationPending = paperPolicy?.production_validation_status === 'pending' || paperPolicy?.verified_production_paper_submit_cancel === false;
  const liveExchangeRouteDisabled = paperPolicy?.live_transport_enabled === false
    && paperPolicy?.exchange_mutation_enabled === false
    && paperPolicy?.real_order_submission_enabled === false
    && paperPolicy?.live_order_cancel_enabled === false;
  const localPaperStagingAllowed = Boolean(
    paperPolicy?.local_paper_repository_enabled === true
    && paperPolicy.local_paper_staging_enabled === true
    && paperPolicy.requires_authenticated_trader_scope === true
    && (
      paperPolicy.production_environment !== true
      || (
        paperPolicy.production_paper_actions_enabled === true
        && paperPolicy.verified_production_paper_submit_cancel === true
        && paperPolicy.verified_paper_execution_service === true
      )
    ),
  );
  const canSubmit = Boolean(previewScopeMatches && localPaperStagingAllowed && liveExchangeRouteDisabled && !submitting);
  const paperPolicyLabel = productionPaperActionsDisabled
    ? 'Production execution actions disabled'
    : productionValidationPending
    ? 'Production validation pending'
    : paperPolicy?.fill_policy === 'no_automatic_fill'
      ? 'Staged only; no automatic fills'
      : 'Execution policy pending';
  const paperGuardLabel = liveExchangeRouteDisabled ? 'Execution route guarded' : 'Policy check connecting';
  const invalidReason = useMemo(() => {
    if (!previewSupportedOrderType) return 'TP/SL preview is not connected yet.';
    if (!quantity || !Number.isFinite(numericQuantity) || numericQuantity <= 0) return 'Enter a quantity greater than zero.';
    if (requiresPrice && (!price || !Number.isFinite(Number(price)) || Number(price) <= 0)) return 'Enter a valid order price.';
    if (previewLoading) return 'Checking order preview.';
    if (preview?.data?.allowed && !previewScopeMatches) return 'Order preview belongs to a different trader account.';
    if (preview?.data?.allowed && !localPaperStagingAllowed) return 'Order staging is disabled until a verified execution policy is available.';
    if (preview?.data?.allowed && !liveExchangeRouteDisabled) return 'Order staging is disabled because exchange-route safety evidence is still connecting.';
    if (preview?.data?.allowed) return 'Order can be staged.';
    return preview?.data?.friendly_reason ? tradeCopy(preview.data.friendly_reason) : (preview?.source_type === 'unavailable' ? 'Order preview connecting.' : missingEndpointCopy(TRADE_ENDPOINTS.orderPreview));
  }, [liveExchangeRouteDisabled, localPaperStagingAllowed, numericQuantity, preview?.data?.allowed, preview?.data?.friendly_reason, preview?.source_type, previewLoading, previewScopeMatches, previewSupportedOrderType, price, quantity, requiresPrice]);

  useEffect(() => {
    setPreview(null);
    setSubmitResult(null);
  }, [state.trader.traderId, state.trader.paperAccountId]);

  useEffect(() => {
    if (!previewSupportedOrderType || !quantity || !Number.isFinite(numericQuantity) || numericQuantity <= 0) {
      setPreview(null);
      setPreviewLoading(false);
      return undefined;
    }
    if (requiresPrice && (!price || !Number.isFinite(Number(price)) || Number(price) <= 0)) {
      setPreview(null);
      setPreviewLoading(false);
      return undefined;
    }

    let active = true;
    setPreviewLoading(true);
    const timer = window.setTimeout(() => {
      void previewV2Order({
        symbol: state.symbol,
        side: side.toLowerCase() as 'buy' | 'sell',
        order_type: orderType.toLowerCase() as 'market' | 'limit' | 'stop',
        quantity: numericQuantity,
        price: requiresPrice ? Number(price) : null,
        trader_id: state.trader.traderId,
        paper_account_id: state.trader.paperAccountId,
        mode: 'paper',
      }).then((result) => {
        if (!active) return;
        setPreview(result);
        setPreviewLoading(false);
      });
    }, 350);

    return () => {
      active = false;
      window.clearTimeout(timer);
    };
  }, [numericQuantity, orderType, previewSupportedOrderType, price, quantity, requiresPrice, side, state.symbol, state.trader.traderId, state.trader.paperAccountId]);

  async function submitPaperOrder(): Promise<void> {
    if (!canSubmit) return;
    setSubmitting(true);
    const result = await submitV2PaperOrder({
      symbol: state.symbol,
      side: side.toLowerCase() as 'buy' | 'sell',
      order_type: orderType.toLowerCase() as 'market' | 'limit' | 'stop',
      quantity: numericQuantity,
      price: requiresPrice ? Number(price) : null,
      trader_id: state.trader.traderId,
      paper_account_id: state.trader.paperAccountId,
      mode: 'paper',
    });
    setSubmitResult(result);
    setSubmitting(false);
  }

  return (
    <div className="trade-mobile-panel" data-mobile-panel="ticket">
      <TradePanel title="Order Ticket" kicker="Execution staging" testId="paper-order-ticket">
        <div className="trade-ticket">
          <div className="trade-ticket__side" role="tablist" aria-label="Order side">
            {(['Buy', 'Sell'] as const).map((item) => (
              <button
                type="button"
                role="tab"
                aria-selected={side === item}
                className={side === item ? `is-active is-${item.toLowerCase()}` : ''}
                onClick={() => setSide(item)}
                key={item}
              >
                {item}
              </button>
            ))}
          </div>

          <label>
            <span>Order type</span>
            <select value={orderType} onChange={(event) => setOrderType(event.target.value as (typeof ORDER_TYPES)[number])}>
              {ORDER_TYPES.map((item) => <option value={item} key={item}>{item}</option>)}
            </select>
          </label>
          <label>
            <span>Quantity</span>
            <input inputMode="decimal" value={quantity} onChange={(event) => setQuantity(event.target.value)} placeholder="0.0000" />
          </label>
          <label>
            <span>{requiresPrice ? 'Price' : 'Reference price'}</span>
            <input
              inputMode="decimal"
              value={price}
              onChange={(event) => setPrice(event.target.value)}
              placeholder={formatPrice(state.market.lastPrice)}
              readOnly={!requiresPrice}
            />
          </label>

          <div className="trade-ticket__percents" aria-label="Account balance percentage">
            {PERCENTS.map((percent) => (
              <button type="button" disabled title="Sizing percentages require account balance and preview support" key={percent}>{percent}%</button>
            ))}
          </div>

          <div className="trade-ticket__summary">
            <span>Account <strong title={state.trader.credentialStatus}>{state.trader.accountLabel}</strong></span>
            <span>Account balance <strong>{formatMoney(state.account.availablePaperBalance)}</strong></span>
            <span>Account source <strong title={state.account.source}>{state.account.reason ?? state.account.scope}</strong></span>
            <span>Notional <strong>
              {preview?.data?.estimated_notional != null
                ? formatMoney(preview.data.estimated_notional)
                : notional > 0 ? formatMoney(notional) : 'Enter quantity'}
            </strong></span>
            <span>Estimated fee <strong>
              {preview?.data?.estimated_fee != null ? formatMoney(preview.data.estimated_fee) : 'After quantity entered'}
            </strong></span>
            <span>Position size <strong>{numericQuantity > 0 ? formatNumber(numericQuantity) : 'Enter quantity'}</strong></span>
            <span>Execution policy <strong>
              {preview?.data?.paper_execution_policy ? paperPolicyLabel : 'Execution route guarded'}
            </strong></span>
            <span>Exchange route <strong>
              {preview?.data?.paper_execution_policy ? paperGuardLabel : 'Execution route guarded'}
            </strong></span>
            <span>Risk pre-check <strong>
              {preview?.data?.friendly_reason
                ? tradeCopy(preview.data.friendly_reason)
                : state.signal.paperFillAllowed
                  ? 'Execution Fill Open'
                  : tradeCopy(state.signal.riskDecision)}
            </strong></span>
          </div>

          <button type="button" className="trade-ticket__submit" disabled={!canSubmit} title={invalidReason} onClick={() => void submitPaperOrder()}>
            <Lock size={15} aria-hidden="true" />
            {submitting ? 'Staging Order' : `Place ${side}`}
          </button>
          <p className="trade-ticket__reason" role="status">{tradeCopy(submitResult?.data?.friendly_reason ?? invalidReason)}</p>
          {!canSubmit && numericQuantity > 0 ? (
            <MissingDataState
              title="Order not ready"
              detail={
                !previewScopeMatches
                  ? 'Enter a quantity — preview will be fetched from the execution engine.'
                  : !localPaperStagingAllowed
                    ? 'Order staging requires a verified execution policy from the backend.'
                    : 'Live exchange route must be confirmed disabled before staging.'
              }
              endpoint={`${TRADE_ENDPOINTS.orderPreview} + execution staging endpoint`}
              showEndpoint
              compact
            />
          ) : null}
        </div>
      </TradePanel>
    </div>
  );
}
