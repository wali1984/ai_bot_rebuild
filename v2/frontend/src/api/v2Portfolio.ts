import type { AccountReadinessData, ApiV2Envelope, AuditEventsData, ExchangeReadOnlyAccountData, ExecutionsData, OrdersData, PortfolioData, PositionsData } from '../types/apiV2';
import { fetchV2Contract } from './v2Shared';

export function getV2Portfolio(): Promise<ApiV2Envelope<PortfolioData>> {
  return fetchV2Contract<PortfolioData>(
    '/api/v2/portfolio',
    ['equity', 'positions', 'pnl'],
    'Portfolio endpoint is unavailable.',
    { mode: 'paper' },
  );
}

export function getV2Positions(): Promise<ApiV2Envelope<PositionsData>> {
  return fetchV2Contract<PositionsData>(
    '/api/v2/account/positions',
    ['positions'],
    'Position endpoint is unavailable.',
    { mode: 'paper' },
  );
}

export function getV2ExchangeReadOnlyAccount(): Promise<ApiV2Envelope<ExchangeReadOnlyAccountData>> {
  return fetchV2Contract<ExchangeReadOnlyAccountData>(
    '/api/v2/account/exchange-readonly',
    ['account_snapshot', 'positions', 'credential'],
    'Trader exchange account source connecting.',
    { mode: 'read_only' },
  );
}

export function getV2AccountReadiness(): Promise<ApiV2Envelope<AccountReadinessData>> {
  return fetchV2Contract<AccountReadinessData>(
    '/api/v2/account/readiness',
    ['trader_account_repository', 'production_database_repository'],
    'Trader account readiness endpoint is unavailable.',
    { mode: 'paper' },
  );
}

export function getV2ExecutionOrders(): Promise<ApiV2Envelope<OrdersData>> {
  return fetchV2Contract<OrdersData>(
    '/api/v2/execution/orders',
    ['orders'],
    'Order endpoint is unavailable.',
    { mode: 'paper' },
  );
}

export function getV2Executions(): Promise<ApiV2Envelope<ExecutionsData>> {
  return fetchV2Contract<ExecutionsData>(
    '/api/v2/execution/executions',
    ['executions'],
    'Execution endpoint is unavailable.',
    { mode: 'paper' },
  );
}

export function getV2AuditEvents(): Promise<ApiV2Envelope<AuditEventsData>> {
  return fetchV2Contract<AuditEventsData>(
    '/api/v2/execution/audit-events',
    ['audit_events'],
    'Execution audit event endpoint is unavailable.',
    { mode: 'paper' },
  );
}
