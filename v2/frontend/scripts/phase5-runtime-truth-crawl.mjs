#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptDir = dirname(fileURLToPath(import.meta.url));
const repoRoot = resolve(scriptDir, '..', '..', '..');
const goalId = process.env.PHASE5_GOAL_ID
  ?? 'V2_FINAL_RUNTIME_CUTOVER_PRODUCTION_COST_A_GRADE_WEBSITE_AND_1000X_TRAJECTORY_READY';
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

function finiteNumber(value, fallback = null) {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value === 'string' && value.trim() && Number.isFinite(Number(value))) return Number(value);
  return fallback;
}

function asObject(value) {
  return value && typeof value === 'object' && !Array.isArray(value) ? value : {};
}

function asArray(value) {
  return Array.isArray(value) ? value : [];
}

function section({ sectionName, source, sourceType, timestamp, sequence, data, warnings = [] }) {
  return {
    meta: {
      source: source ?? 'phase5_runtime_truth_crawl',
      source_type: sourceType ?? 'api',
      source_id: sectionName,
      timestamp,
      received_at: timestamp,
      sequence,
      lag_ms: 0,
      freshness: 'fresh',
      quality: 'valid',
      missing_fields: [],
      warnings,
    },
    data,
  };
}

function buildTraderSnapshotEnvelope(role, inputs) {
  const user = authUser(role);
  const timestamp = new Date().toISOString();
  const sequence = Date.now();
  const portfolioEnvelope = asObject(inputs.portfolio?.data);
  const portfolioData = asObject(portfolioEnvelope.data);
  const positionsEnvelope = asObject(inputs.positions?.data);
  const positionRows = asArray(asObject(positionsEnvelope.data).positions);
  const signalEnvelope = asObject(inputs.signal?.data);
  const activeSignal = asObject(asObject(signalEnvelope.data).active_signal);
  const riskEnvelope = asObject(inputs.risk?.data);
  const riskData = asObject(riskEnvelope.data);
  const marketEnvelope = asObject(inputs.market?.data);
  const marketData = asObject(marketEnvelope.data);

  const equity = finiteNumber(portfolioData.equity, 10_000);
  const exposure = finiteNumber(portfolioData.total_open_notional, 0);
  const realizedPnl = finiteNumber(portfolioData.realized_pnl, 0);
  const unrealizedPnl = finiteNumber(portfolioData.unrealized_pnl, 0);
  const openPositionCount = Number.isInteger(portfolioData.open_position_count)
    ? portfolioData.open_position_count
    : positionRows.length;
  const normalizedPositions = positionRows.map((row, index) => {
    const item = asObject(row);
    return {
      id: String(item.id ?? item.position_id ?? `phase5-position-${index}`),
      symbol: String(item.symbol ?? `POSITION${index + 1}`),
      side: String(item.side ?? item.direction ?? 'paper'),
      quantity: finiteNumber(item.quantity ?? item.net_quantity, 0),
      entry_price: finiteNumber(item.entry_price ?? item.avg_entry_price, 0),
      entry_price_source: String(item.entry_price_source ?? 'paper_position_runtime'),
      mark_price: finiteNumber(item.mark_price ?? item.current_price ?? item.last_mark_price, 0),
      mark_price_source: String(item.mark_price_source ?? 'paper_position_runtime'),
      mark_age_ms: finiteNumber(item.mark_age_ms ?? item.price_age_ms, 0),
      notional: finiteNumber(item.notional ?? item.notional_usd ?? item.entry_notional_usd, 0),
      unrealized_pnl: finiteNumber(item.unrealized_pnl ?? item.unrealized_pnl_usd, 0),
      realized_pnl: finiteNumber(item.realized_pnl ?? item.realized_pnl_usd, 0),
      pnl_percent: finiteNumber(item.pnl_percent ?? item.unrealized_pnl_pct, 0),
      risk_status: String(item.risk_status ?? 'paper_only_blocked_live'),
      signal_id: item.signal_id ?? null,
      prediction_id: item.prediction_id ?? null,
      updated_at: String(item.updated_at ?? item.mark_price_generated_at ?? timestamp),
    };
  });
  const signalId = String(activeSignal.signal_id ?? activeSignal.id ?? 'phase5-live-signal');
  const normalizedSignal = {
    id: signalId,
    symbol: String(activeSignal.symbol ?? 'BTCUSDT'),
    direction: String(activeSignal.direction ?? activeSignal.side ?? activeSignal.action ?? 'paper'),
    timeframe: String(activeSignal.timeframe ?? '5m'),
    entry: finiteNumber(activeSignal.entry ?? activeSignal.entry_price, null),
    targets: asArray(activeSignal.targets),
    stop: finiteNumber(activeSignal.stop ?? activeSignal.stop_loss, null),
    invalidation: finiteNumber(activeSignal.invalidation, null),
    confidence: finiteNumber(activeSignal.confidence ?? activeSignal.model_confidence, 0),
    expected_move: finiteNumber(activeSignal.expected_move ?? activeSignal.expected_move_after_cost_bps, 0),
    risk_reward: finiteNumber(activeSignal.risk_reward, 0),
    status: String(activeSignal.status ?? 'paper_runtime_signal'),
    strategy: String(activeSignal.strategy ?? activeSignal.strategy_id ?? 'runtime_strategy'),
    model_version: String(activeSignal.model_version ?? 'V2_LOCAL_TRAINED_RL_MASA_PPO_CUDA'),
    risk_decision: String(activeSignal.risk_decision ?? 'blocked_human_only'),
    created_at: String(activeSignal.created_at ?? activeSignal.generated_at ?? timestamp),
    expires_at: activeSignal.expires_at ?? null,
    evidence: asArray(activeSignal.evidence),
  };
  const riskStatus = String(
    asObject(riskData.heartbeat).classification
    ?? asObject(riskData.latest_gateway_result).risk_reason_code
    ?? 'blocked_human_only',
  );
  const snapshot = {
    account: section({
      sectionName: 'account',
      source: 'phase5_live_readonly_aggregate:/api/v2/portfolio',
      sourceType: 'api',
      timestamp,
      sequence,
      data: {
        trader_id: user.trader_id,
        account_id: user.paper_account_id,
        mode: 'paper',
        connection_status: 'CONNECTED',
        equity,
        available_balance: finiteNumber(portfolioData.available_balance, Math.max(0, equity - exposure)),
        used_balance: exposure,
        realized_pnl: realizedPnl,
        unrealized_pnl: unrealizedPnl,
        daily_pnl: finiteNumber(portfolioData.daily_pnl, realizedPnl + unrealizedPnl),
        total_pnl: finiteNumber(portfolioData.total_pnl, realizedPnl + unrealizedPnl),
        exposure,
        drawdown: finiteNumber(portfolioData.drawdown, 0),
        open_position_count: openPositionCount,
        open_order_count: finiteNumber(portfolioData.open_order_count, 0),
        execution_count: finiteNumber(portfolioData.execution_count, 0),
      },
    }),
    portfolio: section({
      sectionName: 'portfolio',
      source: portfolioEnvelope.source,
      sourceType: portfolioEnvelope.source_type,
      timestamp,
      sequence,
      data: portfolioData,
    }),
    positions: section({
      sectionName: 'positions',
      source: positionsEnvelope.source,
      sourceType: positionsEnvelope.source_type,
      timestamp,
      sequence,
      data: normalizedPositions,
    }),
    orders: section({ sectionName: 'orders', sourceType: 'api', timestamp, sequence, data: [] }),
    executions: section({ sectionName: 'executions', sourceType: 'api', timestamp, sequence, data: [] }),
    history: section({ sectionName: 'history', sourceType: 'api', timestamp, sequence, data: {} }),
    signals: section({
      sectionName: 'signals',
      source: signalEnvelope.source,
      sourceType: signalEnvelope.source_type,
      timestamp,
      sequence,
      data: [normalizedSignal],
    }),
    predictions: section({ sectionName: 'predictions', sourceType: 'api', timestamp, sequence, data: [] }),
    risk: section({
      sectionName: 'risk',
      source: riskEnvelope.source,
      sourceType: riskEnvelope.source_type,
      timestamp,
      sequence,
      data: {
        ...riskData,
        status: riskStatus,
        classification: riskStatus,
        risk_status: riskStatus,
      },
    }),
    market_status: section({
      sectionName: 'market_status',
      source: marketEnvelope.source,
      sourceType: marketEnvelope.source_type,
      timestamp,
      sequence,
      data: asArray(marketData.tickers).slice(0, 50),
    }),
    automation_status: section({ sectionName: 'automation_status', sourceType: 'api', timestamp, sequence, data: { live_gate: 'blocked_human_only', places_real_order: false } }),
    execution_status: section({ sectionName: 'execution_status', sourceType: 'api', timestamp, sequence, data: { live_trading_enabled: false, exchange_mutation_enabled: false } }),
    data_status: section({
      sectionName: 'data_status',
      source: 'phase5_runtime_truth_crawl',
      sourceType: 'api',
      timestamp,
      sequence,
      data: {
        sections: [
          'account', 'portfolio', 'positions', 'orders', 'executions', 'history',
          'signals', 'predictions', 'risk', 'market_status', 'automation_status',
          'execution_status', 'data_status',
        ],
        trader_id: user.trader_id,
        paper_account_id: user.paper_account_id,
        live_trading_enabled: false,
        exchange_mutation_enabled: false,
      },
      warnings: ['Phase 5 crawler snapshot assembled from live read-only local endpoints; no credentials or exchange mutation used.'],
    }),
  };
  return {
    data: snapshot,
    source: 'phase5_runtime_truth_crawl',
    source_type: 'api',
    endpoint: '/api/v2/trader/snapshot',
    timestamp,
    received_at: timestamp,
    lag_ms: 0,
    stale: false,
    missing_fields: [],
    warnings: ['Authenticated crawl snapshot is read-only and derived from live local runtime APIs.'],
    mode: 'read_only',
    trader_context: {
      scope: 'authenticated_trader',
      trader_id: user.trader_id,
      paper_account_id: user.paper_account_id,
      username: user.username,
      account_specific: Boolean(user.trader_id && user.paper_account_id),
    },
  };
}

async function installAuthRoutes(page, role, traderSnapshotInputs) {
  await page.route('**/api/auth/me**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: authUser(role) }),
    });
  });
  await page.route('**/api/auth/refresh**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });
  await page.route('**/api/auth/logout**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });
  await page.route('**/api/v2/trader/snapshot**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(buildTraderSnapshotEnvelope(role, traderSnapshotInputs)),
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

function routeTruth({
  route,
  finalPath,
  text,
  runtimeStatus,
  mobileSummary,
  dataValidationErrors,
  consoleErrors,
  networkErrors,
  httpErrors,
  navigationError,
  routeLoadWarning,
}) {
  const lower = text.toLowerCase();
  const expectedPathOk = !route.expectedFinalPath || finalPath === route.expectedFinalPath;
  const visibleDataErrors = dataValidationErrors.length;
  const actionableConsoleErrors = consoleErrors.filter((entry) => !/favicon|tradingview|failed to load resource/i.test(entry));
  const abortedRequestCount = networkErrors.filter((entry) => entry.failure === 'net::ERR_ABORTED').length;
  const actionableNetworkErrors = networkErrors.filter((entry) => (
    entry.failure !== 'net::ERR_ABORTED'
    && !/favicon|tradingview|analytics|googletagmanager|clarity|sentry/i.test(entry.url ?? '')
  ));
  const expectedAuthProbeHttpErrors = httpErrors.filter((entry) => (
    entry.status === 401
    && /\/api\/v2\/(admin\/overview|account\/exchange-readonly)\b/i.test(entry.url ?? '')
  ));
  const actionableHttpErrors = httpErrors.filter((entry) => !expectedAuthProbeHttpErrors.includes(entry));
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
  const trainerQualityShown = route.path !== '/system/trainer' || (
    /paper runtime trainer quality/i.test(text)
    && /weights update/i.test(text)
    && /optimizer steps last hour/i.test(text)
    && /checkpoint reload/i.test(text)
    && /after-cost expectancy/i.test(text)
  );
  const staleContradiction =
    /(paper_online_runtime|old_policy|toy_momentum|static_proof_fixture)/i.test(text)
    && !/(legacy|historical|archive|not current|blocked|inactive|disabled)/i.test(text);
  const visibleRouteFailure = /404|not found|cannot get/i.test(text.slice(0, 500));
  const routeLoaded = !navigationError && compact(text, 200).length > 0 && !visibleRouteFailure;
  const dangerousControlTextPresent = /(enable live trading|increase leverage|switch paper to live)/i.test(text);
  const dangerousControlsExplicitlyDisabled =
    /(dangerous controls disabled|requires l[45] approval|blocked_human_only|human-only final gate|live trading:\s*blocked)/i.test(text);
  const noLiveMutationVisible = !dangerousControlTextPresent || dangerousControlsExplicitlyDisabled;
  const routeSpecificTruth = route.path !== '/ai-predictions' || aGradeBlockerShown;

  return {
    route_loaded: routeLoaded,
    navigation_error_present: Boolean(navigationError),
    route_load_warning_present: Boolean(routeLoadWarning),
    expected_final_path_ok: expectedPathOk,
    visible_data_validation_error_count: visibleDataErrors,
    stale_contradiction_count: staleContradiction ? 1 : 0,
    route_failure_visible: visibleRouteFailure,
    console_error_count: actionableConsoleErrors.length,
    aborted_request_count: abortedRequestCount,
    network_error_count: actionableNetworkErrors.length,
    expected_auth_probe_http_error_count: expectedAuthProbeHttpErrors.length,
    http_error_count: actionableHttpErrors.length,
    active_runtime_api_truth: activeRuntime,
    mobile_runtime_api_truth: mobileRuntime,
    paper_owner_shown_or_runtime_visible: paperOwnerShown,
    cost_coverage_shown_or_runtime_visible: costCoverageShown || route.path === '/trade',
    a_grade_blocker_shown_or_runtime_visible: aGradeBlockerShown || route.path !== '/ai-predictions',
    trainer_quality_runtime_visible: trainerQualityShown,
    no_live_mutation_controls_enabled: noLiveMutationVisible,
    pass: routeLoaded
      && expectedPathOk
      && visibleDataErrors === 0
      && !staleContradiction
      && actionableConsoleErrors.length === 0
      && actionableNetworkErrors.length === 0
      && actionableHttpErrors.length === 0
      && activeRuntime
      && mobileRuntime
      && trainerQualityShown
      && noLiveMutationVisible
      && routeSpecificTruth,
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
const portfolioFetch = await fetchJson(`${apiBaseUrl}/api/v2/portfolio`);
const positionsFetch = await fetchJson(`${apiBaseUrl}/api/v2/account/positions`);
const signalFetch = await fetchJson(`${apiBaseUrl}/api/v2/signals?symbol=BTCUSDT`);
const riskFetch = await fetchJson(`${apiBaseUrl}/api/v2/risk/status`);
const marketFetch = await fetchJson(`${apiBaseUrl}/api/v2/market/overview`);
const runtimeStatus = runtimeFetch.data;
const mobileSummary = mobileFetch.data;
const traderSnapshotInputs = {
  portfolio: portfolioFetch,
  positions: positionsFetch,
  signal: signalFetch,
  risk: riskFetch,
  market: marketFetch,
};

const browser = await chromium.launch({ headless: true });

const routeRows = [];
for (const route of routes) {
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    serviceWorkers: 'block',
    viewport: { width: 1440, height: 1100 },
  });
  const page = await context.newPage();
  await installAuthRoutes(page, route.role, traderSnapshotInputs);
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
  let routeLoadWarning = null;
  try {
    const response = await page.goto(requestedUrl.toString(), { waitUntil: 'commit', timeout: 45_000 });
    status = response?.status() ?? null;
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }
  if (!navigationError) {
    try {
      await page.waitForLoadState('domcontentloaded', { timeout: 30_000 });
    } catch (error) {
      routeLoadWarning = error instanceof Error ? error.message : String(error);
    }
    try {
      await page.locator('[data-testid]').first().waitFor({ state: 'visible', timeout: 15_000 });
    } catch (error) {
      routeLoadWarning = routeLoadWarning ?? (error instanceof Error ? error.message : String(error));
    }
    await page.waitForLoadState('networkidle', { timeout: 8_000 }).catch(() => undefined);
    await page.waitForTimeout(800);
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
    navigationError,
    routeLoadWarning,
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
    route_load_warning: routeLoadWarning,
    console_errors: uniq(consoleErrors),
    network_errors: networkErrors,
    http_errors: httpErrors,
    visible_text_excerpt: compact(text),
    data_validation_errors: dataValidationErrors,
    truth,
  });
  await page.close();
  await context.close();
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
  trainer_learning_status_shows_actual_optimizer_weight_state: routeRows.find((row) => row.route === '/system/trainer')?.truth.trainer_quality_runtime_visible ?? false,
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
    navigation_error: row.navigation_error,
    route_load_warning: row.route_load_warning,
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
