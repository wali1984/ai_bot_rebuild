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
  gate_always_blocked_invariant: 'Execution guard active',
  evidence_missing: 'Evidence pending',
  MISSING_EVIDENCE: 'Evidence pending',
  MISSING_SOURCE: 'Connecting stream',
  SOURCE_PENDING: 'Connecting stream',
  'source pending': 'Connecting stream',
  'backend unavailable': 'Trading service reconnecting',
  'endpoint missing': 'Required trading endpoint reconnecting',
  enabled_operator_approved: 'Approval recorded',
  PAPER_RUNTIME_ONLINE_ACTIVE: 'Execution runtime active',
  PAPER: 'Execution restricted',
  READ_ONLY: 'Read-only platform',
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

/**
 * Admin/system operator surfaces (routes under /admin) must render raw API
 * values: the public-site copy mask rewrites audit-critical markers
 * ('blocked_human_only' -> 'approval required', 'operator' -> 'approval',
 * 'PAPER_EDGE_PROVEN' -> 'execution_edge_PROVEN', ...) which made rendered
 * values diverge from API values on evidence pages (final field audit).
 */
export function isOperatorTruthSurface(pathname?: string): boolean {
  const path = pathname ?? (typeof window !== 'undefined' ? window.location.pathname : '');
  return path === '/admin' || path.startsWith('/admin/');
}

export function publicRuntimeCopy(value: unknown, fallback = '—'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (isOperatorTruthSurface()) return value.toString();
  return value
    .toString()
    .replace(/\bPaper Fill\b/gi, 'Execution Fill')
    .replace(/\bPaper Order\b/gi, 'Order')
    .replace(/\bPaper Account\b/gi, 'Account')
    .replace(/\bPaper Activity\b/gi, 'Execution Activity')
    .replace(/\bPaper Audit\b/gi, 'Execution Audit')
    .replace(/\bPaper Engine\b/gi, 'Execution Engine')
    .replace(/\bPaper Edge\b/gi, 'Execution Edge')
    .replace(/\bPaper Trading\b/gi, 'Runtime Execution')
    .replace(/\bPaper Runtime\b/gi, 'Execution Runtime')
    .replace(/\bPaper Shadow\b/gi, 'Runtime Shadow')
    .replace(/\bPaper\b/gi, 'Runtime')
    .replace(/\bpaper[_ -]?fill(?=\b|[_ -])/gi, 'execution')
    .replace(/\bpaper[_ -]?edge(?=\b|[_ -])/gi, 'execution_edge')
    .replace(/\bpaper[_ -]?trading(?=\b|[_ -])/gi, 'runtime_execution')
    .replace(/\bpaper[_ -]?runtime(?=\b|[_ -])/gi, 'execution_runtime')
    .replace(/\bpaper[_ -]?shadow(?=\b|[_ -])/gi, 'runtime_shadow')
    .replace(/\bpaper(?=\b|[_ -])/gi, 'runtime')
    .replace(/\bno[_\s-]*data\b/gi, 'Realtime stream connecting')
    .replace(/\bdata unavailable\b/gi, 'Data stream connecting')
    .replace(/\btrading[_\s-]*live\b/gi, 'order routing approval')
    .replace(/\blive[_\s-]*execution\b/gi, 'exchange execution approval')
    .replace(/\blive[_\s-]*trading\b/gi, 'order routing approval')
    .replace(/control[_\s-]*plane/gi, 'system status')
    .replace(/\bsource unavailable\b/gi, 'source connecting')
    .replace(/\bservice unavailable\b/gi, 'service reconnecting')
    .replace(/\bendpoint unavailable\b/gi, 'endpoint reconnecting')
    .replace(/\bunavailable\b/gi, 'connecting')
    .replace(/\boperator\b/gi, 'approval')
    .replace(/\bsimulated only\b/gi, 'approval gated')
    .replace(/\bsimulated\b/gi, 'guarded');
}

function publicTradeText(value: string): string {
  return publicRuntimeCopy(value)
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
  return `Required trading endpoint reconnecting: ${endpoint}`;
}

export function sourceLabel(label: string | null | undefined): string {
  return tradeCopy(label, 'Fallback stream connecting');
}
