import { test } from '@playwright/test';
import { mockAuth } from './helpers/auth';

test('debug /admin/risk after /admin on main branch', async ({ page }) => {
  await mockAuth(page, 'admin');
  await page.route('**/api/v2/**', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({}) });
  });
  await page.goto('/admin');
  await page.waitForTimeout(500);
  const shell1 = await page.getByTestId('admin-health-strip').count();
  console.log('After /admin - health-strip count:', shell1);
  await page.goto('/admin/risk');
  await page.waitForTimeout(2000);
  const shell2 = await page.getByTestId('admin-health-strip').count();
  const body = await page.locator('body').innerText().catch(() => 'ERROR');
  console.log('After /admin/risk - health-strip count:', shell2);
  console.log('Body (first 200):', body.substring(0, 200));
});
