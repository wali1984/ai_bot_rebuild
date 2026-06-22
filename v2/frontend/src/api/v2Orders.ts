import type { ApiV2Envelope, OrderPreviewData, OrderPreviewRequest, PaperOrderActionData } from '../types/apiV2';
import { fetchV2Contract } from './v2Shared';

export function safeOrderEnvelopeSymbol(symbol: string): string | undefined {
  const normalized = symbol.trim().toUpperCase();
  return normalized && /^[A-Z0-9]+$/.test(normalized) ? normalized : undefined;
}

export function previewV2Order(request: OrderPreviewRequest): Promise<ApiV2Envelope<OrderPreviewData>> {
  return fetchV2Contract<OrderPreviewData>(
    '/api/v2/orders/preview',
    ['preview'],
    'Paper order preview unavailable.',
    {
      symbol: safeOrderEnvelopeSymbol(request.symbol),
      mode: request.mode === 'live' ? 'live_blocked' : 'paper_preview_unverified',
      init: {
        method: 'POST',
        body: JSON.stringify(request),
      },
    },
  );
}

export function submitV2PaperOrder(request: OrderPreviewRequest): Promise<ApiV2Envelope<PaperOrderActionData>> {
  return fetchV2Contract<PaperOrderActionData>(
    '/api/v2/orders/paper',
    ['paper_submit'],
    'Paper order submit unavailable.',
    {
      symbol: safeOrderEnvelopeSymbol(request.symbol),
      mode: 'paper',
      init: {
        method: 'POST',
        body: JSON.stringify({ ...request, mode: 'paper' }),
      },
    },
  );
}

export function cancelV2PaperOrder(orderId: string): Promise<ApiV2Envelope<PaperOrderActionData>> {
  const safeOrderId = encodeURIComponent(orderId);
  return fetchV2Contract<PaperOrderActionData>(
    `/api/v2/orders/paper/${safeOrderId}/cancel`,
    ['paper_order'],
    'Paper order cancel unavailable.',
    {
      mode: 'paper',
      init: {
        method: 'POST',
      },
    },
  );
}

export function fillV2PaperOrder(
  orderId: string,
  request: { price?: number | null; quantity?: number | null; reason?: string } = {},
): Promise<ApiV2Envelope<PaperOrderActionData>> {
  const safeOrderId = encodeURIComponent(orderId);
  return fetchV2Contract<PaperOrderActionData>(
    `/api/v2/orders/paper/${safeOrderId}/fill`,
    ['paper_fill'],
    'Paper order fill unavailable.',
    {
      mode: 'paper',
      init: {
        method: 'POST',
        body: JSON.stringify(request),
      },
    },
  );
}
