import { expect, test } from '@playwright/test';
import { gotoAs } from './_shared';

const PRIMARY_TRADER_ROUTES = [
  '/dashboard',
  '/markets',
  '/derivatives',
  '/signals',
  '/ai-predictions',
  '/portfolio',
  '/backtests',
  '/research',
  '/alerts',
] as const;

const FORBIDDEN_NAV_TERMS = /admin|operator|war room|mission control|codex|claude|ollama|build|coverage|migration|scripts|logs|payload|proof|local role/i;

test.describe('Trader-first product navigation contract', () => {
  test('primary trader nav stays trader-facing and excludes admin/operator destinations', async ({ page }) => {
    await gotoAs(page, '/dashboard', 'trader');

    const topNav = page.locator('nav[aria-label="Primary route navigation"], nav[aria-label="Public navigation"]').first();
    await expect(topNav).toBeVisible();
    await expect(topNav).toContainText('Dashboard');
    await expect(topNav).toContainText('Markets');
    await expect(topNav).toContainText('Trade');
    await expect(topNav).not.toContainText(FORBIDDEN_NAV_TERMS);
  });

  for (const route of PRIMARY_TRADER_ROUTES) {
    test(`${route} renders inside the trader product shell without horizontal overflow`, async ({ page }) => {
      await page.setViewportSize({ width: 1440, height: 900 });
      await gotoAs(page, route, route === '/backtests' ? 'admin' : 'trader');

      await expect(page.getByTestId('live-block-banner')).toBeVisible();
      await expect(page.getByTestId('live-block-banner')).toContainText(/Paper \/ read-only mode active|Live trading disabled/i);
      await expect(page.locator('body')).not.toContainText(/LIVE RUNTIME|enabled_operator_approved|role override|local role/i);

      const hasHorizontalScroll = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
      expect(hasHorizontalScroll).toBe(false);
    });
  }
});
