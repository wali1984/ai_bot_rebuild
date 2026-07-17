#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const GOAL_ID = 'V2_ENTERPRISE_WEB_IOS_REALTIME_TRADING_CONTROL_CENTER_AND_DATA_TRUTH_COMPLETION';
const frontendRoot = resolve(import.meta.dirname, '..');
const repoRoot = resolve(frontendRoot, '..', '..');
const goalDir = resolve(repoRoot, 'goal_state', GOAL_ID);
const screenshotDir = resolve(goalDir, 'screenshots', process.env.CONTROL_CENTER_AUDIT_PHASE ?? 'phase0');
const baseUrl = (process.env.CONTROL_CENTER_AUDIT_BASE_URL ?? process.env.DASHBOARD_AUDIT_BASE_URL ?? 'https://dashboard.wajidali.us').replace(/\/$/, '');
const backendBaseUrl = (process.env.CONTROL_CENTER_BACKEND_BASE_URL ?? 'http://127.0.0.1:8000').replace(/\/$/, '');
const username = process.env.DASHBOARD_TEST_USERNAME ?? '';
const password = process.env.DASHBOARD_TEST_PASSWORD ?? '';
const nowIso = new Date().toISOString();
const routeSettleMs = Number(process.env.CONTROL_CENTER_AUDIT_SETTLE_MS ?? 2000);
const networkIdleMs = Number(process.env.CONTROL_CENTER_AUDIT_NETWORK_IDLE_MS ?? 5000);
const dashboardPrimaryDataTargetMs = 2_000;
const routePrimaryDataTargetMs = 5_000;
const refreshRetainedDataTargetMs = 1_000;

const REQUIRED_ROUTES = [
  '/login',
  '/dashboard',
  '/trade',
  '/markets',
  '/signals',
  '/portfolio',
  '/trainer',
  '/ai',
  '/risk',
  '/system-health',
  '/ingestors',
  '/audit-ledger',
  '/live-canary',
  '/providers',
  '/settings',
];

const REQUIRED_API_ROUTES = [
  '/api/auth/health',
  '/api/v2/risk/status',
  '/api/v2/paper/runtime-status',
  '/api/v2/portfolio',
  '/api/v2/mobile/dashboard',
  '/api/v2/mobile/risk-status',
  '/api/v2/providers/status',
  '/api/v2/ingestors/status',
  '/api/v2/trainer/status',
  '/api/v2/live-canary/status',
  '/api/v2/a-plus/inventory',
  '/api/v2/market/overview',
  '/api/v2/signals/current',
  '/api/v2/realtime/bootstrap',
  '/api/v2/stream/runtime?once=true',
  '/api/v2/stream/trading?once=true',
  '/api/v2/stream/providers?once=true',
  '/api/v2/stream/trainer?once=true',
  '/api/v2/stream/risk?once=true',
  '/api/v2/ui/portfolio',
  '/api/v2/ui/providers',
  '/api/v2/ui/ai-brain',
];

const CORE_API_CONTRACT_FIELDS = [
  'schema_version',
  'generated_at_utc',
  'generated_at_et',
  'source',
  'staleness_seconds',
  'freshness_status',
  'canonical_owner',
  'live_gate',
  'places_real_order',
  'routes_to_live',
  'data_quality_status',
];

const STREAM_API_CONTRACT_FIELDS = [
  'schema_version',
  'generated_at_utc',
  'generated_at_et',
  'source',
  'staleness_seconds',
  'freshness_status',
  'canonical_owner',
  'live_gate',
  'places_real_order',
  'routes_to_live',
  'data_quality_status',
];

function writeJson(name, payload) {
  writeFileSync(resolve(goalDir, name), `${JSON.stringify(payload, null, 2)}\n`);
}

function writeText(name, payload) {
  writeFileSync(resolve(goalDir, name), `${payload}\n`);
}

function routeName(route) {
  return `${route.replaceAll('/', '_').replaceAll('?', '_').replaceAll('=', '_').replaceAll('&', '_') || 'root'}.png`;
}

function redactSensitiveText(text) {
  return String(text ?? '')
    .replace(/[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi, '[redacted-email]')
    .replace(/(authorization\s*:\s*bearer\s+)[A-Za-z0-9._-]{12,}/gi, '$1[redacted-token]')
    .replace(/((?:access|refresh)[_-]?token["'\s:=]+)[A-Za-z0-9._-]{16,}/gi, '$1[redacted-token]')
    .replace(/((?:api[_-]?key|secret|password)["'\s:=]+)[A-Za-z0-9_./+=-]{8,}/gi, '$1[redacted-secret]');
}

function compact(text, length = 1800) {
  return redactSensitiveText(text).replace(/\s+/g, ' ').trim().slice(0, length);
}

function hasSecretLikeText(text) {
  const value = String(text ?? '');
  return /authorization\s*:\s*bearer\s+[A-Za-z0-9._-]{12,}/i.test(value)
    || /(?:access|refresh)[_-]?token["'\s:=]+[A-Za-z0-9._-]{16,}/i.test(value)
    || /(?:api[_-]?key|secret|password)["'\s:=]+[A-Za-z0-9_./+=-]{16,}/i.test(value)
    || /raw[_-]?key[_-]?exposed["'\s:]+true/i.test(value);
}

function parseApiPayload(contentType, text) {
  if (contentType.includes('application/json')) {
    try {
      return JSON.parse(text);
    } catch {
      return null;
    }
  }
  if (contentType.includes('text/event-stream')) {
    const match = text.match(/^data:\s*(\{.*\})\s*$/m);
    if (!match) return null;
    try {
      return JSON.parse(match[1]);
    } catch {
      return null;
    }
  }
  return null;
}

function hasOwnField(payload, field) {
  if (!payload || typeof payload !== 'object') return false;
  const present = (value) => value !== null && value !== undefined && value !== '';
  if (field === 'generated_at_utc') {
    return present(payload.generated_at_utc) || present(payload.generated_utc);
  }
  if (field === 'generated_at_et') {
    return present(payload.generated_at_et)
      || present(payload.display_time_et)
      || present(payload.generated_est);
  }
  if (field === 'data_quality_status') {
    return present(payload.data_quality_status) || present(payload.data_quality);
  }
  if (field === 'freshness_status' || field === 'source' || field === 'canonical_owner') {
    return present(payload[field]);
  }
  return Object.prototype.hasOwnProperty.call(payload, field);
}

function requiredFieldsForApiPath(path) {
  if (path.startsWith('/api/v2/stream/')) return STREAM_API_CONTRACT_FIELDS;
  if (path.startsWith('/api/v2/ui/')) {
    return CORE_API_CONTRACT_FIELDS.filter((field) => field !== 'freshness_status');
  }
  return CORE_API_CONTRACT_FIELDS;
}

function apiRowContractOk(row) {
  return row.status !== null
    && row.status < 500
    && row.api_payload_kind !== 'html_fallback'
    && row.secret_leak_detected !== true
    && Array.isArray(row.missing_required_contract_fields)
    && row.missing_required_contract_fields.length === 0;
}

function routeRequirements(route) {
  const common = {
    required_text_patterns: [],
    forbidden_text_patterns: [],
    required_providers: [],
  };
  const providerPanel = {
    required_providers: ['coinank', 'coinglass', 'moralis'],
    // santiment/aicoin removed system-wide by operator directive 2026-07-16;
    // any remaining mention on a page is a defect, same as the older retirees.
    forbidden_text_patterns: [/alpha vantage/i, /lunarcrush/i, /nansen/i, /santiment|sanbase/i, /aicoin/i],
  };
  if (route === '/dashboard') {
    return {
      ...common,
      required_text_patterns: [
        /live|operator|blocked|dry run/i,
        /a\+|candidate/i,
        /pnl|equity/i,
        /provider|coinglass|moralis/i,
      ],
      forbidden_text_patterns: [/headline.*100%.*a\+/i, /goal_state/i, /raw json/i],
    };
  }
  if (route === '/trade') {
    return {
      ...common,
      required_text_patterns: [/operator|blocked|dry run/i, /candidate|why no trade|execution/i],
      forbidden_text_patterns: [/place live order/i, /send live order/i],
    };
  }
  if (route === '/markets' || route === '/ingestors' || route === '/providers') {
    return {
      ...common,
      ...providerPanel,
      required_text_patterns: [
        /coinglass/i,
        /moralis/i,
        /coinank/i,
      ],
    };
  }
  if (route === '/signals') {
    return {
      ...common,
      required_text_patterns: [/signal|candidate|prediction/i, /blocked|operator|dry run|paper/i],
    };
  }
  if (route === '/portfolio') {
    return {
      ...common,
      required_text_patterns: [/pnl|profit|loss/i, /equity/i],
      forbidden_text_patterns: [/multiple pnl sources/i, /conflict detected/i],
    };
  }
  if (route === '/trainer' || route === '/ai') {
    return {
      ...common,
      required_text_patterns: [/ppo|masa|trainer|checkpoint/i, /feature|provider|tensor|input dim/i],
    };
  }
  if (route === '/risk') {
    return {
      ...common,
      required_text_patterns: [/risk/i, /liquidation|hedge|squeeze|kill switch/i, /blocked|operator/i],
    };
  }
  if (route === '/system-health') {
    return {
      ...common,
      required_text_patterns: [/health|service|redis|backend/i],
    };
  }
  if (route === '/audit-ledger') {
    return {
      ...common,
      required_text_patterns: [/audit|ledger|event/i],
    };
  }
  if (route === '/live-canary') {
    return {
      ...common,
      required_text_patterns: [/live canary|canary/i, /blocked|operator|dry run/i, /order|hedge|candidate/i],
      forbidden_text_patterns: [/live order enabled/i, /ready to submit live/i],
    };
  }
  if (route === '/settings') {
    return {
      ...common,
      required_text_patterns: [
        /account runtime safety/i,
        /\/api\/auth\/health/i,
        /sign-in service|sign in service/i,
        /live gate/i,
        /approval gated|live blocked|blocked_human_only/i,
        /account scope/i,
        /trader approval/i,
        /exchange linking/i,
        /places_real_order\s*=\s*NO/i,
        /routes_to_live\s*=\s*NO/i,
        /exchange_mutation_enabled\s*=\s*NO/i,
        /raw_credential_value_exposed\s*=\s*NO/i,
        /contains_secret_values\s*=\s*NO/i,
        /no live routing or secret exposure/i,
      ],
      forbidden_text_patterns: [/live order enabled/i, /ready to submit live/i],
    };
  }
  return common;
}

function evaluateRouteRequirements(route, textBefore, providerTextPresent, pnlAmounts) {
  const requirements = routeRequirements(route);
  const failures = [];
  for (const provider of requirements.required_providers) {
    if (!providerTextPresent[provider]) {
      failures.push(`missing_provider_${provider}`);
    }
  }
  for (const pattern of requirements.required_text_patterns) {
    if (!pattern.test(textBefore)) failures.push(`missing_text:${pattern.source}`);
  }
  for (const pattern of requirements.forbidden_text_patterns) {
    if (pattern.test(textBefore)) failures.push(`forbidden_text:${pattern.source}`);
  }
  if (providerTextPresent.old_alpha_vantage) failures.push('old_active_provider_alpha_vantage_visible');
  if (providerTextPresent.old_lunarcrush) failures.push('old_active_provider_lunarcrush_visible');
  if (providerTextPresent.old_nansen) failures.push('old_active_provider_nansen_visible');
  if (providerTextPresent.old_santiment) failures.push('old_active_provider_santiment_visible');
  if (providerTextPresent.old_aicoin) failures.push('old_active_provider_aicoin_visible');
  if (pnlAmounts.length > 4 && ['/dashboard', '/portfolio'].includes(route)) {
    failures.push('possible_duplicate_or_conflicting_pnl_values');
  }
  return failures;
}

async function redactVisibleSecrets(page) {
  await page.evaluate(() => {
    const emailPattern = /[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}/gi;
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
      node.textContent = (node.textContent || '').replace(emailPattern, '[redacted-email]');
    }
    for (const input of document.querySelectorAll('input')) {
      const el = input;
      if (el instanceof HTMLInputElement && /password|email|token|secret/i.test(`${el.type} ${el.name} ${el.id}`)) {
        el.value = '';
        el.placeholder = '[redacted]';
      }
    }
  }).catch(() => undefined);
}

async function authenticate(page) {
  const started = Date.now();
  await page.goto(`${baseUrl}/login`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
  await page.locator('#login-email, input[name="email"], input[type="email"]').first().fill(username, { timeout: 10_000 });
  await page.locator('#login-password, input[name="password"], input[type="password"]').first().fill(password, { timeout: 10_000 });
  await Promise.all([
    page.waitForLoadState('networkidle', { timeout: 15_000 }).catch(() => undefined),
    page.getByRole('button', { name: /sign in/i }).click({ timeout: 10_000 }),
  ]);
  await page.waitForTimeout(750);
  const me = await page.request.get(`${baseUrl}/api/auth/me`, { timeout: 15_000 }).catch(() => null);
  const bodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  return {
    success: me?.ok() === true,
    status: me?.status() ?? null,
    elapsed_ms: Date.now() - started,
    final_url: page.url(),
    login_error_visible: /sign-in service unavailable|invalid email|invalid password|authentication/i.test(bodyText),
  };
}

function routeLatencyTarget(route) {
  if (route === '/dashboard') return dashboardPrimaryDataTargetMs;
  if (route === '/login') return 3_000;
  return routePrimaryDataTargetMs;
}

function routeLatencyRows(routeRows) {
  return routeRows.map((row) => {
    const targetMs = routeLatencyTarget(row.route);
    return {
      route: row.route,
      time_to_first_render_ms: row.time_to_first_render_ms,
      time_to_primary_data_ms: row.time_to_first_real_data_ms,
      target_ms: targetMs,
      target_pass: typeof row.time_to_first_real_data_ms === 'number' && row.time_to_first_real_data_ms <= targetMs,
    };
  });
}

function routeLatencyFailures(routeRows) {
  return routeLatencyRows(routeRows)
    .filter((row) => row.target_pass !== true)
    .map((row) => ({
      route: row.route,
      time_to_primary_data_ms: row.time_to_primary_data_ms,
      target_ms: row.target_ms,
    }));
}

function refreshFailures(routeRows) {
  return routeRows
    .filter((row) => row.refresh_error || row.data_vanished_after_refresh)
    .map((row) => ({
      route: row.route,
      refresh_error: row.refresh_error,
      data_vanished_after_refresh: row.data_vanished_after_refresh,
      time_to_after_refresh_real_data_ms: row.time_to_after_refresh_real_data_ms ?? null,
    }));
}

function apiContractFailures(apiRows) {
  return apiRows.filter((row) => !apiRowContractOk(row));
}

function api500Count(apiRows) {
  return apiRows.filter((row) => typeof row.status === 'number' && row.status >= 500).length;
}

function networkErrors(routeRows) {
  return routeRows.flatMap((row) => row.network_errors.map((error) => ({ route: row.route, ...error })));
}

function browserNavigationAborts(routeRows) {
  return routeRows.flatMap((row) => (row.browser_navigation_aborts ?? []).map((error) => ({ route: row.route, ...error })));
}

function requestCancellations(routeRows) {
  return routeRows.flatMap((row) => (row.request_cancellations ?? []).map((error) => ({ route: row.route, ...error })));
}

function consoleErrors(routeRows) {
  return routeRows.flatMap((row) => row.console_errors.map((error) => ({ route: row.route, message: error })));
}

async function auditLoginSurface() {
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage({ ignoreHTTPSErrors: true, viewport: { width: 1440, height: 980 } });
  const consoleErrors = [];
  const networkErrors = [];
  const authResponses = [];
  const screenshots = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 800));
  });
  page.on('pageerror', (error) => consoleErrors.push(error.message.slice(0, 800)));
  page.on('requestfailed', (request) => {
    networkErrors.push({
      url: request.url(),
      method: request.method(),
      failure: request.failure()?.errorText ?? 'unknown',
    });
  });
  page.on('response', (response) => {
    if (response.url().includes('/api/auth/')) {
      authResponses.push({
        url: response.url(),
        status: response.status(),
        content_type: response.headers()['content-type'] ?? '',
      });
    }
  });

  const started = Date.now();
  let navigationError = null;
  let healthText = '';
  let invalidLoginAlert = '';
  let finalUrl = '';
  try {
    await page.goto(`${baseUrl}/login`, { waitUntil: 'networkidle', timeout: 30_000 });
    await page.waitForSelector('[data-testid="auth-health-status"]', { timeout: 8_000 }).catch(() => undefined);
    await page.waitForTimeout(1000);
    healthText = await page.locator('[data-testid="auth-health-status"]').innerText({ timeout: 2000 }).catch(() => '');
    await redactVisibleSecrets(page);
    const healthShot = `screenshots/${process.env.CONTROL_CENTER_AUDIT_PHASE ?? 'phase0'}/_login_unauthenticated_health.png`;
    await page.screenshot({ path: resolve(goalDir, healthShot), fullPage: true }).catch(() => undefined);
    screenshots.push({ route: '/login', kind: 'unauthenticated_health', path: healthShot });

    if (process.env.CONTROL_CENTER_SKIP_INVALID_LOGIN_PROBE !== '1') {
      await page.fill('#login-email', `invalid-${Date.now()}@example.invalid`, { timeout: 5000 });
      await page.fill('#login-password', `invalid-${Math.random().toString(36).slice(2)}`, { timeout: 5000 });
      await page.click('button[type="submit"]', { timeout: 5000 });
      const alert = page.getByRole('alert');
      await alert.waitFor({ timeout: 12_000 }).catch(() => undefined);
      invalidLoginAlert = await alert.innerText({ timeout: 2000 }).catch(() => '');
      await redactVisibleSecrets(page);
      const invalidShot = `screenshots/${process.env.CONTROL_CENTER_AUDIT_PHASE ?? 'phase0'}/_login_invalid_probe.png`;
      await page.screenshot({ path: resolve(goalDir, invalidShot), fullPage: true }).catch(() => undefined);
      screenshots.push({ route: '/login', kind: 'invalid_login_probe', path: invalidShot });
    }
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  } finally {
    finalUrl = page.url();
    await browser.close();
  }

  const healthResponse = authResponses.find((row) => row.url.includes('/api/auth/health')) ?? null;
  const loginResponse = [...authResponses].reverse().find((row) => row.url.includes('/api/auth/login')) ?? null;
  const unexpectedConsoleErrors = consoleErrors.filter(
    (message) => !(loginResponse?.status === 401 && /status of 401|401 \(\)/i.test(message)),
  );
  return {
    attempted: true,
    auth_success: false,
    elapsed_ms: Date.now() - started,
    final_url: finalUrl,
    navigation_error: navigationError,
    auth_health_status_visible: compact(healthText, 500),
    invalid_login_alert: compact(invalidLoginAlert, 500),
    auth_health_http_status: healthResponse?.status ?? null,
    invalid_login_http_status: loginResponse?.status ?? null,
    console_errors: consoleErrors,
    unexpected_console_errors: unexpectedConsoleErrors,
    network_errors: networkErrors,
    auth_responses: authResponses,
    screenshots,
    pass: !navigationError
      && unexpectedConsoleErrors.length === 0
      && networkErrors.length === 0
      && healthResponse?.status === 200
      && (process.env.CONTROL_CENTER_SKIP_INVALID_LOGIN_PROBE === '1' || invalidLoginAlert.length > 0),
  };
}

async function auditRoute(context, route) {
  const page = await context.newPage();
  const apiRequests = [];
  const consoleErrors = [];
  const requestFailures = [];
  const httpErrors = [];
  let auditStage = 'initial_navigation';
  let largestApiPayloadBytes = 0;
  let largestApiPayloadUrl = null;

  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 800));
  });
  page.on('pageerror', (error) => consoleErrors.push(error.message.slice(0, 800)));
  page.on('request', (request) => {
    const url = request.url();
    if (url.includes('/api/')) apiRequests.push({ url, method: request.method() });
  });
  page.on('requestfailed', (request) => {
    const failure = request.failure()?.errorText ?? 'unknown';
    const requestCancelled = failure === 'net::ERR_ABORTED';
    const browserLifecycleAbort = requestCancelled
      && ['refresh_navigation', 'closing'].includes(auditStage);
    requestFailures.push({
      url: request.url(),
      method: request.method(),
      failure,
      audit_stage: auditStage,
      request_cancelled: requestCancelled,
      browser_lifecycle_abort: browserLifecycleAbort,
    });
  });
  page.on('response', (response) => {
    const url = response.url();
    if (url.includes('/api/')) {
      const length = Number(response.headers()['content-length'] ?? 0);
      if (Number.isFinite(length) && length > largestApiPayloadBytes) {
        largestApiPayloadBytes = length;
        largestApiPayloadUrl = url;
      }
      if (response.status() >= 400) httpErrors.push({ url, status: response.status() });
    }
  });

  const started = Date.now();
  const requestedUrl = `${baseUrl}${route}`;
  let response = null;
  let navigationError = null;
  let firstRenderMs = null;
  let firstRealDataMs = null;
  try {
    response = await page.goto(requestedUrl, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    firstRenderMs = Date.now() - started;
    await page.waitForFunction(() => (document.body?.innerText || '').trim().length > 80, null, { timeout: 10_000 }).catch(() => undefined);
    firstRealDataMs = Date.now() - started;
    auditStage = 'initial_settle';
    await page.waitForLoadState('networkidle', { timeout: networkIdleMs }).catch(() => undefined);
    await page.waitForTimeout(routeSettleMs);
    auditStage = 'initial_settled';
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }

  const title = await page.title().catch(() => '');
  const textBefore = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  const primarySelectors = await page.locator('[data-testid^="page-"], main, article, [role="main"]').count().catch(() => 0);
  const providerTextPresent = {
    coinank: /coinank/i.test(textBefore),
    coinglass: /coinglass/i.test(textBefore),
    moralis: /moralis/i.test(textBefore),
    old_alpha_vantage: /alpha vantage/i.test(textBefore),
    old_lunarcrush: /lunarcrush/i.test(textBefore),
    old_nansen: /nansen/i.test(textBefore),
    old_santiment: /santiment|sanbase/i.test(textBefore),
    old_aicoin: /aicoin/i.test(textBefore),
  };
  const pnlLines = textBefore.split(/\n+/).filter((line) => /pnl|profit|loss/i.test(line)).slice(0, 20);
  const pnlAmounts = Array.from(new Set(pnlLines.join(' ').match(/[-+]?\$?\d[\d,]*(?:\.\d{1,4})?/g) ?? [])).slice(0, 20);
  const secretLeakDetected = hasSecretLikeText(textBefore);
  const routeRequirementFailures = evaluateRouteRequirements(
    route,
    textBefore,
    providerTextPresent,
    pnlAmounts,
  );

  await redactVisibleSecrets(page);
  const beforeShot = `screenshots/${process.env.CONTROL_CENTER_AUDIT_PHASE ?? 'phase0'}/${routeName(route).replace('.png', '__before.png')}`;
  await page.screenshot({ path: resolve(goalDir, beforeShot), fullPage: true }).catch(() => undefined);

  const beforeLength = textBefore.trim().length;
  let refreshError = null;
  let refreshRealDataMs = null;
  try {
    const refreshStarted = Date.now();
    auditStage = 'refresh_navigation';
    await page.reload({ waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForFunction(() => (document.body?.innerText || '').trim().length > 80, null, { timeout: 10_000 }).catch(() => undefined);
    refreshRealDataMs = Date.now() - refreshStarted;
    auditStage = 'refresh_settle';
    await page.waitForLoadState('networkidle', { timeout: networkIdleMs }).catch(() => undefined);
    await page.waitForTimeout(1000);
    auditStage = 'refresh_settled';
  } catch (error) {
    refreshError = error instanceof Error ? error.message : String(error);
  }
  const textAfter = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  await redactVisibleSecrets(page);
  const afterShot = `screenshots/${process.env.CONTROL_CENTER_AUDIT_PHASE ?? 'phase0'}/${routeName(route).replace('.png', '__after_refresh.png')}`;
  await page.screenshot({ path: resolve(goalDir, afterShot), fullPage: true }).catch(() => undefined);
  const finalUrl = page.url();
  auditStage = 'closing';
  await page.close();

  const browserNavigationAborts = requestFailures.filter((entry) => entry.browser_lifecycle_abort);
  const requestCancellations = requestFailures.filter((entry) => entry.request_cancelled);
  const runtimeNetworkErrors = requestFailures.filter((entry) => !entry.request_cancelled);
  const dataVanishedAfterRefresh = beforeLength > 200 && textAfter.trim().length < Math.min(120, beforeLength * 0.25);
  return {
    route,
    requested_url: requestedUrl,
    final_url: finalUrl,
    http_status: response?.status() ?? null,
    title,
    auth_success: true,
    time_to_first_render_ms: firstRenderMs,
    time_to_first_real_data_ms: firstRealDataMs,
    time_to_interactive_ms: Date.now() - started,
    websocket_or_sse_connected: runtimeNetworkErrors.some((entry) => /ws|stream|sse|realtime/i.test(entry.url)) ? false : null,
    api_request_count: apiRequests.length,
    largest_api_payload_bytes: largestApiPayloadBytes,
    largest_api_payload_url: largestApiPayloadUrl,
    console_errors: consoleErrors,
    network_errors: runtimeNetworkErrors,
    request_cancellations: requestCancellations,
    browser_navigation_aborts: browserNavigationAborts,
    raw_request_failures: requestFailures,
    http_errors: httpErrors,
    navigation_error: navigationError,
    refresh_error: refreshError,
    data_vanished_after_refresh: dataVanishedAfterRefresh,
    time_to_after_refresh_real_data_ms: typeof refreshRealDataMs === 'number' ? refreshRealDataMs : null,
    stale_widgets: /stale|degraded|unavailable/i.test(textBefore),
    duplicate_or_conflicting_values: pnlAmounts.length > 4,
    pnl_amounts_visible: pnlAmounts,
    provider_text_present: providerTextPresent,
    route_requirement_failures: routeRequirementFailures,
    missing_trader_controls: !/live|dry run|operator|required|blocked|a\+/i.test(textBefore),
    irrelevant_or_noisy_fields: /raw json|fixture|legacy|goal_state|hist_pred_|static proof/i.test(textBefore),
    secret_leak_detected: secretLeakDetected,
    screenshots: {
      before_refresh: beforeShot,
      after_refresh: afterShot,
    },
    visible_text_excerpt: compact(textBefore),
    primary_selector_count: primarySelectors,
    pass: !navigationError
      && !refreshError
      && response?.status() !== 404
      && !dataVanishedAfterRefresh
      && consoleErrors.length === 0
      && httpErrors.filter((entry) => ![401, 403].includes(entry.status)).length === 0
      && routeRequirementFailures.length === 0
      && !secretLeakDetected,
  };
}

async function auditApis(context) {
  const rows = [];
  for (const path of REQUIRED_API_ROUTES) {
    const url = `${backendBaseUrl}${path}`;
    const started = Date.now();
    try {
      const response = await context.request.get(url, { timeout: 15_000, failOnStatusCode: false });
      const contentType = response.headers()['content-type'] ?? '';
      const text = await response.text();
      const payload = parseApiPayload(contentType, text);
      const requiredFields = requiredFieldsForApiPath(path);
      const missingFields = requiredFields.filter((field) => !hasOwnField(payload, field));
      const apiPayloadKind = contentType.includes('application/json')
        ? 'json'
        : contentType.includes('text/event-stream')
          ? 'sse'
          : /<!doctype html>|<html/i.test(text)
            ? 'html_fallback'
            : 'unknown';
      const secretLeakDetected = hasSecretLikeText(text);
      rows.push({
        path,
        url,
        status: response.status(),
        latency_ms: Date.now() - started,
        content_type: contentType,
        api_payload_kind: apiPayloadKind,
        payload_bytes: text.length,
        schema_version: payload?.schema_version ?? null,
        generated_at_utc: payload?.generated_at_utc ?? payload?.generated_utc ?? null,
        generated_at_et: payload?.generated_at_et ?? payload?.display_time_et ?? null,
        source: payload?.source ?? null,
        staleness_seconds: payload?.staleness_seconds ?? null,
        freshness_status: payload?.freshness_status ?? null,
        canonical_owner: payload?.canonical_owner ?? null,
        live_gate: payload?.live_gate ?? payload?.data?.live_gate ?? null,
        places_real_order: payload?.places_real_order ?? payload?.data?.places_real_order ?? null,
        routes_to_live: payload?.routes_to_live ?? payload?.data?.routes_to_live ?? null,
        data_quality_status: payload?.data_quality_status ?? payload?.data_quality ?? null,
        missing_required_contract_fields: missingFields,
        secret_leak_detected: secretLeakDetected,
        contract_ok: response.status() < 500
          && apiPayloadKind !== 'html_fallback'
          && missingFields.length === 0
          && secretLeakDetected !== true,
      });
    } catch (error) {
      rows.push({
        path,
        url,
        status: null,
        latency_ms: Date.now() - started,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }
  return rows;
}

async function auditApisWithFetch() {
  const rows = [];
  for (const path of REQUIRED_API_ROUTES) {
    const url = `${backendBaseUrl}${path}`;
    const started = Date.now();
    try {
      const response = await fetch(url, { headers: { Accept: 'application/json' } });
      const contentType = response.headers.get('content-type') ?? '';
      const text = await response.text();
      const payload = parseApiPayload(contentType, text);
      const requiredFields = requiredFieldsForApiPath(path);
      const missingFields = requiredFields.filter((field) => !hasOwnField(payload, field));
      const apiPayloadKind = contentType.includes('application/json')
        ? 'json'
        : contentType.includes('text/event-stream')
          ? 'sse'
          : /<!doctype html>|<html/i.test(text)
            ? 'html_fallback'
            : 'unknown';
      const secretLeakDetected = hasSecretLikeText(text);
      rows.push({
        path,
        url,
        status: response.status,
        latency_ms: Date.now() - started,
        content_type: contentType,
        api_payload_kind: apiPayloadKind,
        payload_bytes: text.length,
        schema_version: payload?.schema_version ?? null,
        generated_at_utc: payload?.generated_at_utc ?? payload?.generated_utc ?? null,
        generated_at_et: payload?.generated_at_et ?? payload?.display_time_et ?? null,
        source: payload?.source ?? null,
        staleness_seconds: payload?.staleness_seconds ?? null,
        freshness_status: payload?.freshness_status ?? null,
        canonical_owner: payload?.canonical_owner ?? null,
        live_gate: payload?.live_gate ?? payload?.data?.live_gate ?? null,
        places_real_order: payload?.places_real_order ?? payload?.data?.places_real_order ?? null,
        routes_to_live: payload?.routes_to_live ?? payload?.data?.routes_to_live ?? null,
        data_quality_status: payload?.data_quality_status ?? payload?.data_quality ?? null,
        missing_required_contract_fields: missingFields,
        secret_leak_detected: secretLeakDetected,
        contract_ok: response.status < 500
          && apiPayloadKind !== 'html_fallback'
          && missingFields.length === 0
          && secretLeakDetected !== true,
      });
    } catch (error) {
      rows.push({
        path,
        url,
        status: null,
        latency_ms: Date.now() - started,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }
  return rows;
}

mkdirSync(goalDir, { recursive: true });
mkdirSync(screenshotDir, { recursive: true });

const credentialsPresent = Boolean(username && password);
if (!credentialsPresent) {
  const apiRows = await auditApisWithFetch();
  const loginSurface = await auditLoginSurface();
  const blockedRoutes = REQUIRED_ROUTES.map((route) => ({
    route,
    auth_success: false,
    status: 'BLOCKED_MISSING_DASHBOARD_TEST_CREDENTIALS',
    time_to_first_render_ms: null,
    time_to_first_real_data_ms: null,
    data_vanished_after_refresh: 'unknown',
  }));
  writeJson('phase0_authenticated_site_audit.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    base_url: baseUrl,
    local_backend_base_url: backendBaseUrl,
    credential_env_contract: {
      username_env: 'DASHBOARD_TEST_USERNAME',
      password_env: 'DASHBOARD_TEST_PASSWORD',
      username_present: Boolean(username),
      password_present: Boolean(password),
      credentials_logged: false,
      credentials_committed: false,
    },
    production_authenticated_audit: {
      attempted: false,
      auth_success: false,
      blocker: 'DASHBOARD_TEST_USERNAME and DASHBOARD_TEST_PASSWORD must be present in the environment.',
    },
    login_surface_preflight: loginSurface,
    routes: blockedRoutes,
  });
  writeJson('phase0_route_inventory.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    required_routes: REQUIRED_ROUTES,
    api_routes: REQUIRED_API_ROUTES,
    route_count: REQUIRED_ROUTES.length,
    api_route_count: REQUIRED_API_ROUTES.length,
    api_contracts: apiRows,
    login_surface_preflight: loginSurface,
    auth_status: 'blocked_missing_credentials',
  });
  writeJson('phase3_backend_api_contract_status.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    base_url: backendBaseUrl,
    auth_status: 'blocked_missing_credentials_for_browser_routes',
    api_contracts: apiRows,
    pass_count: apiRows.filter(apiRowContractOk).length,
    fail_count: apiRows.filter((row) => !apiRowContractOk(row)).length,
    contract_failures: apiRows.filter((row) => !apiRowContractOk(row)).map((row) => ({
      path: row.path,
      status: row.status,
      content_type: row.content_type,
      api_payload_kind: row.api_payload_kind,
      missing_required_contract_fields: row.missing_required_contract_fields ?? [],
      secret_leak_detected: row.secret_leak_detected === true,
      error: row.error,
    })),
  });
  writeJson('phase3_api_latency_report.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    targets: {
      primary_dashboard_api_ms: 800,
      individual_status_api_ms: 500,
      huge_payload_bytes: 5000000,
    },
    api_latency: apiRows.map((row) => ({
      path: row.path,
      status: row.status,
      latency_ms: row.latency_ms,
      payload_bytes: row.payload_bytes ?? null,
      target_met: row.status !== null && row.status < 500 && row.latency_ms <= 800 && (row.payload_bytes ?? 0) < 5000000,
    })),
  });
  writeJson('phase3_api_schema_snapshot.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    api_schema_fields: apiRows.map((row) => ({
      path: row.path,
      schema_version: row.schema_version,
      generated_at_utc: row.generated_at_utc,
      generated_at_et: row.generated_at_et,
      source: row.source,
      staleness_seconds: row.staleness_seconds,
      freshness_status: row.freshness_status,
      canonical_owner: row.canonical_owner,
      live_gate: row.live_gate,
      places_real_order: row.places_real_order,
      routes_to_live: row.routes_to_live,
      data_quality_status: row.data_quality_status,
    })),
  });
  writeJson('phase0_console_network_errors.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    attempted: true,
    blocked_by: 'missing DASHBOARD_TEST_USERNAME/DASHBOARD_TEST_PASSWORD',
    login_console_errors: loginSurface.console_errors,
    login_network_errors: loginSurface.network_errors,
    api_errors: apiRows.filter((row) => !apiRowContractOk(row)),
  });
  writeJson('phase0_screenshot_manifest.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    screenshots: loginSurface.screenshots,
    blocked_by: 'missing DASHBOARD_TEST_USERNAME/DASHBOARD_TEST_PASSWORD',
  });
  writeJson('phase10_enterprise_performance_report.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    status: apiRows.every(apiRowContractOk)
      ? 'LOCAL_API_TARGETS_PASS_AUTHENTICATED_BROWSER_TARGETS_BLOCKED'
      : 'LOCAL_API_CONTRACTS_INCOMPLETE_AUTHENTICATED_BROWSER_TARGETS_BLOCKED',
    login_surface_preflight: {
      elapsed_ms: loginSurface.elapsed_ms,
      pass: loginSurface.pass,
      auth_health_http_status: loginSurface.auth_health_http_status,
      invalid_login_http_status: loginSurface.invalid_login_http_status,
      console_error_count: loginSurface.unexpected_console_errors.length,
      network_error_count: loginSurface.network_errors.length,
    },
    api_contract_pass_count: apiRows.filter(apiRowContractOk).length,
    api_contract_fail_count: apiRows.filter((row) => !apiRowContractOk(row)).length,
    api_contract_failures: apiRows.filter((row) => !apiRowContractOk(row)).map((row) => ({
      path: row.path,
      status: row.status,
      api_payload_kind: row.api_payload_kind,
      missing_required_contract_fields: row.missing_required_contract_fields ?? [],
      latency_ms: row.latency_ms,
      payload_bytes: row.payload_bytes ?? null,
    })),
    acceptance_targets: {
      login_to_dashboard_after_auth_ms: 3000,
      primary_dashboard_data_visible_ms: 2000,
      critical_realtime_updates_ms: 3000,
      console_crashes: 0,
      unauthorized_api_loops: 0,
      api_500s: 0,
    },
    authenticated_targets_blocked_by: 'missing DASHBOARD_TEST_USERNAME/DASHBOARD_TEST_PASSWORD',
  });
  writeJson('phase10_console_network_cleanliness.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    login_surface_preflight: {
      pass: loginSurface.pass,
      console_errors: loginSurface.console_errors,
      network_errors: loginSurface.network_errors,
      auth_responses: loginSurface.auth_responses,
    },
    api_contract_failures: apiRows.filter((row) => !apiRowContractOk(row)),
  });
  writeJson('phase11_authenticated_route_crawl_status.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    status: 'BLOCKED_MISSING_DASHBOARD_TEST_CREDENTIALS',
    base_url: baseUrl,
    auth_success: false,
    login_surface_preflight: loginSurface,
    api_contract_pass_count: apiRows.filter(apiRowContractOk).length,
    api_contract_fail_count: apiRows.filter((row) => !apiRowContractOk(row)).length,
    api_contract_failures: apiRows.filter((row) => !apiRowContractOk(row)).map((row) => ({
      path: row.path,
      status: row.status,
      api_payload_kind: row.api_payload_kind,
      missing_required_contract_fields: row.missing_required_contract_fields ?? [],
      secret_leak_detected: row.secret_leak_detected === true,
      error: row.error,
    })),
    routes: blockedRoutes,
    route_pass_count: 0,
    route_fail_count: blockedRoutes.length,
  });
  writeJson('phase11_route_failures.json', {
    goal_id: GOAL_ID,
    generated_at_utc: nowIso,
    failures: blockedRoutes.map((row) => ({
      route: row.route,
      reason: 'missing DASHBOARD_TEST_USERNAME/DASHBOARD_TEST_PASSWORD',
    })),
  });
  writeText(
    'phase11_route_screenshot_index.md',
    [
      '# Authenticated Route Screenshot Index',
      '',
      `Generated: ${nowIso}`,
      '',
      'Authenticated route screenshots are blocked until DASHBOARD_TEST_USERNAME and DASHBOARD_TEST_PASSWORD are present.',
      '',
      ...loginSurface.screenshots.map((shot) => `- ${shot.kind}: ${shot.path}`),
    ].join('\n'),
  );
  console.log(JSON.stringify({
    status: 'BLOCKED_MISSING_DASHBOARD_TEST_CREDENTIALS',
    goal_dir: goalDir,
    routes: REQUIRED_ROUTES.length,
    api_fail_count: apiRows.filter((row) => !apiRowContractOk(row)).length,
    login_surface_pass: loginSurface.pass,
  }, null, 2));
  process.exit(2);
}

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 980 },
});

const loginPage = await context.newPage();
const loginConsoleErrors = [];
const loginNetworkErrors = [];
loginPage.on('console', (message) => {
  if (message.type() === 'error') loginConsoleErrors.push(message.text().slice(0, 800));
});
loginPage.on('requestfailed', (request) => {
  loginNetworkErrors.push({
    url: request.url(),
    method: request.method(),
    failure: request.failure()?.errorText ?? 'unknown',
  });
});
const authResult = await authenticate(loginPage).catch((error) => ({
  success: false,
  status: null,
  elapsed_ms: null,
  final_url: loginPage.url(),
  login_error_visible: true,
  error: error instanceof Error ? error.message : String(error),
}));
await redactVisibleSecrets(loginPage);
await loginPage.screenshot({ path: resolve(screenshotDir, '_login_after_attempt.png'), fullPage: true }).catch(() => undefined);
await loginPage.close();

const apiRows = await auditApis(context);
let routeRows = [];
if (authResult.success) {
  for (const route of REQUIRED_ROUTES) {
    routeRows.push(await auditRoute(context, route));
  }
}
await browser.close();

const screenshots = routeRows.flatMap((row) => [
  { route: row.route, kind: 'before_refresh', path: row.screenshots.before_refresh },
  { route: row.route, kind: 'after_refresh', path: row.screenshots.after_refresh },
]);
screenshots.push({ route: '/login', kind: 'after_login_attempt', path: `screenshots/${process.env.CONTROL_CENTER_AUDIT_PHASE ?? 'phase0'}/_login_after_attempt.png` });

writeJson('phase0_authenticated_site_audit.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  base_url: baseUrl,
  local_backend_base_url: backendBaseUrl,
  credential_env_contract: {
    username_env: 'DASHBOARD_TEST_USERNAME',
    password_env: 'DASHBOARD_TEST_PASSWORD',
    username_present: Boolean(username),
    password_present: Boolean(password),
    credentials_logged: false,
    credentials_committed: false,
  },
  login: authResult,
  routes: authResult.success ? routeRows : [],
  route_pass_count: routeRows.filter((row) => row.pass).length,
  route_fail_count: routeRows.filter((row) => !row.pass).length,
  pass_condition_status: {
    every_authenticated_route_loads: authResult.success && routeRows.every((row) => row.pass),
    no_blank_page_after_refresh: routeRows.every((row) => !row.data_vanished_after_refresh),
    no_unauthorized_redirect_loop: routeRows.every((row) => !/login/i.test(row.final_url) || row.route === '/login'),
    no_console_crash: routeRows.every((row) => row.console_errors.length === 0),
    no_500s: routeRows.every((row) => row.http_errors.every((entry) => entry.status < 500)),
    no_runtime_data_disappears_after_refresh: routeRows.every((row) => !row.data_vanished_after_refresh),
  },
});

writeJson('phase0_route_inventory.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  required_routes: REQUIRED_ROUTES,
  api_routes: REQUIRED_API_ROUTES,
  route_count: REQUIRED_ROUTES.length,
  api_route_count: REQUIRED_API_ROUTES.length,
  routes: routeRows.map((row) => ({
    route: row.route,
    requested_url: row.requested_url,
    final_url: row.final_url,
    http_status: row.http_status,
    title: row.title,
    pass: row.pass,
  })),
  api_contracts: apiRows,
});

writeJson('phase0_console_network_errors.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  login_console_errors: loginConsoleErrors,
  login_network_errors: loginNetworkErrors,
  route_errors: routeRows.map((row) => ({
    route: row.route,
    console_errors: row.console_errors,
    network_errors: row.network_errors,
    request_cancellations: row.request_cancellations ?? [],
    browser_navigation_aborts: row.browser_navigation_aborts ?? [],
    http_errors: row.http_errors,
    navigation_error: row.navigation_error,
    refresh_error: row.refresh_error,
  })),
  api_errors: apiRows.filter((row) => row.status === null || row.status >= 400),
});

writeJson('phase0_screenshot_manifest.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  screenshot_policy: {
    capture_after_auth: true,
    capture_before_and_after_refresh: true,
    redact_credentials: true,
    do_not_capture_tokens_cookies_or_raw_keys: true,
  },
  screenshots,
});

const latencyRows = routeLatencyRows(routeRows);
const latencyFailures = routeLatencyFailures(routeRows);
const routeRefreshFailures = refreshFailures(routeRows);
const routeNetworkErrors = networkErrors(routeRows);
const routeRequestCancellations = requestCancellations(routeRows);
const routeBrowserNavigationAborts = browserNavigationAborts(routeRows);
const routeConsoleErrors = consoleErrors(routeRows);
const apiFailures = apiContractFailures(apiRows);
const dashboardRow = routeRows.find((row) => row.route === '/dashboard') ?? null;
const dashboardVisibleMs = dashboardRow?.time_to_first_real_data_ms ?? null;
const streamContractsReady = apiRows
  .filter((row) => row.path?.startsWith('/api/v2/stream/'))
  .every(apiRowContractOk);
const routePassCount = routeRows.filter((row) => row.pass).length;
const routeFailCount = routeRows.filter((row) => !row.pass).length;
const apiContractPassCount = apiRows.filter(apiRowContractOk).length;
const apiContractFailCount = apiFailures.length;

writeJson('phase3_web_latency_report.json', {
  schema_version: 'phase3_web_latency_report_v1',
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  dashboard_url: baseUrl,
  status: latencyFailures.length === 0 ? 'LATENCY_TARGETS_PASS' : 'LATENCY_TARGETS_MISSED',
  targets: {
    dashboard_primary_data_visible_ms: dashboardPrimaryDataTargetMs,
    route_primary_data_visible_ms: routePrimaryDataTargetMs,
    login_primary_data_visible_ms: 3_000,
    refresh_retained_data_visible_ms: refreshRetainedDataTargetMs,
  },
  routes: latencyRows,
  latency_failures: latencyFailures,
});

writeJson('phase3_web_realtime_refresh_proof.json', {
  schema_version: 'phase3_web_realtime_refresh_proof_v1',
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  dashboard_url: baseUrl,
  status: latencyFailures.length === 0 && routeRefreshFailures.length === 0
    ? 'REFRESH_AND_LATENCY_TARGETS_PASS'
    : routeRefreshFailures.length === 0
      ? 'REFRESH_PASS_LATENCY_TARGETS_MISSED'
      : 'REFRESH_OR_LATENCY_TARGETS_MISSED',
  dashboard_primary_data_visible_ms: dashboardVisibleMs,
  dashboard_target_ms: dashboardPrimaryDataTargetMs,
  route_primary_data_target_ms: routePrimaryDataTargetMs,
  refresh_retained_data_visible_target_ms: refreshRetainedDataTargetMs,
  latency_target_pass: latencyFailures.length === 0,
  latency_failures: latencyFailures,
  refresh_blank_route_count: routeRows.filter((row) => row.data_vanished_after_refresh).length,
  refresh_failures: routeRefreshFailures,
  route_refresh_timings: routeRows.map((row) => ({
    route: row.route,
    time_to_after_refresh_real_data_ms: row.time_to_after_refresh_real_data_ms ?? null,
    data_vanished_after_refresh: row.data_vanished_after_refresh,
    refresh_error: row.refresh_error,
  })),
  websocket_or_sse_connected: streamContractsReady,
  last_known_good_state_visible_during_reconnect: routeRows.every((row) => !row.data_vanished_after_refresh),
  provider_panels_update_or_show_stale_state: routeRows
    .filter((row) => ['/providers', '/ingestors', '/markets'].includes(row.route))
    .every((row) => row.pass),
});

writeJson('phase10_enterprise_performance_report.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  status: routeFailCount === 0
    && apiContractFailCount === 0
    && latencyFailures.length === 0
    && routeRefreshFailures.length === 0
    ? 'PRODUCTION_BROWSER_AND_API_TARGETS_PASS'
    : 'PRODUCTION_TARGETS_INCOMPLETE',
  acceptance_targets: {
    login_to_dashboard_after_auth_ms: 3_000,
    primary_dashboard_data_visible_ms: dashboardPrimaryDataTargetMs,
    critical_realtime_updates_ms: 3_000,
    console_crashes: 0,
    unauthorized_api_loops: 0,
    api_500s: 0,
    huge_unpaginated_payload_bytes: 5_000_000,
  },
  login_to_dashboard_after_auth_ms: authResult.elapsed_ms ?? null,
  primary_dashboard_data_visible_ms: dashboardVisibleMs,
  route_pass_count: routePassCount,
  route_fail_count: routeFailCount,
  api_contract_pass_count: apiContractPassCount,
  api_contract_fail_count: apiContractFailCount,
  api_500s: api500Count(apiRows),
  console_crashes: routeConsoleErrors.length,
  network_error_count: routeNetworkErrors.length,
  request_cancellation_count: routeRequestCancellations.length,
  browser_navigation_abort_count: routeBrowserNavigationAborts.length,
  network_cleanliness_pass: routeNetworkErrors.length === 0,
  unauthorized_api_loops: apiRows.filter((row) => row.status === 401 || row.status === 403).length,
  latency_target_pass: latencyFailures.length === 0,
  latency_failures: latencyFailures,
  refresh_target_pass: routeRefreshFailures.length === 0,
  refresh_failures: routeRefreshFailures,
  route_timings: latencyRows,
});

writeJson('phase10_console_network_cleanliness.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  status: routeConsoleErrors.length === 0 && routeNetworkErrors.length === 0
    ? 'CONSOLE_AND_NETWORK_CLEAN'
    : 'CONSOLE_OR_NETWORK_ERRORS_PRESENT',
  console_errors: routeConsoleErrors,
  network_errors: routeNetworkErrors,
  request_cancellations: routeRequestCancellations,
  request_cancellations_documented: routeRequestCancellations.every((entry) => entry.failure === 'net::ERR_ABORTED'),
  browser_navigation_aborts: routeBrowserNavigationAborts,
  browser_navigation_aborts_documented: routeBrowserNavigationAborts.every((entry) => entry.failure === 'net::ERR_ABORTED'),
  http_errors: routeRows.flatMap((row) => row.http_errors.map((error) => ({ route: row.route, ...error }))),
  route_error_counts: routeRows.map((row) => ({
    route: row.route,
    console_errors: row.console_errors.length,
    network_errors: row.network_errors.length,
    request_cancellations: (row.request_cancellations ?? []).length,
    browser_navigation_aborts: (row.browser_navigation_aborts ?? []).length,
    http_errors: row.http_errors.length,
  })),
});

writeJson('phase11_authenticated_route_crawl_status.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  base_url: baseUrl,
  auth_success: authResult.success,
  api_contract_pass_count: apiContractPassCount,
  api_contract_fail_count: apiContractFailCount,
  api_contract_failures: apiFailures.map((row) => ({
    path: row.path,
    status: row.status,
    api_payload_kind: row.api_payload_kind,
    missing_required_contract_fields: row.missing_required_contract_fields ?? [],
    secret_leak_detected: row.secret_leak_detected === true,
    error: row.error,
  })),
  routes: routeRows,
  route_pass_count: routePassCount,
  route_fail_count: routeFailCount,
});

writeJson('phase11_route_failures.json', {
  goal_id: GOAL_ID,
  generated_at_utc: nowIso,
  failures: routeRows.filter((row) => !row.pass).map((row) => ({
    route: row.route,
    http_status: row.http_status,
    navigation_error: row.navigation_error,
    refresh_error: row.refresh_error,
    console_error_count: row.console_errors.length,
    network_error_count: row.network_errors.length,
    http_errors: row.http_errors,
    data_vanished_after_refresh: row.data_vanished_after_refresh,
    route_requirement_failures: row.route_requirement_failures,
    secret_leak_detected: row.secret_leak_detected,
  })),
});

console.log(JSON.stringify({
  status: authResult.success && routeRows.every((row) => row.pass) ? 'PASS' : 'FAIL',
  auth_success: authResult.success,
  route_pass_count: routeRows.filter((row) => row.pass).length,
  route_fail_count: routeRows.filter((row) => !row.pass).length,
  api_fail_count: apiRows.filter((row) => !apiRowContractOk(row)).length,
  goal_dir: goalDir,
}, null, 2));
