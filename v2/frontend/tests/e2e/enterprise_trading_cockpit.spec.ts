import { test, expect } from '@playwright/test';
import { gotoAs } from './_shared';
import { mockAuth } from './helpers/auth';

test.describe('enterprise trading cockpit', () => {
  test('renders mission control as a cockpit with live blocked and freshness labels', async ({ page }) => {
    await mockAuth(page, 'admin');
    await gotoAs(page, '/admin/mission-control');

    await expect(page).toHaveURL(/\/dashboard$/);
    await expect(page.getByTestId('page-dashboard')).toContainText('NERVYX EXECUTE');
    await expect(page.getByTestId('dashboard-websocket-status')).toContainText('Browser');
    await expect(page.getByTestId('dashboard-admin-diagnostics')).toBeVisible();
    await expect(page.getByTestId('mission-control-readiness-banner')).toBeVisible();
    await expect(page.getByTestId('mc-live-gate-status')).toContainText('blocked_human_only');
    await expect(page.getByTestId('stale-state-alerts-panel')).toBeVisible();
    await expect(page.getByTestId('adaptive-capital-telemetry-panel')).toContainText('Capital Productivity');
    await expect(page.getByTestId('page-dashboard')).not.toContainText('AI BOT V2');
  });

  test('renders required admin pages with real evidence or explicit gaps', async ({ page }) => {
    await mockAuth(page, 'superadmin');
    await gotoAs(page, '/admin/monitor-center');
    await expect(page.getByTestId('page-monitor-center')).toContainText('Monitor Center');
    await expect(page.getByTestId('page-monitor-center')).toContainText('Realtime stream health');

    await gotoAs(page, '/admin/trainer-prediction-monitor');
    await expect(page).toHaveURL(/\/admin\/trainer-prediction-monitor$/);
    await expect(page.getByTestId('page-trainer-prediction-monitor')).toContainText('AI Predictions');
    await expect(page.getByTestId('adaptive-capital-telemetry-panel')).toContainText('Prediction Accuracy');

    await gotoAs(page, '/admin/signal-explainability');
    await expect(page.getByTestId('page-signal-explainability')).toContainText('Signal Explainability');
    await expect(page.getByTestId('page-signal-explainability')).toContainText('risk_decision_id');

    await gotoAs(page, '/admin/exchange-manager');
    await expect(page).toHaveURL(/\/admin\/exchanges$/);
    await expect(page.getByTestId('admin-exchanges-page')).toContainText('Exchanges');
    await expect(page.getByTestId('admin-exchanges-page')).toContainText('Exchange connectivity');

    await gotoAs(page, '/admin/config-admin');
    await expect(page).toHaveURL(/\/admin\/config$/);
    await expect(page.getByTestId('admin-config-page')).toContainText('Configuration');
    await page.getByRole('button', { name: 'Locks' }).click();
    await expect(page.getByTestId('admin-config-page')).toContainText('Enable Live Trading');
    await expect(page.getByTestId('admin-config-page')).toContainText('L5');

    await gotoAs(page, '/admin/external-manual-position-quarantine');
    await expect(page.getByTestId('page-external-manual-position-quarantine')).toContainText('External / Manual Position Quarantine');
    await expect(page.getByTestId('page-external-manual-position-quarantine')).toContainText('Duplicate accounting');

    await gotoAs(page, '/admin/operator-proof-dashboard');
    await expect(page).toHaveURL(/\/admin\/evidence$/);
    await expect(page.getByTestId('operator-proof-dashboard')).toContainText('NERVYX EVIDENCE');
  });
});
