import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';

const GOAL_ID = 'V2_ENTERPRISE_WEB_IOS_REALTIME_DATA_PLANE_PUBLIC_READY_COMPLETION';

function readArg(name, fallback = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : fallback;
}

function nowIso() {
  return new Date().toISOString();
}

function outputPath() {
  const repoRoot = path.resolve(process.cwd(), '..', '..');
  return readArg('output')
    ?? path.join(repoRoot, 'goal_state', GOAL_ID, 'phase12_public_ready_completion_audit.json');
}

function testUser(role) {
  const trader = role === 'trader';
  return {
    id: `audit-${role}`,
    trader_id: trader ? 'audit-trader' : null,
    username: `audit_${role}`,
    email: `${role}@audit.local`,
    role,
    paper_account_id: trader ? 'audit-paper' : null,
    exchange_accounts: [],
    watchlist: ['BTCUSDT', 'ETHUSDT'],
    alert_preferences: {},
    is_active: true,
    created_at: '2026-07-09T00:00:00Z',
    updated_at: '2026-07-09T00:00:00Z',
    last_login: '2026-07-09T00:00:00Z',
  };
}

async function installAuth(page, role) {
  await page.route('**/api/auth/me', async (route) => {
    if (!role) {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'authentication_required' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: testUser(role) }),
    });
  });
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
}

function wsCategory(url) {
  if (url.includes('/api/v2/realtime/ws')) return 'enterprise_shared_realtime';
  if (url.includes('/api/v2/ws/resource') || url.includes('/ws/resource')) return 'legacy_resource_stream';
  if (url.includes('/api/v2/ws/paper-activity') || url.includes('/ws/paper-activity')) return 'paper_activity_stream';
  if (url.includes('fstream.binance.com')) return 'native_binance_market_stream';
  return 'other';
}

function wireSockets(page) {
  const records = [];
  const counts = {};
  let active = 0;
  let maxConcurrent = 0;
  page.on('websocket', (ws) => {
    const category = wsCategory(ws.url());
    counts[category] = (counts[category] ?? 0) + 1;
    active += 1;
    maxConcurrent = Math.max(maxConcurrent, active);
    const row = { url: ws.url(), category, opened_at: nowIso(), closed_at: null };
    records.push(row);
    ws.on('close', () => {
      row.closed_at = nowIso();
      active = Math.max(0, active - 1);
    });
  });
  return {
    summary: () => ({
      total_opened: records.length,
      active_at_end: active,
      max_concurrent: maxConcurrent,
      category_counts: counts,
      legacy_resource_socket_count: counts.legacy_resource_stream ?? 0,
      enterprise_shared_realtime_count: counts.enterprise_shared_realtime ?? 0,
    }),
  };
}

async function backendDownLoginAudit(browser, baseUrl) {
  const page = await browser.newPage({ serviceWorkers: 'block' });
  await installAuth(page, null);
  await page.route('**/api/auth/login', async (route) => route.abort('failed'));
  const errors = [];
  page.on('pageerror', (err) => errors.push(String(err)));
  await page.goto(new URL('/login', baseUrl).toString(), { waitUntil: 'domcontentloaded' });
  await page.getByLabel('Email').fill('operator@example.com');
  await page.getByPlaceholder('Enter password').fill('not-a-real-password');
  await page.getByRole('button', { name: /^Sign in$/ }).click();
  const alert = await page.getByRole('alert').textContent({ timeout: 5_000 }).catch(() => null);
  await page.close();
  return {
    status: alert === 'Sign-in service unavailable' && errors.length === 0 ? 'PASS' : 'FAIL',
    simulated_condition: 'api_auth_login_network_failure',
    alert_text: alert,
    page_error_count: errors.length,
  };
}

async function refreshPersistenceAudit(browser, baseUrl) {
  const page = await browser.newPage({ serviceWorkers: 'block' });
  await installAuth(page, 'trader');
  const sockets = wireSockets(page);
  await page.goto(new URL('/dashboard?role=trader', baseUrl).toString(), { waitUntil: 'domcontentloaded' });
  await page.getByTestId('page-dashboard').waitFor({ state: 'visible', timeout: 10_000 });
  await page.waitForTimeout(2_500);
  const beforeUrl = page.url();
  await page.reload({ waitUntil: 'domcontentloaded' });
  await page.getByTestId('page-dashboard').waitFor({ state: 'visible', timeout: 10_000 });
  await page.waitForTimeout(2_500);
  const summary = sockets.summary();
  const afterUrl = page.url();
  await page.close();
  const pass = !afterUrl.includes('/login')
    && summary.enterprise_shared_realtime_count > 0
    && summary.legacy_resource_socket_count === 0;
  return {
    status: pass ? 'PASS' : 'FAIL',
    route: '/dashboard?role=trader',
    before_url: beforeUrl,
    after_url: afterUrl,
    page_visible_after_reload: pass,
    websocket_summary: summary,
  };
}

async function aiPageAudit(browser, baseUrl) {
  const response = await fetch(new URL('/api/v2/ui/ai-brain', baseUrl).toString());
  const snapshot = response.ok ? await response.json() : {};
  const contract = snapshot?.payload?.ai_page_contract ?? {};
  const page = await browser.newPage({ serviceWorkers: 'block' });
  await installAuth(page, 'admin');
  await page.goto(new URL('/admin/intelligence?role=admin', baseUrl).toString(), { waitUntil: 'domcontentloaded' });
  await page.getByTestId('admin-intelligence-page').waitFor({ state: 'visible', timeout: 10_000 });
  await page.getByText('Enterprise AI Data Plane').waitFor({ state: 'visible', timeout: 10_000 });
  const panelText = await page.locator('#enterprise-ai-data-plane').innerText({ timeout: 10_000 }).catch(() => '');
  await page.close();
  const providerCounts = contract.provider_feature_count_by_provider ?? {};
  const pass = response.ok
    && contract.schema_version === 'enterprise_ai_page_contract_v1'
    && contract.routes_to_live === false
    && contract.places_real_order === false
    && ['coinglass', 'santiment', 'moralis'].every((provider) => Object.prototype.hasOwnProperty.call(providerCounts, provider))
    && panelText.includes('PPO tensor')
    && panelText.includes('MASA tensor');
  return {
    status: pass ? 'PASS' : 'FAIL',
    backend_status: response.status,
    backend_schema: snapshot?.schema_version ?? null,
    contract_schema: contract.schema_version ?? null,
    provider_feature_count_by_provider: providerCounts,
    routes_to_live: contract.routes_to_live,
    places_real_order: contract.places_real_order,
    rendered_panel_contains_tensor_fields: panelText.includes('PPO tensor') && panelText.includes('MASA tensor'),
  };
}

async function main() {
  const baseUrl = readArg('base-url') ?? process.env.PUBLIC_READY_BASE_URL ?? 'http://127.0.0.1:8000';
  const started = nowIso();
  const browser = await chromium.launch({ headless: true });
  let result;
  try {
    const backendDownLogin = await backendDownLoginAudit(browser, baseUrl);
    const refreshPersistence = await refreshPersistenceAudit(browser, baseUrl);
    const aiTrainerPage = await aiPageAudit(browser, baseUrl);
    const checks = { backend_down_login_error_path: backendDownLogin, refresh_persistence: refreshPersistence, ai_trainer_page: aiTrainerPage };
    const status = Object.values(checks).every((check) => check.status === 'PASS') ? 'PUBLIC_READY_COMPLETION_AUDIT_PASS' : 'PUBLIC_READY_COMPLETION_AUDIT_FAIL';
    result = {
      schema_version: 'public_ready_completion_audit_v1',
      generated_utc: nowIso(),
      started_utc: started,
      base_url: baseUrl,
      checks,
      safety: {
        live_gate_expected: 'blocked_human_only',
        places_real_order: false,
        places_test_order: false,
        mutates_leverage: false,
        mutates_margin_mode: false,
        transfers_or_withdraws: false,
      },
      status,
    };
  } finally {
    await browser.close();
  }

  const out = outputPath();
  mkdirSync(path.dirname(out), { recursive: true });
  writeFileSync(out, `${JSON.stringify(result, null, 2)}\n`);
  console.log(JSON.stringify({ status: result.status, output: out }, null, 2));
  if (result.status !== 'PUBLIC_READY_COMPLETION_AUDIT_PASS') {
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
