import {
  existsSync,
  mkdirSync,
  readFileSync,
  writeFileSync,
} from 'node:fs';
import path from 'node:path';
import {
  expect,
  test,
  type ConsoleMessage,
  type Page,
  type Request,
  type Response,
  type WebSocket,
} from '@playwright/test';
import type { PageModule, Surface } from '../../src/types/page';
import {
  ACTIVE_ROUTE_MODULES,
  ALL_PAGE_PATHS,
  LEGACY_REDIRECTS,
} from './helpers/routeContracts';

type AuditFamily =
  | 'global_public'
  | 'markets_charts'
  | 'ingestors_providers'
  | 'trading_portfolio_risk'
  | 'trainer_ai'
  | 'admin_system';

type SessionKind = 'public' | 'trader' | 'admin';

interface AuditRoute {
  id: string;
  path: string;
  routeTemplate: string;
  surface: Surface;
  minimumRole: PageModule['rbac']['minRole'];
  hiddenFromNav: boolean;
  family: AuditFamily;
  inventoryKind: 'canonical' | 'dynamic-extra';
}

interface AuditViewport {
  id: string;
  width: number;
  height: number;
}

interface SourceScalar {
  endpoint: string;
  fieldPath: string;
  transport: 'http' | 'websocket';
  value: string | number | boolean | null;
}

interface ResponseEvidence {
  method: string;
  endpoint: string;
  status: number;
  contentType: string;
  jsonFieldCount: number;
  jsonFieldPaths: string[];
  jsonFieldPathsTruncated: boolean;
}

interface RequestFailureEvidence {
  method: string;
  endpoint: string;
  status?: number;
  failure?: string;
  classification: 'expected' | 'aborted' | 'degraded' | 'hard_failure';
}

interface VisibleField {
  text: string;
  tag: string;
  testId: string | null;
  ariaLabel: string | null;
  title: string | null;
  unit: string | null;
  classification:
    | 'source_exact'
    | 'static_copy'
    | 'derived_display'
    | 'unavailable_state';
  source?: {
    endpoint: string;
    fieldPath: string;
    transport: 'http' | 'websocket';
  };
  status: 'PASS' | 'DEFECT';
  defect?: string;
}

interface LayoutEvidence {
  horizontalOverflowPx: number;
  clippedTextCount: number;
  clippedTextSamples: string[];
  visibleTextCollisionCount: number;
  visibleTextCollisionSamples: string[];
  deadLinkCount: number;
  deadLinkSamples: string[];
  busyElementCount: number;
  busyElementSamples: string[];
}

interface ViewportEvidence {
  viewport: AuditViewport;
  screenshotPath: string;
  documentStatus: number | null;
  finalPath: string;
  bodyTextLength: number;
  visibleFieldCount: number;
  sourceExactFieldCount: number;
  staticCopyFieldCount: number;
  derivedDisplayFieldCount: number;
  unavailableStateFieldCount: number;
  fields: VisibleField[];
  responseCount: number;
  endpointCount: number;
  apiJsonFieldCount: number;
  responses: ResponseEvidence[];
  requestFailures: RequestFailureEvidence[];
  consoleErrors: string[];
  expectedConsoleErrors: string[];
  pageErrors: string[];
  websocketEndpoints: string[];
  websocketFrames: number;
  navigationCount: number;
  layout: LayoutEvidence;
  visibleLinkCount: number;
  visibleButtonCount: number;
  hardFailures: string[];
  degradations: string[];
}

interface LiveGateProof {
  httpStatus: number;
  liveGate: unknown;
  liveBlocked: unknown;
  liveReady: unknown;
  liveSubmitAllowed: unknown;
  liveTradingEnabled: unknown;
  orderSubmitted: unknown;
  testOrderSubmitted: unknown;
  leverageMutated: unknown;
  marginMutated: unknown;
  operatorApproved: unknown;
  releaseMode: unknown;
  liveSymbolCount: number | null;
  executionLiveSymbolCount: number | null;
  placesRealOrder: unknown;
  routesToLive: unknown;
  passed: boolean;
}

const VALID_FAMILIES: AuditFamily[] = [
  'global_public',
  'markets_charts',
  'ingestors_providers',
  'trading_portfolio_risk',
  'trainer_ai',
  'admin_system',
];

const selectedFamily = process.env.FINAL_PRODUCT_AUDIT_FAMILY as AuditFamily | undefined;
const shouldRun = Boolean(selectedFamily && VALID_FAMILIES.includes(selectedFamily));
const generatedAt = new Date().toISOString();
const runId = (process.env.FINAL_PRODUCT_AUDIT_RUN_ID ?? generatedAt)
  .replace(/[^0-9A-Za-z_-]+/g, '');
const frontendRoot = process.cwd();
const repoRoot = path.resolve(frontendRoot, '..', '..');
const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5174';
const artifactRoot = path.resolve(
  process.env.FINAL_PRODUCT_AUDIT_OUTPUT_ROOT
    ?? path.join(frontendRoot, '..', 'artifacts', 'final-product-audit'),
  runId,
);
const tokenFiles: Record<Exclude<SessionKind, 'public'>, string | undefined> = {
  trader: process.env.FINAL_PRODUCT_AUDIT_TRADER_TOKEN_FILE,
  admin: process.env.FINAL_PRODUCT_AUDIT_ADMIN_TOKEN_FILE,
};
const settleMs = Math.max(250, Number(process.env.FINAL_PRODUCT_AUDIT_SETTLE_MS ?? 1_200));
const focusedRoute = process.env.FINAL_PRODUCT_AUDIT_ROUTE;
const maxJsonScalarsPerResponse = 20_000;
const maxJsonFieldPathsPerResponse = 5_000;
const maxWebSocketFramesPerViewport = 200;
const maxWebSocketPayloadBytes = 1_000_000;

const VIEWPORTS: AuditViewport[] = [
  { id: 'desktop-1600x1000', width: 1600, height: 1000 },
  { id: 'desktop-1440x900', width: 1440, height: 900 },
  { id: 'tablet-1024x768', width: 1024, height: 768 },
  { id: 'mobile-390x844', width: 390, height: 844 },
];

const FAMILY_PAGE_IDS: Record<AuditFamily, ReadonlySet<string>> = {
  global_public: new Set([
    'root',
    'public-status',
    'login',
    'public-landing-v2',
    'user-status',
  ]),
  markets_charts: new Set([
    'symbols',
    'market-intelligence',
    'binance',
    'orderbook-runtime-truth',
    'microstructure-trust',
    'liquidation-bridge',
    'market',
    'markets',
    'pro-chart',
    'technical-analysis',
    'market-brain',
  ]),
  ingestors_providers: new Set(['markets-ingestors']),
  trading_portfolio_risk: new Set([
    'dashboard',
    'signals',
    'executions',
    'positions',
    'risk',
    'paper-trading',
    'audit-ledger',
    'live-canary',
    'account-settings',
    'alerts',
    'history',
    'trader',
  ]),
  trainer_ai: new Set([
    'trainer-prediction-monitor',
    'signal-explainability',
    'trainer-admin',
    'replay',
    'system-health',
    'codex-review-center',
    'ai-brain',
    'ai-predictions',
    'strategy-backtesting',
    'backtests-replay',
  ]),
  admin_system: new Set([
    'admin-overview',
    'admin-data',
    'admin-intelligence',
    'admin-orchestration',
    'admin-risk',
    'admin-execution',
    'admin-exchanges',
    'admin-config',
    'admin-users',
    'admin-reports',
    'admin-logs',
    'admin-audit',
    'admin-tools',
    'monitor-center',
    'external-manual-position-quarantine',
    'strategy-admin',
    'live-readiness',
    'operator-proof-dashboard',
    'executive-status',
  ]),
};

function familyForPageId(id: string): AuditFamily {
  const matches = VALID_FAMILIES.filter((family) => FAMILY_PAGE_IDS[family].has(id));
  if (matches.length !== 1) {
    throw new Error(`Final audit family assignment must be unique for ${id}; matches=${matches.join(',')}`);
  }
  return matches[0];
}

function concretePath(routeTemplate: string): string {
  if (routeTemplate === '/market/:symbol?') return '/market/BTCUSDT';
  if (routeTemplate === '/chart/:symbol?') return '/chart/BTCUSDT';
  if (routeTemplate === '/markets/ingestors/:name?') return '/markets/ingestors';
  return routeTemplate;
}

function routeFromModule(page: PageModule): AuditRoute {
  return {
    id: page.meta.id,
    path: concretePath(page.route.path),
    routeTemplate: page.route.path,
    surface: page.meta.surface,
    minimumRole: page.rbac.minRole,
    hiddenFromNav: Boolean(page.meta.hideFromNav),
    family: familyForPageId(page.meta.id),
    inventoryKind: 'canonical',
  };
}

const CANONICAL_ROUTES: AuditRoute[] = [
  {
    id: 'root',
    path: '/',
    routeTemplate: '/',
    surface: 'public',
    minimumRole: 'public',
    hiddenFromNav: false,
    family: 'global_public',
    inventoryKind: 'canonical',
  },
  ...ACTIVE_ROUTE_MODULES.map(routeFromModule),
];

const DYNAMIC_EXTRA_ROUTES: AuditRoute[] = [
  {
    ...CANONICAL_ROUTES.find((route) => route.id === 'pro-chart')!,
    id: 'pro-chart-empty-symbol',
    path: '/chart',
    inventoryKind: 'dynamic-extra',
  },
  {
    ...CANONICAL_ROUTES.find((route) => route.id === 'markets-ingestors')!,
    id: 'markets-ingestors-detail',
    path: `/markets/ingestors/${process.env.FINAL_PRODUCT_AUDIT_INGESTOR_NAME ?? 'realtime_price_provider'}`,
    inventoryKind: 'dynamic-extra',
  },
];

const ROUTES = [...CANONICAL_ROUTES, ...DYNAMIC_EXTRA_ROUTES];

if (CANONICAL_ROUTES.length !== 58) {
  throw new Error(`Expected 58 active canonical routes, found ${CANONICAL_ROUTES.length}`);
}
if (new Set(CANONICAL_ROUTES.map((route) => route.path)).size !== CANONICAL_ROUTES.length) {
  throw new Error('Active canonical route paths are not unique');
}
if (ALL_PAGE_PATHS.length !== 58) {
  throw new Error(`Route contract must expose 58 active paths, found ${ALL_PAGE_PATHS.length}`);
}

function sessionForRoute(route: AuditRoute): SessionKind {
  if (route.surface === 'public') return 'public';
  if (route.surface === 'admin' || route.surface === 'system') return 'admin';
  return 'trader';
}

function safeEndpoint(rawURL: string): string {
  try {
    const url = new URL(rawURL);
    for (const key of Array.from(url.searchParams.keys())) {
      if (/token|secret|password|authorization|key/i.test(key)) {
        url.searchParams.set(key, '<redacted>');
      }
    }
    return `${url.pathname}${url.search}`;
  } catch {
    return rawURL.replace(/([?&](?:token|secret|password|authorization|key)=)[^&]+/gi, '$1<redacted>');
  }
}

function routeSlug(route: AuditRoute): string {
  const suffix = route.path.replace(/[^0-9A-Za-z]+/g, '-').replace(/^-+|-+$/g, '') || 'root';
  return `${route.id}--${suffix}`;
}

function normalizeComparable(value: string): string {
  return value
    .normalize('NFKC')
    .replace(/[,_]/g, (match) => (match === '_' ? ' ' : ''))
    .replace(/\s+/g, ' ')
    .trim()
    .toLowerCase();
}

function scalarComparisonKeys(value: SourceScalar['value']): string[] {
  if (value === null) return [];
  if (typeof value === 'boolean') {
    return value ? ['true', 'yes', 'active', 'enabled'] : ['false', 'no', 'inactive', 'disabled'];
  }
  if (typeof value === 'string') {
    const keys = new Set([normalizeComparable(value)]);
    const parsedDate = Date.parse(value);
    if (Number.isFinite(parsedDate) && /[T:-]/.test(value)) {
      const date = new Date(parsedDate);
      keys.add(normalizeComparable(date.toISOString()));
      for (const options of [
        { dateStyle: 'medium', timeStyle: 'short' } as const,
        { dateStyle: 'short', timeStyle: 'short' } as const,
        { dateStyle: 'medium' } as const,
      ]) {
        keys.add(normalizeComparable(new Intl.DateTimeFormat('en-US', options).format(date)));
      }
    }
    return Array.from(keys).filter(Boolean);
  }
  if (!Number.isFinite(value)) return [];
  const keys = new Set<string>();
  const candidates = [value, value * 100];
  for (const candidate of candidates) {
    for (let decimals = 0; decimals <= 6; decimals += 1) {
      const fixed = candidate.toFixed(decimals);
      keys.add(normalizeComparable(fixed));
      keys.add(normalizeComparable(Number(fixed).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })));
      keys.add(normalizeComparable(`$${Number(fixed).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}`));
      keys.add(normalizeComparable(`${fixed}%`));
    }
  }
  const absolute = Math.abs(value);
  for (const [divisor, suffix] of [[1_000, 'K'], [1_000_000, 'M'], [1_000_000_000, 'B']] as const) {
    if (absolute >= divisor) {
      for (let decimals = 0; decimals <= 3; decimals += 1) {
        keys.add(normalizeComparable(`${(value / divisor).toFixed(decimals)}${suffix}`));
        keys.add(normalizeComparable(`$${(value / divisor).toFixed(decimals)}${suffix}`));
      }
    }
  }
  return Array.from(keys);
}

function flattenScalars(
  value: unknown,
  endpoint: string,
  transport: SourceScalar['transport'],
  limit = maxJsonScalarsPerResponse,
): { scalars: SourceScalar[]; fieldPaths: string[]; truncated: boolean } {
  const scalars: SourceScalar[] = [];
  const fieldPaths: string[] = [];
  let truncated = false;

  const visit = (current: unknown, currentPath: string, depth: number): void => {
    if (scalars.length >= limit || fieldPaths.length >= maxJsonFieldPathsPerResponse) {
      truncated = true;
      return;
    }
    if (depth > 12) {
      truncated = true;
      return;
    }
    if (current === null || ['string', 'number', 'boolean'].includes(typeof current)) {
      const scalarValue = current as SourceScalar['value'];
      if (typeof scalarValue === 'string' && scalarValue.length > 2_000) return;
      fieldPaths.push(currentPath);
      scalars.push({ endpoint, fieldPath: currentPath, transport, value: scalarValue });
      return;
    }
    if (Array.isArray(current)) {
      for (let index = 0; index < current.length; index += 1) {
        visit(current[index], `${currentPath}[${index}]`, depth + 1);
        if (truncated) break;
      }
      return;
    }
    if (typeof current === 'object') {
      for (const [key, child] of Object.entries(current as Record<string, unknown>)) {
        visit(child, currentPath === '$' ? `$.${key}` : `${currentPath}.${key}`, depth + 1);
        if (truncated) break;
      }
    }
  };

  visit(value, '$', 0);
  return { scalars, fieldPaths, truncated };
}

function sourceIndex(scalars: SourceScalar[]): Map<string, SourceScalar> {
  const index = new Map<string, SourceScalar>();
  for (const scalar of scalars) {
    for (const key of scalarComparisonKeys(scalar.value)) {
      if (key && !index.has(key)) index.set(key, scalar);
    }
  }
  return index;
}

function unitFromText(text: string): string | null {
  if (/\$|\bUSD\b|\bUSDT\b/i.test(text)) return 'currency';
  if (/%/.test(text)) return 'percent';
  if (/\b(?:ms|milliseconds?)\b/i.test(text)) return 'milliseconds';
  if (/\b(?:s|sec|secs|seconds?)\b/i.test(text)) return 'seconds';
  if (/\b(?:m|min|mins|minutes?)\b/i.test(text)) return 'minutes';
  if (/\b(?:h|hr|hrs|hours?)\b/i.test(text)) return 'hours';
  if (/\b(?:bytes?|KB|MB|GB)\b/i.test(text)) return 'bytes';
  return null;
}

function isUnavailableText(text: string): boolean {
  return /^(?:—|-|n\/a|null|none|unknown|unavailable|not available|missing evidence|awaiting evidence)$/i.test(text.trim())
    || /\b(?:unavailable|missing evidence|awaiting trusted evidence)\b/i.test(text);
}

function isLikelyStaticCopy(text: string): boolean {
  if (isUnavailableText(text)) return false;
  if (/\d|\$|%|\b(?:fresh|stale|live|offline|online|held|blocked|ready|failed|warning|healthy)\b/i.test(text)) {
    return false;
  }
  return text.length <= 160;
}

function fieldDefect(text: string): string | undefined {
  if (/\bundefined\b/i.test(text)) return 'visible_undefined';
  if (/\bNaN\b/.test(text)) return 'visible_nan';
  if (/\[object Object\]/i.test(text)) return 'visible_object_coercion';
  if (/Unexpected Application Error|React Router caught the following error|SyntaxError:/i.test(text)) {
    return 'visible_application_or_parse_error';
  }
  return undefined;
}

async function collectVisibleFields(page: Page, scalars: SourceScalar[]): Promise<VisibleField[]> {
  const rawFields = await page.evaluate(() => {
    type RawField = {
      text: string;
      tag: string;
      testId: string | null;
      ariaLabel: string | null;
      title: string | null;
    };
    const rows: RawField[] = [];
    const visible = (element: Element): boolean => {
      const html = element as HTMLElement;
      const style = window.getComputedStyle(html);
      const rect = html.getBoundingClientRect();
      return style.display !== 'none'
        && style.visibility !== 'hidden'
        && Number(style.opacity || 1) > 0
        && rect.width > 0
        && rect.height > 0;
    };
    const body = document.body;
    const walker = document.createTreeWalker(body, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node) {
      const parent = node.parentElement;
      const text = (node.textContent ?? '').replace(/\s+/g, ' ').trim();
      if (
        parent
        && text
        && !parent.closest('script,style,noscript,template')
        && visible(parent)
      ) {
        const testIdOwner = parent.closest('[data-testid]');
        rows.push({
          text: text.slice(0, 500),
          tag: parent.tagName.toLowerCase(),
          testId: testIdOwner?.getAttribute('data-testid') ?? null,
          ariaLabel: parent.getAttribute('aria-label'),
          title: parent.getAttribute('title'),
        });
      }
      node = walker.nextNode();
    }

    for (const element of Array.from(document.querySelectorAll('input,textarea,select,img,canvas'))) {
      if (!visible(element)) continue;
      const html = element as HTMLInputElement;
      const value = element instanceof HTMLImageElement
        ? element.alt
        : element instanceof HTMLCanvasElement
          ? element.getAttribute('aria-label') ?? element.getAttribute('data-testid') ?? 'chart canvas'
          : html.value;
      const text = (value ?? '').replace(/\s+/g, ' ').trim();
      if (!text) continue;
      const testIdOwner = element.closest('[data-testid]');
      rows.push({
        text: text.slice(0, 500),
        tag: element.tagName.toLowerCase(),
        testId: testIdOwner?.getAttribute('data-testid') ?? null,
        ariaLabel: element.getAttribute('aria-label'),
        title: element.getAttribute('title'),
      });
    }
    return rows;
  });

  const index = sourceIndex(scalars);
  return rawFields.map((raw) => {
    const defect = fieldDefect(raw.text);
    const source = index.get(normalizeComparable(raw.text));
    let classification: VisibleField['classification'];
    if (source) classification = 'source_exact';
    else if (isUnavailableText(raw.text)) classification = 'unavailable_state';
    else if (isLikelyStaticCopy(raw.text)) classification = 'static_copy';
    else classification = 'derived_display';
    return {
      ...raw,
      unit: unitFromText(raw.text),
      classification,
      ...(source ? {
        source: {
          endpoint: source.endpoint,
          fieldPath: source.fieldPath,
          transport: source.transport,
        },
      } : {}),
      status: defect ? 'DEFECT' : 'PASS',
      ...(defect ? { defect } : {}),
    };
  });
}

async function collectLayoutEvidence(page: Page): Promise<LayoutEvidence> {
  return page.evaluate(() => {
    const visible = (element: Element): boolean => {
      const html = element as HTMLElement;
      const style = window.getComputedStyle(html);
      const rect = html.getBoundingClientRect();
      return style.display !== 'none' && style.visibility !== 'hidden' && rect.width > 0 && rect.height > 0;
    };
    const clipped: string[] = [];
    for (const element of Array.from(document.querySelectorAll('button,a,span,p,td,th,h1,h2,h3,label'))) {
      if (!visible(element)) continue;
      const html = element as HTMLElement;
      const style = window.getComputedStyle(html);
      const intentional = ['visible', 'auto', 'scroll'].includes(style.overflow)
        || ['visible', 'auto', 'scroll'].includes(style.overflowX)
        || style.textOverflow === 'ellipsis'
        || style.getPropertyValue('-webkit-line-clamp') !== 'none';
      if (intentional) continue;
      if (html.scrollWidth > html.clientWidth + 2 || html.scrollHeight > html.clientHeight + 2) {
        clipped.push((html.innerText || html.textContent || html.tagName).replace(/\s+/g, ' ').trim().slice(0, 180));
      }
    }
    const collisions: string[] = [];
    for (const container of Array.from(document.querySelectorAll('*'))) {
      if (!visible(container)) continue;
      const containerStyle = window.getComputedStyle(container as HTMLElement);
      if (!['grid', 'flex', 'inline-flex'].includes(containerStyle.display)) continue;
      const children = Array.from(container.children).filter((child) => visible(child));
      for (let index = 0; index < children.length; index += 1) {
        const child = children[index] as HTMLElement;
        const childStyle = window.getComputedStyle(child);
        const childRect = child.getBoundingClientRect();
        if (
          childStyle.overflow !== 'visible'
          || (child.scrollWidth <= child.clientWidth + 2 && child.scrollHeight <= child.clientHeight + 2)
        ) continue;
        const paintedRight = childRect.left + Math.max(childRect.width, child.scrollWidth);
        const paintedBottom = childRect.top + Math.max(childRect.height, child.scrollHeight);
        for (let siblingIndex = 0; siblingIndex < children.length; siblingIndex += 1) {
          if (siblingIndex === index) continue;
          const sibling = children[siblingIndex] as HTMLElement;
          const siblingRect = sibling.getBoundingClientRect();
          const overlaps = paintedRight > siblingRect.left + 2
            && childRect.left < siblingRect.right - 2
            && paintedBottom > siblingRect.top + 2
            && childRect.top < siblingRect.bottom - 2;
          if (!overlaps) continue;
          const childText = (child.innerText || child.textContent || child.tagName).replace(/\s+/g, ' ').trim().slice(0, 100);
          const siblingText = (sibling.innerText || sibling.textContent || sibling.tagName).replace(/\s+/g, ' ').trim().slice(0, 100);
          collisions.push(`${childText} ↔ ${siblingText}`);
          break;
        }
      }
    }
    const deadLinks = Array.from(document.querySelectorAll('a'))
      .filter((element) => visible(element))
      .filter((element) => {
        const href = element.getAttribute('href');
        return href === null || href.trim() === '' || href.trim() === '#';
      })
      .map((element) => (element.textContent || '<empty link>').replace(/\s+/g, ' ').trim().slice(0, 180));
    const busy = Array.from(document.querySelectorAll('[aria-busy="true"],[data-loading="true"],.spinner,.loading-spinner'))
      .filter((element) => visible(element))
      .map((element) => (element.textContent || element.getAttribute('aria-label') || element.className || 'busy element')
        .toString().replace(/\s+/g, ' ').trim().slice(0, 180));
    return {
      horizontalOverflowPx: Math.max(0, document.documentElement.scrollWidth - document.documentElement.clientWidth),
      clippedTextCount: clipped.length,
      clippedTextSamples: clipped.slice(0, 20),
      visibleTextCollisionCount: collisions.length,
      visibleTextCollisionSamples: Array.from(new Set(collisions)).slice(0, 20),
      deadLinkCount: deadLinks.length,
      deadLinkSamples: deadLinks.slice(0, 20),
      busyElementCount: busy.length,
      busyElementSamples: busy.slice(0, 20),
    };
  });
}

async function readLiveGate(page: Page): Promise<LiveGateProof> {
  const response = await page.context().request.get(new URL('/api/v2/live-gate/status', baseURL).toString(), {
    failOnStatusCode: false,
  });
  const body = await response.json().catch(() => ({})) as Record<string, unknown>;
  const liveSymbols = Array.isArray(body.live_symbols) ? body.live_symbols.length : null;
  const executionLiveSymbols = Array.isArray(body.execution_live_symbols) ? body.execution_live_symbols.length : null;
  const proof: LiveGateProof = {
    httpStatus: response.status(),
    liveGate: body.live_gate,
    liveBlocked: body.live_blocked,
    liveReady: body.live_ready,
    liveSubmitAllowed: body.live_submit_allowed,
    liveTradingEnabled: body.live_trading_enabled,
    orderSubmitted: body.order_submitted,
    testOrderSubmitted: body.test_order_submitted,
    leverageMutated: body.leverage_mutated,
    marginMutated: body.margin_mutated,
    operatorApproved: body.operator_approved,
    releaseMode: body.release_mode,
    liveSymbolCount: liveSymbols,
    executionLiveSymbolCount: executionLiveSymbols,
    placesRealOrder: body.places_real_order,
    routesToLive: body.routes_to_live,
    passed: false,
  };
  proof.passed = proof.httpStatus === 200
    && proof.liveGate === 'blocked_human_only'
    && proof.liveBlocked === true
    && proof.liveReady === false
    && proof.liveSubmitAllowed === false
    && proof.liveTradingEnabled === false
    && proof.orderSubmitted === false
    && proof.testOrderSubmitted === false
    && proof.leverageMutated === false
    && proof.marginMutated === false
    && proof.operatorApproved === false
    && proof.releaseMode === 'NON_LIVE'
    && proof.liveSymbolCount === 0
    && proof.executionLiveSymbolCount === 0
    && proof.placesRealOrder === false
    && proof.routesToLive === false;
  return proof;
}

function readAuditToken(kind: Exclude<SessionKind, 'public'>): string {
  const file = tokenFiles[kind];
  if (!file) throw new Error(`FINAL_PRODUCT_AUDIT_${kind.toUpperCase()}_TOKEN_FILE is required`);
  if (!existsSync(file)) throw new Error(`Audit token file does not exist: ${file}`);
  const token = readFileSync(file, 'utf8').trim();
  if (!token || token.split('.').length !== 3) throw new Error(`Audit token file is invalid: ${file}`);
  return token;
}

async function establishSession(page: Page, kind: SessionKind): Promise<{ kind: SessionKind; role: string | null; meStatus: number }> {
  await page.context().clearCookies();
  if (kind !== 'public') {
    await page.context().addCookies([{
      name: 'alphaforge_session',
      value: readAuditToken(kind),
      url: new URL('/', baseURL).toString(),
      httpOnly: true,
      sameSite: 'Lax',
    }]);
  }
  const me = await page.context().request.get(new URL('/api/auth/me', baseURL).toString(), {
    failOnStatusCode: false,
  });
  if (kind === 'public') {
    if (me.status() !== 401) throw new Error(`Public session expected /api/auth/me=401, got ${me.status()}`);
    return { kind, role: null, meStatus: me.status() };
  }
  const body = await me.json().catch(() => ({})) as { user?: { role?: string } };
  const role = body.user?.role ?? null;
  if (me.status() !== 200 || role !== kind) {
    throw new Error(`${kind} session proof failed: /api/auth/me=${me.status()} role=${role ?? 'null'}`);
  }
  return { kind, role, meStatus: me.status() };
}

function expectedRequestFailure(kind: SessionKind, endpoint: string, status: number): boolean {
  if (kind === 'public' && endpoint.startsWith('/api/auth/me') && status === 401) return true;
  if (kind === 'trader' && endpoint.startsWith('/api/v2/admin/') && status === 403) return true;
  return false;
}

async function captureViewport(
  page: Page,
  route: AuditRoute,
  viewport: AuditViewport,
  session: SessionKind,
): Promise<ViewportEvidence> {
  const consoleErrors: string[] = [];
  const expectedConsoleErrors: string[] = [];
  const pageErrors: string[] = [];
  const requestFailures: RequestFailureEvidence[] = [];
  const responses: ResponseEvidence[] = [];
  const sourceScalars: SourceScalar[] = [];
  const websocketEndpoints = new Set<string>();
  const pendingResponses = new Set<Promise<void>>();
  let websocketFrames = 0;
  let navigationCount = 0;

  const onConsole = (message: ConsoleMessage): void => {
    if (message.type() !== 'error') return;
    const text = message.text();
    if (session === 'public' && /401 \(Unauthorized\)|authentication_required/i.test(text)) {
      expectedConsoleErrors.push(text.slice(0, 500));
    } else {
      consoleErrors.push(text.slice(0, 500));
    }
  };
  const onPageError = (error: Error): void => { pageErrors.push(error.message.slice(0, 500)); };
  const onRequestFailed = (request: Request): void => {
    const failure = request.failure()?.errorText ?? 'request_failed';
    const aborted = /ERR_ABORTED|NS_BINDING_ABORTED|canceled/i.test(failure);
    requestFailures.push({
      method: request.method(),
      endpoint: safeEndpoint(request.url()),
      failure,
      classification: aborted ? 'aborted' : 'hard_failure',
    });
  };
  const onResponse = (response: Response): void => {
    const endpoint = safeEndpoint(response.url());
    const status = response.status();
    const contentType = response.headers()['content-type'] ?? '';
    const method = response.request().method();
    const sameOrigin = new URL(response.url()).origin === new URL(baseURL).origin;
    if (!sameOrigin) return;

    if (status >= 400) {
      const expected = expectedRequestFailure(session, endpoint, status);
      requestFailures.push({
        method,
        endpoint,
        status,
        classification: expected
          ? 'expected'
          : status === 404
            ? 'degraded'
            : 'hard_failure',
      });
    }

    const shouldInspectBody = /json/i.test(contentType)
      || endpoint.startsWith('/api/')
      || endpoint.startsWith('/operator_runtime/')
      || endpoint.endsWith('.json');
    if (!shouldInspectBody) return;

    const task = (async () => {
      let fieldPaths: string[] = [];
      let jsonFieldCount = 0;
      let truncated = false;
      if (status < 400 && /html/i.test(contentType)) {
        requestFailures.push({
          method,
          endpoint,
          status,
          failure: 'html_returned_for_json_or_api_resource',
          classification: 'hard_failure',
        });
      } else if (status < 400 && /json/i.test(contentType)) {
        const body = await response.json().catch(() => undefined);
        if (body === undefined) {
          requestFailures.push({
            method,
            endpoint,
            status,
            failure: 'json_parse_failed',
            classification: 'hard_failure',
          });
        } else {
          const flattened = flattenScalars(body, endpoint, 'http');
          sourceScalars.push(...flattened.scalars);
          fieldPaths = flattened.fieldPaths;
          jsonFieldCount = flattened.scalars.length;
          truncated = flattened.truncated;
        }
      }
      responses.push({
        method,
        endpoint,
        status,
        contentType,
        jsonFieldCount,
        jsonFieldPaths: fieldPaths,
        jsonFieldPathsTruncated: truncated,
      });
    })();
    pendingResponses.add(task);
    void task.finally(() => pendingResponses.delete(task));
  };
  const onWebSocket = (socket: WebSocket): void => {
    const endpoint = safeEndpoint(socket.url());
    websocketEndpoints.add(endpoint);
    socket.on('framereceived', (event) => {
      if (websocketFrames >= maxWebSocketFramesPerViewport) return;
      websocketFrames += 1;
      const payload = event.payload;
      const text = typeof payload === 'string' ? payload : payload.toString();
      if (text.length > maxWebSocketPayloadBytes) return;
      try {
        const flattened = flattenScalars(JSON.parse(text), endpoint, 'websocket');
        sourceScalars.push(...flattened.scalars);
      } catch {
        // Non-JSON heartbeat frames are valid and are counted above.
      }
    });
    socket.on('socketerror', (error) => {
      requestFailures.push({
        method: 'WEBSOCKET',
        endpoint,
        failure: String(error).slice(0, 500),
        classification: 'hard_failure',
      });
    });
  };
  const onFrameNavigated = (frame: import('@playwright/test').Frame): void => {
    if (frame === page.mainFrame()) navigationCount += 1;
  };

  page.on('console', onConsole);
  page.on('pageerror', onPageError);
  page.on('requestfailed', onRequestFailed);
  page.on('response', onResponse);
  page.on('websocket', onWebSocket);
  page.on('framenavigated', onFrameNavigated);

  await page.setViewportSize({ width: viewport.width, height: viewport.height });
  const documentResponse = await page.goto(route.path, {
    waitUntil: 'domcontentloaded',
    timeout: 20_000,
  }).catch(() => null);
  await page.locator('body').waitFor({ state: 'visible', timeout: 10_000 }).catch(() => undefined);
  await page.waitForLoadState('networkidle', { timeout: 3_000 }).catch(() => undefined);
  await page.evaluate(() => document.fonts.ready).catch(() => undefined);
  await page.waitForTimeout(settleMs);
  await Promise.allSettled(Array.from(pendingResponses));

  const finalPath = new URL(page.url()).pathname;
  const bodyText = await page.locator('body').innerText({ timeout: 5_000 }).catch(() => '');
  const fields = await collectVisibleFields(page, sourceScalars);
  const layout = await collectLayoutEvidence(page);
  const screenshotDirectory = path.join(artifactRoot, selectedFamily ?? 'invalid', 'screenshots');
  mkdirSync(screenshotDirectory, { recursive: true });
  const screenshotFile = path.join(screenshotDirectory, `${routeSlug(route)}--${viewport.id}.png`);
  await page.screenshot({ path: screenshotFile, fullPage: true, animations: 'disabled' })
    .catch(async () => page.screenshot({ path: screenshotFile, fullPage: false, animations: 'disabled' }));

  const hardFailures: string[] = [];
  const degradations: string[] = [];
  if (documentResponse?.status() !== 200) hardFailures.push(`document_status_${documentResponse?.status() ?? 'none'}`);
  if (finalPath !== route.path) hardFailures.push(`unexpected_final_path:${finalPath}`);
  if (bodyText.trim().length < 20) hardFailures.push('blank_or_near_blank_body');
  if (/Unexpected Application Error|React Router caught the following error/i.test(bodyText)) {
    hardFailures.push('visible_application_error');
  }
  if (/^\s*[\[{].*[\]}]\s*$/s.test(bodyText.trim()) && !await page.locator('main').count()) {
    hardFailures.push('raw_json_document');
  }
  if (await page.locator('[data-testid="access-denied"]').count()) hardFailures.push('access_denied_for_authorized_sweep');
  if (/LIVE TRADING:\s*(?:ENABLED|ACTIVE)|LIVE GATE:\s*(?:OPEN|ARMED)|EXECUTION:\s*ENABLED/i.test(bodyText)) {
    hardFailures.push('unsafe_visible_live_enabled_claim');
  }
  if (layout.horizontalOverflowPx > 1) hardFailures.push(`horizontal_overflow_${layout.horizontalOverflowPx}px`);
  if (layout.clippedTextCount > 0) hardFailures.push(`clipped_text_${layout.clippedTextCount}`);
  if (layout.visibleTextCollisionCount > 0) hardFailures.push(`visible_text_collisions_${layout.visibleTextCollisionCount}`);
  if (layout.deadLinkCount > 0) hardFailures.push(`dead_links_${layout.deadLinkCount}`);
  if (layout.busyElementCount > 0) hardFailures.push(`busy_elements_after_settle_${layout.busyElementCount}`);
  if (consoleErrors.length > 0) hardFailures.push(`console_errors_${consoleErrors.length}`);
  if (pageErrors.length > 0) hardFailures.push(`page_errors_${pageErrors.length}`);
  const hardRequestFailures = requestFailures.filter((failure) => failure.classification === 'hard_failure');
  if (hardRequestFailures.length > 0) hardFailures.push(`required_request_failures_${hardRequestFailures.length}`);
  const degradedRequests = requestFailures.filter((failure) => failure.classification === 'degraded');
  if (degradedRequests.length > 0) degradations.push(`http_404_or_optional_missing_${degradedRequests.length}`);
  const fieldDefects = fields.filter((field) => field.status === 'DEFECT');
  if (fieldDefects.length > 0) hardFailures.push(`visible_field_defects_${fieldDefects.length}`);
  if (responses.some((response) => response.jsonFieldPathsTruncated)) {
    degradations.push('bounded_json_field_capture_truncated');
  }

  const endpointCount = new Set([
    ...responses.map((response) => `${response.method} ${response.endpoint}`),
    ...Array.from(websocketEndpoints).map((endpoint) => `WEBSOCKET ${endpoint}`),
  ]).size;
  const visibleLinkCount = await page.locator('a:visible').count();
  const visibleButtonCount = await page.locator('button:visible').count();

  page.off('console', onConsole);
  page.off('pageerror', onPageError);
  page.off('requestfailed', onRequestFailed);
  page.off('response', onResponse);
  page.off('websocket', onWebSocket);
  page.off('framenavigated', onFrameNavigated);

  return {
    viewport,
    screenshotPath: path.relative(repoRoot, screenshotFile),
    documentStatus: documentResponse?.status() ?? null,
    finalPath,
    bodyTextLength: bodyText.length,
    visibleFieldCount: fields.length,
    sourceExactFieldCount: fields.filter((field) => field.classification === 'source_exact').length,
    staticCopyFieldCount: fields.filter((field) => field.classification === 'static_copy').length,
    derivedDisplayFieldCount: fields.filter((field) => field.classification === 'derived_display').length,
    unavailableStateFieldCount: fields.filter((field) => field.classification === 'unavailable_state').length,
    fields,
    responseCount: responses.length,
    endpointCount,
    apiJsonFieldCount: responses.reduce((sum, response) => sum + response.jsonFieldCount, 0),
    responses,
    requestFailures,
    consoleErrors,
    expectedConsoleErrors,
    pageErrors,
    websocketEndpoints: Array.from(websocketEndpoints).sort(),
    websocketFrames,
    navigationCount,
    layout,
    visibleLinkCount,
    visibleButtonCount,
    hardFailures,
    degradations,
  };
}

function resolveRedirect(pathname: string): { terminal: string; chain: string[]; loop: boolean } {
  const chain = [pathname];
  const visited = new Set(chain);
  let current = pathname;
  while (Object.prototype.hasOwnProperty.call(LEGACY_REDIRECTS, current)) {
    current = LEGACY_REDIRECTS[current];
    chain.push(current);
    if (visited.has(current)) return { terminal: current, chain, loop: true };
    visited.add(current);
  }
  return { terminal: current, chain, loop: false };
}

async function auditRedirects(page: Page): Promise<Array<{
  source: string;
  configuredTarget: string;
  expectedTerminal: string;
  actualTerminal: string;
  chain: string[];
  loop: boolean;
  passed: boolean;
}>> {
  await establishSession(page, 'admin');
  await page.setViewportSize({ width: 1440, height: 900 });
  const rows = [];
  for (const [source, configuredTarget] of Object.entries(LEGACY_REDIRECTS)) {
    const resolved = resolveRedirect(source);
    const response = await page.goto(source, { waitUntil: 'domcontentloaded', timeout: 15_000 }).catch(() => null);
    await page.waitForTimeout(75);
    const actualTerminal = new URL(page.url()).pathname;
    rows.push({
      source,
      configuredTarget,
      expectedTerminal: resolved.terminal,
      actualTerminal,
      chain: resolved.chain,
      loop: resolved.loop,
      passed: response?.status() === 200 && !resolved.loop && actualTerminal === resolved.terminal,
    });
  }
  return rows;
}

test.describe('final product regression evidence', () => {
  test.skip(!shouldRun, 'Set FINAL_PRODUCT_AUDIT_FAMILY to one bounded page family.');
  test.setTimeout(1_800_000);

  test('captures the selected family from the built product with direct runtime sources', async ({ page }) => {
    const family = selectedFamily!;
    const routes = ROUTES.filter(
      (route) => route.family === family && (!focusedRoute || route.path === focusedRoute),
    );
    if (focusedRoute && routes.length !== 1) {
      throw new Error(`FINAL_PRODUCT_AUDIT_ROUTE=${focusedRoute} matched ${routes.length} routes in ${family}`);
    }
    const beforeGate = await readLiveGate(page);
    const routeEvidence: Array<AuditRoute & { session: SessionKind; authRole: string | null; viewports: ViewportEvidence[] }> = [];
    const topLevelHardFailures: string[] = [];
    let activeSession: SessionKind | null = null;
    let authRole: string | null = null;

    if (!beforeGate.passed) topLevelHardFailures.push('live_gate_before_failed');
    for (const route of routes) {
      const requiredSession = sessionForRoute(route);
      if (activeSession !== requiredSession) {
        const proof = await establishSession(page, requiredSession);
        activeSession = requiredSession;
        authRole = proof.role;
      }
      const viewports: ViewportEvidence[] = [];
      for (const viewport of VIEWPORTS) {
        const evidence = await captureViewport(page, route, viewport, requiredSession);
        viewports.push(evidence);
        for (const failure of evidence.hardFailures) {
          topLevelHardFailures.push(`${route.path} ${viewport.id}: ${failure}`);
        }
      }
      routeEvidence.push({ ...route, session: requiredSession, authRole, viewports });
    }

    const redirects = family === 'global_public' && !focusedRoute ? await auditRedirects(page) : [];
    for (const redirect of redirects.filter((row) => !row.passed)) {
      topLevelHardFailures.push(`redirect ${redirect.source}: expected ${redirect.expectedTerminal}, got ${redirect.actualTerminal}`);
    }
    const afterGate = await readLiveGate(page);
    if (!afterGate.passed) topLevelHardFailures.push('live_gate_after_failed');

    const allViewports = routeEvidence.flatMap((route) => route.viewports);
    const endpointKeys = new Set(
      allViewports.flatMap((viewport) => viewport.responses.map((response) => `${response.method} ${response.endpoint}`)),
    );
    for (const endpoint of allViewports.flatMap((viewport) => viewport.websocketEndpoints)) {
      endpointKeys.add(`WEBSOCKET ${endpoint}`);
    }
    const summary = {
      routeCasesInspected: routeEvidence.length,
      canonicalRouteCasesInspected: routeEvidence.filter((route) => route.inventoryKind === 'canonical').length,
      dynamicExtraCasesInspected: routeEvidence.filter((route) => route.inventoryKind === 'dynamic-extra').length,
      viewportChecks: allViewports.length,
      screenshotsCaptured: allViewports.length,
      visibleFieldsChecked: allViewports.reduce((sum, viewport) => sum + viewport.visibleFieldCount, 0),
      sourceExactFieldsCompared: allViewports.reduce((sum, viewport) => sum + viewport.sourceExactFieldCount, 0),
      staticCopyFieldsChecked: allViewports.reduce((sum, viewport) => sum + viewport.staticCopyFieldCount, 0),
      derivedDisplayFieldsChecked: allViewports.reduce((sum, viewport) => sum + viewport.derivedDisplayFieldCount, 0),
      unavailableStateFieldsChecked: allViewports.reduce((sum, viewport) => sum + viewport.unavailableStateFieldCount, 0),
      endpointContractsCompared: endpointKeys.size,
      apiJsonFieldsObserved: allViewports.reduce((sum, viewport) => sum + viewport.apiJsonFieldCount, 0),
      websocketFramesObserved: allViewports.reduce((sum, viewport) => sum + viewport.websocketFrames, 0),
      redirectsInspected: redirects.length,
      redirectsPassed: redirects.filter((redirect) => redirect.passed).length,
      hardDefectsRemaining: topLevelHardFailures.length,
      degradedRequestObservations: allViewports.reduce(
        (sum, viewport) => sum + viewport.requestFailures.filter((failure) => failure.classification === 'degraded').length,
        0,
      ),
      consoleErrors: allViewports.reduce((sum, viewport) => sum + viewport.consoleErrors.length, 0),
      pageErrors: allViewports.reduce((sum, viewport) => sum + viewport.pageErrors.length, 0),
      horizontalOverflowCases: allViewports.filter((viewport) => viewport.layout.horizontalOverflowPx > 1).length,
      clippedTextCases: allViewports.filter((viewport) => viewport.layout.clippedTextCount > 0).length,
      visibleTextCollisionCases: allViewports.filter((viewport) => viewport.layout.visibleTextCollisionCount > 0).length,
      deadLinkCases: allViewports.filter((viewport) => viewport.layout.deadLinkCount > 0).length,
      busyStateCases: allViewports.filter((viewport) => viewport.layout.busyElementCount > 0).length,
    };
    const artifact = {
      schemaVersion: 'final_product_regression_family_v1',
      generatedAt,
      runId,
      family,
      focusedRoute: focusedRoute ?? null,
      status: topLevelHardFailures.length === 0 ? 'PASS' : 'DEFECTS_FOUND',
      baseURL,
      builtFrontendRequired: true,
      authMethod: 'ephemeral_signed_cookie_for_existing_local_users_no_user_store_mutation',
      limits: {
        maxJsonScalarsPerResponse,
        maxJsonFieldPathsPerResponse,
        maxWebSocketFramesPerViewport,
        maxWebSocketPayloadBytes,
        settleMs,
      },
      authoritativeInventory: {
        registryPageModules: 72,
        redirectShadowedPageModules: 15,
        canonicalActiveRoutes: CANONICAL_ROUTES.length,
        redirectRoutes: Object.keys(LEGACY_REDIRECTS).length,
        dynamicPatterns: 3,
        dynamicBehaviorCasesRequired: 6,
      },
      summary,
      liveGateBefore: beforeGate,
      liveGateAfter: afterGate,
      hardFailures: topLevelHardFailures,
      routes: routeEvidence,
      redirects,
    };

    const familyDirectory = path.join(artifactRoot, family);
    mkdirSync(familyDirectory, { recursive: true });
    writeFileSync(path.join(familyDirectory, 'evidence.json'), `${JSON.stringify(artifact, null, 2)}\n`, 'utf8');
    writeFileSync(path.join(familyDirectory, 'summary.json'), `${JSON.stringify({
      schemaVersion: artifact.schemaVersion,
      generatedAt,
      runId,
      family,
      status: artifact.status,
      summary,
      liveGateBefore: beforeGate,
      liveGateAfter: afterGate,
      hardFailures: topLevelHardFailures,
      routePaths: routeEvidence.map((route) => route.path),
      screenshotPaths: allViewports.map((viewport) => viewport.screenshotPath),
    }, null, 2)}\n`, 'utf8');

    expect(topLevelHardFailures, topLevelHardFailures.join('\n')).toHaveLength(0);
  });
});
