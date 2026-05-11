import { test, expect, type Route } from '@playwright/test';
import { gotoAs } from './_shared';

const BANNER_PATH_GLOB = '**/api/v1/live-readiness/banner';
const MISSION_CONTROL_PATH = '/admin/mission-control';

const READY_FIXTURE = {
  rollup_version: 'v1',
  generated_at: '2026-05-11T07:15:00+00:00',
  go_no_go_marker: 'CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_READY',
  all_required_matched: true,
  blocking_lanes: [],
  forbidden_operations: [
    'place_exchange_order',
    'enable_live_trading',
    'restart_live_trader',
  ],
  live_gate_status: 'blocked_human_only',
  lanes: [
    {
      lane_id: 'final_non_live_rebuild',
      description: 'Top-level non-live rebuild go/no-go marker',
      required_marker: 'FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW',
      actual_marker: 'FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW',
      marker_path: 'claude_worklog/final_readiness/04_GO_NO_GO.md',
      found: true,
      matched: true,
      is_required_for_online: true,
      error: null,
    },
    {
      lane_id: 'automation_liveness',
      description: 'Automation liveness + legacy trader down tolerance',
      required_marker: 'AUTOMATION_LIVENESS_AND_LEGACY_TRADER_DOWN_TOLERANCE_READY',
      actual_marker: 'AUTOMATION_LIVENESS_AND_LEGACY_TRADER_DOWN_TOLERANCE_READY',
      marker_path: 'claude_worklog/final_readiness/automation_liveness/latest/GO_NO_GO.md',
      found: true,
      matched: true,
      is_required_for_online: true,
      error: null,
    },
    {
      lane_id: 'trainer_lineage_and_readiness',
      description: 'Trainer lineage + readiness evidence',
      required_marker: 'TRAINER_LINEAGE_AND_READINESS_READY',
      actual_marker: 'TRAINER_LINEAGE_AND_READINESS_READY',
      marker_path: 'claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md',
      found: true,
      matched: true,
      is_required_for_online: true,
      error: null,
    },
    {
      lane_id: 'readonly_market_exchange_data_plane',
      description: 'Read-only market + exchange data plane (Phase 2Z)',
      required_marker: 'PHASE2Z_READONLY_MARKET_AND_EXCHANGE_DATA_PLANE_READY',
      actual_marker: 'PHASE2Z_READONLY_MARKET_AND_EXCHANGE_DATA_PLANE_READY',
      marker_path: 'claude_worklog/final_readiness/readonly_market_exchange_data_plane/latest/GO_NO_GO.md',
      found: true,
      matched: true,
      is_required_for_online: true,
      error: null,
    },
    {
      lane_id: 'decision_explainability_lineage',
      description: 'Decision explainability 069 chain validation',
      required_marker: '069D2_DECISION_LINEAGE_VALIDATION_RERUN_READY',
      actual_marker: '069D2_DECISION_LINEAGE_VALIDATION_RERUN_READY',
      marker_path: 'claude_worklog/final_readiness/decision_explainability_lineage/latest/069D2_GO_NO_GO.md',
      found: true,
      matched: true,
      is_required_for_online: true,
      error: null,
    },
  ],
};

const BLOCKED_MISSING_FIXTURE = {
  ...READY_FIXTURE,
  generated_at: '2026-05-11T07:30:00+00:00',
  go_no_go_marker: 'CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_BLOCKED',
  all_required_matched: false,
  blocking_lanes: ['final_non_live_rebuild'],
  lanes: READY_FIXTURE.lanes.map((lane, index) =>
    index === 0
      ? { ...lane, found: false, matched: false, actual_marker: null, error: 'missing' }
      : lane,
  ),
};

const BLOCKED_DIVERGENT_FIXTURE = {
  ...READY_FIXTURE,
  generated_at: '2026-05-11T07:45:00+00:00',
  go_no_go_marker: 'CLAUDE_PRIMARY_ONLINE_READINESS_BUILD_WITH_CODEX_PARALLEL_AUDIT_AND_UI_POLISH_BLOCKED',
  all_required_matched: false,
  blocking_lanes: ['decision_explainability_lineage'],
  lanes: READY_FIXTURE.lanes.map((lane) =>
    lane.lane_id === 'decision_explainability_lineage'
      ? { ...lane, matched: false, actual_marker: 'SOMETHING_ELSE', error: null }
      : lane,
  ),
};

async function fulfillJson(route: Route, body: unknown): Promise<void> {
  await route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: JSON.stringify(body),
  });
}

test.describe('mission_control_readiness_banner', () => {
  test('renders READY chip and lane list when all_required_matched is true', async ({ page }) => {
    const observedMethods: string[] = [];
    await page.route(BANNER_PATH_GLOB, async (route) => {
      observedMethods.push(route.request().method());
      await fulfillJson(route, READY_FIXTURE);
    });

    await gotoAs(page, MISSION_CONTROL_PATH, 'admin');

    const banner = page.getByTestId('mission-control-readiness-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('data-ready', 'true');
    await expect(banner).toHaveAttribute('data-loaded', 'true');
    await expect(banner).toHaveAttribute('data-blocking-count', '0');

    const chip = page.getByTestId('mc-readiness-chip');
    await expect(chip).toBeVisible();
    await expect(chip).toContainText('READY');
    await expect(chip).toHaveAttribute('data-chip-state', 'ready');

    const liveGate = page.getByTestId('mc-live-gate-status');
    await expect(liveGate).toBeVisible();
    await expect(liveGate).toContainText('blocked_human_only');
    await expect(liveGate).toHaveAttribute('data-live-gate-status', 'blocked_human_only');

    const laneList = page.getByTestId('mc-readiness-lane-list');
    await expect(laneList).toHaveAttribute('data-lane-count', String(READY_FIXTURE.lanes.length));

    for (const lane of READY_FIXTURE.lanes) {
      const row = page.getByTestId(`mc-readiness-lane-${lane.lane_id}`);
      await expect(row).toBeVisible();
      await expect(row).toContainText(lane.lane_id);
      await expect(row).toContainText(lane.marker_path);
      await expect(row).toHaveAttribute('data-lane-status', 'matched');
      await expect(page.getByTestId(`mc-readiness-lane-${lane.lane_id}-status`)).toContainText('matched');
      await expect(page.getByTestId(`mc-readiness-lane-${lane.lane_id}-marker-path`)).toContainText(lane.marker_path);
    }

    expect(observedMethods.length).toBeGreaterThan(0);
    expect(observedMethods.every((m) => m === 'GET')).toBe(true);

    await page.screenshot({
      path: 'test-results/mission_control_readiness_banner/ready.png',
      fullPage: false,
      clip: { x: 0, y: 0, width: 1280, height: 600 },
    });
  });

  test('renders BLOCKED chip and missing-lane status when a required marker is absent', async ({ page }) => {
    await page.route(BANNER_PATH_GLOB, async (route) => {
      await fulfillJson(route, BLOCKED_MISSING_FIXTURE);
    });

    await gotoAs(page, MISSION_CONTROL_PATH, 'admin');

    const banner = page.getByTestId('mission-control-readiness-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('data-ready', 'false');
    await expect(banner).toHaveAttribute('data-blocking-count', '1');

    const chip = page.getByTestId('mc-readiness-chip');
    await expect(chip).toContainText('BLOCKED');
    await expect(chip).toHaveAttribute('data-chip-state', 'blocked');

    const liveGate = page.getByTestId('mc-live-gate-status');
    await expect(liveGate).toContainText('blocked_human_only');

    const missingRow = page.getByTestId('mc-readiness-lane-final_non_live_rebuild');
    await expect(missingRow).toBeVisible();
    await expect(missingRow).toHaveAttribute('data-lane-status', 'missing');
    await expect(page.getByTestId('mc-readiness-lane-final_non_live_rebuild-status')).toContainText('missing');

    await page.screenshot({
      path: 'test-results/mission_control_readiness_banner/blocked-missing.png',
      fullPage: false,
      clip: { x: 0, y: 0, width: 1280, height: 600 },
    });
  });

  test('renders BLOCKED chip and divergent-lane status when a marker text diverges', async ({ page }) => {
    await page.route(BANNER_PATH_GLOB, async (route) => {
      await fulfillJson(route, BLOCKED_DIVERGENT_FIXTURE);
    });

    await gotoAs(page, MISSION_CONTROL_PATH, 'admin');

    const banner = page.getByTestId('mission-control-readiness-banner');
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute('data-ready', 'false');
    await expect(banner).toHaveAttribute('data-blocking-count', '1');

    const chip = page.getByTestId('mc-readiness-chip');
    await expect(chip).toContainText('BLOCKED');

    const divergentRow = page.getByTestId('mc-readiness-lane-decision_explainability_lineage');
    await expect(divergentRow).toBeVisible();
    await expect(divergentRow).toHaveAttribute('data-lane-status', 'divergent');
    await expect(page.getByTestId('mc-readiness-lane-decision_explainability_lineage-status')).toContainText('divergent');

    await page.screenshot({
      path: 'test-results/mission_control_readiness_banner/blocked-divergent.png',
      fullPage: false,
      clip: { x: 0, y: 0, width: 1280, height: 600 },
    });
  });

  test('only issues read-only GET requests against the banner endpoint', async ({ page }) => {
    const observed: Array<{ method: string; postData: string | null }> = [];
    await page.route(BANNER_PATH_GLOB, async (route) => {
      const req = route.request();
      observed.push({ method: req.method(), postData: req.postData() });
      await fulfillJson(route, READY_FIXTURE);
    });

    await gotoAs(page, MISSION_CONTROL_PATH, 'admin');
    await expect(page.getByTestId('mission-control-readiness-banner')).toBeVisible();

    expect(observed.length).toBeGreaterThan(0);
    for (const call of observed) {
      expect(call.method).toBe('GET');
      expect(call.postData).toBeNull();
    }
  });
});
