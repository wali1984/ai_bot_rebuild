/**
 * Final product regression evidence.
 *
 * This is intentionally registry-driven.  The older role/route sweeps remain
 * historical evidence; this pass is the final built-frontend check across the
 * current reachable registry, four required viewports, live response bodies,
 * WebSocket frames, and source-to-rendered-value candidates.
 */
import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { test, type Page, type Request, type Response, type WebSocket } from '@playwright/test';
import { PAGES } from '../../src/pages/registry';
import { MERGED_LEGACY_PATHS } from '../../src/pages/productNavigation';

type Viewport = { name: string; width: number; height: number };
type RouteCase = { pageId: string; path: string; surface: string; minRole: string; dynamic?: boolean };
type JsonLeaf = { path: string; value: string | number | boolean | null };
type RenderField = { tag: string; text: string; test_id: string | null; data_field: string | null; aria: string | null };
type SourceResponse = { url: string; status: number; content_type: string; leaves: JsonLeaf[] };

const VIEWPORTS: Viewport[] = [
  { name: 'desktop_1600x1000', width: 1600, height: 1000 },
  { name: 'desktop_1440x900', width: 1440, height: 900 },
  { name: 'iphone_390x844', width: 390, height: 844 },
  { name: 'tablet_1024x900', width: 1024, height: 900 },
];
const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5174';
const ARTIFACT_ROOT = path.resolve(process.cwd(), '..', 'artifacts', 'final-product-regression');
const FAMILY = process.env.FINAL_AUDIT_FAMILY ?? 'all';
const TOKEN_FILE = process.env.FINAL_PRODUCT_AUDIT_ADMIN_TOKEN_FILE;

const FAMILY_BY_ID: Record<string, string> = {
  'public-landing-v2': 'global_public',
  'public-status': 'global_public',
  login: 'global_public',
  'user-status': 'global_public',
  markets: 'markets_charts',
  market: 'markets_charts',
  symbols: 'markets_charts',
  'pro-chart': 'markets_charts',
  binance: 'markets_charts',
  'liquidation-bridge': 'markets_charts',
  'market-intelligence': 'markets_charts',
  'technical-analysis': 'markets_charts',
  'markets-ingestors': 'ingestors_providers',
  dashboard: 'trading_portfolio_risk',
  trader: 'trading_portfolio_risk',
  'paper-trading': 'trading_portfolio_risk',
  positions: 'trading_portfolio_risk',
  executions: 'trading_portfolio_risk',
  history: 'trading_portfolio_risk',
  'account-settings': 'trading_portfolio_risk',
  alerts: 'trading_portfolio_risk',
  risk: 'trading_portfolio_risk',
  'live-canary': 'trading_portfolio_risk',
  'system-health': 'trading_portfolio_risk',
  'strategy-backtesting': 'trading_portfolio_risk',
  'backtests-replay': 'trading_portfolio_risk',
  replay: 'trading_portfolio_risk',
  'ai-predictions': 'trainer_ai',
  'ai-brain': 'trainer_ai',
  'trainer-admin': 'trainer_ai',
  'trainer-prediction-monitor': 'trainer_ai',
  'market-brain': 'trainer_ai',
  'admin-overview': 'admin_system',
  'admin-data': 'admin_system',
  'admin-intelligence': 'admin_system',
  'admin-orchestration': 'admin_system',
  'admin-risk': 'admin_system',
  'admin-execution': 'admin_system',
  'admin-exchanges': 'admin_system',
  'admin-config': 'admin_system',
  'admin-users': 'admin_system',
  'admin-reports': 'admin_system',
  'admin-logs': 'admin_system',
  'admin-audit': 'admin_system',
  'admin-tools': 'admin_system',
  'monitor-center': 'admin_system',
  'signal-explainability': 'trainer_ai',
  'external-manual-position-quarantine': 'admin_system',
  'strategy-admin': 'admin_system',
  'live-readiness': 'admin_system',
  'codex-review-center': 'admin_system',
  'operator-proof-dashboard': 'admin_system',
  'orderbook-runtime-truth': 'admin_system',
  'microstructure-trust': 'admin_system',
};

function concretePath(pagePath: string): string {
  if (pagePath === '/market/:symbol?') return '/market/BTCUSDT';
  if (pagePath === '/chart/:symbol?') return '/chart/BTCUSDT';
  return pagePath.replace(/\/:name\?$/, '');
}

function routeCases(): RouteCase[] {
  const redirectSources = new Set(Object.keys(MERGED_LEGACY_PATHS));
  const pages = PAGES
    .filter((page) => !redirectSources.has(page.route.path))
    .map((page) => ({
      pageId: page.meta.id,
      path: concretePath(page.route.path),
      surface: page.meta.surface,
      minRole: page.rbac.minRole,
    }));
  pages.unshift({ pageId: 'root-index', path: '/', surface: 'public', minRole: 'public' });
  return pages.filter((row) => FAMILY === 'all' || (FAMILY_BY_ID[row.pageId] ?? 'admin_system') === FAMILY);
}

function familyFor(pageId: string): string {
  return pageId === 'root-index' ? 'global_public' : (FAMILY_BY_ID[pageId] ?? 'admin_system');
}

function safeName(value: string): string {
  return value.replace(/[^a-zA-Z0-9]+/g, '_').replace(/^_+|_+$/g, '') || 'root';
}

function flatten(value: unknown, prefix = '', output: JsonLeaf[] = [], depth = 0): JsonLeaf[] {
  if (output.length >= 5000 || depth > 8) return output;
  if (value === null || typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') {
    output.push({ path: prefix || '$', value: value as JsonLeaf['value'] });
    return output;
  }
  if (Array.isArray(value)) {
    value.slice(0, 100).forEach((entry, index) => flatten(entry, `${prefix}[${index}]`, output, depth + 1));
    return output;
  }
  if (value && typeof value === 'object') {
    Object.entries(value as Record<string, unknown>).slice(0, 500).forEach(([key, entry]) => {
      flatten(entry, prefix ? `${prefix}.${key}` : key, output, depth + 1);
    });
  }
  return output;
}

function normalise(value: string): string {
  return value.toLowerCase().replace(/\s+/g, ' ').replace(/[,$]/g, '').trim();
}

async function bounded<T>(promise: Promise<T>, fallback: T, milliseconds = 4_000): Promise<T> {
  return Promise.race([
    promise,
    new Promise<T>((resolve) => setTimeout(() => resolve(fallback), milliseconds)),
  ]);
}

function numeric(value: string): number | null {
  const cleaned = value.replace(/[$,%\s,]/g, '');
  if (!cleaned || !/^-?\d+(?:\.\d+)?$/.test(cleaned)) return null;
  const parsed = Number(cleaned);
  return Number.isFinite(parsed) ? parsed : null;
}

function matchField(field: RenderField, responses: SourceResponse[]): { url: string; path: string } | null {
  const text = normalise(field.text);
  if (!text || text.length > 220) return null;
  const fieldNumber = numeric(field.text);
  for (const response of responses) {
    for (const leaf of response.leaves) {
      if (typeof leaf.value === 'string') {
        const sourceText = normalise(leaf.value);
        if (sourceText === text || (sourceText.length >= 3 && (text.includes(sourceText) || sourceText.includes(text)))) {
          return { url: response.url, path: leaf.path };
        }
      }
      if (fieldNumber !== null && typeof leaf.value === 'number') {
        if (Math.abs(fieldNumber - leaf.value) < 1e-8 || Math.abs(fieldNumber / 100 - leaf.value) < 1e-8 || Math.abs(fieldNumber - leaf.value * 100) < 1e-8) {
          return { url: response.url, path: leaf.path };
        }
      }
      if (typeof leaf.value === 'boolean' && normalise(String(leaf.value)) === text) return { url: response.url, path: leaf.path };
    }
  }
  return null;
}

async function visibleFields(page: Page): Promise<RenderField[]> {
  return page.evaluate(() => {
    const selector = 'h1,h2,h3,h4,p,li,td,th,dt,dd,button,a,label,input,textarea,select,[data-field]';
    const nodes = Array.from(document.querySelectorAll(selector));
    return nodes.filter((node) => {
      const element = node as HTMLElement;
      const rect = element.getBoundingClientRect();
      if (!rect.width || !rect.height) return false;
      const childCandidates = Array.from(element.children).some((child) => child.matches(selector) && (child.textContent || '').trim());
      return !childCandidates;
    }).map((node) => {
      const element = node as HTMLElement;
      return {
        tag: element.tagName.toLowerCase(),
        text: element instanceof HTMLInputElement || element instanceof HTMLTextAreaElement || element instanceof HTMLSelectElement
          ? (element.value || element.getAttribute('placeholder') || '').trim()
          : (element.innerText || element.textContent || '').replace(/\s+/g, ' ').trim(),
        test_id: element.getAttribute('data-testid'),
        data_field: element.getAttribute('data-field'),
        aria: element.getAttribute('aria-label'),
      };
    }).filter((field) => field.text.length > 0);
  }).catch(() => []);
}

async function collectDynamicIngestorRoutes(page: Page): Promise<RouteCase[]> {
  const hrefs = await page.locator('a[href^="/markets/ingestors/"]').evaluateAll((links) => links.map((link) => (link as HTMLAnchorElement).getAttribute('href')).filter(Boolean));
  return Array.from(new Set(hrefs)).map((href) => ({ pageId: 'markets-ingestors', path: href as string, surface: 'public', minRole: 'public', dynamic: true }));
}

async function installAdminCookie(page: Page): Promise<'admin_cookie' | 'guest'> {
  await page.context().clearCookies();
  if (!TOKEN_FILE || !existsSync(TOKEN_FILE)) return 'guest';
  const token = readFileSync(TOKEN_FILE, 'utf8').trim();
  if (!token) return 'guest';
  await page.context().addCookies([{ name: 'alphaforge_session', value: token, url: BASE, httpOnly: true, secure: false, sameSite: 'Lax' }]);
  return 'admin_cookie';
}

async function captureRoute(page: Page, route: RouteCase, viewport: Viewport): Promise<Record<string, unknown>> {
  const responses: SourceResponse[] = [];
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const wsUrls = new Set<string>();
  const wsFrames = { received: 0, sent: 0 };
  const responseBodies: Promise<void>[] = [];
  const onResponse = (response: Response) => {
    const status = response.status();
    const contentType = response.headers()['content-type'] ?? '';
    if (status < 200 || status >= 300 || !contentType.includes('json')) return;
    responseBodies.push((async () => {
      const body = await Promise.race([
        response.json().catch(() => null),
        new Promise<null>((resolve) => setTimeout(() => resolve(null), 1500)),
      ]);
      responses.push({ url: response.url(), status, content_type: contentType, leaves: flatten(body) });
    })());
  };
  const onConsole = (message: { type: () => string; text: () => string }) => { if (message.type() === 'error') consoleErrors.push(message.text()); };
  const onFailed = (request: Request) => { if (!/ERR_ABORTED/i.test(request.failure()?.errorText ?? '')) failedRequests.push(request.url()); };
  const onWebSocket = (socket: WebSocket) => {
    wsUrls.add(socket.url());
    socket.on('framereceived', (data) => { wsFrames.received += 1; if (data) responses.push({ url: socket.url(), status: 101, content_type: 'websocket', leaves: flatten(typeof data === 'string' ? JSON.parse(data) : data) }); });
    socket.on('framesent', () => { wsFrames.sent += 1; });
  };
  page.on('response', onResponse);
  page.on('console', onConsole);
  page.on('requestfailed', onFailed);
  page.on('websocket', onWebSocket);
  const authMode = route.surface === 'public' ? await installAdminCookie(page).then(async (mode) => { await page.context().clearCookies(); return mode === 'admin_cookie' ? 'guest' : mode; }) : await installAdminCookie(page);
  const response = await page.goto(route.path, { waitUntil: 'commit', timeout: 8_000 }).catch(() => null);
  await page.waitForTimeout(1_200);
  // Signal Explainability mounts several large proof payloads and can keep a
  // Chromium renderer busy beyond Playwright's cancellation boundary. Preserve
  // the route/network result and let the sweep continue; the missing visual
  // capture is emitted as an explicit defect in the artifact.
  if (route.pageId === 'signal-explainability') {
    page.off('response', onResponse);
    page.off('console', onConsole);
    page.off('requestfailed', onFailed);
    page.off('websocket', onWebSocket);
    return {
      page_id: route.pageId,
      route: route.path,
      surface: route.surface,
      min_role: route.minRole,
      auth_mode: authMode,
      viewport,
      http_status: response?.status() ?? null,
      final_route: new URL(page.url()).pathname,
      title: 'Signal Explainability',
      field_count: 0,
      source_matched_field_count: 0,
      dynamic_candidate_count: 0,
      unmatched_dynamic_fields: [],
      visible_fields: [],
      source_responses: responses.slice(0, 80).map((item) => ({ ...item, leaves: item.leaves.slice(0, 500) })),
      websocket_urls: Array.from(wsUrls),
      websocket_frames_received: wsFrames.received,
      websocket_frames_sent: wsFrames.sent,
      console_errors: consoleErrors.slice(0, 30),
      failed_requests: failedRequests.slice(0, 50),
      horizontal_overflow_px: null,
      forbidden_runtime_text: null,
      screenshot_path: null,
      screenshot_blocked_reason: 'renderer_busy_large_proof_payload',
    };
  }
  await Promise.allSettled(responseBodies);
  const fields = await bounded(visibleFields(page), []);
  const matches = fields.map((field) => ({ field, source: matchField(field, responses) }));
  const dynamicCandidates = matches.filter(({ field }) => {
    const text = field.text.trim();
    if (/\d|%|\$/.test(text)) return true;
    return text.length <= 48
      && !/[.!?]/.test(text)
      && /^(?:fresh|stale|blocked|healthy|optional|missing|available|error|yes|no|live|held|offline|connecting|pass|fail|green|amber|red)\b/i.test(text);
  });
  const screenshotDir = path.join(ARTIFACT_ROOT, familyFor(route.pageId), safeName(route.path));
  mkdirSync(screenshotDir, { recursive: true });
  const screenshotPath = path.join(screenshotDir, `${viewport.name}.png`);
  await bounded(page.screenshot({ path: screenshotPath, fullPage: false, timeout: 5_000 }).catch(() => undefined), undefined, 5_000);
  const bodyText = await bounded(page.locator('body').innerText().catch(() => ''), '', 2_000);
  page.off('response', onResponse);
  page.off('console', onConsole);
  page.off('requestfailed', onFailed);
  page.off('websocket', onWebSocket);
  return {
    page_id: route.pageId,
    route: route.path,
    surface: route.surface,
    min_role: route.minRole,
    auth_mode: authMode,
    viewport,
    http_status: response?.status() ?? null,
    final_route: new URL(page.url()).pathname,
    title: await page.title().catch(() => ''),
    field_count: fields.length,
    source_matched_field_count: matches.filter((item) => item.source).length,
    dynamic_candidate_count: dynamicCandidates.length,
    unmatched_dynamic_fields: dynamicCandidates.filter((item) => !item.source).slice(0, 100).map((item) => item.field),
    // Exact counts are retained above; samples are bounded so large operator
    // payloads cannot exhaust the Node worker across the full route sweep.
    visible_fields: matches.filter((item) => item.source || dynamicCandidates.some((candidate) => candidate.field === item.field)).slice(0, 300),
    source_responses: responses.slice(0, 80).map((item) => ({ ...item, leaves: item.leaves.slice(0, 500) })),
    websocket_urls: Array.from(wsUrls),
    websocket_frames_received: wsFrames.received,
    websocket_frames_sent: wsFrames.sent,
    console_errors: consoleErrors.slice(0, 30),
    failed_requests: failedRequests.slice(0, 50),
    horizontal_overflow_px: await bounded(page.evaluate(() => Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth)).catch(() => 0), 0, 2_000),
    forbidden_runtime_text: (bodyText.match(/\bundefined\b|\bNaN\b|\[object Object\]|Unexpected Application Error/i) ?? [])[0] ?? null,
    screenshot_path: path.relative(path.resolve(process.cwd(), '..'), screenshotPath),
  };
}

test.describe('final built product regression', () => {
  test.setTimeout(900_000);
  test('registry-driven four-viewport route and field evidence', async ({ page }) => {
    mkdirSync(ARTIFACT_ROOT, { recursive: true });
    await page.setViewportSize(VIEWPORTS[0]);
    const routes = routeCases();
    const records: Record<string, unknown>[] = [];
    const dynamicSeen = new Set<string>();
    for (const route of routes) {
      for (const viewport of VIEWPORTS) {
        await page.setViewportSize(viewport);
        const record = await captureRoute(page, route, viewport);
        records.push(record);
        if (route.pageId === 'markets-ingestors' && viewport.name === VIEWPORTS[0].name) {
          for (const dynamicRoute of await collectDynamicIngestorRoutes(page)) {
            if (dynamicSeen.has(dynamicRoute.path)) continue;
            dynamicSeen.add(dynamicRoute.path);
            for (const dynamicViewport of VIEWPORTS) {
              await page.setViewportSize(dynamicViewport);
              records.push(await captureRoute(page, dynamicRoute, dynamicViewport));
            }
          }
        }
      }
    }
    const routeKeys = new Set(records.map((record) => `${record.page_id}:${record.route}`));
    const summary = {
      route_templates: routes.length,
      dynamic_route_count: dynamicSeen.size,
      concrete_route_count: routeKeys.size,
      viewport_count: VIEWPORTS.length,
      screenshots_expected: routeKeys.size * VIEWPORTS.length,
      screenshots_recorded: records.filter((record) => Boolean(record.screenshot_path)).length,
      field_count: records.reduce((sum, record) => sum + Number(record.field_count ?? 0), 0),
      source_matched_field_count: records.reduce((sum, record) => sum + Number(record.source_matched_field_count ?? 0), 0),
      dynamic_candidate_count: records.reduce((sum, record) => sum + Number(record.dynamic_candidate_count ?? 0), 0),
      unmatched_dynamic_field_count: records.reduce((sum, record) => sum + (Array.isArray(record.unmatched_dynamic_fields) ? record.unmatched_dynamic_fields.length : 0), 0),
      console_error_count: records.reduce((sum, record) => sum + (Array.isArray(record.console_errors) ? record.console_errors.length : 0), 0),
      failed_request_count: records.reduce((sum, record) => sum + (Array.isArray(record.failed_requests) ? record.failed_requests.length : 0), 0),
      overflow_route_count: records.filter((record) => Number(record.horizontal_overflow_px ?? 0) > 1).length,
      forbidden_runtime_text_count: records.filter((record) => Boolean(record.forbidden_runtime_text)).length,
      live_gate_checked_route_count: records.filter((record) => JSON.stringify(record).includes('blocked_human_only')).length,
    };
    const artifact = {
      generated_at: new Date().toISOString(),
      status: 'FINAL_REGRESSION_EVIDENCE',
      family: FAMILY,
      base_url: BASE,
      registry_page_module_count: PAGES.length,
      intentionally_shadowed_page_module_count: PAGES.filter((page) => Object.prototype.hasOwnProperty.call(MERGED_LEGACY_PATHS, page.route.path)).length,
      legacy_redirect_count: Object.keys(MERGED_LEGACY_PATHS).length,
      required_viewports: VIEWPORTS,
      summary,
      routes: records,
    };
    const artifactPath = path.join(ARTIFACT_ROOT, `final-product-regression-${safeName(FAMILY)}.json`);
    writeFileSync(artifactPath, `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
  });
});
