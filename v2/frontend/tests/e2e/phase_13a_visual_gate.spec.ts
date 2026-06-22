import { mkdirSync } from 'node:fs';
import path from 'node:path';
import { expect, test, type Page } from '@playwright/test';

const VIEWPORTS = [
  { name: '1920x1080', width: 1920, height: 1080 },
  { name: '1440x900', width: 1440, height: 900 },
  { name: '768x1024', width: 768, height: 1024 },
  { name: '390x844', width: 390, height: 844 },
] as const;

const ROUTES = [
  { path: '/', name: 'home' },
  { path: '/login', name: 'login' },
  { path: '/status', name: 'status' },
  { path: '/dashboard', name: 'dashboard', authenticated: true },
  { path: '/markets', name: 'markets', authenticated: true },
  { path: '/market/BTCUSDT', name: 'market-detail' },
  { path: '/chart/BTCUSDT', name: 'pro-chart', authenticated: true },
  { path: '/trade', name: 'trade' },
] as const;

const FORBIDDEN = [
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
  'raw payload',
  'proof',
  'gap matrix',
  'local role',
  'role override',
  'fake admin',
  'session role',
  'migration',
  'script',
  'build validation',
  'coverage',
  'quarantine',
  'raw audit ledger',
  'source pending',
] as const;

async function mockAuth(page: Page, authenticated = false): Promise<void> {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: authenticated
          ? {
            id: 'visual-viewer',
            trader_id: 'visual-viewer',
            username: 'visual.viewer',
            email: 'visual.viewer@example.com',
            role: 'viewer',
            paper_account_id: 'paper-visual',
            exchange_accounts: [],
            watchlist: ['BTCUSDT'],
            alert_preferences: {},
            is_active: true,
            created_at: '2026-06-13T00:00:00Z',
            updated_at: '2026-06-13T00:00:00Z',
            last_login: '2026-06-13T00:00:00Z',
          }
          : null,
      }),
    });
  });
}

async function openRoute(page: Page, route: (typeof ROUTES)[number]): Promise<void> {
  await mockAuth(page, 'authenticated' in route && Boolean(route.authenticated));
  await page.goto(route.path);
  await page.waitForLoadState('networkidle').catch(() => undefined);
  await page.locator('body').waitFor({ state: 'visible' });
}

async function visibleMainText(page: Page): Promise<string> {
  return page.locator('body').innerText();
}

function assertNoForbiddenCopy(text: string, label: string): void {
  for (const forbidden of FORBIDDEN) {
    expect(text, `${label} contains forbidden public/trader string: ${forbidden}`).not.toMatch(new RegExp(forbidden, 'i'));
  }
  expect(text, `${label} exposes snake_case`).not.toMatch(/\b[a-z]+_[a-z0-9]+(?:_[a-z0-9]+)+\b/);
  expect(text, `${label} exposes backend enum`).not.toMatch(/\b[A-Z]{2,}_[A-Z0-9_]{2,}\b/);
  expect(text, `${label} exposes raw JSON`).not.toMatch(/^\s*\{[\s\S]*"[^"]+"\s*:/m);
}

test.describe('phase 13a visual gate', () => {
  test.describe.configure({ mode: 'serial' });

  for (const viewport of VIEWPORTS) {
    for (const route of ROUTES) {
      test(`${route.name} renders cleanly at ${viewport.name}`, async ({ page }) => {
        await page.setViewportSize({ width: viewport.width, height: viewport.height });
        await openRoute(page, route);

        const overflow = await page.evaluate(() => ({
          scrollWidth: document.documentElement.scrollWidth,
          clientWidth: document.documentElement.clientWidth,
          bodyScrollWidth: document.body.scrollWidth,
          bodyClientWidth: document.body.clientWidth,
        }));
        expect(Math.max(overflow.scrollWidth, overflow.bodyScrollWidth), `${route.name} horizontal overflow at ${viewport.name}`).toBeLessThanOrEqual(
          Math.max(overflow.clientWidth, overflow.bodyClientWidth) + 1,
        );

        const text = await visibleMainText(page);
        assertNoForbiddenCopy(text, `${route.name} ${viewport.name}`);

        const root = path.resolve(process.cwd(), '..', 'screenshots', 'final');
        mkdirSync(root, { recursive: true });
        await page.screenshot({
          path: path.join(root, `${route.name}-${viewport.name}.png`),
          fullPage: true,
        });
      });
    }
  }

  test('route-specific product modules are visible', async ({ page }) => {
    await openRoute(page, { path: '/trade', name: 'trade' });
    await expect(page.getByTestId('paper-readonly-badge')).toBeVisible();
    await expect(page.getByTestId('chart-panel')).toBeVisible();
    await expect(page.getByTestId('order-book-panel')).toBeVisible();
    await expect(page.getByTestId('market-depth-panel')).toBeVisible();
    await expect(page.getByTestId('recent-trades-tape')).toBeVisible();
    await expect(page.getByTestId('paper-order-ticket')).toBeVisible();
    await expect(page.getByTestId('trade-bottom-tabs')).toBeVisible();
    await expect(page.getByRole('button', { name: /Place Live/i })).toHaveCount(0);

    await openRoute(page, { path: '/market/BTCUSDT', name: 'market-detail' });
    await expect(page.getByTestId('market-chart-section')).toBeVisible();
    await expect(page.getByTestId('market-microstructure-section')).toBeVisible();
    await expect(page.getByTestId('market-derivatives-section')).toBeVisible();
    await expect(page.getByTestId('market-signal-section')).toBeVisible();
    await expect(page.getByTestId('market-evidence-section')).toBeVisible();

    await openRoute(page, { path: '/login', name: 'login' });
    await expect(page.getByLabel(/Email/i)).toBeVisible();
    await expect(page.getByPlaceholder('Enter password')).toBeVisible();
    await expect(page.getByText(/role selector/i)).toHaveCount(0);

    await openRoute(page, { path: '/status', name: 'status' });
    const statusPage = page.getByTestId('page-public-status');
    await expect(statusPage.getByText(/Platform availability/i)).toBeVisible();
    await expect(statusPage.getByText(/Market stream/i)).toBeVisible();
    await expect(statusPage.getByText(/Stream alert/i)).toBeVisible();
    await expect(statusPage.getByText(/Live trading disabled/i)).toBeVisible();

    await openRoute(page, { path: '/markets', name: 'markets', authenticated: true });
    await expect(page.getByRole('table', { name: /Market screener/i })).toBeVisible();
  });
});
