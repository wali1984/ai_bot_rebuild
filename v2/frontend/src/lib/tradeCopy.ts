export const TRADE_ENDPOINTS = {
  depth: '/api/v2/market/{symbol}/depth',
  trades: '/api/v2/market/{symbol}/trades',
  marketStream: '/ws/market-data or /events',
  orderPreview: '/api/v2/orders/preview',
  paperSubmit: '/api/v2/orders/paper',
  paperCancel: '/api/v2/orders/paper/{order_id}/cancel',
  paperFill: '/api/v2/orders/paper/{order_id}/fill',
  positions: '/api/v2/account/positions',
  orders: '/api/v2/execution/orders',
  executions: '/api/v2/execution/executions',
  auditEvents: '/api/v2/execution/audit-events',
  signals: '/api/v2/signals',
  portfolio: '/api/v2/portfolio',
} as const;

const COPY_MAP: Record<string, string> = {
  LIVE_ARMED_BALANCE_HOLD: 'Balance hold',
  LIVE_ARMED_COMPLIANCE_HOLD: 'Compliance hold',
  INSUFFICIENT_AVAILABLE_BALANCE_FOR_MIN_ORDER: 'Insufficient available balance for minimum order',
  'paper_fill_allowed:false': 'Execution fill blocked',
  churn_blocked: 'Churn protection active',
  fee_gate_allowed: 'Fee gate passed',
  gate_always_blocked_invariant: 'Live trading guard active',
  evidence_missing: 'Evidence unavailable',
  MISSING_EVIDENCE: 'Evidence unavailable',
  MISSING_SOURCE: 'Data source unavailable',
  SOURCE_PENDING: 'Data source unavailable',
  'source pending': 'Data source unavailable',
  'backend unavailable': 'Trading service unavailable',
  'endpoint missing': 'Required trading endpoint unavailable',
  enabled_operator_approved: 'Live mode approved',
  PAPER_RUNTIME_ONLINE_ACTIVE: 'Execution runtime active',
  PAPER: 'Live',
  READ_ONLY: 'Live platform',
  BUY: 'Buy',
  SELL: 'Sell',
  LONG: 'Long',
  SHORT: 'Short',
  HOLD: 'Hold',
};

function titleCase(value: string): string {
  return value
    .replace(/[_-]+/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase()
    .replace(/\b\w/g, (letter) => letter.toUpperCase());
}

function publicTradeText(value: string): string {
  return value
    .replace(/\bPaper Fill\b/gi, 'Execution Fill')
    .replace(/\bPaper Order\b/gi, 'Order')
    .replace(/\bPaper Account\b/gi, 'Account')
    .replace(/\bPaper Activity\b/gi, 'Execution Activity')
    .replace(/\bPaper Audit\b/gi, 'Execution Audit')
    .replace(/\bPaper Engine\b/gi, 'Execution Engine')
    .replace(/\bPaper\b/gi, 'Runtime');
}

export function tradeCopy(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  const text = String(value).trim();
  if (!text) return fallback;
  if (COPY_MAP[text]) return publicTradeText(COPY_MAP[text]);
  if (COPY_MAP[text.toLowerCase()]) return publicTradeText(COPY_MAP[text.toLowerCase()]);
  if (/^[A-Z0-9_:-]+$/.test(text) || text.includes('_')) return publicTradeText(titleCase(text));
  return publicTradeText(text);
}

export function missingEndpointCopy(endpoint: string): string {
  return `Required trading endpoint unavailable: ${endpoint}`;
}

export function sourceLabel(label: string | null | undefined): string {
  return tradeCopy(label, 'Fallback data unavailable');
}
