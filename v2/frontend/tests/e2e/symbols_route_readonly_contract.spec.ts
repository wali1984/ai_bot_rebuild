import { expect, test } from '@playwright/test';

const FORBIDDEN_MAIN_UI_TERMS = [
  'Mission Control',
  'War Room',
  'Operator Proof',
  'raw payload',
  'gap matrix',
  'role override',
  'fake admin',
  'session role',
  'build validation',
  'coverage',
  'quarantine',
  'raw audit ledger',
];

test.describe('/markets/symbols read-only product contract', () => {
  test('redirects, protects access, or renders as a trader-safe read-only symbol universe page', async ({ page }) => {
    await page.goto('/markets/symbols');

    const pathname = await page.evaluate(() => window.location.pathname);
    if (pathname !== '/markets/symbols') {
      expect(['/markets', '/login']).toContain(pathname);
    } else {
      await expect(page.getByTestId('page-symbols')).toBeVisible();
      await expect(page.getByText('Read-only symbol universe')).toBeVisible();
      await expect(page.getByText('Live trading disabled')).toBeVisible();
      await expect(page.getByText('Market Chart Coverage And Symbol Health')).toBeVisible();
      await expect(page.getByText('Signal Quality Coverage')).toBeVisible();
    }

    const bodyText = await page.locator('body').innerText();
    for (const term of FORBIDDEN_MAIN_UI_TERMS) {
      expect(bodyText).not.toContain(term);
    }

    expect(bodyText).not.toMatch(/\b[A-Z]{3,}_[A-Z0-9_]{3,}\b/);
  });

  test('does not expose uncontrolled horizontal scroll on mobile', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto('/markets/symbols');

    const pathname = await page.evaluate(() => window.location.pathname);
    if (pathname === '/markets/symbols') {
      await expect(page.getByTestId('page-symbols')).toBeVisible();
    } else {
      expect(['/markets', '/login']).toContain(pathname);
    }
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(overflow).toBe(false);
  });
});
