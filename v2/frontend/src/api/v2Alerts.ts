import type { AlertsData, ApiV2Envelope } from '../types/apiV2';
import { safeV2MarketSymbol } from './v2Market';
import { fetchV2Contract, unavailableV2Response } from './v2Shared';

export interface AlertMutationRequest {
  alert_type?: string;
  symbol?: string;
  condition?: string;
  threshold?: number | null;
  enabled?: boolean;
  muted?: boolean;
  note?: string | null;
}

export function getV2Alerts(): Promise<ApiV2Envelope<AlertsData>> {
  return fetchV2Contract<AlertsData>(
    '/api/v2/alerts',
    ['alert_repository', 'notification_delivery'],
    'Alert service unavailable.',
  );
}

export function safeAlertMutationSymbol(symbol: string | null | undefined): string | undefined {
  if (symbol == null || symbol === '') return undefined;
  return safeV2MarketSymbol(symbol);
}

function invalidAlertSymbol(): Promise<ApiV2Envelope<AlertsData>> {
  return Promise.resolve(unavailableV2Response<AlertsData>(
    '/api/v2/alerts',
    ['symbol', 'alert_repository'],
    'Enter a valid market symbol.',
    { mode: 'paper' },
  ));
}

async function mutateAlert(path: string, method: 'POST' | 'PUT' | 'DELETE', body?: AlertMutationRequest): Promise<ApiV2Envelope<AlertsData>> {
  const safeSymbol = safeAlertMutationSymbol(body?.symbol);
  if (body?.symbol != null && body.symbol !== '' && !safeSymbol) {
    return invalidAlertSymbol();
  }
  const nextBody = body && safeSymbol ? { ...body, symbol: safeSymbol } : body;
  const response = await fetch(path, {
    method,
    credentials: 'include',
    headers: nextBody ? { 'Content-Type': 'application/json' } : undefined,
    body: nextBody ? JSON.stringify(nextBody) : undefined,
  });
  if (!response.ok) throw new Error('Alert action unavailable');
  return response.json() as Promise<ApiV2Envelope<AlertsData>>;
}

export function createV2Alert(request: Required<Pick<AlertMutationRequest, 'alert_type' | 'condition'>> & AlertMutationRequest): Promise<ApiV2Envelope<AlertsData>> {
  return mutateAlert('/api/v2/alerts', 'POST', request);
}

export function updateV2Alert(alertId: string, request: AlertMutationRequest): Promise<ApiV2Envelope<AlertsData>> {
  return mutateAlert(`/api/v2/alerts/${encodeURIComponent(alertId)}`, 'PUT', request);
}

export function deleteV2Alert(alertId: string): Promise<ApiV2Envelope<AlertsData>> {
  return mutateAlert(`/api/v2/alerts/${encodeURIComponent(alertId)}`, 'DELETE');
}
