import { test, expect } from '@playwright/test';
import { PAGES_WITH_DANGEROUS_CONTROLS, gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

test.describe('default_deny_inventory', () => {
  for (const entry of PAGES_WITH_DANGEROUS_CONTROLS) {
    test(`every dangerous control on ${entry.path} is disabled and shows approval badge`, async ({ page }) => {
      await mockAuth(page, 'reviewer');
      await gotoAs(page, entry.path, 'reviewer');
      const panel = page.getByTestId('dangerous-control-panel');
      await expect(panel).toBeVisible();
      for (const id of entry.controls) {
        const item = page.getByTestId(`dangerous-control-${id}`);
        await expect(item).toBeVisible();
        const button = item.locator('button.dangerous-control-button');
        await expect(button).toBeDisabled();
        await expect(button).toHaveAttribute('aria-disabled', 'true');
        await expect(page.getByTestId(`requires-approval-${id}`)).toBeVisible();
      }
    });
  }
});
