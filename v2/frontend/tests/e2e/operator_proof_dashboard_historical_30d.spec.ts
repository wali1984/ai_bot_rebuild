import { test, expect } from '@playwright/test';
import { gotoAs } from './_shared';

test.describe('operator proof dashboard historical 30d', () => {
  test('renders professional operator cockpit evidence without live controls', async ({ page }) => {
    await gotoAs(page, '/admin/operator-proof-dashboard', 'admin');

    await expect(page.getByTestId('operator-top-status-bar')).toBeVisible();
    await expect(page.getByTestId('operator-gui-marker')).toContainText(
      'PROFESSIONAL_OPERATOR_GUI_AND_DECISION_EXPLAINABILITY_READY',
    );
    await expect(page.getByTestId('operator-live-gate')).toContainText('blocked_human_only');
    await expect(page.getByTestId('cockpit-mission-control')).toContainText('Mission Control');
    await expect(page.getByTestId('cockpit-monitor-center')).toContainText('Monitor Center');
    await expect(page.getByTestId('cockpit-trainer-prediction-monitor')).toContainText('Trainer Prediction Monitor');
    await expect(page.getByTestId('cockpit-signal-explainability')).toContainText('LABUSDT');
    await expect(page.getByTestId('cockpit-feature-attribution')).toContainText('feature_snapshot');
    await expect(page.getByTestId('cockpit-symbol-universe')).toContainText('Universe');
    await expect(page.getByTestId('cockpit-risk-gateway')).toContainText('short_squeeze_and_hedge_unwind_residual_exposure');
    await expect(page.getByTestId('cockpit-config-admin')).toContainText('requires explicit human approval');
    await expect(page.getByTestId('cockpit-live-readiness')).toContainText('Dangerous controls enabled');
    await expect(page.getByTestId('cockpit-remaining-blockers')).toContainText('Evidence gaps');
    await expect(page.getByTestId('operator-proof-dashboard').getByRole('button')).toHaveCount(0);
  });
});
