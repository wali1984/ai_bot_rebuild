import type { ApiV2Envelope, SignalData } from '../types/apiV2';
import { safeV2MarketSymbol, safeV2MarketTimeframe } from './v2Market';
import { fetchV2Contract, unavailableV2Response } from './v2Shared';

export function getV2Signals(symbol?: string, timeframe?: string): Promise<ApiV2Envelope<SignalData>> {
  const safeSymbol = symbol ? safeV2MarketSymbol(symbol) : undefined;
  if (symbol && !safeSymbol) {
    return Promise.resolve(unavailableV2Response<SignalData>(
      '/api/v2/signals?symbol={symbol}',
      ['symbol', 'active_signal'],
      'Enter a valid market symbol.',
      { mode: 'paper' },
    ));
  }
  const safeTimeframe = timeframe ? safeV2MarketTimeframe(timeframe) : undefined;
  if (timeframe && !safeTimeframe) {
    return Promise.resolve(unavailableV2Response<SignalData>(
      '/api/v2/signals?timeframe={timeframe}',
      ['timeframe', 'active_signal'],
      'Select a supported signal timeframe.',
      { symbol: safeSymbol, mode: 'paper' },
    ));
  }
  const params = new URLSearchParams();
  if (safeSymbol) params.set('symbol', safeSymbol);
  if (safeTimeframe && safeTimeframe !== '5m') params.set('timeframe', safeTimeframe);
  const query = params.toString() ? `?${params.toString()}` : '';
  return fetchV2Contract<SignalData>(
    `/api/v2/signals${query}`,
    ['active_signal'],
    'Signal endpoint is unavailable.',
    { mode: 'paper' },
  );
}
