import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';
import { marketDataStreamTestHooks } from '../../src/hooks/useMarketDataStream';
import { proChartTestHooks } from '../../src/components/charts/ProChart';
import { candleEnvelopeCanDriveTradingChart, indicatorSourceLabel } from '../../src/components/trade/TradingChartPanel';
import { tradeTerminalTestHooks } from '../../src/hooks/useTradeTerminal';

const VIEWPORTS = [
  { name: '1440x900', width: 1440, height: 900 },
  { name: '390x844', width: 390, height: 844 },
] as const;

async function mockProChartData(page: Page, options: { indicators?: 'available' | 'unavailable' } = {}): Promise<void> {
  const candles = [
    { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: true },
    { time: 1781323260, open: 100150, high: 100400, low: 100120, close: 100350, volume: 18.1, is_final: true },
    { time: 1781323320, open: 100350, high: 100500, low: 100300, close: 100420, volume: 14.2, is_final: true },
  ];

  await page.route('**/api/v2/market/BTCUSDT/candles**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: { symbol: 'BTCUSDT', timeframe: '5m', candles, candle_count: candles.length },
        source: 'mocked candle source',
        source_type: 'api',
        endpoint: '/api/v2/market/BTCUSDT/candles?timeframe=5m',
        timestamp: '2026-06-13T03:00:00Z',
        received_at: '2026-06-13T03:00:01Z',
        lag_ms: 1000,
        stale: false,
        missing_fields: [],
        warnings: ['Read-only mocked public candle source'],
        symbol: 'BTCUSDT',
        exchange: 'Binance USD-M',
        mode: 'read_only',
      }),
    });
  });

  await page.route('**/api/v2/market/BTCUSDT/indicators**', async (route) => {
    const indicatorsAvailable = options.indicators === 'available';
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        data: {
          symbol: 'BTCUSDT',
          timeframe: '5m',
          ema20: indicatorsAvailable ? candles.map((candle) => ({ time: candle.time, value: candle.close })) : [],
          ema50: indicatorsAvailable ? candles.map((candle) => ({ time: candle.time, value: candle.close - 50 })) : [],
          bb_upper: indicatorsAvailable ? candles.map((candle) => ({ time: candle.time, value: candle.close + 120 })) : [],
          bb_lower: indicatorsAvailable ? candles.map((candle) => ({ time: candle.time, value: candle.close - 120 })) : [],
          bb_middle: indicatorsAvailable ? candles.map((candle) => ({ time: candle.time, value: candle.close })) : [],
          ai_target: [],
          indicator_count: indicatorsAvailable ? 15 : 0,
          controls_enabled: indicatorsAvailable,
        },
        source: indicatorsAvailable ? 'mocked public kline indicator source' : 'unavailable',
        source_type: indicatorsAvailable ? 'api' : 'unavailable',
        endpoint: '/api/v2/market/BTCUSDT/indicators?timeframe=5m',
        timestamp: indicatorsAvailable ? '2026-06-13T03:00:00Z' : null,
        received_at: '2026-06-13T03:00:01Z',
        lag_ms: indicatorsAvailable ? 1000 : null,
        stale: !indicatorsAvailable,
        missing_fields: indicatorsAvailable ? ['ai_target'] : ['ema20', 'ema50', 'bb_upper', 'bb_lower', 'bb_middle', 'ai_target', 'indicator_repository'],
        warnings: indicatorsAvailable
          ? ['EMA and Bollinger indicators are derived from Binance public USD-M closed klines']
          : ['Indicator source unavailable'],
        symbol: 'BTCUSDT',
        exchange: 'Binance USD-M',
        mode: 'read_only',
      }),
    });
  });

  await page.route('**/operator_runtime/v2_professional_market_chart/latest/BTCUSDT_5m_chart.json', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        status: 'CURRENT',
        candles,
        volume: candles.map((candle) => ({ time: candle.time, value: candle.volume })),
        overlays: {
          ema20: candles.map((candle) => ({ time: candle.time, value: candle.close })),
          ema50: candles.map((candle) => ({ time: candle.time, value: candle.close - 100 })),
          price_target: candles.map((candle) => ({ time: candle.time, value: candle.close + 200 })),
        },
        signal: { selected_action: 'BUY', confidence_calibrated: 0.72, target_line_value: 100800 },
      }),
    });
  });

  await page.route('**/api/v1/chart/coinank/BTCUSDT/5m**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        oi_kline: candles.map((candle) => ({ time: candle.time * 1000, value: 1200000000 + candle.volume * 1000 })),
        net_long: candles.map((candle) => ({ time: candle.time * 1000, value: candle.volume })),
        funding_kline: [],
        ls_kline: [],
        cvd: [],
        stats: {
          market_cap: 1900000000000,
          total_oi: 1200000000,
          ls_ratio: 1.12,
          funding_rate: 0.0001,
          fear_greed: 61,
        },
      }),
    });
  });
}

test.describe('ProChart realtime contract', () => {
  test('keeps chart and symbol data on realtime resources instead of component polling', () => {
    const files = [
      'src/components/charts/ProChart.tsx',
      'src/components/trade/TradingChartPanel.tsx',
      'src/components/charts/ProChartSymbolPanel.tsx',
      'src/hooks/useSymbolData.ts',
    ];

    for (const file of files) {
      const source = readFileSync(path.resolve(process.cwd(), file), 'utf8');
      expect(source, file).toContain('useRealtimeResource');
      expect(source, file).toContain("source_type: 'websocket'");
      expect(source, file).not.toContain('setInterval(');
      expect(source, file).not.toContain('fetch(');
    }
  });

  test('uses a bounded idle-rotation window for silent realtime endpoints', () => {
    expect(marketDataStreamTestHooks.streamIdleRotateMs(1_000)).toBe(3_500);
    expect(marketDataStreamTestHooks.streamIdleRotateMs(2_000)).toBe(4_000);
    expect(marketDataStreamTestHooks.streamIdleRotateMs(5_000)).toBe(10_000);
  });

  test('prefers native read-only Binance public stream before backend fallbacks', () => {
    const urls = marketDataStreamTestHooks.streamUrls('BTCUSDT', 2_000, '5m');

    expect(urls[0]).toContain('wss://fstream.binance.com/stream');
    expect(urls[0]).toContain('btcusdt@kline_5m');
    expect(urls.some((url) => url.includes('/api/v2/ws/market-data'))).toBe(true);
    expect(urls.some((url) => url.includes('/ws/market-data'))).toBe(true);
  });

  test('labels WebSocket stream data as realtime and fresh resource data as current', () => {
    const envelopeBase = {
      data: null,
      endpoint: '/api/v2/market/BTCUSDT/ticker',
      timestamp: '2026-06-14T00:00:00Z',
      received_at: '2026-06-14T00:00:01Z',
      lag_ms: 1000,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

	    expect(proChartTestHooks.proChartStreamDomainStatus({
	      ...envelopeBase,
	      source: 'binance_usdm_public_websocket_adapter',
	      source_type: 'websocket' as const,
	      stale: false,
	    }).label).toBe('Realtime');
    expect(proChartTestHooks.proChartStreamDomainStatus({
      ...envelopeBase,
      source: 'market_polling',
      source_type: 'api' as const,
      stale: false,
    }).label).toBe('Current');
	    expect(proChartTestHooks.proChartStreamDomainStatus({
	      ...envelopeBase,
	      source: 'safe_api_contract_stream',
	      endpoint: '/api/v2/ws/market-data',
	      source_type: 'websocket' as const,
	      stale: false,
	    }).label).toBe('Current');
    expect(proChartTestHooks.proChartStreamDomainStatus({
      ...envelopeBase,
      source: 'market_polling',
      source_type: 'api' as const,
      stale: true,
    }).label).toBe('Stale');
    expect(proChartTestHooks.proChartStreamDomainStatus(null).label).toBe('Connecting');
  });

  test('labels stale ProChart stream state before connected/frame states', () => {
    expect(proChartTestHooks.proChartLiveCandleLabel({
      stale: true,
      liveCandle: null,
      candleIsStreamBacked: true,
      hasStreamFrame: true,
      streamSource: 'binance_usdm_public_websocket',
      connected: true,
    })).toBe('Stream data stale');
    expect(proChartTestHooks.proChartLiveCandleLabel({
      stale: false,
      liveCandle: { is_final: false },
      candleIsStreamBacked: true,
      hasStreamFrame: true,
      streamSource: 'binance_usdm_public_websocket',
      connected: true,
    })).toBe('Stream forming candle');
    expect(proChartTestHooks.proChartLiveCandleLabel({
      stale: false,
      liveCandle: null,
      candleIsStreamBacked: false,
      hasStreamFrame: false,
      streamSource: 'safe_api_contract_stream',
      connected: true,
    })).toBe('Waiting for stream frame');
  });

  test('does not build realtime stream URLs for malformed symbols or timeframes', () => {
    expect(marketDataStreamTestHooks.safeMarketStreamSymbol(' btcusdt ')).toBe('BTCUSDT');
    expect(marketDataStreamTestHooks.safeMarketStreamSymbol('btcusdt../')).toBeNull();
    expect(marketDataStreamTestHooks.safeMarketStreamSymbol('ETH-USDT')).toBeNull();
    expect(marketDataStreamTestHooks.safeMarketStreamTimeframe('5m')).toBe('5m');
    expect(marketDataStreamTestHooks.safeMarketStreamTimeframe('2m')).toBeNull();
    expect(marketDataStreamTestHooks.safeMarketStreamTimeframe('1m@trade')).toBeNull();
    expect(marketDataStreamTestHooks.streamUrls('btcusdt../', 2_000, '1m')).toEqual([]);
    expect(marketDataStreamTestHooks.streamUrls('BTCUSDT', 2_000, '1m@trade')).toEqual([]);
  });

  test('rejects malformed or unknown native public stream channels', () => {
    expect(marketDataStreamTestHooks.nativeStreamMatchesRequest('btcusdt@ticker', 'BTCUSDT', '1m')).toBe(true);
    expect(marketDataStreamTestHooks.nativeStreamMatchesRequest('@ticker', 'BTCUSDT', '1m')).toBe(false);
    expect(marketDataStreamTestHooks.nativeStreamMatchesRequest('btcusdt@unknown', 'BTCUSDT', '1m')).toBe(false);
    expect(marketDataStreamTestHooks.nativeStreamMatchesRequest('btcusdt@kline_1m@trade', 'BTCUSDT', '1m')).toBe(false);
  });

  test('keeps a bounded native kline candle history for ProChart fallback rendering', () => {
    let state = marketDataStreamTestHooks.initialMarketDataStreamState();
    const frame = (openTime: number, close: string, final = false) => ({
      stream: 'btcusdt@kline_5m',
      data: {
        E: openTime + 60_000,
        k: {
          t: openTime,
          T: openTime + 299_999,
          o: '100000',
          h: '100600',
          l: '99900',
          c: close,
          v: '12.5',
          q: '1250000',
          n: 144,
          V: '6',
          Q: '600000',
          x: final,
        },
      },
    });

    state = marketDataStreamTestHooks.handleNativeMessage(state, frame(1781323200000, '100100', true), 'BTCUSDT', '5m');
    state = marketDataStreamTestHooks.handleNativeMessage(state, frame(1781323500000, '100300'), 'BTCUSDT', '5m');
    state = marketDataStreamTestHooks.handleNativeMessage(state, frame(1781323500000, '100450'), 'BTCUSDT', '5m');

    expect(state.candles?.data?.candles).toHaveLength(2);
    expect(state.candles?.data?.candle_count).toBe(2);
    expect(state.candles?.data?.candles.at(-1)?.close).toBe(100450);
    expect(state.liveCandle?.close).toBe(100450);
  });

  test('builds a display candle from native trade ticks when kline frames are absent', () => {
    let state = marketDataStreamTestHooks.initialMarketDataStreamState();
    const tradeFrame = (eventTime: number, price: string, size = '0.25') => ({
      stream: 'btcusdt@trade',
      data: {
        E: eventTime,
        T: eventTime,
        p: price,
        q: size,
        m: false,
      },
    });

    state = marketDataStreamTestHooks.handleNativeMessage(
      state,
      tradeFrame(1781323210000, '100100'),
      'BTCUSDT',
      '5m',
    );
    state = marketDataStreamTestHooks.handleNativeMessage(
      state,
      tradeFrame(1781323220000, '100250'),
      'BTCUSDT',
      '5m',
    );

    expect(state.candles?.source).toBe('binance_usdm_public_trade_candle_ws');
    expect(state.candles?.data?.candles).toHaveLength(1);
    expect(state.candles?.data?.candles[0]?.open_time_ms).toBe(1781323200000);
    expect(state.candles?.data?.candles[0]?.open).toBe(100100);
    expect(state.candles?.data?.candles[0]?.high).toBe(100250);
    expect(state.candles?.data?.candles[0]?.low).toBe(100100);
    expect(state.candles?.data?.candles[0]?.close).toBe(100250);
    expect(state.candles?.data?.candles[0]?.is_final).toBe(false);
    expect(state.liveCandle?.close).toBe(100250);
    expect(state.candles?.warnings.join(' ')).toContain('display-only');
  });

  test('merges realtime ProChart candle rows over REST or typed history by candle time', () => {
    const baseRows = [
      { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: true },
      { time: 1781323500, open: 100150, high: 100400, low: 100120, close: 100300, volume: 18.1, is_final: true },
    ];
    const streamRows = [
      { time: 1781323500, open: 100150, high: 100550, low: 100120, close: 100480, volume: 22.4, is_final: false, source: 'binance_usdm_public_kline_ws' },
      { time: 1781323800, open: 100480, high: 100700, low: 100430, close: 100620, volume: 16.2, is_final: false, source: 'binance_usdm_public_kline_ws' },
    ];

    const merged = proChartTestHooks.mergeRealtimeCandleRows(baseRows, streamRows);

    expect(merged).toHaveLength(3);
    expect(merged.map((row) => row.time)).toEqual([1781323200, 1781323500, 1781323800]);
    expect(merged[1].close).toBe(100480);
    expect(merged[1].source).toBe('binance_usdm_public_kline_ws');
  });

  test('normalizes second and millisecond event timestamps for realtime freshness', () => {
    expect(marketDataStreamTestHooks.timestampMilliseconds(1781323200)).toBe(1781323200000);
    expect(marketDataStreamTestHooks.timestampMilliseconds(1781323200000)).toBe(1781323200000);
    expect(marketDataStreamTestHooks.eventIso(1781323200)).toBe('2026-06-13T04:00:00.000Z');
  });

  test('filters invalid OHLC rows before ProChart rendering', () => {
    expect(proChartTestHooks.validOhlc(100000, 100250, 99900, 100150)).toBe(true);
    expect(proChartTestHooks.validOhlc(100000, 99900, 100250, 100150)).toBe(false);
    expect(proChartTestHooks.validOhlc(100000, 100250, 99900, 0)).toBe(false);
    expect(proChartTestHooks.validOhlc(100000, Number.NaN, 99900, 100150)).toBe(false);
  });

  test('accepts current WebSocket candle envelopes without direct REST kline helpers', () => {
    const envelope = {
      data: {
        symbol: 'BTCUSDT',
        timeframe: '5m',
        candles: [
          { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: true },
          { time: 1781323500, open: 100150, high: 100400, low: 100120, close: 100350, volume: 18.1, is_final: true },
        ],
        candle_count: 2,
      },
      source: '/api/v2/ws/resource',
      source_type: 'websocket' as const,
      endpoint: '/api/v2/market/BTCUSDT/candles?timeframe=5m',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only WebSocket candle resource'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(proChartTestHooks.typedEnvelopeCanDriveRealtimeChart(envelope, 'BTCUSDT', '5m')).toBe(true);
    expect(candleEnvelopeCanDriveTradingChart(envelope, 'BTCUSDT', '5m')).toBe(true);
    expect(proChartTestHooks.typedEnvelopeCanDriveRealtimeChart({ ...envelope, stale: true }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.typedEnvelopeCanDriveRealtimeChart({ ...envelope, source_type: 'static_payload' as const }, 'BTCUSDT', '5m')).toBe(false);
  });

  test('withholds stale or static candle data from the trading chart panel', () => {
    const candle = { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: true };
    const envelope = {
      data: { symbol: 'BTCUSDT', timeframe: '5m', candles: [candle], candle_count: 1 },
      source: 'candle source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/candles?timeframe=5m',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(candleEnvelopeCanDriveTradingChart(envelope)).toBe(true);
    expect(candleEnvelopeCanDriveTradingChart(envelope, 'BTCUSDT', '5m')).toBe(true);
    expect(candleEnvelopeCanDriveTradingChart({ ...envelope, symbol: 'ETHUSDT', data: { ...envelope.data, symbol: 'ETHUSDT' } }, 'BTCUSDT', '5m')).toBe(false);
    expect(candleEnvelopeCanDriveTradingChart({ ...envelope, data: { ...envelope.data, timeframe: '1h' } }, 'BTCUSDT', '5m')).toBe(false);
    expect(candleEnvelopeCanDriveTradingChart({ ...envelope, stale: true })).toBe(false);
    expect(candleEnvelopeCanDriveTradingChart({ ...envelope, source_type: 'static_payload' as const })).toBe(false);
    expect(candleEnvelopeCanDriveTradingChart({ ...envelope, source_type: 'unavailable' as const })).toBe(false);
  });

  test('uses only fresh derivatives for ProChart overlays', () => {
    const derivatives = {
      data: {
        symbol: 'BTCUSDT',
        funding_rate: 0.0001,
        next_funding: '2026-06-13T08:00:00Z',
        open_interest: 1200000000,
        open_interest_change: null,
        funding_history: [{ time: '2026-06-13T03:00:00Z', value: 0.0001 }],
        open_interest_history: [{ time: '2026-06-13T03:00:00Z', value: 1200000000 }],
        liquidations_1h: null,
        liquidations_24h: null,
        long_short_ratio: 1.12,
        basis: null,
        exchange_comparison: [],
      },
      source: 'derivatives source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/derivatives',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(proChartTestHooks.derivativeEnvelopeCanDriveOverlay(derivatives)).toBe(true);
    expect(proChartTestHooks.derivativeEnvelopeCanDriveOverlay({ ...derivatives, stale: true })).toBe(false);
    expect(proChartTestHooks.derivativeEnvelopeCanDriveOverlay({ ...derivatives, source_type: 'static_payload' as const })).toBe(false);
    expect(proChartTestHooks.derivativeEnvelopeCanDriveOverlay({ ...derivatives, source_type: 'unavailable' as const, data: null })).toBe(false);
  });

  test('clears stale derivative overlay series when overlay source becomes unavailable', () => {
    const calls = {
      oi: 0,
      netLong: 0,
      netShort: 0,
    };
    const makeSeries = (key: keyof typeof calls) => ({
      setData(rows: never[]) {
        expect(rows).toEqual([]);
        calls[key] += 1;
      },
    });

    proChartTestHooks.clearDerivativeOverlaySeries(
      makeSeries('oi'),
      makeSeries('netLong'),
      makeSeries('netShort'),
    );

    expect(calls).toEqual({ oi: 1, netLong: 1, netShort: 1 });
  });

  test('strips static chart overlays and AI targets from realtime ProChart payloads', () => {
    const payload = proChartTestHooks.realtimeChartPayload(
      [{ time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150 }],
      [{ time: 1781323200, value: 21.5 }],
      { is_final: false },
    );

    expect(payload.status).toBe('CURRENT_WITH_PARTIAL_STREAM_CANDLE');
    expect(payload.candles).toHaveLength(1);
    expect(payload.volume).toHaveLength(1);
    expect(payload.overlays).toEqual({});
    expect(payload.signal).toBeUndefined();
  });

  test('enables ProChart indicator controls only from fresh indicator sources', () => {
    const indicators = {
      data: {
        symbol: 'BTCUSDT',
        timeframe: '5m',
        ema20: [{ time: 1781323200, value: 100100 }],
        ema50: [],
        bb_upper: [],
        bb_lower: [],
        bb_middle: [],
        ai_target: [],
        indicator_count: 1,
        controls_enabled: true,
      },
      source: 'indicator source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/indicators?timeframe=5m',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls(indicators, 'BTCUSDT', '5m')).toBe(true);
    expect(proChartTestHooks.indicatorSeriesAvailable(indicators, 'BTCUSDT', '5m', ['ema20', 'ema50'])).toBe(true);
    expect(proChartTestHooks.indicatorSeriesAvailable(indicators, 'BTCUSDT', '5m', ['bb_upper', 'bb_lower', 'bb_middle'])).toBe(false);
    expect(proChartTestHooks.indicatorSeriesAvailable(indicators, 'BTCUSDT', '5m', ['ai_target'])).toBe(false);
    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls({ ...indicators, stale: true }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls({ ...indicators, source_type: 'static_payload' as const }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls({ ...indicators, data: { ...indicators.data, controls_enabled: false } }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls({ ...indicators, data: { ...indicators.data, indicator_count: 0 } }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls({ ...indicators, data: { ...indicators.data, symbol: 'ETHUSDT' } }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.indicatorEnvelopeCanEnableControls({ ...indicators, data: { ...indicators.data, timeframe: '1h' } }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.indicatorControlTitle(indicators, 'BTCUSDT', '5m', ['ema20', 'ema50'], 'Toggle EMA overlay', 'EMA')).toBe('Toggle EMA overlay');
    expect(proChartTestHooks.indicatorControlTitle(indicators, 'BTCUSDT', '5m', ['ai_target'], 'Toggle AI target overlay', 'AI target')).toContain('Indicator source connecting');
    expect(proChartTestHooks.indicatorControlTitle({ ...indicators, stale: true }, 'BTCUSDT', '5m', ['ema20'], 'Toggle EMA overlay', 'EMA')).toContain('Indicator source connecting');
  });

  test('maps fresh indicators into ProChart overlay series', () => {
    const indicators = {
      data: {
        symbol: 'BTCUSDT',
        timeframe: '5m',
        ema20: [{ time: 1781323200, value: 100100 }],
        ema50: [{ time: '2026-06-13T03:05:00Z', value: 100050 }],
        bb_upper: [{ time: 1781323200, value: 100300 }],
        bb_lower: [{ time: 1781323200, value: 99900 }],
        bb_middle: [{ time: 1781323200, value: 100100 }],
        ai_target: [{ time: 1781323200, value: 100800 }],
        indicator_count: 6,
        controls_enabled: true,
      },
      source: 'indicator source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/indicators?timeframe=5m',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    const overlay = proChartTestHooks.indicatorOverlayFromEnvelope(indicators, 'BTCUSDT', '5m');
    if (!overlay) throw new Error('Expected current indicator overlay evidence');

    expect(overlay.ema20).toEqual([{ time: 1781323200, value: 100100 }]);
    expect(overlay.ema50).toEqual([{ time: 1781319900, value: 100050 }]);
    expect(overlay.bb_upper).toHaveLength(1);
    expect(overlay.bb_lower).toHaveLength(1);
    expect(overlay.price_target).toEqual([{ time: 1781323200, value: 100800 }]);
    expect(proChartTestHooks.indicatorEvidenceSummary(indicators, 'BTCUSDT', '5m')).toContain('EMA, Bollinger Bands, AI target');
    expect(proChartTestHooks.indicatorOverlayFromEnvelope({ ...indicators, stale: true }, 'BTCUSDT', '5m')).toEqual({});
    expect(proChartTestHooks.indicatorOverlayFromEnvelope({ ...indicators, source_type: 'static_payload' as const }, 'BTCUSDT', '5m')).toEqual({});
    expect(proChartTestHooks.indicatorOverlayFromEnvelope({ ...indicators, data: { ...indicators.data, symbol: 'ETHUSDT' } }, 'BTCUSDT', '5m')).toEqual({});
  });

  test('labels shared trading chart indicator source states honestly', () => {
    const indicators = {
      data: {
        symbol: 'BTCUSDT',
        timeframe: '5m',
        ema20: [],
        ema50: [],
        bb_upper: [],
        bb_lower: [],
        bb_middle: [],
        ai_target: [],
        indicator_count: 0,
        controls_enabled: false,
      },
      source: 'unavailable',
      source_type: 'unavailable' as const,
      endpoint: '/api/v2/market/BTCUSDT/indicators?timeframe=5m',
      timestamp: null,
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: null,
      stale: true,
      missing_fields: ['indicator_repository'],
      warnings: ['Indicator source unavailable'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(indicatorSourceLabel(null)).toBe('Indicator source connecting');
    expect(indicatorSourceLabel(indicators)).toBe('Indicator source connecting');
    expect(indicatorSourceLabel({ ...indicators, source_type: 'api' as const, source: 'indicator api', stale: true })).toBe('Stale indicator source');
    expect(indicatorSourceLabel({ ...indicators, source_type: 'static_payload' as const, source: 'static chart file', stale: false })).toBe('Static indicators withheld');
    expect(indicatorSourceLabel({ ...indicators, source_type: 'api' as const, source: 'indicator api', stale: false })).toBe('Indicators connecting');
    expect(indicatorSourceLabel({
      ...indicators,
      source_type: 'api' as const,
      source: 'indicator api',
      stale: false,
      data: { ...indicators.data, controls_enabled: true, indicator_count: 1, ema20: [{ time: 1781323200, value: 100100 }] },
    })).toBe('Indicators available');
  });

  test('trade terminal does not select stale or static stream envelopes as realtime data', () => {
    const ticker = {
      data: {
        symbol: 'BTCUSDT',
        last_price: 100150,
        mark_price: null,
        index_price: null,
        change_1h: null,
        change_4h: null,
        change_24h: null,
        high_24h: null,
        low_24h: null,
        volume_24h: null,
        turnover_24h: null,
        funding_rate: null,
        next_funding: null,
        open_interest: null,
        open_interest_change: null,
        bid: null,
        ask: null,
        spread_bps: null,
      },
      source: 'read-only public stream',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(tradeTerminalTestHooks.realtimeEnvelopeMatchesSymbol(ticker, 'BTCUSDT')).toBe(true);
    expect(tradeTerminalTestHooks.realtimeEnvelopeMatchesSymbol({ ...ticker, stale: true }, 'BTCUSDT')).toBe(false);
    expect(tradeTerminalTestHooks.realtimeEnvelopeMatchesSymbol({ ...ticker, source_type: 'static_payload' as const }, 'BTCUSDT')).toBe(false);
    expect(tradeTerminalTestHooks.realtimeEnvelopeMatchesSymbol({ ...ticker, symbol: 'ETHUSDT', data: { ...ticker.data, symbol: 'ETHUSDT' } }, 'BTCUSDT')).toBe(false);
  });

  test('trade terminal only shows trader-specific activity source labels after scope proof', () => {
    const envelope = {
      data: {
        account_specific: true,
        trader_id: 'trader-wajidali1984',
        paper_account_id: 'paper-wajidali1984',
        orders: [],
      },
      source: 'local paper account repository',
      source_type: 'repository' as const,
      endpoint: '/api/v2/execution/orders',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      mode: 'paper' as const,
    };

    expect(tradeTerminalTestHooks.activitySourceLabel(envelope, true, 'Trader order source', 'Order source unavailable')).toBe('Trader order source');
    expect(tradeTerminalTestHooks.activitySourceLabel(envelope, false, 'Trader order source', 'Order source unavailable')).toBe('Order source unavailable');
    expect(tradeTerminalTestHooks.activitySourceLabel({ ...envelope, stale: true }, true, 'Trader order source', 'Order source unavailable')).toBe('Fallback data');
    expect(tradeTerminalTestHooks.activitySourceLabel({ ...envelope, source_type: 'static_payload' as const }, true, 'Trader order source', 'Order source unavailable')).toBe('Fallback data');
    expect(tradeTerminalTestHooks.activitySourceLabel({ ...envelope, source_type: 'unavailable' as const }, true, 'Trader order source', 'Order source unavailable')).toBe('Order source unavailable');
  });

  test('trade terminal labels stale market streams without connected copy', () => {
    expect(tradeTerminalTestHooks.marketStreamSourceLabel({
      streamSource: 'binance_usdm_public_websocket',
      connected: true,
      stale: false,
    })).toBe('Native public market stream connected');
    expect(tradeTerminalTestHooks.marketStreamSourceLabel({
      streamSource: 'safe_api_contract_stream',
      connected: true,
      stale: false,
    })).toBe('Live market stream connected');
    expect(tradeTerminalTestHooks.marketStreamSourceLabel({
      streamSource: 'safe_api_contract_stream',
      connected: true,
      stale: true,
    })).toBe('Market stream stale; using shared resource fallback');
  });

  test('rejects mismatched backend stream snapshots before they can update the chart', () => {
    const candle = { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: false };
    const envelope = {
      data: { symbol: 'BTCUSDT', timeframe: '5m', candles: [candle], candle_count: 1 },
      source: 'mocked backend market stream',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only backend stream snapshot'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    const matching = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: envelope, received_at: '2026-06-13T03:00:01Z', stale: false },
      'BTCUSDT',
      '5m',
    );
    expect(matching?.liveCandle?.close).toBe(100150);

    const wrongSymbol = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: { ...envelope, symbol: 'ETHUSDT', data: { ...envelope.data, symbol: 'ETHUSDT' } } },
      'BTCUSDT',
      '5m',
    );
    expect(wrongSymbol).toBeNull();

    const wrongTimeframe = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: { ...envelope, data: { ...envelope.data, timeframe: '1h' } } },
      'BTCUSDT',
      '5m',
    );
    expect(wrongTimeframe).toBeNull();
  });

  test('preserves previous backend stream panels when partial snapshots omit them', () => {
    const candle = { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: false };
    const candles = {
      data: { symbol: 'BTCUSDT', timeframe: '5m', candles: [candle], candle_count: 1 },
      source: 'mocked backend market stream',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only backend stream snapshot'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };
    const ticker = {
      data: {
        symbol: 'BTCUSDT',
        last_price: 100150,
        mark_price: null,
        index_price: null,
        change_1h: null,
        change_4h: null,
        change_24h: null,
        high_24h: null,
        low_24h: null,
        volume_24h: null,
        turnover_24h: null,
        funding_rate: null,
        next_funding: null,
        open_interest: null,
        open_interest_change: null,
        bid: null,
        ask: null,
        spread_bps: null,
      },
      source: 'mocked backend ticker stream',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only backend stream snapshot'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    const initial = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', ticker, candles, received_at: '2026-06-13T03:00:01Z', stale: false },
      'BTCUSDT',
      '5m',
    );
    expect(initial?.ticker?.data?.last_price).toBe(100150);
    expect(initial?.liveCandle?.close).toBe(100150);

    const partial = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', received_at: '2026-06-13T03:00:02Z', stale: false },
      'BTCUSDT',
      '5m',
      initial,
    );
    expect(partial?.ticker?.data?.last_price).toBe(100150);
    expect(partial?.candles?.data?.candle_count).toBe(1);
    expect(partial?.liveCandle?.close).toBe(100150);

    const stalePartial = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', received_at: '2026-06-13T03:00:03Z', stale: true, warnings: ['Backend snapshot stale'] },
      'BTCUSDT',
      '5m',
      initial,
    );
    expect(stalePartial?.stale).toBe(true);
    expect(stalePartial?.ticker?.stale).toBe(true);
    expect(stalePartial?.candles?.stale).toBe(true);
    expect(stalePartial?.liveCandle).toBeNull();
    expect(stalePartial?.warnings.join(' ')).toContain('Backend snapshot stale');
  });

  test('does not promote stale or static backend candle snapshots to live chart candles', () => {
    const candle = { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: false };
    const envelope = {
      data: { symbol: 'BTCUSDT', timeframe: '5m', candles: [candle], candle_count: 1 },
      source: 'mocked stale chart snapshot',
      source_type: 'static_payload' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: true,
      missing_fields: [],
      warnings: ['Fallback candle snapshot is stale'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    const staleStatic = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: envelope, received_at: '2026-06-13T03:00:01Z', stale: true },
      'BTCUSDT',
      '5m',
    );
    expect(staleStatic?.candles?.source_type).toBe('static_payload');
    expect(staleStatic?.liveCandle).toBeNull();

    const staleApi = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      {
        type: 'market_snapshot',
        candles: { ...envelope, source_type: 'api' as const, stale: true },
        received_at: '2026-06-13T03:00:01Z',
        stale: true,
      },
      'BTCUSDT',
      '5m',
    );
    expect(staleApi?.candles?.source_type).toBe('api');
    expect(staleApi?.liveCandle).toBeNull();

    const initial = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      {
        type: 'market_snapshot',
        candles: {
          ...envelope,
          source: 'mocked backend market stream',
          source_type: 'api' as const,
          stale: false,
          warnings: ['Read-only backend stream snapshot'],
        },
        received_at: '2026-06-13T03:00:00Z',
        stale: false,
      },
      'BTCUSDT',
      '5m',
    );
    expect(initial?.liveCandle?.close).toBe(100150);

    const staleAfterValid = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: envelope, received_at: '2026-06-13T03:00:01Z', stale: true },
      'BTCUSDT',
      '5m',
      initial,
    );
    expect(staleAfterValid?.candles?.source_type).toBe('static_payload');
    expect(staleAfterValid?.liveCandle).toBeNull();
  });

  test('rejects backend candle snapshots without explicit symbol and timeframe proof', () => {
    const candle = { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: false };
    const envelope = {
      data: { symbol: 'BTCUSDT', timeframe: '5m', candles: [candle], candle_count: 1 },
      source: 'mocked backend market stream',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only backend stream snapshot'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };
    const missingSymbolEnvelope = JSON.parse(JSON.stringify(envelope));
    delete missingSymbolEnvelope.symbol;
    delete missingSymbolEnvelope.data.symbol;
    const missingTimeframeEnvelope = JSON.parse(JSON.stringify(envelope));
    delete missingTimeframeEnvelope.data.timeframe;

    expect(marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: missingSymbolEnvelope },
      'BTCUSDT',
      '5m',
    )).toBeNull();
    expect(marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: missingTimeframeEnvelope },
      'BTCUSDT',
      '5m',
    )).toBeNull();
  });

  test('preserves the last valid backend stream candle when a fresh invalid snapshot arrives', () => {
    const validCandle = { time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5, is_final: false };
    const invalidCandle = { time: 1781323260, open: 100150, high: 100000, low: 100300, close: 100220, volume: 18.1, is_final: false };
    const envelope = {
      data: { symbol: 'BTCUSDT', timeframe: '5m', candles: [validCandle], candle_count: 1 },
      source: 'mocked backend market stream',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only backend stream snapshot'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    const valid = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      { type: 'market_snapshot', candles: envelope, received_at: '2026-06-13T03:00:01Z', stale: false },
      'BTCUSDT',
      '5m',
    );
    const invalid = marketDataStreamTestHooks.handleBackendSnapshotMessage(
      {
        type: 'market_snapshot',
        candles: { ...envelope, data: { ...envelope.data, candles: [invalidCandle] } },
        received_at: '2026-06-13T03:00:02Z',
        stale: false,
      },
      'BTCUSDT',
      '5m',
      valid,
    );

    expect(invalid?.liveCandle?.close).toBe(100150);
    expect(invalid?.warnings.join(' ')).toContain('Invalid backend stream candle frame ignored');
  });

  test('rejects mismatched native public stream frames before they can update the chart', () => {
    const state = marketDataStreamTestHooks.initialMarketDataStreamState();
    const btcKline = {
      stream: 'btcusdt@kline_5m',
      data: {
        E: 1781323201000,
        k: {
          t: 1781323200000,
          T: 1781323499999,
          o: '100000',
          h: '100250',
          l: '99900',
          c: '100150',
          v: '21.5',
          q: '2150000',
          n: 42,
          V: '11',
          Q: '1100000',
          x: false,
        },
      },
    };

    const matching = marketDataStreamTestHooks.handleNativeMessage(state, btcKline, 'BTCUSDT', '5m');
    expect(matching.liveCandle?.close).toBe(100150);

    const wrongSymbol = marketDataStreamTestHooks.handleNativeMessage(
      state,
      { ...btcKline, stream: 'ethusdt@kline_5m' },
      'BTCUSDT',
      '5m',
    );
    expect(wrongSymbol.liveCandle).toBeNull();

    const wrongTimeframe = marketDataStreamTestHooks.handleNativeMessage(
      state,
      { ...btcKline, stream: 'btcusdt@kline_1h' },
      'BTCUSDT',
      '5m',
    );
    expect(wrongTimeframe.liveCandle).toBeNull();
  });

  test('rejects invalid native public kline OHLC before ProChart can render it', () => {
    const state = marketDataStreamTestHooks.initialMarketDataStreamState();
    const valid = marketDataStreamTestHooks.handleNativeMessage(
      state,
      {
        stream: 'btcusdt@kline_5m',
        data: {
          E: 1781323201000,
          k: {
            t: 1781323200000,
            T: 1781323499999,
            o: '100000',
            h: '100250',
            l: '99900',
            c: '100150',
            v: '21.5',
            q: '2150000',
            n: 42,
            V: '11',
            Q: '1100000',
            x: false,
          },
        },
      },
      'BTCUSDT',
      '5m',
    );
    const invalid = marketDataStreamTestHooks.handleNativeMessage(
      valid,
      {
        stream: 'btcusdt@kline_5m',
        data: {
          E: 1781323261000,
          k: {
            t: 1781323260000,
            T: 1781323559999,
            o: '100200',
            h: '100100',
            l: '100300',
            c: '100250',
            v: '10',
            q: '1000000',
            n: 13,
            V: '5',
            Q: '500000',
            x: false,
          },
        },
      },
      'BTCUSDT',
      '5m',
    );

    expect(invalid.liveCandle?.close).toBe(100150);
    expect(invalid.candles?.data?.candle_count).toBe(1);
    expect(invalid.warnings.join(' ')).toContain('Invalid public kline frame ignored');
    expect(invalid.warnings.join(' ')).toContain('valid_ohlc');
  });

  test('clears live ProChart candles when the market stream becomes stale', () => {
    const active = marketDataStreamTestHooks.handleNativeMessage(
      marketDataStreamTestHooks.initialMarketDataStreamState(),
      {
        stream: 'btcusdt@kline_5m',
        data: {
          E: 1781323201000,
          k: {
            t: 1781323200000,
            T: 1781323499999,
            o: '100000',
            h: '100250',
            l: '99900',
            c: '100150',
            v: '21.5',
            q: '2150000',
            n: 42,
            V: '11',
            Q: '1100000',
            x: false,
          },
        },
      },
      'BTCUSDT',
      '5m',
    );

    expect(active.liveCandle?.close).toBe(100150);
    const stale = marketDataStreamTestHooks.markMarketStreamStale(
      active,
      'Market stream idle',
      ['Market stream endpoint was idle; rotating to the next read-only source'],
    );
    expect(stale.stale).toBe(true);
    expect(stale.candles?.stale).toBe(true);
    expect(stale.liveCandle).toBeNull();
    expect(stale.error).toBe('Market stream idle');
  });

  test('marks cached stream envelopes stale when realtime transport becomes stale', () => {
    const ticker = {
      data: {
        symbol: 'BTCUSDT',
        last_price: 100150,
        mark_price: null,
        index_price: null,
        change_1h: null,
        change_4h: null,
        change_24h: null,
        high_24h: null,
        low_24h: null,
        volume_24h: null,
        turnover_24h: null,
        funding_rate: null,
        next_funding: null,
        open_interest: null,
        open_interest_change: null,
        bid: null,
        ask: null,
        spread_bps: null,
      },
      source: 'binance_usdm_public_24h_ticker_ws',
      source_type: 'api' as const,
      endpoint: 'wss://fstream.binance.com/stream btcusdt@ticker',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };
    const staleTicker = marketDataStreamTestHooks.markEnvelopeStale(ticker, ['Market stream idle']);
    expect(staleTicker?.stale).toBe(true);
    expect(staleTicker?.warnings).toContain('Market stream idle');
    expect(tradeTerminalTestHooks.realtimeEnvelopeMatchesSymbol(staleTicker, 'BTCUSDT')).toBe(false);
  });

  test('does not replace the traded last price with book midprice', () => {
    const state = marketDataStreamTestHooks.handleNativeMessage(
      marketDataStreamTestHooks.initialMarketDataStreamState(),
      {
        stream: 'btcusdt@ticker',
        data: {
          E: 1781323201000,
          c: '100000',
          P: '1.5',
          h: '101000',
          l: '99000',
          v: '1200',
          q: '120000000',
        },
      },
      'BTCUSDT',
      '5m',
    );
    const next = marketDataStreamTestHooks.handleNativeMessage(
      state,
      {
        stream: 'btcusdt@bookTicker',
        data: {
          E: 1781323202000,
          b: '99990',
          a: '100010',
        },
      },
      'BTCUSDT',
      '5m',
    );

    expect(next.ticker?.data?.last_price).toBe(100000);
    expect(next.ticker?.data?.bid).toBe(99990);
    expect(next.ticker?.data?.ask).toBe(100010);
    expect(next.ticker?.data?.spread_bps).toBeGreaterThan(0);
  });

  test('rejects mismatched candle envelopes before rendering ProChart data', () => {
    const envelope = {
      data: {
        symbol: 'BTCUSDT',
        timeframe: '5m',
        candles: [{ time: 1781323200, open: 100000, high: 100250, low: 99900, close: 100150, volume: 21.5 }],
        candle_count: 1,
      },
      source: 'mocked candle source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/candles?timeframe=5m',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only mocked public candle source'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };
    const missingSymbolEnvelope = JSON.parse(JSON.stringify(envelope));
    delete missingSymbolEnvelope.symbol;
    delete missingSymbolEnvelope.data.symbol;
    const missingTimeframeEnvelope = JSON.parse(JSON.stringify(envelope));
    delete missingTimeframeEnvelope.data.timeframe;

    expect(proChartTestHooks.typedEnvelopeMatchesChart(envelope, 'BTCUSDT', '5m')).toBe(true);
    expect(proChartTestHooks.typedEnvelopeCanDriveRealtimeChart(envelope, 'BTCUSDT', '5m')).toBe(true);
    expect(proChartTestHooks.typedEnvelopeMatchesChart({ ...envelope, symbol: 'ETHUSDT', data: { ...envelope.data, symbol: 'ETHUSDT' } }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.typedEnvelopeMatchesChart(missingSymbolEnvelope, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.typedEnvelopeMatchesChart({ ...envelope, data: { ...envelope.data, timeframe: '1h' } }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.typedEnvelopeMatchesChart(missingTimeframeEnvelope, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.typedEnvelopeCanDriveRealtimeChart({ ...envelope, source_type: 'static_payload' }, 'BTCUSDT', '5m')).toBe(false);
    expect(proChartTestHooks.typedEnvelopeCanDriveRealtimeChart({ ...envelope, stale: true }, 'BTCUSDT', '5m')).toBe(false);
  });

  test('maps derivatives into ProChart OI and funding overlays', () => {
    const envelope = {
      data: {
        symbol: 'BTCUSDT',
        funding_rate: 0.0001,
        next_funding: '2026-06-13T08:00:00Z',
        open_interest: 12345,
        open_interest_change: null,
        funding_history: [
          { time: '2026-06-13T03:00:00Z', value: '0.0001' },
          { time: 1781323500000, value: 0.00012 },
        ],
        open_interest_history: [
          { time: '2026-06-13T03:00:00Z', value: 12000, notional: 1200000000 },
          { time: 1781323500000, value: 12345, notional: 1234500000 },
        ],
        liquidations_1h: null,
        liquidations_24h: null,
        long_short_ratio: 1.12,
        basis: 0.0002,
        exchange_comparison: [],
      },
      source: 'mocked derivatives source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/derivatives',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only mocked derivatives source'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    const overlay = proChartTestHooks.overlayFromDerivatives(envelope);

    expect(overlay?.funding_kline).toHaveLength(2);
    expect(overlay?.oi_kline).toHaveLength(2);
    expect(overlay?.stats.total_oi).toBe(1234500000);
    expect(overlay?.stats.ls_ratio).toBe(1.12);
    expect(overlay?.stats.funding_rate).toBe(0.0001);
    expect(proChartTestHooks.overlayFromDerivatives({ ...envelope, source_type: 'unavailable' })).toBeNull();
  });

  test('rejects mismatched terminal market envelopes before showing microstructure rows', () => {
    const depthEnvelope = {
      data: {
        symbol: 'BTCUSDT',
        bids: [[100000, 1.2]],
        asks: [[100020, 0.8]],
        spread_bps: 2,
        depth_type: 'mocked_depth',
      },
      source: 'mocked depth source',
      source_type: 'api' as const,
      endpoint: '/api/v2/market/BTCUSDT/depth',
      timestamp: '2026-06-13T03:00:00Z',
      received_at: '2026-06-13T03:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only mocked public depth source'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(tradeTerminalTestHooks.envelopeMatchesSymbol(depthEnvelope, 'BTCUSDT')).toBe(true);
    expect(tradeTerminalTestHooks.envelopeMatchesSymbol({ ...depthEnvelope, symbol: 'ETHUSDT' }, 'BTCUSDT')).toBe(false);
    expect(tradeTerminalTestHooks.envelopeMatchesSymbol({ ...depthEnvelope, data: { ...depthEnvelope.data, symbol: 'ETHUSDT' } }, 'BTCUSDT')).toBe(false);
  });

  test('keeps ProChart indicator controls disabled when only static chart-file indicators exist', async ({ page }) => {
    await mockProChartData(page);
    await gotoAs(page, '/chart/BTCUSDT', 'trader');
    await expect(page.getByTestId('page-pro-chart')).toBeVisible();

    await expect(page.getByRole('button', { name: 'EMA pending' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'BB pending' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'AI target pending' })).toBeDisabled();
    await expect(page.getByRole('button', { name: /EMA/i })).toHaveAttribute(
      'title',
      /Indicator source connecting/,
    );
  });

  test('enables ProChart EMA and Bollinger controls from public-kline indicators', async ({ page }) => {
    await mockProChartData(page, { indicators: 'available' });
    await gotoAs(page, '/chart/BTCUSDT', 'trader');
    await expect(page.getByTestId('page-pro-chart')).toBeVisible();

    await expect(page.getByRole('button', { name: 'EMA' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'BB' })).toBeEnabled();
    await expect(page.getByRole('button', { name: 'AI target pending' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'EMA' })).toHaveAttribute(
      'title',
      /Toggle EMA overlay/,
    );
    await expect(page.getByRole('button', { name: 'AI target pending' })).toHaveAttribute(
      'title',
      /Indicator source connecting/,
    );
  });

  test('uses signed-in trader watchlist in ProChart favorites', async ({ page }) => {
    await page.route('**/api/v1/chart/symbols', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          symbols: [
            { symbol: 'BTCUSDT', price: 100000, signal: null, source_age_s: 1 },
            { symbol: 'ETHUSDT', price: 5000, signal: null, source_age_s: 1 },
            { symbol: 'SOLUSDT', price: 200, signal: null, source_age_s: 1 },
          ],
        }),
      });
    });
    await mockProChartData(page);
    await gotoAs(page, '/chart/BTCUSDT', 'trader');
    await expect(page.getByTestId('page-pro-chart')).toBeVisible();

    await expect(page.getByRole('option', { name: /BTC/i })).toBeVisible();
    await expect(page.getByRole('option', { name: /BTC/i }).locator('.symbol-row__freshness')).toHaveText(/\d+s/);
    await expect(page.getByRole('option', { name: /ETH/i })).toBeVisible();
    await expect(page.getByRole('option', { name: /SOL/i })).toHaveCount(0);
  });

  test('syncs the displayed ProChart symbol when the route parameter changes', async ({ page }) => {
    await mockProChartData(page);
    await gotoAs(page, '/chart/BTCUSDT', 'trader');
    await expect(page.getByTestId('page-pro-chart')).toBeVisible();
    await expect(page.locator('.pro-chart-header__name')).toHaveText('BTCUSDT');

    await page.evaluate(() => {
      window.history.pushState({}, '', '/chart/ETHUSDT');
      window.dispatchEvent(new PopStateEvent('popstate'));
    });

    await expect(page.locator('.pro-chart-header__name')).toHaveText('ETHUSDT');
  });

  test('normalizes malformed ProChart route symbols to the safe default', async ({ page }) => {
    await mockProChartData(page);
    await gotoAs(page, '/chart/btcusdt..', 'trader');
    await expect(page.getByTestId('page-pro-chart')).toBeVisible();
    await expect(page.locator('.pro-chart-header__name')).toHaveText('BTCUSDT');
    await expect(page).toHaveURL(/\/chart\/BTCUSDT$/);
  });

  for (const viewport of VIEWPORTS) {
    test(`renders read-only ProChart without horizontal overflow at ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await mockProChartData(page);
      await gotoAs(page, '/chart/BTCUSDT', 'trader');
      await expect(page.getByTestId('page-pro-chart')).toBeVisible();
      await expect(page.locator('.prochart__canvas')).toBeVisible();
      await expect(page.getByText(/Live chart/i)).toBeVisible();
      await expect(page.getByText(/Live order placement off/i)).toBeVisible();
      await expect(page.getByLabel(/Chart source and account status/i)).toContainText('Live market data');
      await expect(page.getByLabel(/Chart source and account status/i)).toContainText('Realtime source: Binance public stream plus shared WebSocket resources with API fallback');
      await expect(page.getByLabel(/Chart source and account status/i)).toContainText('Trader scope: Authenticated trader account');
      await expect(page.getByText(/Stream forming candle|Stream closed candle|Current candle update|Resource stream connected|Stream connected|Waiting for stream frame|Fallback candles/i).first()).toBeVisible();
      await expect(page.getByText(/Price stream:/i)).toBeVisible();
      await expect(page.getByText(/Depth stream:/i)).toBeVisible();
      await expect(page.getByText(/Trades stream:/i)).toBeVisible();
      await expect(page.getByRole('button', { name: /Place Live/i })).toHaveCount(0);

      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
      expect(overflow).toBeLessThanOrEqual(1);
    });
  }
});
