import { test, expect } from '@playwright/test';
import { gotoAs } from './_shared';

test.describe('operator proof dashboard historical 30d', () => {
  test('renders historical 30D proof evidence without live controls', async ({ page }) => {
    await gotoAs(page, '/admin/operator-proof-dashboard', 'admin');

    const section = page.getByTestId('historical-30d-proof');
    await expect(section).toBeVisible();
    await expect(page.getByTestId('historical-30d-marker')).toContainText(
      'HISTORICAL_30D_REPLAY_AND_PAPER_PROOF_READY',
    );
    await expect(section).toContainText('blocked_human_only');
    await expect(page.getByTestId('historical-legacy-vs-v2')).toContainText('LABUSDT');
    await expect(page.getByTestId('historical-blocked-losses')).toContainText(
      'short_squeeze_and_hedge_unwind_residual_exposure',
    );
    await expect(page.getByTestId('historical-preserved-winners')).toContainText('BTCUSDT');
    await expect(page.getByTestId('historical-reduced-rejected')).toContainText('ETHUSDT');
    await expect(page.getByTestId('historical-paper-shadow-summary')).toContainText('shadow divergences');
    await expect(page.getByTestId('historical-data-gaps')).toContainText('No external exchange');
    await expect(section.getByRole('button')).toHaveCount(0);
  });
});
