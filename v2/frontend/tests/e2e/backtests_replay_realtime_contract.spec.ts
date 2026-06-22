import { readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test } from '@playwright/test';

test.describe('backtests replay realtime contract', () => {
  test('uses streamed candle and replay status resources', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/backtests-replay/index.tsx'), 'utf8');
    const route = readFileSync(path.resolve(process.cwd(), 'src/pages/backtests-replay/route.ts'), 'utf8');
    const productNavigation = readFileSync(path.resolve(process.cwd(), 'src/pages/productNavigation.ts'), 'utf8');

    expect(source).toContain('useRealtimeResource<MarketCandlesData>');
    expect(source).toContain("url: candleUrl");
    expect(source).toContain("source_type: 'websocket'");
    expect(source).toContain("url: '/api/v2/replay/status'");
    expect(source).not.toContain('getV2MarketCandles');
    expect(source).not.toContain('Pending Features');
    expect(route).toContain("path: '/backtests/replay'");
    expect(productNavigation).toContain("replay: {");
    expect(productNavigation).toContain("path: '/replay'");
  });

  test('binance chart history uses resource streams instead of candle helper fetches', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/binance/index.tsx'), 'utf8');

    expect(source).toContain('useRealtimeResource<MarketCandlesData>');
    expect(source).toContain("url: candleUrl");
    expect(source).toContain("source_type: 'websocket'");
    expect(source).not.toContain("import { getV2MarketCandles }");
    expect(source).not.toContain('await getV2MarketCandles');
  });

  test('live platform telemetry copy does not expose paper-only phrasing', () => {
    const telemetry = readFileSync(path.resolve(process.cwd(), 'src/components/trading/AdaptiveCapitalTelemetryPanel.tsx'), 'utf8');
    const marketIntelligence = readFileSync(path.resolve(process.cwd(), 'src/pages/market-intelligence/index.tsx'), 'utf8');

    expect(telemetry).toContain('operator-gated execution controls');
    expect(telemetry).toContain("replace(/\\bpaper\\s*only");
    expect(marketIntelligence).toContain('title="Signal Accuracy + Capital Productivity"');
    expect(marketIntelligence).not.toContain('Research Signal Accuracy + Capital Productivity');
  });
});
