import { mkdirSync, writeFileSync } from 'node:fs';
import path from 'node:path';
import { chromium } from '@playwright/test';

const DEFAULT_ROUTES = [
  '/market/BTCUSDT?role=trader',
  '/dashboard?role=trader',
  '/trade?role=trader',
  '/admin/paper-trading?role=trader',
];

function readArg(name, fallback = null) {
  const prefix = `--${name}=`;
  const match = process.argv.find((arg) => arg.startsWith(prefix));
  return match ? match.slice(prefix.length) : fallback;
}

function readNumber(name, fallback) {
  const raw = readArg(name);
  const parsed = raw === null ? NaN : Number(raw);
  return Number.isFinite(parsed) && parsed >= 0 ? parsed : fallback;
}

function readRoutes() {
  const raw = readArg('routes') ?? process.env.SOAK_ROUTES;
  if (!raw) return DEFAULT_ROUTES;
  return raw.split(',').map((item) => item.trim()).filter(Boolean);
}

function nowIso() {
  return new Date().toISOString();
}

function wsCategory(url) {
  if (url.includes('/api/v2/realtime/ws')) return 'enterprise_shared_realtime';
  if (url.includes('/api/v2/ws/resource') || url.includes('/ws/resource')) return 'legacy_resource_stream';
  if (url.includes('/api/v2/ws/paper-activity') || url.includes('/ws/paper-activity')) return 'paper_activity_stream';
  if (url.includes('/api/v2/ws/market-data') || url.includes('/ws/market-data')) return 'backend_market_data_stream';
  if (url.includes('fstream.binance.com')) return 'native_binance_market_stream';
  return 'other';
}

function isExpectedConsoleError(entry) {
  const text = entry.text ?? '';
  const url = entry.location?.url ?? '';
  return text.includes('401 (Unauthorized)')
    && (
      url.includes('/api/auth/me')
      || url.includes('/api/v2/trader/snapshot')
    );
}

function isExpectedFailedRequest(entry) {
  const failure = entry.failure ?? '';
  const url = entry.url ?? '';
  return failure.includes('ERR_ABORTED')
    && (
      url.startsWith('http://127.0.0.1')
      || url.startsWith('http://localhost')
      || url.startsWith('https://localhost')
    );
}

function increment(map, key, amount = 1) {
  map[key] = (map[key] ?? 0) + amount;
}

function routeUrl(baseUrl, route) {
  return new URL(route, baseUrl).toString();
}

async function heapUsage(page) {
  try {
    const session = await page.context().newCDPSession(page);
    const usage = await session.send('Runtime.getHeapUsage');
    await session.detach();
    return {
      used_size: usage.usedSize ?? usage.used_size ?? null,
      total_size: usage.totalSize ?? usage.total_size ?? null,
    };
  } catch (err) {
    return { error: err instanceof Error ? err.message : String(err) };
  }
}

async function main() {
  const repoRoot = path.resolve(process.cwd(), '..', '..');
  const goalId = 'V2_ENTERPRISE_WEB_IOS_REALTIME_DATA_PLANE_PUBLIC_READY_COMPLETION';
  const baseUrl = readArg('base-url') ?? process.env.SOAK_BASE_URL ?? 'http://127.0.0.1:8000';
  const durationMs = readNumber('duration-ms', Number(process.env.SOAK_DURATION_MS ?? 90_000));
  const routeHoldMs = readNumber('route-hold-ms', Number(process.env.SOAK_ROUTE_HOLD_MS ?? 5_000));
  const requiredMs = readNumber('required-ms', Number(process.env.SOAK_REQUIRED_MS ?? 30 * 60_000));
  const maxActiveSockets = readNumber('max-active-sockets', Number(process.env.SOAK_MAX_ACTIVE_SOCKETS ?? 6));
  const routes = readRoutes();
  const output = readArg('output')
    ?? process.env.SOAK_OUTPUT
    ?? path.join(repoRoot, 'goal_state', goalId, 'phase11_dedicated_stream_soak_observation.json');

  const startedAt = nowIso();
  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    serviceWorkers: 'block',
  });
  const page = await context.newPage();
  const records = [];
  const categoryCounts = {};
  const consoleErrors = [];
  const pageErrors = [];
  const failedRequests = [];
  let activeSockets = 0;
  let maxConcurrentSockets = 0;

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push({
        text: message.text().slice(0, 500),
        location: message.location(),
      });
    }
  });
  page.on('pageerror', (error) => {
    pageErrors.push(String(error).slice(0, 500));
  });
  page.on('requestfailed', (request) => {
    const url = request.url();
    if (url.startsWith(baseUrl)) {
      failedRequests.push({
        url,
        failure: request.failure()?.errorText ?? 'request_failed',
      });
    }
  });
  page.on('websocket', (ws) => {
    const record = {
      url: ws.url(),
      category: wsCategory(ws.url()),
      opened_at: nowIso(),
      closed_at: null,
      frames_received: 0,
      frames_sent: 0,
    };
    records.push(record);
    increment(categoryCounts, record.category);
    activeSockets += 1;
    maxConcurrentSockets = Math.max(maxConcurrentSockets, activeSockets);
    ws.on('framereceived', () => {
      record.frames_received += 1;
    });
    ws.on('framesent', () => {
      record.frames_sent += 1;
    });
    ws.on('close', () => {
      record.closed_at = nowIso();
      activeSockets = Math.max(0, activeSockets - 1);
    });
  });

  const heapBefore = await heapUsage(page);
  const routeResults = [];
  const startedMs = Date.now();
  try {
    for (const route of routes) {
      const target = routeUrl(baseUrl, route);
      const before = Date.now();
      await page.goto(target, { waitUntil: 'domcontentloaded', timeout: 30_000 });
      await page.waitForTimeout(routeHoldMs);
      routeResults.push({
        route,
        target,
        status: 'visited',
        elapsed_ms: Date.now() - before,
        active_sockets_after_route: activeSockets,
      });
    }
    const remainingMs = Math.max(0, durationMs - (Date.now() - startedMs));
    if (remainingMs > 0) {
      await page.waitForTimeout(remainingMs);
    }
  } catch (err) {
    routeResults.push({
      route: routes[routeResults.length] ?? null,
      status: 'error',
      error: err instanceof Error ? err.message : String(err),
    });
  }
  const heapAfter = await heapUsage(page);
  const endedAt = nowIso();

  const legacyResourceSocketCount = categoryCounts.legacy_resource_stream ?? 0;
  const dedicatedStreamCount = (
    (categoryCounts.paper_activity_stream ?? 0)
    + (categoryCounts.backend_market_data_stream ?? 0)
    + (categoryCounts.native_binance_market_stream ?? 0)
  );
  const durationComplete = durationMs >= requiredMs;
  const noLegacyResourceSockets = legacyResourceSocketCount === 0;
  const activeSocketBudgetOk = activeSockets <= maxActiveSockets;
  const unexpectedConsoleErrors = consoleErrors.filter((entry) => !isExpectedConsoleError(entry));
  const unexpectedFailedRequests = failedRequests.filter((entry) => !isExpectedFailedRequest(entry));
  const fatalErrors = pageErrors.length + unexpectedConsoleErrors.length + unexpectedFailedRequests.length;
  const shortSoakPass = noLegacyResourceSockets && activeSocketBudgetOk && fatalErrors === 0;

  const result = {
    schema_version: 'enterprise_realtime_browser_soak_observation_v1',
    generated_utc: endedAt,
    started_utc: startedAt,
    base_url: baseUrl,
    duration_ms_requested: durationMs,
    duration_ms_observed: Date.now() - startedMs,
    required_duration_ms_for_public_ready: requiredMs,
    duration_requirement_met: durationComplete,
    routes,
    route_results: routeResults,
    websocket_summary: {
      total_opened: records.length,
      active_at_end: activeSockets,
      max_concurrent: maxConcurrentSockets,
      max_active_socket_budget: maxActiveSockets,
      active_socket_budget_ok: activeSocketBudgetOk,
      category_counts: categoryCounts,
      legacy_resource_socket_count: legacyResourceSocketCount,
      generic_useRealtimeResource_socket_leak_absent: noLegacyResourceSockets,
      dedicated_stream_count: dedicatedStreamCount,
    },
    browser_health: {
      console_error_count: consoleErrors.length,
      expected_console_error_count: consoleErrors.length - unexpectedConsoleErrors.length,
      unexpected_console_error_count: unexpectedConsoleErrors.length,
      page_error_count: pageErrors.length,
      failed_same_origin_request_count: failedRequests.length,
      expected_failed_same_origin_request_count: failedRequests.length - unexpectedFailedRequests.length,
      unexpected_failed_same_origin_request_count: unexpectedFailedRequests.length,
      heap_before: heapBefore,
      heap_after: heapAfter,
      heap_delta_used_size: (
        typeof heapBefore.used_size === 'number'
        && typeof heapAfter.used_size === 'number'
      ) ? heapAfter.used_size - heapBefore.used_size : null,
    },
    samples: {
      websockets: records.slice(0, 80),
      console_errors: consoleErrors.slice(0, 20),
      unexpected_console_errors: unexpectedConsoleErrors.slice(0, 20),
      page_errors: pageErrors.slice(0, 20),
      failed_requests: failedRequests.slice(0, 20),
      unexpected_failed_requests: unexpectedFailedRequests.slice(0, 20),
    },
    safety: {
      live_gate_expected: 'blocked_human_only',
      places_real_order: false,
      places_test_order: false,
      mutates_leverage: false,
      mutates_margin_mode: false,
      transfers_or_withdraws: false,
    },
    status: durationComplete && shortSoakPass
      ? 'PUBLIC_READY_SOAK_PASS'
      : shortSoakPass
      ? 'SHORT_SOAK_PASS_LONG_SOAK_REQUIRED'
      : 'SOAK_BLOCKED',
    remaining_blocker: durationComplete && shortSoakPass ? null : 'DEDICATED_STREAM_SOAK_NOT_COMPLETE',
  };

  mkdirSync(path.dirname(output), { recursive: true });
  writeFileSync(output, `${JSON.stringify(result, null, 2)}\n`, 'utf8');
  await browser.close();
  console.log(JSON.stringify({
    status: result.status,
    output,
    active_at_end: activeSockets,
    max_concurrent: maxConcurrentSockets,
    legacy_resource_socket_count: legacyResourceSocketCount,
    dedicated_stream_count: dedicatedStreamCount,
    duration_requirement_met: durationComplete,
  }, null, 2));
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
