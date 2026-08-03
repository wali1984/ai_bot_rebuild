import { mkdirSync, readFileSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';
import { marketDetailTestHooks } from '../../src/hooks/useMarketDetail';

const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
] as const;

const FORBIDDEN_STRINGS = [
  'AI BOT V2',
  'Control Plane',
  'Admin',
  'Operator',
  'War Room',
  'Mission Control',
  'Codex',
  'Claude',
  'Ollama',
  'payload',
  'proof',
  'gap matrix',
  'local role',
  'role override',
  'migration',
  'script',
  'build validation',
  'coverage',
  'quarantine',
  'raw audit ledger',
] as const;

async function openMarket(page: Page): Promise<void> {
  await gotoAs(page, '/market/BTCUSDT', undefined, { waitUntil: 'domcontentloaded' });
  await expect(page.getByTestId('page-market-detail')).toBeVisible();
}

test.describe('market detail redesign', () => {
  test('promotes only fresh read-only stream envelopes into market detail state', () => {
    const envelope = {
      data: { symbol: 'BTCUSDT', timeframe: '1m', candles: [], candle_count: 0 },
      source: 'binance_usdm_public_websocket_adapter',
      source_type: 'api' as const,
      endpoint: '/api/v2/ws/market-data',
      timestamp: '2026-06-14T00:00:00Z',
      received_at: '2026-06-14T00:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: ['Read-only stream snapshot'],
      symbol: 'BTCUSDT',
      exchange: 'Binance USD-M',
      mode: 'read_only' as const,
    };

    expect(marketDetailTestHooks.currentReadOnlyEnvelope(envelope)).toBe(envelope);
    expect(marketDetailTestHooks.currentReadOnlyEnvelope(envelope, 'BTCUSDT', '1m')).toBe(envelope);
    expect(marketDetailTestHooks.currentReadOnlyEnvelope({ ...envelope, symbol: 'ETHUSDT', data: { ...envelope.data, symbol: 'ETHUSDT' } }, 'BTCUSDT', '1m')).toBeNull();
    expect(marketDetailTestHooks.currentReadOnlyEnvelope({ ...envelope, data: { ...envelope.data, timeframe: '5m' } }, 'BTCUSDT', '1m')).toBeNull();
    expect(marketDetailTestHooks.currentReadOnlyEnvelope({ ...envelope, stale: true })).toBeNull();
    expect(marketDetailTestHooks.currentReadOnlyEnvelope({ ...envelope, source_type: 'static_payload' as const })).toBeNull();
    expect(marketDetailTestHooks.currentReadOnlyEnvelope({ ...envelope, source_type: 'unavailable' as const })).toBeNull();
  });

  test('withholds account-specific market signals without matching trader scope', () => {
    const signal = {
      data: {
        account_specific: true,
        trader_id: 'trader-wajidali1984',
        paper_account_id: 'paper-wajidali1984',
        active_signal: {
          symbol: 'BTCUSDT',
          direction: 'LONG',
        },
      },
      source: 'trader_signal_repository',
      source_type: 'repository' as const,
      endpoint: '/api/v2/signals',
      timestamp: '2026-06-14T00:00:00Z',
      received_at: '2026-06-14T00:00:01Z',
      lag_ms: 1000,
      stale: false,
      missing_fields: [],
      warnings: [],
      mode: 'paper' as const,
    };

    expect(marketDetailTestHooks.signalMatchesTraderScope(signal, null, null)).toBe(false);
    expect(marketDetailTestHooks.signalMatchesTraderScope(signal, 'trader-other', 'paper-other')).toBe(false);
    expect(marketDetailTestHooks.signalMatchesTraderScope(signal, 'trader-wajidali1984', 'paper-wajidali1984')).toBe(true);

    const publicScoped = marketDetailTestHooks.signalForTraderAndSymbol(signal, 'BTCUSDT', null, null, true);
    expect(publicScoped.data?.active_signal).toBeNull();
    expect(publicScoped.missing_fields).toContain('trader_signal_scope');
  });

  test('renders the canonical market detail route', async ({ page }) => {
    await openMarket(page);
    await expect(page.getByTestId('market-symbol-header')).toBeVisible();
  });

  test('market detail route uses readonly WebSocket market stream as primary data path', () => {
    const source = readFileSync(path.resolve(process.cwd(), 'src/pages/market/index.tsx'), 'utf8');
    const hookSource = readFileSync(path.resolve(process.cwd(), 'src/hooks/useMarketDetail.ts'), 'utf8');

    expect(source).toContain("useMarketDataStream(querySymbol, 2_000, timeframe)");
    expect(source).toContain('useRealtimeResource<MarketTickerData>');
    expect(source).toContain('useRealtimeResource<MarketCandlesData>');
    expect(source).toContain('streamTickerForSymbol(marketStream.ticker, querySymbol)');
    expect(source).toContain('streamCandlesForSymbol(marketStream.candles, querySymbol, timeframe)');
    expect(source).toContain("source_type: 'websocket'");
    expect(source).not.toMatch(/Ticker polling/i);
    expect(source).not.toMatch(/Candles — refresh/i);
    expect(source).not.toContain('fetchTicker');
    expect(source).not.toContain('fetchCandles');
    expect(source).not.toContain('setInterval(');
    expect(source).not.toContain("fetch(`/api/v2/market");
    expect(hookSource).toContain('useRealtimeResource<MarketCandlesData>');
    expect(hookSource).toContain('useRealtimeResource<MarketDerivativesData>');
    expect(hookSource).toContain("source_type: 'websocket'");
    expect(hookSource).not.toContain('setInterval(');
    expect(hookSource).not.toContain('getV2MarketCandles');
    expect(hookSource).not.toContain('getV2Signals');
  });

  test('does not show forbidden public copy or raw JSON by default', async ({ page }) => {
    await openMarket(page);
    const text = await page.locator('body').innerText();
    for (const forbidden of FORBIDDEN_STRINGS) {
      expect(text, `forbidden public /market string: ${forbidden}`).not.toMatch(new RegExp(forbidden, 'i'));
    }
    expect(text).not.toMatch(/\{\s*"/);
    expect(text).not.toMatch(/\b[A-Z]{3,}_[A-Z0-9_]+\b/);
    expect(text).not.toMatch(/Typed API data/i);
  });

  for (const viewport of VIEWPORTS) {
    test(`has no body horizontal scroll and captures ${viewport.name}`, async ({ page }) => {
      await page.setViewportSize({ width: viewport.width, height: viewport.height });
      await openMarket(page);

      const overflow = await page.evaluate(() => ({
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        bodyClientWidth: document.body.clientWidth,
      }));

      expect(Math.max(overflow.scrollWidth, overflow.bodyScrollWidth)).toBeLessThanOrEqual(
        Math.max(overflow.clientWidth, overflow.bodyClientWidth) + 1,
      );

      const root = path.resolve(process.cwd(), '..', 'screenshots', 'final');
      mkdirSync(root, { recursive: true });
      await page.screenshot({
        path: path.join(root, `market-detail-${viewport.name}.png`),
        fullPage: true,
      });
    });
  }

  test('shows market, chart, microstructure, derivatives, signal, and evidence sections', async ({ page }) => {
    await openMarket(page);
    await expect(page.getByText('Last price').first()).toBeVisible();
    await expect(page.getByText('1h change').first()).toBeVisible();
    await expect(page.getByText('4h change').first()).toBeVisible();
    await expect(page.getByText('24h change').first()).toBeVisible();
    await expect(page.getByTestId('market-chart-section')).toBeVisible();
    await expect(page.getByTestId('chart-panel')).toBeVisible();
    await expect(page.getByTestId('market-microstructure-section')).toBeVisible();
    await expect(page.getByTestId('market-derivatives-section')).toBeVisible();
    await expect(page.getByTestId('market-signal-section')).toBeVisible();
    await expect(page.getByTestId('market-evidence-section')).toBeVisible();
    await expect(page.getByTestId('market-evidence-drawer')).toBeVisible();
    await expect(page.getByText('Indicators').first()).toBeVisible();
  });

  test('uses designed missing source states for incomplete market data', async ({ page }) => {
    await openMarket(page);
    await expect(page.getByText(/Depth data not connected|Depth data unavailable|Data source unavailable|Order book|Spread/i).first()).toBeVisible();
    await expect(page.getByText(/Recent trades unavailable|Trade tape unavailable|Data source unavailable|Recent trades|Buy|Sell/i).first()).toBeVisible();
    await expect(page.getByText(/Liquidation stream|Liquidation levels|Connecting/i).first()).toBeVisible();
    await expect(page.getByText(/Liquidation stream/i).first()).toBeVisible();
    await expect(page.getByText(/Liquidation levels/i).first()).toBeVisible();
    await expect(page.getByText(/Funding history|Funding chart unavailable|Open interest history|Open interest chart unavailable/i).first()).toBeVisible();
    await expect(page.getByText(/Source validation|Source evidence pending|Source evidence verified/i).first()).toBeVisible();
    await expect(page.getByText(/Signal evidence unavailable|Active Prediction|Sign in to see AI signals|Prediction source unavailable/i).first()).toBeVisible();
    await expect(page.getByText(/Indicators unavailable|Indicator source unavailable|current indicator source/i).first()).toBeVisible();
    await expect(page.getByText('/api/v2/market/{symbol}/indicators')).toHaveCount(0);
  });

  test('invalid route symbols show designed unavailable state without fallback market identity', async ({ page }) => {
    await gotoAs(page, '/market/btcusdt..', undefined, { waitUntil: 'domcontentloaded' });
    await expect(page.getByTestId('page-market-detail')).toBeVisible();
    await expect(page.getByText('Invalid market symbol').first()).toBeVisible();
    await expect(page.getByText(/Enter a valid market symbol/i).first()).toBeVisible();
    const text = await page.locator('body').innerText();
    expect(text).not.toMatch(/BTCUSDT\.\./);
    expect(text).not.toMatch(/Static fallback data; not a live market stream/i);
  });

  test('mobile layout stacks modules without wide tables', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await openMarket(page);
    await expect(page.getByTestId('market-symbol-header')).toBeVisible();
    await expect(page.getByTestId('market-evidence-section')).toBeVisible();
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
    expect(overflow).toBeLessThanOrEqual(1);
  });
});
