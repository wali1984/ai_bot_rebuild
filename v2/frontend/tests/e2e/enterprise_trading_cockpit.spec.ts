import { test, expect } from '@playwright/test';
import { gotoAs } from './_shared';

test.describe('enterprise trading cockpit', () => {
  test('renders mission control as a cockpit with live blocked and freshness labels', async ({ page }) => {
    await gotoAs(page, '/admin/mission-control', 'admin');

    await expect(page.getByTestId('page-mission-control')).toContainText('AI BOT V2 Mission Control');
    await expect(page.getByTestId('page-mission-control')).toContainText('LIVE TRADING: blocked_human_only');
    await expect(page.getByTestId('cockpit-topbar')).toContainText('blocked_human_only');
    await expect(page.getByTestId('cockpit-charting-market-data')).toContainText('STATIC_PROOF_FIXTURE');
    await expect(page.getByTestId('cockpit-market-pulse')).toContainText('BTCUSDT');
    await expect(page.getByTestId('cockpit-market-pulse')).toContainText('Funding');
    await expect(page.getByTestId('cockpit-decision-explainability')).toContainText('feature_snapshot_id');
    await expect(page.getByTestId('cockpit-decision-explainability')).toContainText('Evidence missing - cannot explain without guessing');
    await expect(page.getByTestId('cockpit-exchange-manager')).toContainText('Binance USD-M');
    await expect(page.getByTestId('cockpit-exchange-manager')).toContainText('disabled_no_order_methods');
    await expect(page.getByTestId('cockpit-external-manual-position-quarantine')).toContainText('2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_READY');
    await expect(page.getByTestId('cockpit-freshness-and-live-readiness-blockers')).toContainText('real_time_market_feed');
    await expect(page.getByTestId('page-mission-control').getByRole('button')).toHaveCount(0);
  });

  test('renders required admin pages with real evidence or explicit gaps', async ({ page }) => {
    await gotoAs(page, '/admin/monitor-center', 'admin');
    await expect(page.getByTestId('page-monitor-center')).toContainText('scripts/monitor_trainer_predictions.py');
    await expect(page.getByTestId('page-monitor-center')).toContainText('trainer monitor logs');

    await gotoAs(page, '/admin/trainer-prediction-monitor', 'admin');
    await expect(page.getByTestId('page-trainer-prediction-monitor')).toContainText('hist_pred_day03_btc_winner_preserved');
    await expect(page.getByTestId('page-trainer-prediction-monitor')).toContainText('feature_snapshot_id');

    await gotoAs(page, '/admin/signal-explainability', 'admin');
    await expect(page.getByTestId('page-signal-explainability')).toContainText('Evidence missing - cannot explain without guessing');
    await expect(page.getByTestId('page-signal-explainability')).toContainText('risk_decision_id');

    await gotoAs(page, '/admin/exchange-manager', 'admin');
    await expect(page.getByTestId('page-exchange-manager')).toContainText('KuCoin');
    await expect(page.getByTestId('page-exchange-manager')).toContainText('blocked_no_sandbox');

    await gotoAs(page, '/admin/config-admin', 'admin');
    await expect(page.getByTestId('page-config-admin')).toContainText('live_trading_enabled');
    await expect(page.getByTestId('page-config-admin')).toContainText('requires_human_approval');

    await gotoAs(page, '/admin/external-manual-position-quarantine', 'admin');
    await expect(page.getByTestId('page-external-manual-position-quarantine')).toContainText('manual_external');
    await expect(page.getByTestId('page-external-manual-position-quarantine')).toContainText('duplicate_accounting');

    await gotoAs(page, '/admin/operator-proof-dashboard', 'admin');
    await expect(page.getByTestId('operator-proof-dashboard')).toContainText('Operator Proof');
  });
});
