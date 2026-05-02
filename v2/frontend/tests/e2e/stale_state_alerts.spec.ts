import { test, expect, type Page } from '@playwright/test';
import { gotoAs } from './_shared';

const MISSION_CONTROL_PATH = '/admin/mission-control';

const NOW_ISO = new Date().toISOString();

const ALERT_QUEUE_PAYLOAD = {
  _meta: {
    source: 'synthetic',
    read_at: NOW_ISO,
    error: null as string | null,
  },
  data: {
    generated_at: NOW_ISO,
    next_pending_task: null as string | null,
    current_running_task: 'stuck_task',
    blocked_quota: {
      task_id: 'quota_task_42',
      agent: 'claude',
      resume_after_utc: NOW_ISO,
    },
    stale_running_count: 1,
    stale_running_tasks: ['stuck_task'],
    no_event_count: 1,
    no_event_tasks: ['silent_task'],
    no_output_growth_count: 1,
    no_output_growth_tasks: ['frozen_task'],
    human_attention_required_count: 1,
    human_attention_required_tasks: [
      {
        task_id: 'broken_task',
        agent: 'claude',
        attention_reason: 'max_attempts_exhausted_stale_running',
        last_summary: 'retries exhausted',
      },
    ],
    counts: {
      pending: 0,
      running: 1,
      completed: 0,
      failed: 0,
      blocked: 1,
      retry_scheduled: 0,
      skipped: 0,
      cancelled: 0,
      human_attention_required: 1,
    },
    gate: 'BLOCKED_HUMAN_ATTENTION_REQUIRED',
  },
};

const CLEAN_QUEUE_PAYLOAD = {
  _meta: { source: 'synthetic', read_at: NOW_ISO, error: null as string | null },
  data: {
    generated_at: NOW_ISO,
    next_pending_task: null as string | null,
    current_running_task: 'happy_task',
    blocked_quota: null,
    stale_running_count: 0,
    stale_running_tasks: [],
    no_event_count: 0,
    no_event_tasks: [],
    no_output_growth_count: 0,
    no_output_growth_tasks: [],
    human_attention_required_count: 0,
    human_attention_required_tasks: [],
    counts: {
      pending: 0,
      running: 1,
      completed: 1,
      failed: 0,
      blocked: 0,
      retry_scheduled: 0,
      skipped: 0,
      cancelled: 0,
      human_attention_required: 0,
    },
    gate: 'READY_FOR_SCAFFOLD_PLANNING',
  },
};

const HEALTH_PAYLOAD = {
  _meta: {
    agent_health_source: 'synthetic',
    heartbeat_source: 'synthetic',
    read_at: NOW_ISO,
    agent_health_error: null,
    heartbeat_error: null,
  },
  agent_health: {
    generated_at: NOW_ISO,
    terminal_operator: 'test',
    active_agents: ['Claude', 'Codex', 'Ollama'],
    supervisor_version: '2.0-reliability-hardened',
    last_auto_commit_hash: null,
  },
  heartbeat: {
    pid: 12345,
    tmux_session: '%99',
    loop_count: 7,
    last_loop_ts: NOW_ISO,
    current_task: 'stuck_task',
    last_event_ts: NOW_ISO,
    started_at: NOW_ISO,
    version: '2.0-reliability-hardened',
  },
  heartbeat_age_s: 30,
  heartbeat_stale: false,
  heartbeat_missing: false,
};

const BUILD_PAYLOAD = {
  _meta: { source: 'synthetic', read_at: NOW_ISO, total_runs: 0, returned: 0 },
  runs: [],
};

const AUDIT_PAYLOAD = {
  _meta: { source: 'synthetic', read_at: NOW_ISO, exists: true, returned: 0, limit: 50 },
  events: [],
  chain_intact: true,
  chain_breaks: [],
};

async function mockSupervisorEndpoints(
  page: Page,
  queue: typeof ALERT_QUEUE_PAYLOAD,
): Promise<void> {
  // Keep the existing live-block banner mock honest: route any banner fetch
  // to a "blocked" payload so the layout assertion in nav_smoke does not
  // regress through this spec.
  await page.route('**/api/v1/live/state', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ state: 'blocked', reason: 'default_deny' }),
    }),
  );
  await page.route('**/api/v1/_meta/queue-status', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(queue),
    }),
  );
  await page.route('**/api/v1/_meta/agent-health', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(HEALTH_PAYLOAD),
    }),
  );
  await page.route('**/api/v1/_meta/build-status*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(BUILD_PAYLOAD),
    }),
  );
  await page.route('**/api/v1/_meta/audit-chain*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(AUDIT_PAYLOAD),
    }),
  );
}

test.describe('stale_state_alerts', () => {
  test('surfaces all five alert categories with task ids', async ({ page }) => {
    await mockSupervisorEndpoints(page, ALERT_QUEUE_PAYLOAD);
    await gotoAs(page, MISSION_CONTROL_PATH, 'admin');

    const panel = page.getByTestId('stale-state-alerts-panel');
    await expect(panel).toBeVisible();
    await expect(panel).toHaveAttribute('data-state', 'ok');
    await expect(panel).toHaveAttribute('data-alert-total', '5');

    // stale_running → stuck_task
    const stale = page.getByTestId('stale-state-stale-running');
    await expect(stale).toHaveAttribute('data-count', '1');
    await expect(
      stale.locator('[data-alert-kind="stale_running"][data-task-id="stuck_task"]'),
    ).toHaveCount(1);

    // no_event → silent_task
    const noEvent = page.getByTestId('stale-state-no-event');
    await expect(noEvent).toHaveAttribute('data-count', '1');
    await expect(
      noEvent.locator('[data-alert-kind="no_event"][data-task-id="silent_task"]'),
    ).toHaveCount(1);

    // no_output_growth → frozen_task
    const noGrowth = page.getByTestId('stale-state-no-output-growth');
    await expect(noGrowth).toHaveAttribute('data-count', '1');
    await expect(
      noGrowth.locator(
        '[data-alert-kind="no_output_growth"][data-task-id="frozen_task"]',
      ),
    ).toHaveCount(1);

    // blocked_quota → quota_task_42 with resume-after attribute
    const quota = page.getByTestId('stale-state-blocked-quota');
    await expect(quota).toHaveAttribute('data-count', '1');
    const quotaRow = quota.locator(
      '[data-alert-kind="blocked_quota"][data-task-id="quota_task_42"]',
    );
    await expect(quotaRow).toHaveCount(1);
    await expect(quotaRow).toHaveAttribute('data-resume-after', /.+/);

    // human_attention_required → broken_task with reason attribute
    const human = page.getByTestId('stale-state-human-attention-required');
    await expect(human).toHaveAttribute('data-count', '1');
    const humanRow = human.locator(
      '[data-alert-kind="human_attention_required"][data-task-id="broken_task"]',
    );
    await expect(humanRow).toHaveCount(1);
    await expect(humanRow).toHaveAttribute(
      'data-attention-reason',
      'max_attempts_exhausted_stale_running',
    );
  });

  test('renders empty-state for each category when feed is clean', async ({ page }) => {
    await mockSupervisorEndpoints(page, CLEAN_QUEUE_PAYLOAD);
    await gotoAs(page, MISSION_CONTROL_PATH, 'admin');

    const panel = page.getByTestId('stale-state-alerts-panel');
    await expect(panel).toHaveAttribute('data-state', 'ok');
    await expect(panel).toHaveAttribute('data-alert-total', '0');

    for (const groupTestId of [
      'stale-state-stale-running',
      'stale-state-no-event',
      'stale-state-no-output-growth',
      'stale-state-blocked-quota',
      'stale-state-human-attention-required',
    ]) {
      const group = page.getByTestId(groupTestId);
      await expect(group).toHaveAttribute('data-count', '0');
      await expect(group.locator('[data-testid="alert-task-id"]')).toHaveCount(0);
    }
  });
});
