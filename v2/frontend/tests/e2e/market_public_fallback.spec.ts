import { expect, test } from '@playwright/test';
import { getV2MarketCandles, getV2MarketOverview } from '../../src/api/v2Market';

function contractUnavailable(endpoint: string, missingFields: string[]) {
  return {
    data: null,
    source: 'unavailable',
    source_type: 'unavailable',
    endpoint,
    timestamp: null,
    received_at: '2026-06-15T12:00:00.000Z',
    lag_ms: null,
    stale: true,
    missing_fields: missingFields,
    warnings: ['Local V2 market contract unavailable.'],
    symbol: null,
    exchange: null,
    mode: 'read_only',
  };
}

function installFetchMock(handler: (url: string) => unknown): void {
  globalThis.fetch = (async (input: RequestInfo | URL) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const payload = handler(url);
    return new Response(JSON.stringify(payload), {
      status: 200,
      headers: { 'content-type': 'application/json' },
    });
  }) as typeof fetch;
}

test.describe('V2 market public fallback', () => {
  const originalFetch = globalThis.fetch;

  test.afterEach(() => {
    globalThis.fetch = originalFetch;
  });

  test('recovers overview symbols and 24h ticker data when the local market contract is unavailable', async () => {
    const closeTime = Date.now() - 1_000;
    installFetchMock((url) => {
      if (url === '/api/v2/market/overview') {
        return contractUnavailable('/api/v2/market/overview', ['symbols', 'markets']);
      }
      if (url.startsWith('https://fapi.binance.com/fapi/v1/ticker/24hr')) {
        return [
          {
            symbol: 'ETHUSDT',
            lastPrice: '2500',
            priceChangePercent: '1.50',
            highPrice: '2600',
            lowPrice: '2400',
            volume: '20000',
            quoteVolume: '500000000',
            count: 200,
            weightedAvgPrice: '2490',
            closeTime,
          },
          {
            symbol: 'BTCUSDT',
            lastPrice: '100000',
            priceChangePercent: '2.50',
            highPrice: '101000',
            lowPrice: '99000',
            volume: '15000',
            quoteVolume: '1500000000',
            count: 300,
            weightedAvgPrice: '100100',
            closeTime,
          },
          {
            symbol: 'BTCUSD_PERP',
            lastPrice: '100000',
            priceChangePercent: '1.00',
            highPrice: '101000',
            lowPrice: '99000',
            volume: '1',
            quoteVolume: '1',
            count: 1,
            weightedAvgPrice: '100000',
            closeTime,
          },
        ];
      }
      throw new Error(`Unexpected fetch ${url}`);
    });

    const overview = await getV2MarketOverview();

    expect(overview.source).toContain('Binance USD-M public market data');
    expect(overview.data?.symbols.slice(0, 2)).toEqual(['BTCUSDT', 'ETHUSDT']);
    expect(overview.data?.timeframes).toContain('5m');
    expect(overview.data?.tickers?.find((ticker) => ticker.symbol === 'BTCUSDT')?.change_24h).toBeCloseTo(0.025);
    expect(overview.warnings.join(' ')).toContain('read-only Binance USD-M public market fallback');
  });

  test('uses only fully closed candles in public candle fallback', async () => {
    const now = Date.now();
    const closedClose = now - 60_000;
    const unfinishedClose = now + 60_000;

    installFetchMock((url) => {
      if (url.startsWith('/api/v2/market/BTCUSDT/candles')) {
        return contractUnavailable('/api/v2/market/BTCUSDT/candles', ['candles']);
      }
      if (url.startsWith('https://fapi.binance.com/fapi/v1/klines')) {
        const parsed = new URL(url);
        expect(parsed.searchParams.get('symbol')).toBe('BTCUSDT');
        expect(parsed.searchParams.get('interval')).toBe('5m');
        return [
          [closedClose - 300_000, '100', '110', '90', '105', '12', closedClose, '1260', 20, '6', '630', '0'],
          [now, '105', '115', '100', '112', '13', unfinishedClose, '1456', 21, '7', '784', '0'],
        ];
      }
      throw new Error(`Unexpected fetch ${url}`);
    });

    const candles = await getV2MarketCandles('BTCUSDT', '5m');

    expect(candles.data?.timeframe).toBe('5m');
    expect(candles.data?.candles).toHaveLength(1);
    expect(candles.data?.candles[0]?.close).toBe(105);
    expect(candles.data?.candles[0]?.is_final).toBe(true);
    expect(candles.warnings.join(' ')).toContain('unfinished candles are filtered out');
  });
});
