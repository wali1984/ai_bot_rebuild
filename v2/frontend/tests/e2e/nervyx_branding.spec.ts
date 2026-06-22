import { expect, test } from '@playwright/test';

const adminUser = {
  id: 'admin-local',
  trader_id: 'trader-local',
  username: 'admin',
  email: 'admin@local.nervyx',
  role: 'admin',
  paper_account_id: 'paper-local',
  exchange_accounts: [],
  watchlist: [],
  alert_preferences: {},
  is_active: true,
  created_at: '2026-06-21T00:00:00Z',
  updated_at: '2026-06-21T00:00:00Z',
  last_login: null,
};

test('public landing and manifest expose NERVYX ONE identity on port 5173', async ({ page, request }) => {
  await page.goto('/');

  await expect(page.getByText('NERVYX ONE').first()).toBeVisible();
  await expect(page.getByText('Adaptive Market Intelligence').first()).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/AI BOT V2|AlphaForge|Control Plane|Control Portal/);

  const response = await request.get('/manifest.webmanifest');
  expect(response.ok()).toBeTruthy();
  const manifest = await response.json();
  expect(manifest.name).toBe('NERVYX ONE');
  expect(manifest.short_name).toBe('NERVYX ONE');
  expect(manifest.description).toContain('Adaptive Market Intelligence');
});

test('public and trader chrome expose NERVYX module mapping and Polar Signal theme', async ({ page }) => {
  await page.goto('/markets');

  await expect(page.getByAltText('NERVYX ONE').first()).toBeVisible();
  await expect(page.locator('[data-testid="topbar"]')).toContainText(/Adaptive Market Intelligence/i);
  await expect(page.locator('[data-nervyx-module="sense"]').first()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Polar' })).toBeVisible();

  await page.getByRole('button', { name: 'Polar' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-nervyx-theme', 'polar-signal');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'light');

  await page.getByRole('button', { name: 'Midnight' }).click();
  await expect(page.locator('html')).toHaveAttribute('data-nervyx-theme', 'midnight-neural');
  await expect(page.locator('html')).toHaveAttribute('data-theme', 'dark');
});

test('admin shell uses NERVYX OBSERVE branding without changing auth semantics', async ({ page }) => {
  await page.route('/api/auth/me', (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify({ user: adminUser }),
  }));

  await page.goto('/admin/monitor-center');

  await expect(page.getByTestId('admin-shell')).toHaveAttribute('data-nervyx-theme', 'ops-terminal');
  await expect(page.getByAltText('NERVYX ONE').first()).toBeVisible();
  await expect(page.getByText('NERVYX OBSERVE').first()).toBeVisible();
  await expect(page.locator('[data-nervyx-module="observe"]').first()).toBeVisible();
  await expect(page.locator('[data-nervyx-module="guard"]').first()).toBeVisible();
  await expect(page.locator('body')).not.toContainText(/AlphaForge|Control Portal/);
});
