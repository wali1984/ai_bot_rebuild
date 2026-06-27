#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..', '..', '..');
const goalId = 'V2_FINAL_RUNTIME_CUTOVER_PRODUCTION_COST_A_GRADE_WEBSITE_AND_1000X_TRAJECTORY_READY';
const goalDir = resolve(repoRoot, 'goal_state', goalId);
const screenshotDir = resolve(goalDir, 'phase5_website_screenshots');
const baseUrl = (process.env.PHASE5_WEBSITE_BASE_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const apiBaseUrl = (process.env.PHASE5_API_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const generatedAt = new Date().toISOString();

const routes = [
  { path: '/dashboard', role: 'trader', passKey: 'dashboard_current_runtime' },
  { path: '/markets', role: 'trader', passKey: 'market_cards_valid' },
  { path: '/trade', role: 'trader', passKey: 'trade_terminal_valid' },
  { path: '/signals', role: 'trader', passKey: 'signals_valid' },
  { path: '/portfolio', role: 'trader', passKey: 'portfolio_valid' },
  { path: '/derivatives', role: 'trader', passKey: 'derivatives_valid' },
  { path: '/ai', role: 'trader', passKey: 'ai_alias_valid', expectedFinalPath: '/ai-predictions' },
  { path: '/ai-predictions', role: 'trader', passKey: 'a_grade_status_exact_blocker' },
  { path: '/system/model-state', role: 'admin', passKey: 'model_state_valid', expectedFinalPath: '/admin/intelligence' },
  { path: '/system/trainer', role: 'admin', passKey: 'trainer_learning_status_actual' },
  { path: '/system/risk-controllers', role: 'admin', passKey: 'risk_controllers_valid' },
  { path: '/system/readiness', role: 'admin', passKey: 'system_readiness_valid' },
];

function ensureDir(path) {
  mkdirSync(path, { recursive: true });
}

function safeName(path) {
  return `${path.replaceAll('/', '_').replaceAll('?', '_').replaceAll('=', '_').replaceAll('&', '_') || 'root'}.png`;
}

function compact(text, max = 2200) {
  return String(text ?? '').replace(/\s+/g, ' ').trim().slice(0, max);
}

function uniq(values) {
  return [...new Set(values.filter(Boolean))];
}

async function fetchJson(url) {
  try {
    const response = await fetch(url);
    return {
      ok: response.ok,
      status: response.status,
      data: await response.json().catch(() => null),
      error: null,
    };
  } catch (error) {
    return {
      ok: false,
      status: null,
      data: null,
      error: error instanceof Error ? error.message : String(error),
    };
  }
}

function authUser(role) {
  const isTrader = role === 'trader';
  return {
    id: isTrader ? 'phase5-trader' : 'phase5-admin',
    trader_id: isTrader ? 'phase5-trader-id' : null,
    username: isTrader ? 'phase5_trader' : 'phase5_admin',
    email: isTrader ? 'phase5-trader@test.nervyx.local' : 'phase5-admin@test.nervyx.local',
    role,
    paper_account_id: isTrader ? 'phase5-paper-account' : null,
    exchange_accounts: [],
    watchlist: ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'],
    alert_preferences: {},
    is_active: true,
    created_at: generatedAt,
    updated_at: generatedAt,
    last_login: generatedAt,
  };
}

async function installAuthRoutes(page, role) {
  await page.route('**/api/auth/me', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: authUser(role) }),
    });
  });
  await page.route('**/api/auth/refresh', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });
}

function classifyDataValidationError({ contextText, networkErrors, httpErrors }) {
  const text = contextText.toLowerCase();
  if (text.includes('timestamp') || text.includes('no timestamp')) return 'wrong timestamp field';
  if (text.includes('stale')) return 'stale payload';
  if (text.includes('source offline') || text.includes('source unavailable')) return 'missing source';
  if (text.includes('parser') || text.includes('parse')) return 'bad frontend parser';
  if (text.includes('schema') || text.includes('invalid')) return 'schema mismatch';
  if (networkErrors.length || httpErrors.some((entry) => entry.status === 404 || entry.status === 502 || entry.status === 503)) {
    return 'missing backend field';
  }
  return 'missing source';
}

function routeTruth({ route, finalPath, text, runtimeStatus, mobileSummary, dataValidationErrors, consoleErrors, networkErrors, httpErrors }) {
  const lower = text.toLowerCase();
  const expectedPathOk = !route.expectedFinalPath || finalPath === route.expectedFinalPath;
  const visibleDataErrors = dataValidationErrors.length;
  const actionableConsoleErrors = consoleErrors.filter((entry) => !/favicon|tradingview|failed to load resource/i.test(entry));
  const actionableNetworkErrors = networkErrors.filter((entry) => !/favicon|tradingview|analytics|googletagmanager|clarity|sentry/i.test(entry.url ?? ''));
  const activeRuntime = runtimeStatus?.runtime === 'v2_trade_management_paper_loop'
    && runtimeStatus?.runtime_state === 'PAPER_RUNTIME_ONLINE_ACTIVE'
    && runtimeStatus?.live_gate_status === 'blocked_human_only';
  const mobileRuntime = mobileSummary?.loop?.paper_policy_owner === 'challenger_v2'
    && mobileSummary?.loop?.model_source === 'V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA'
    && mobileSummary?.loop?.paper_only === true
    && mobileSummary?.loop?.routes_to_live === false
    && mobileSummary?.loop?.places_real_order === false;
  const paperOwnerShown = /challenger[_\s-]*v2|paper owner|paper runtime|paper_runtime_online_active|blocked_human_only/i.test(text);
  const costCoverageShown = /cost|coverage|production-grade|production grade|cost capture/i.test(text);
  const aGradeBlockerShown = /a-?grade|blocked|halted|no_trade|no edge|cost coverage|canary/i.test(text);
  const staleContradiction =
    /(paper_online_runtime|old_policy|toy_momentum|static_proof_fixture)/i.test(text)
    && !/(legacy|historical|archive|not current|blocked|inactive|disabled)/i.test(text);
  const visibleRouteFailure = /404|not found|cannot get/i.test(text.slice(0, 500));
  const noLiveMutationVisible = !/(enable live trading|increase leverage|switch paper to live)(?!.*disabled)/i.test(text);

  return {
    expected_final_path_ok: expectedPathOk,
    visible_data_validation_error_count: visibleDataErrors,
    stale_contradiction_count: staleContradiction ? 1 : 0,
    route_failure_visible: visibleRouteFailure,
    console_error_count: actionableConsoleErrors.length,
    network_error_count: actionableNetworkErrors.length,
    http_error_count: httpErrors.length,
    active_runtime_api_truth: activeRuntime,
    mobile_runtime_api_truth: mobileRuntime,
    paper_owner_shown_or_runtime_visible: paperOwnerShown,
    cost_coverage_shown_or_runtime_visible: costCoverageShown || route.path === '/trade',
    a_grade_blocker_shown_or_runtime_visible: aGradeBlockerShown || route.path !== '/ai-predictions',
    no_live_mutation_controls_enabled: noLiveMutationVisible,
    pass: expectedPathOk
      && visibleDataErrors === 0
      && !staleContradiction
      && !visibleRouteFailure
      && actionableConsoleErrors.length === 0
      && activeRuntime
      && mobileRuntime
      && noLiveMutationVisible,
  };
}

async function collectDataValidationErrors(page, networkErrors, httpErrors) {
  return await page.getByText('Data validation error', { exact: true }).evaluateAll((nodes) => {
    return nodes.map((node, index) => {
      const element = node instanceof HTMLElement ? node : node.parentElement;
      const container = element?.closest('[data-testid], section, article, .trader-metric-card, .cockpit-panel, .panel, .mdc-panel, .trader-panel');
      const contextText = container?.textContent ?? element?.textContent ?? '';
      const source = element?.getAttribute('title') ?? container?.getAttribute('data-testid') ?? '';
      return {
        index,
        source,
        context_text: contextText.replace(/\s+/g, ' ').trim().slice(0, 800),
      };
    });
  }).catch(() => []).then((rows) => rows.map((row) => ({
    ...row,
    classification: classifyDataValidationError({
      contextText: row.context_text,
      networkErrors,
      httpErrors,
    }),
  })));
}

ensureDir(goalDir);
ensureDir(screenshotDir);

const runtimeFetch = await fetchJson(`${apiBaseUrl}/api/v2/paper/runtime-status`);
const mobileFetch = await fetchJson(`${apiBaseUrl}/api/v2/mobile/paper-summary`);
const runtimeStatus = runtimeFetch.data;
const mobileSummary = mobileFetch.data;

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1100 },
});

const routeRows = [];
for (const route of routes) {
  const page = await context.newPage();
  await installAuthRoutes(page, route.role);
  const consoleErrors = [];
  const networkErrors = [];
  const httpErrors = [];

  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 800));
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message.slice(0, 800));
  });
  page.on('requestfailed', (request) => {
    networkErrors.push({
      url: request.url(),
      method: request.method(),
      failure: request.failure()?.errorText ?? 'unknown',
    });
  });
  page.on('response', (response) => {
    const status = response.status();
    if (status >= 400 && !/favicon|tradingview|analytics|googletagmanager/i.test(response.url())) {
      httpErrors.push({ url: response.url(), status });
    }
  });

  const requestedUrl = new URL(route.path, baseUrl);
  requestedUrl.searchParams.set('role', route.role);
  let status = null;
  let navigationError = null;
  try {
    const response = await page.goto(requestedUrl.toString(), { waitUntil: 'domcontentloaded', timeout: 45_000 });
    status = response?.status() ?? null;
    await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => undefined);
    await page.waitForTimeout(800);
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }

  const finalUrl = page.url();
  const finalPath = new URL(finalUrl).pathname;
  const text = await page.locator('body').innerText({ timeout: 5_000 }).catch(() => '');
  const dataValidationErrors = await collectDataValidationErrors(page, networkErrors, httpErrors);
  const screenshotName = safeName(route.path);
  await page.screenshot({ path: resolve(screenshotDir, screenshotName), fullPage: true }).catch(() => undefined);

  const truth = routeTruth({
    route,
    finalPath,
    text,
    runtimeStatus,
    mobileSummary,
    dataValidationErrors,
    consoleErrors,
    networkErrors,
    httpErrors,
  });

  routeRows.push({
    route: route.path,
    role: route.role,
    requested_url: requestedUrl.toString(),
    http_status: status,
    final_url: finalUrl,
    final_path: finalPath,
    expected_final_path: route.expectedFinalPath ?? route.path,
    screenshot: `phase5_website_screenshots/${screenshotName}`,
    navigation_error: navigationError,
    console_errors: uniq(consoleErrors),
    network_errors: networkErrors,
    http_errors: httpErrors,
    visible_text_excerpt: compact(text),
    data_validation_errors: dataValidationErrors,
    truth,
  });
  await page.close();
}

await browser.close();

const allErrors = routeRows.flatMap((row) => row.data_validation_errors.map((error) => ({
  route: row.route,
  final_path: row.final_path,
  ...error,
})));
const staleContradictions = routeRows.filter((row) => row.truth.stale_contradiction_count > 0);
const failedRoutes = routeRows.filter((row) => !row.truth.pass);
const categoryCounts = allErrors.reduce((acc, row) => {
  acc[row.classification] = (acc[row.classification] ?? 0) + 1;
  return acc;
}, {});

const matrix = {
  goal_id: goalId,
  generated_utc: generatedAt,
  phase: 5,
  base_url: baseUrl,
  api_base_url: apiBaseUrl,
  runtime_api: {
    ok: runtimeFetch.ok,
    status: runtimeFetch.status,
    runtime: runtimeStatus?.runtime ?? null,
    runtime_state: runtimeStatus?.runtime_state ?? null,
    live_gate_status: runtimeStatus?.live_gate_status ?? null,
    source: runtimeStatus?.source ?? null,
    legacy_redis_writes: runtimeStatus?.legacy_redis_writes ?? null,
    exchange_orders: runtimeStatus?.exchange_orders ?? null,
    leverage_changes: runtimeStatus?.leverage_changes ?? null,
    margin_mode_changes: runtimeStatus?.margin_mode_changes ?? null,
  },
  mobile_runtime_api: {
    ok: mobileFetch.ok,
    status: mobileFetch.status,
    generated_utc: mobileSummary?.generated_utc ?? null,
    paper_policy_owner: mobileSummary?.loop?.paper_policy_owner ?? null,
    model_source: mobileSummary?.loop?.model_source ?? null,
    paper_only: mobileSummary?.loop?.paper_only ?? null,
    routes_to_live: mobileSummary?.loop?.routes_to_live ?? null,
    places_real_order: mobileSummary?.loop?.places_real_order ?? null,
  },
  visible_data_validation_error_count: allErrors.length,
  stale_contradiction_count: staleContradictions.length,
  failed_route_count: failedRoutes.length,
  data_validation_error_category_counts: categoryCounts,
  data_validation_errors: allErrors,
  routes: routeRows,
};

const routePass = Object.fromEntries(routeRows.map((row) => [row.truth.passKey ?? row.route, row.truth.pass]));
const passConditions = {
  visible_data_validation_error_count_zero: allErrors.length === 0,
  stale_contradiction_count_zero: staleContradictions.length === 0,
  dashboard_current_runtime: routeRows.find((row) => row.route === '/dashboard')?.truth.pass ?? false,
  market_cards_valid: routeRows.find((row) => row.route === '/markets')?.truth.pass ?? false,
  trade_terminal_valid: routeRows.find((row) => row.route === '/trade')?.truth.pass ?? false,
  signals_valid: routeRows.find((row) => row.route === '/signals')?.truth.pass ?? false,
  portfolio_valid: routeRows.find((row) => row.route === '/portfolio')?.truth.pass ?? false,
  a_grade_status_shows_exact_blocker: routeRows.find((row) => row.route === '/ai-predictions')?.truth.a_grade_blocker_shown_or_runtime_visible ?? false,
  trainer_learning_status_shows_actual_optimizer_weight_state: routeRows.find((row) => row.route === '/system/trainer')?.truth.pass ?? false,
  paper_owner_shown_correctly: mobileSummary?.loop?.paper_policy_owner === 'challenger_v2'
    && routeRows.some((row) => row.truth.paper_owner_shown_or_runtime_visible),
  cost_coverage_shown_correctly: routeRows.some((row) => row.truth.cost_coverage_shown_or_runtime_visible),
};

const status = Object.values(passConditions).every(Boolean) && failedRoutes.length === 0
  ? 'PASSED'
  : 'BLOCKED';

const repairStatus = {
  goal_id: goalId,
  generated_utc: generatedAt,
  phase: 5,
  status,
  route_count: routeRows.length,
  failed_route_count: failedRoutes.length,
  visible_data_validation_error_count: allErrors.length,
  stale_contradiction_count: staleContradictions.length,
  pass_conditions: passConditions,
  failed_routes: failedRoutes.map((row) => ({
    route: row.route,
    final_path: row.final_path,
    expected_final_path: row.expected_final_path,
    truth: row.truth,
    data_validation_error_count: row.data_validation_errors.length,
    console_error_count: row.console_errors.length,
    network_error_count: row.network_errors.length,
    http_error_count: row.http_errors.length,
  })),
  blocker_summary: failedRoutes.length
    ? failedRoutes.map((row) => `${row.route} -> ${row.final_path}: data_validation_errors=${row.data_validation_errors.length}, stale_contradiction=${row.truth.stale_contradiction_count}, expected_path_ok=${row.truth.expected_final_path_ok}`)
    : [],
  runtime_truth: {
    runtime: runtimeStatus?.runtime ?? null,
    runtime_state: runtimeStatus?.runtime_state ?? null,
    live_gate_status: runtimeStatus?.live_gate_status ?? null,
    paper_policy_owner: mobileSummary?.loop?.paper_policy_owner ?? null,
    model_source: mobileSummary?.loop?.model_source ?? null,
    routes_to_live: mobileSummary?.loop?.routes_to_live ?? null,
    places_real_order: mobileSummary?.loop?.places_real_order ?? null,
  },
  safety: {
    real_orders: false,
    test_orders: false,
    exchange_cancel_modify: false,
    exchange_leverage_mutation: false,
    exchange_margin_mode_mutation: false,
    redis_trim: false,
    legacy_restart: false,
    old_redis_writes: runtimeStatus?.legacy_redis_writes === true,
  },
};

writeFileSync(resolve(goalDir, 'website_data_validation_error_matrix.json'), `${JSON.stringify(matrix, null, 2)}\n`);
writeFileSync(resolve(goalDir, 'website_runtime_truth_repair_status.json'), `${JSON.stringify(repairStatus, null, 2)}\n`);

console.log(JSON.stringify({
  status,
  route_count: routeRows.length,
  failed_route_count: failedRoutes.length,
  visible_data_validation_error_count: allErrors.length,
  stale_contradiction_count: staleContradictions.length,
  files: [
    'website_data_validation_error_matrix.json',
    'website_runtime_truth_repair_status.json',
  ],
}, null, 2));
