import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { test, type Page, type Request, type WebSocket } from '@playwright/test';
import {
  ALL_PAGE_PATHS,
  LEGACY_REDIRECTS,
  PUBLIC_PAGE_PATHS,
  TRADER_PAGE_PATHS,
  ADMIN_PAGE_PATHS,
  SUPERADMIN_PAGE_PATHS,
} from './helpers/routeContracts';

type AuditRole = 'guest' | 'viewer' | 'trader' | 'admin' | 'superadmin';
type AuditRouteKind = 'canonical' | 'legacy-redirect';

interface AuditRoute {
  path: string;
  kind: AuditRouteKind;
  expectedFinalRoute?: string;
  canonicalGroup: 'public' | 'trader' | 'admin' | 'superadmin' | 'legacy-target';
}

type RequestIssue = { url: string; method: string; status?: number; failure?: string };
type ClippedTextSample = {
  tag: string;
  class_name: string;
  text: string;
  overflow: string;
  scroll_width: number;
  client_width: number;
  scroll_height: number;
  client_height: number;
};

interface AuditRow {
  route: string;
  route_kind: AuditRouteKind;
  expected_final_route?: string;
  canonical_group: string;
  role: AuditRole;
  auth_fixture_kind: string;
  auth_backend_login_proven: boolean;
  auth_backend_guest_401_proven: boolean;
  auth_backend_me_role?: string | null;
  http_status: number | null;
  final_route: string;
  rendered_restricted_redirect: 'rendered' | 'restricted' | 'redirected' | 'loading' | 'error';
  websocket_urls: string[];
  websocket_frames_received: number;
  websocket_frames_sent: number;
  field_count: number;
  missing_fields: string[];
  stale_fields: string[];
  console_errors: string[];
  expected_auth_console_errors: string[];
  failed_requests: RequestIssue[];
  aborted_requests: RequestIssue[];
  horizontal_overflow_px: number;
  clipped_text_count: number;
  clipped_text_samples: ClippedTextSample[];
  visible_old_branding: string[];
  unauthorized_content_leakage: boolean;
  screenshot_path: string;
}

interface BackendAuthUser {
  email: string;
  password: string;
}

interface BackendAuthProof {
  login_status: number | null;
  me_status: number | null;
  me_role: string | null;
  login_proven: boolean;
  guest_401_proven: boolean;
  error?: string;
}

const ROLES: AuditRole[] = ['guest', 'viewer', 'trader', 'admin', 'superadmin'];
const AUTH_MODE = process.env.NERVYX_ROLE_ROUTE_AUTH_MODE === 'backend_login' ? 'backend_login' : 'fixture';
const AUTH_FIXTURE_KIND = AUTH_MODE === 'backend_login'
  ? 'backend_login_cookie_session_isolated_user_store'
  : 'playwright_api_auth_me_fixture_not_backend_login';
const GENERATED_AT = new Date().toISOString();
const BASE_URL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173';
const ARTIFACT_ROOT = path.resolve(process.cwd(), '..', 'artifacts');
const ARTIFACT_FILE = AUTH_MODE === 'backend_login'
  ? 'nervyx-role-route-audit-backend-auth.json'
  : 'nervyx-role-route-audit.json';
const SCREENSHOT_ROOT = path.join(
  ARTIFACT_ROOT,
  AUTH_MODE === 'backend_login'
    ? 'nervyx-role-route-audit-backend-auth-screenshots'
    : 'nervyx-role-route-audit-screenshots',
);
const CANONICAL_GROUPS: Array<[readonly string[], AuditRoute['canonicalGroup']]> = [
  [PUBLIC_PAGE_PATHS, 'public'],
  [TRADER_PAGE_PATHS, 'trader'],
  [ADMIN_PAGE_PATHS, 'admin'],
  [SUPERADMIN_PAGE_PATHS, 'superadmin'],
];
const OLD_BRANDING_PATTERNS = [
  /AI BOT V2/i,
  /AlphaForge/i,
  /Control Plane/i,
  /Control Portal/i,
  /Live trading platform/i,
  /Live execution/i,
  /Trading live/i,
  /Paper only/i,
  /\bNO DATA\b/i,
];
const MISSING_PATTERNS = [
  /\bNo data\b/i,
  /\bUnavailable\b/i,
  /\bMissing\b/i,
  /\bNot available\b/i,
  /\bData unavailable\b/i,
];
const STALE_PATTERNS = [
  /\bStale\b/i,
  /\bDelayed\b/i,
  /\bOffline\b/i,
  /\bConnecting\b/i,
  /\bFallback\b/i,
];

function parseBackendAuthUsers(): Partial<Record<Exclude<AuditRole, 'guest'>, BackendAuthUser>> {
  const raw = process.env.NERVYX_ROLE_ROUTE_AUTH_USERS;
  if (!raw) return {};
  const parsed = JSON.parse(raw) as unknown;
  if (!parsed || typeof parsed !== 'object') {
    throw new Error('NERVYX_ROLE_ROUTE_AUTH_USERS must be a JSON object keyed by role');
  }
  const users: Partial<Record<Exclude<AuditRole, 'guest'>, BackendAuthUser>> = {};
  for (const role of ROLES.filter((value): value is Exclude<AuditRole, 'guest'> => value !== 'guest')) {
    const value = (parsed as Record<string, unknown>)[role];
    if (!value || typeof value !== 'object') continue;
    const email = String((value as Record<string, unknown>).email ?? '').trim();
    const password = String((value as Record<string, unknown>).password ?? '');
    if (!email || !password) {
      throw new Error(`NERVYX_ROLE_ROUTE_AUTH_USERS.${role} requires email and password`);
    }
    users[role] = { email, password };
  }
  return users;
}

const BACKEND_AUTH_USERS = parseBackendAuthUsers();

function absoluteApiPath(apiPath: string): string {
  return new URL(apiPath, BASE_URL).toString();
}

function canonicalGroupFor(route: string): AuditRoute['canonicalGroup'] {
  return CANONICAL_GROUPS.find(([paths]) => paths.includes(route as never))?.[1] ?? 'legacy-target';
}

function auditRoutes(): AuditRoute[] {
  const canonical = ALL_PAGE_PATHS.map((route) => ({
    path: route,
    kind: 'canonical' as const,
    canonicalGroup: canonicalGroupFor(route),
  }));
  const legacy = Object.entries(LEGACY_REDIRECTS).map(([from, to]) => ({
    path: from,
    kind: 'legacy-redirect' as const,
    expectedFinalRoute: to,
    canonicalGroup: 'legacy-target' as const,
  }));
  const targets = Array.from(new Set(Object.values(LEGACY_REDIRECTS)))
    .filter((route) => !ALL_PAGE_PATHS.includes(route as never))
    .map((route) => ({
      path: route,
      kind: 'canonical' as const,
      canonicalGroup: 'legacy-target' as const,
    }));
  return [...canonical, ...targets, ...legacy].sort((a, b) => `${a.kind}:${a.path}`.localeCompare(`${b.kind}:${b.path}`));
}

function userFor(role: Exclude<AuditRole, 'guest'>) {
  const trader = role === 'trader';
  return {
    id: trader ? 'user-wajidali1984' : `audit-${role}`,
    trader_id: trader ? 'trader-wajidali1984' : null,
    username: trader ? 'wajidali1984' : `audit_${role}`,
    email: trader ? 'wajidali1984@hotmail.com' : `${role}@test.nervyx.local`,
    role,
    paper_account_id: trader ? 'paper-wajidali1984' : null,
    exchange_accounts: trader
      ? [
        {
          id: 'binance-wajidali1984',
          trader_id: 'trader-wajidali1984',
          paper_account_id: 'paper-wajidali1984',
          exchange: 'binance',
          label: 'Wajid Ali Binance Futures',
          account_type: 'usd_m_futures',
          mode: 'read_only',
          read_only: true,
          live_trading_enabled: false,
          status: 'credential_source_pending',
          credential_status: {
            credential_scope: 'backend_only_readonly',
            source_type: 'environment_reference',
            configured: false,
            status: 'credential_source_pending',
            read_only_required: true,
            live_trading_enabled: false,
            binding_blocked_reason: null,
            raw_credential_value_exposed: false,
            checked_at: '2026-06-14T00:00:00Z',
          },
          created_at: '2026-06-14T00:00:00Z',
          updated_at: '2026-06-14T00:00:00Z',
        },
      ]
      : [],
    watchlist: trader ? ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'] : ['BTCUSDT', 'ETHUSDT'],
    alert_preferences: {},
    is_active: true,
    created_at: '2026-06-14T00:00:00Z',
    updated_at: '2026-06-14T00:00:00Z',
    last_login: '2026-06-14T00:00:00Z',
  };
}

async function installAuthFixture(page: Page, getRole: () => AuditRole): Promise<void> {
  await page.route('**/api/auth/me', async (route) => {
    const role = getRole();
    if (role === 'guest') {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Authentication required' }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user: userFor(role) }),
    });
  });
  await page.route('**/api/auth/refresh', async (route) => {
    const role = getRole();
    await route.fulfill({
      status: role === 'guest' ? 401 : 200,
      contentType: 'application/json',
      body: JSON.stringify(role === 'guest' ? { detail: 'Authentication required' } : { ok: true }),
    });
  });
  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true }) });
  });
}

async function parseJson(response: { json: () => Promise<unknown> }): Promise<Record<string, unknown>> {
  const body = await response.json().catch(() => null);
  return body && typeof body === 'object' ? body as Record<string, unknown> : {};
}

async function clearBrowserAuth(page: Page): Promise<void> {
  await page.context().clearCookies();
  await page.goto(BASE_URL, { waitUntil: 'domcontentloaded', timeout: 15_000 }).catch(() => null);
  await page.evaluate(() => {
    window.localStorage.clear();
    window.sessionStorage.clear();
  }).catch(() => undefined);
  await page.goto('about:blank').catch(() => null);
}

async function establishBackendAuth(page: Page, role: AuditRole): Promise<BackendAuthProof> {
  await clearBrowserAuth(page);
  const request = page.context().request;
  if (role === 'guest') {
    const me = await request.get(absoluteApiPath('/api/auth/me'), { failOnStatusCode: false });
    return {
      login_status: null,
      me_status: me.status(),
      me_role: null,
      login_proven: false,
      guest_401_proven: me.status() === 401,
    };
  }

  const credentials = BACKEND_AUTH_USERS[role];
  if (!credentials) {
    return {
      login_status: null,
      me_status: null,
      me_role: null,
      login_proven: false,
      guest_401_proven: false,
      error: `missing_backend_auth_credentials_for_${role}`,
    };
  }

  const login = await request.post(absoluteApiPath('/api/auth/login'), {
    failOnStatusCode: false,
    data: {
      email: credentials.email,
      password: credentials.password,
    },
  });
  const me = await request.get(absoluteApiPath('/api/auth/me'), { failOnStatusCode: false });
  const meBody = await parseJson(me);
  const user = meBody.user && typeof meBody.user === 'object' ? meBody.user as Record<string, unknown> : {};
  const meRole = typeof user.role === 'string' ? user.role : null;

  return {
    login_status: login.status(),
    me_status: me.status(),
    me_role: meRole,
    login_proven: login.status() === 200 && me.status() === 200 && meRole === role,
    guest_401_proven: false,
  };
}

function requestRecord(request: Request, status?: number) {
  return {
    url: request.url(),
    method: request.method(),
    ...(status === undefined ? {} : { status }),
    ...(request.failure()?.errorText ? { failure: request.failure()?.errorText } : {}),
  };
}

function isAbortedNavigationRequest(record: RequestIssue): boolean {
  return /net::ERR_ABORTED/i.test(record.failure ?? '');
}

function isExpectedGuestAuthConsole(role: AuditRole, text: string): boolean {
  return role === 'guest' && /status of 401 \(Unauthorized\)/i.test(text);
}

async function textMatches(page: Page, patterns: RegExp[]): Promise<string[]> {
  const bodyText = await page.locator('body').innerText({ timeout: 2_000 }).catch(() => '');
  return patterns.filter((pattern) => pattern.test(bodyText)).map((pattern) => pattern.source);
}

async function classifyRender(page: Page, finalRoute: string, originalRoute: string): Promise<AuditRow['rendered_restricted_redirect']> {
  const accessDenied = await page.getByTestId('access-denied').count().catch(() => 0);
  if (accessDenied > 0) return 'restricted';
  if (finalRoute !== originalRoute) return 'redirected';
  const errorText = await page.locator('body').innerText({ timeout: 2_000 }).catch(() => '');
  if (/error boundary|application error|uncaught/i.test(errorText)) return 'error';
  const headingCount = await page.locator('h1,h2,[data-testid^="page-"],main,[data-testid="admin-main"]').count().catch(() => 0);
  if (headingCount > 0) return 'rendered';
  return 'loading';
}

async function visibleFieldCount(page: Page): Promise<number> {
  return page.evaluate(() => {
    const selectors = [
      '[data-testid]',
      '[data-field]',
      'table td',
      'table th',
      'dl dd',
      'dl dt',
      '[class*="metric"]',
      '[class*="card"]',
      '[class*="panel"]',
    ].join(',');
    return Array.from(document.querySelectorAll(selectors))
      .filter((element) => {
        const rect = element.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
      }).length;
  }).catch(() => 0);
}

async function overflowPx(page: Page): Promise<number> {
  return page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)).catch(() => 0);
}

async function clippedTextCount(page: Page): Promise<number> {
  return page.evaluate(() => {
    return Array.from(document.querySelectorAll('button,a,span,div,p,td,th,h1,h2,h3'))
      .filter((element) => {
        const text = (element.textContent || '').trim();
        if (!text) return false;
        const htmlElement = element as HTMLElement;
        const style = window.getComputedStyle(htmlElement);
        if (style.overflow === 'visible' || style.overflow === 'auto' || style.overflow === 'scroll') return false;
        return htmlElement.scrollWidth > htmlElement.clientWidth + 2 || htmlElement.scrollHeight > htmlElement.clientHeight + 2;
      })
      .length;
  }).catch(() => 0);
}

async function clippedTextSamples(page: Page): Promise<ClippedTextSample[]> {
  return page.evaluate(() => {
    return Array.from(document.querySelectorAll('button,a,span,div,p,td,th,h1,h2,h3'))
      .filter((element) => {
        const text = (element.textContent || '').trim();
        if (!text) return false;
        const htmlElement = element as HTMLElement;
        const style = window.getComputedStyle(htmlElement);
        if (style.overflow === 'visible' || style.overflow === 'auto' || style.overflow === 'scroll') return false;
        return htmlElement.scrollWidth > htmlElement.clientWidth + 2 || htmlElement.scrollHeight > htmlElement.clientHeight + 2;
      })
      .slice(0, 16)
      .map((element) => {
        const htmlElement = element as HTMLElement;
        const style = window.getComputedStyle(htmlElement);
        return {
          tag: htmlElement.tagName.toLowerCase(),
          class_name: htmlElement.className ? String(htmlElement.className).slice(0, 160) : '',
          text: (htmlElement.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 180),
          overflow: style.overflow,
          scroll_width: htmlElement.scrollWidth,
          client_width: htmlElement.clientWidth,
          scroll_height: htmlElement.scrollHeight,
          client_height: htmlElement.clientHeight,
        };
      });
  }).catch(() => []);
}

async function unauthorizedLeakage(page: Page, role: AuditRole, route: AuditRoute, state: AuditRow['rendered_restricted_redirect']): Promise<boolean> {
  if (role === 'admin' || role === 'superadmin') return false;
  if (route.canonicalGroup !== 'admin' && route.canonicalGroup !== 'superadmin' && !route.path.startsWith('/admin') && !route.path.startsWith('/system')) {
    return false;
  }
  const adminMain = await page.getByTestId('admin-main').count().catch(() => 0);
  const adminNav = await page.getByTestId('admin-nav').count().catch(() => 0);
  return state === 'rendered' || adminMain > 0 || adminNav > 0;
}

function screenshotName(role: AuditRole, route: AuditRoute): string {
  const safe = route.path.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'root';
  return `${role}_${route.kind}_${safe}.png`;
}

test.describe('NERVYX role-route audit evidence', () => {
  test.setTimeout(900_000);

  test('captures canonical and legacy route behavior for each role without query-role authorization', async ({ page }) => {
    mkdirSync(SCREENSHOT_ROOT, { recursive: true });
    const routes = auditRoutes();
    const rows: AuditRow[] = [];
    const authProofs: Partial<Record<AuditRole, BackendAuthProof>> = {};
    let activeRole: AuditRole = 'guest';
    if (AUTH_MODE === 'fixture') {
      await installAuthFixture(page, () => activeRole);
    }

    for (const role of ROLES) {
      activeRole = role;
      if (AUTH_MODE === 'backend_login') {
        authProofs[role] = await establishBackendAuth(page, role);
      }
      for (const route of routes) {
        const consoleErrors: string[] = [];
        const expectedAuthConsoleErrors: string[] = [];
        const failedRequests: RequestIssue[] = [];
        const abortedRequests: RequestIssue[] = [];
        const websockets: Array<{ url: string; frames_received: number; frames_sent: number }> = [];
        const onConsole = (message: { type: () => string; text: () => string }) => {
          if (message.type() !== 'error') return;
          const text = message.text();
          if (isExpectedGuestAuthConsole(role, text)) expectedAuthConsoleErrors.push(text);
          else consoleErrors.push(text);
        };
        const onRequestFailed = (request: Request) => {
          const record = requestRecord(request);
          if (isAbortedNavigationRequest(record)) abortedRequests.push(record);
          else failedRequests.push(record);
        };
        const onResponse = (response: { status: () => number; request: () => Request }) => {
          const status = response.status();
          if (status >= 400) failedRequests.push(requestRecord(response.request(), status));
        };
        const onWebSocket = (ws: WebSocket) => {
          const record = { url: ws.url(), frames_received: 0, frames_sent: 0 };
          websockets.push(record);
          ws.on('framereceived', () => { record.frames_received += 1; });
          ws.on('framesent', () => { record.frames_sent += 1; });
        };

        page.on('console', onConsole);
        page.on('requestfailed', onRequestFailed);
        page.on('response', onResponse);
        page.on('websocket', onWebSocket);

        const response = await page.goto(route.path, { waitUntil: 'domcontentloaded', timeout: 15_000 }).catch(() => null);
        await page.waitForTimeout(650);
        const finalRoute = new URL(page.url()).pathname;
        const state = await classifyRender(page, finalRoute, route.path);
        const screenshotPath = path.join(SCREENSHOT_ROOT, screenshotName(role, route));
        await page.screenshot({ path: screenshotPath, fullPage: false }).catch(() => undefined);

        rows.push({
          route: route.path,
          route_kind: route.kind,
          expected_final_route: route.expectedFinalRoute,
          canonical_group: route.canonicalGroup,
          role,
          auth_fixture_kind: AUTH_FIXTURE_KIND,
          auth_backend_login_proven: Boolean(authProofs[role]?.login_proven),
          auth_backend_guest_401_proven: Boolean(authProofs[role]?.guest_401_proven),
          auth_backend_me_role: authProofs[role]?.me_role ?? null,
          http_status: response?.status() ?? null,
          final_route: finalRoute,
          rendered_restricted_redirect: state,
          websocket_urls: Array.from(new Set(websockets.map((ws) => ws.url))),
          websocket_frames_received: websockets.reduce((sum, ws) => sum + ws.frames_received, 0),
          websocket_frames_sent: websockets.reduce((sum, ws) => sum + ws.frames_sent, 0),
          field_count: await visibleFieldCount(page),
          missing_fields: await textMatches(page, MISSING_PATTERNS),
          stale_fields: await textMatches(page, STALE_PATTERNS),
          console_errors: consoleErrors.slice(0, 20),
          expected_auth_console_errors: expectedAuthConsoleErrors.slice(0, 20),
          failed_requests: failedRequests
            .filter((entry) => !entry.url.includes('/api/auth/me') || role !== 'guest')
            .slice(0, 50),
          aborted_requests: abortedRequests.slice(0, 50),
          horizontal_overflow_px: await overflowPx(page),
          clipped_text_count: await clippedTextCount(page),
          clipped_text_samples: await clippedTextSamples(page),
          visible_old_branding: await textMatches(page, OLD_BRANDING_PATTERNS),
          unauthorized_content_leakage: await unauthorizedLeakage(page, role, route, state),
          screenshot_path: path.relative(path.resolve(process.cwd(), '..'), screenshotPath),
        });

        page.off('console', onConsole);
        page.off('requestfailed', onRequestFailed);
        page.off('response', onResponse);
        page.off('websocket', onWebSocket);
      }
    }

    const summary = {
      total_rows: rows.length,
      by_role: Object.fromEntries(ROLES.map((role) => [role, rows.filter((row) => row.role === role).length])),
      rendered: rows.filter((row) => row.rendered_restricted_redirect === 'rendered').length,
      restricted: rows.filter((row) => row.rendered_restricted_redirect === 'restricted').length,
      redirected: rows.filter((row) => row.rendered_restricted_redirect === 'redirected').length,
      loading_or_error: rows.filter((row) => row.rendered_restricted_redirect === 'loading' || row.rendered_restricted_redirect === 'error').length,
      rows_with_websockets: rows.filter((row) => row.websocket_urls.length > 0).length,
      rows_with_frames: rows.filter((row) => row.websocket_frames_received > 0 || row.websocket_frames_sent > 0).length,
      rows_with_failed_requests: rows.filter((row) => row.failed_requests.length > 0).length,
      failed_request_count: rows.reduce((sum, row) => sum + row.failed_requests.length, 0),
      rows_with_aborted_requests: rows.filter((row) => row.aborted_requests.length > 0).length,
      aborted_request_count: rows.reduce((sum, row) => sum + row.aborted_requests.length, 0),
      rows_with_console_errors: rows.filter((row) => row.console_errors.length > 0).length,
      console_error_count: rows.reduce((sum, row) => sum + row.console_errors.length, 0),
      rows_with_expected_auth_console_errors: rows.filter((row) => row.expected_auth_console_errors.length > 0).length,
      expected_auth_console_error_count: rows.reduce((sum, row) => sum + row.expected_auth_console_errors.length, 0),
      rows_with_horizontal_overflow: rows.filter((row) => row.horizontal_overflow_px > 1).length,
      rows_with_clipped_text: rows.filter((row) => row.clipped_text_count > 0).length,
      rows_with_old_branding: rows.filter((row) => row.visible_old_branding.length > 0).length,
      rows_with_unauthorized_content_leakage: rows.filter((row) => row.unauthorized_content_leakage).length,
    };
    const backendAuthSummary = Object.fromEntries(
      ROLES.map((role) => {
        const proof = authProofs[role];
        return [role, proof ? {
          login_status: proof.login_status,
          me_status: proof.me_status,
          me_role: proof.me_role,
          login_proven: proof.login_proven,
          guest_401_proven: proof.guest_401_proven,
          error: proof.error ?? null,
        } : null];
      }),
    );
    const backendAuthGateProven = AUTH_MODE === 'backend_login'
      && ROLES.every((role) => {
        const proof = authProofs[role];
        if (!proof) return false;
        return role === 'guest' ? proof.guest_401_proven : proof.login_proven;
      });

    const artifact = {
      generated_at: GENERATED_AT,
      status: AUTH_MODE === 'backend_login'
        ? 'IN_PROGRESS_BACKEND_AUTH_ROUTE_AUDIT'
        : 'IN_PROGRESS_PARTIAL_FIXTURE_AUDIT',
      final_gate_proof: false,
      reason_not_final: AUTH_MODE === 'backend_login'
        ? 'This audit proves backend login-cookie sessions for route coverage only; the broader NERVYX goal still requires field parity, full suites, native macOS/Xcode validation, and TestFlight evidence.'
        : 'This audit does not prove backend-authenticated login sessions; it uses a Playwright /api/auth/me fixture and records auth_backend_login_proven=false for every row.',
      auth_fixture_kind: AUTH_FIXTURE_KIND,
      auth_mode: AUTH_MODE,
      auth_backend_login_gate_proven: backendAuthGateProven,
      auth_backend_summary: backendAuthSummary,
      query_role_used: false,
      base_url: test.info().project.use.baseURL ?? null,
      required_roles: ROLES,
      canonical_route_count: routes.filter((route) => route.kind === 'canonical').length,
      legacy_redirect_count: routes.filter((route) => route.kind === 'legacy-redirect').length,
      summary,
      routes: rows,
    };
    writeFileSync(path.join(ARTIFACT_ROOT, ARTIFACT_FILE), `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
  });
});
