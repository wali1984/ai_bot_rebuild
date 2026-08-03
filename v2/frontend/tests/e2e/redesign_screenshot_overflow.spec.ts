import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';

const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
] as const;

const PUBLIC_ROUTES = ['/', '/landing', '/status', '/status-simple', '/login'] as const;

const TRADER_ROUTES = [
  '/dashboard',
  '/markets',
  '/markets/symbols',
  '/market/BTCUSDT',
  '/chart/BTCUSDT',
  '/trade',
  '/trade/paper',
  '/derivatives',
  '/signals',
  '/ai-predictions',
  '/ai-predictions/model-state',
  '/portfolio',
  '/portfolio/executions',
  '/portfolio/history',
  '/backtests',
  '/backtests/replay',
  '/research',
  '/research/technical-analysis',
  '/alerts',
] as const;

const ROUTES = [...PUBLIC_ROUTES, ...TRADER_ROUTES] as const;

function screenshotRoot(): string {
  const phase = process.env.REDESIGN_SCREENSHOT_PHASE === 'before' ? 'before' : 'final';
  return path.resolve(process.cwd(), '..', 'screenshots', phase);
}

function safeRouteName(route: string): string {
  return route.replace(/^\//, '').replace(/[^a-zA-Z0-9]+/g, '_') || 'root';
}

async function settle(page: Page): Promise<void> {
  await page.waitForLoadState('domcontentloaded').catch(() => undefined);
  await page.locator('body').waitFor({ state: 'visible', timeout: 5_000 });
  await page.waitForTimeout(150);
}

function roleForRoute(route: string): 'public' | 'trader' | 'admin' {
  if ((PUBLIC_ROUTES as readonly string[]).includes(route)) return 'public';
  if (route === '/backtests') return 'admin';
  return 'trader';
}

test.describe.configure({ mode: 'serial' });

test.describe('redesign screenshot crawler and overflow guard', () => {
  for (const viewport of VIEWPORTS) {
    test(`captures current route screenshots and checks body overflow at ${viewport.name}`, async ({ browser }) => {
      test.setTimeout(480_000);
      const root = screenshotRoot();
      mkdirSync(root, { recursive: true });

      for (const route of ROUTES) {
        await test.step(`${viewport.name} ${route}`, async () => {
          const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
          try {
            await gotoAs(page, route, roleForRoute(route));
            await settle(page);

            const overflow = await page.evaluate(() => ({
              scrollWidth: document.documentElement.scrollWidth,
              clientWidth: document.documentElement.clientWidth,
              bodyScrollWidth: document.body.scrollWidth,
              bodyClientWidth: document.body.clientWidth,
              pathname: window.location.pathname,
            }));

            expect(
              Math.max(overflow.scrollWidth, overflow.bodyScrollWidth),
              `${route} rendered as ${overflow.pathname} should not horizontally overflow at ${viewport.name}`,
            ).toBeLessThanOrEqual(Math.max(overflow.clientWidth, overflow.bodyClientWidth) + 1);

            await page.screenshot({
              path: path.join(root, `${viewport.name}_${safeRouteName(route)}.png`),
              fullPage: true,
            });
          } finally {
            await page.close().catch(() => undefined);
          }
        });
      }
    });
  }
});
