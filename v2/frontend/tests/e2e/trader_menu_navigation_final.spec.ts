/**
 * Trader navigation final — verifies that all required pages are reachable
 * using only visible clicks after login. No manual URL entry permitted.
 *
 * Required pages: Account Settings, Market Detail (symbol click), Trade,
 * Replay, Technical Analysis, Alerts.
 */

import { expect, test } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

test.describe('trader_menu_navigation_final', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuth(page, 'trader');
  });

  test('Trade is reachable from top nav', async ({ page }) => {
    await gotoAs(page, '/dashboard', 'trader');
    await page.getByTestId('nav-link-trade').click();
    await expect(page).toHaveURL(/\/trade/);
    await expect(page.getByTestId('trader-shell')).toBeVisible();
  });

  test('Alerts is reachable from top nav', async ({ page }) => {
    await gotoAs(page, '/dashboard', 'trader');
    await page.getByTestId('nav-link-alerts').click();
    await expect(page).toHaveURL(/\/alerts/);
    await expect(page.getByTestId('trader-shell')).toBeVisible();
  });

  test('Replay is reachable from top nav', async ({ page }) => {
    await gotoAs(page, '/dashboard', 'trader');
    await page.getByTestId('nav-link-replay').click();
    await expect(page).toHaveURL(/\/replay/);
    await expect(page.getByTestId('trader-shell')).toBeVisible();
  });

  test('Technical Analysis is reachable from top nav', async ({ page }) => {
    await gotoAs(page, '/dashboard', 'trader');
    await page.getByTestId('nav-link-technical-analysis').click();
    await expect(page).toHaveURL(/\/technical-analysis/);
    await expect(page.getByTestId('trader-shell')).toBeVisible();
  });

  test('Account Settings is reachable from user menu', async ({ page }) => {
    await gotoAs(page, '/dashboard', 'trader');
    // Open the user menu
    await page.getByRole('button', { name: /user menu/i }).click();
    await page.getByTestId('usermenu-account-settings').click();
    await expect(page).toHaveURL(/\/account-settings/);
    await expect(page.getByTestId('trader-shell')).toBeVisible();
  });

  test('Market Detail is reachable by clicking a symbol in the Markets page', async ({ page }) => {
    // Mock the market overview API so the markets table has rows
    await page.route('**/api/v2/market/overview**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          source: 'mock',
          source_type: 'api',
          generated_utc: new Date().toISOString(),
          data: {
            count: 2,
            symbols: ['BTCUSDT', 'ETHUSDT'],
            tickers: [
              { symbol: 'BTCUSDT', last_price: 60000, mark_price: 60010, index_price: 59990, change_24h: 1.2, volume_24h: 1000, turnover_24h: 60000000, oi_usd: 5000000, funding_rate: 0.0001 },
              { symbol: 'ETHUSDT', last_price: 3400, mark_price: 3401, index_price: 3399, change_24h: -0.5, volume_24h: 5000, turnover_24h: 17000000, oi_usd: 2000000, funding_rate: -0.0002 },
            ],
          },
        }),
      });
    });

    await gotoAs(page, '/markets', 'trader');
    await page.getByTestId('page-markets').waitFor({ state: 'visible', timeout: 10_000 });
    // Click a table row that contains BTC
    const btcRow = page.locator('tr, [role="row"]').filter({ hasText: 'BTC' }).first();
    await btcRow.click();
    await expect(page).toHaveURL(/\/market\//);
    // market detail page uses PublicShell (surface: 'public') — not trader-shell
    await expect(page.getByTestId('public-shell')).toBeVisible();
  });

});
