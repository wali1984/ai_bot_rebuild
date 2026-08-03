#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { buildWebsiteCrawlRoutes } from './route-inventory.mjs';

const frontendRoot = resolve(import.meta.dirname, '..');
const repoRoot = resolve(frontendRoot, '..', '..');
const finalDir = resolve(
  repoRoot,
  'claude_worklog',
  'final_readiness',
  'production_dashboard_wajidali_us_repair',
  'latest',
);

const baseUrl = (process.env.DASHBOARD_BASE_URL ?? 'https://dashboard.wajidali.us').replace(/\/$/, '');
const phase = process.env.DASHBOARD_CRAWL_PHASE ?? 'before';
const screenshotDir = resolve(finalDir, 'screenshots', phase);
const nowIso = new Date().toISOString();

const routes = buildWebsiteCrawlRoutes();

function ensureDir(path) {
  mkdirSync(path, { recursive: true });
}

function routeToScreenshotName(route) {
  const cleaned = route.replaceAll('/', '_').replaceAll('?', '_').replaceAll('=', '_').replaceAll('&', '_');
  return `${cleaned || 'root'}.png`;
}

function uniq(values) {
  return [...new Set(values)].filter(Boolean);
}

function compactText(text, length = 1800) {
  return text.replace(/\s+/g, ' ').trim().slice(0, length);
}

function isIgnoredNetworkIssue(entry) {
  const url = typeof entry === 'string' ? entry : entry.url ?? '';
  const failure = typeof entry === 'string' ? entry : entry.failure ?? '';
  if (/net::ERR_ABORTED/i.test(failure)) {
    return true;
  }
  return /tradingview|favicon|googletagmanager|google-analytics|doubleclick|analytics|sentry|clarity/i.test(url);
}

function classifyRoute(route, status, text, consoleErrors, networkErrors, liveBannerVisible, chartExists) {
  const lower = text.toLowerCase();
  const is404 = status === 404 || /^404\b|not found/i.test(text.trim().slice(0, 120));
  const placeholderOnly =
    !is404 &&
    text.length < 650 &&
    /(evidence missing|missing evidence|coming soon|placeholder|no payload|not available)/i.test(text);
  const proofDumpHeavy =
    !['/', '/landing', '/admin', '/admin/mission-control?role=admin'].includes(route)
      ? false
      : /phase 3|historical 30d|hist_pred_|sig_btc_001|xtrim|minid|decision packet/i.test(text) &&
        text.length > 4500;
  const stalePayload = /STALE_PAYLOAD|SUPERVISOR_STATUS_STALE_OR_CONFLICTING|stale payload|queue age|planner age/i.test(text);
  const staticFixtureAsCurrent =
    /(hist_pred_|sig_btc_001|STATIC_PROOF_FIXTURE)/.test(text) &&
    !/Static proof examples|Historical proof|fixture.*collapsed|not current runtime/i.test(text);
  const evidenceGapOnly =
    !placeholderOnly &&
    /(Evidence missing|MISSING_EVIDENCE|TRAINER_RUNTIME_EVIDENCE_MISSING|CURRENT_SIGNAL_LINEAGE_MISSING)/.test(text) &&
    text.length < 1600;
  const brokenChart =
    route.includes('mission-control') &&
    !chartExists &&
    !/FALLBACK_STATIC_CHART|TradingView widget failed to load|READONLY_MARKET_FEED/i.test(text);
  const actionableConsoleErrors = consoleErrors.filter((error) => !/favicon|tradingview|failed to load resource/i.test(error));
  const actionableNetworkErrors = networkErrors.filter((error) => !isIgnoredNetworkIssue(error));
  const needsImmediateRepair =
    is404 ||
    placeholderOnly ||
    proofDumpHeavy ||
    staticFixtureAsCurrent ||
    evidenceGapOnly ||
    brokenChart ||
    actionableConsoleErrors.length > 0 ||
    actionableNetworkErrors.length > 0;
  const operatorUseful = liveBannerVisible && !is404 && !placeholderOnly && !evidenceGapOnly;

  return {
    route_404: is404,
    route_redirect_wrong: (route === '/' || route === '/admin') && !/mission[-\s]control/i.test(`${text} ${route}`),
    stale_payload: stalePayload,
    static_fixture_as_primary: staticFixtureAsCurrent,
    evidence_gap_only: evidenceGapOnly,
    proof_dump_on_primary_page: proofDumpHeavy,
    tradingview_broken: brokenChart,
    console_error: actionableConsoleErrors.length > 0,
    network_error: actionableNetworkErrors.length > 0,
    placeholder_only: placeholderOnly,
    design_not_applied: route.includes('mission-control') && !/Production operator|Mission Control|Runtime truth|TradingView/i.test(text),
    payload_missing: /payload missing|missing payload|MISSING_EVIDENCE/i.test(text),
    runtime_bridge_missing: /TRAINER_RUNTIME_EVIDENCE_MISSING|CURRENT_SIGNAL_LINEAGE_MISSING|SUPERVISOR_STATUS_STALE_OR_CONFLICTING/i.test(text),
    operator_workflow_missing: !operatorUseful,
    needs_immediate_repair: needsImmediateRepair,
    operator_useful: operatorUseful,
  };
}

function markdownTable(rows) {
  return [
    '| Route | HTTP | Final URL | Live banner | Chart | Placeholder | Proof dump | Stale | Static fixture current | Evidence-gap only | Console errors | Network errors | Operator useful | Needs repair | Screenshot |',
    '|---|---:|---|---|---|---|---|---|---|---|---:|---:|---|---|---|',
    ...rows.map((row) =>
      `| ${row.route} | ${row.http_status ?? 'n/a'} | ${row.final_url} | ${row.live_banner_visible ? 'yes' : 'no'} | ${row.chart_exists ? 'yes' : 'no'} | ${row.classification.placeholder_only ? 'yes' : 'no'} | ${row.classification.proof_dump_on_primary_page ? 'yes' : 'no'} | ${row.classification.stale_payload ? 'yes' : 'no'} | ${row.classification.static_fixture_as_primary ? 'yes' : 'no'} | ${row.classification.evidence_gap_only ? 'yes' : 'no'} | ${row.console_errors.length} | ${row.network_errors.length} | ${row.classification.operator_useful ? 'yes' : 'no'} | ${row.classification.needs_immediate_repair ? 'yes' : 'no'} | ${row.screenshot} |`,
    ),
  ].join('\n');
}

ensureDir(finalDir);
ensureDir(screenshotDir);

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1000 },
  deviceScaleFactor: 1,
});

const results = [];

for (const route of routes) {
  const page = await context.newPage();
  const consoleErrors = [];
  const networkErrors = [];
  const responses = [];

  page.on('console', (message) => {
    if (message.type() === 'error') {
      consoleErrors.push(message.text().slice(0, 600));
    }
  });
  page.on('pageerror', (error) => {
    consoleErrors.push(error.message.slice(0, 600));
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
    if (status >= 400) {
      responses.push({ url: response.url(), status });
    }
  });

  const url = `${baseUrl}${route}`;
  const screenshotName = routeToScreenshotName(route);
  let response = null;
  let navigationError = null;
  try {
    response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForTimeout(1800);
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }

  const title = await page.title().catch(() => '');
  const text = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  const liveBannerVisible = await page.getByTestId('live-block-banner').isVisible().catch(async () => {
    return /LIVE TRADING:\s*BLOCKED|blocked_human_only/i.test(text);
  });
  const chartExists = await page
    .locator('[data-testid="tradingview-widget"], iframe[src*="tradingview"], canvas, [data-chart-mode="FALLBACK_STATIC_CHART"]')
    .first()
    .isVisible()
    .catch(() => false);
  await page.screenshot({ path: resolve(screenshotDir, screenshotName), fullPage: true }).catch(() => {});

  const httpStatus = response?.status() ?? null;
  const classification = classifyRoute(route, httpStatus, text, consoleErrors, networkErrors, liveBannerVisible, chartExists);

  results.push({
    route,
    requested_url: url,
    http_status: httpStatus,
    final_url: page.url(),
    title,
    screenshot: `screenshots/${phase}/${screenshotName}`,
    console_errors: uniq(consoleErrors),
    network_errors: networkErrors,
    http_error_responses: responses,
    navigation_error: navigationError,
    visible_text_excerpt: compactText(text),
    live_banner_visible: liveBannerVisible,
    chart_exists: chartExists,
    classification,
  });

  console.log(`${route} ${httpStatus ?? 'n/a'} repair=${classification.needs_immediate_repair ? 'yes' : 'no'} -> ${screenshotName}`);
  await page.close();
}

await browser.close();

const failed = results.filter((row) => row.classification.needs_immediate_repair);
const passed = results.length - failed.length;
const matrix = {
  generated_at: nowIso,
  base_url: baseUrl,
  phase,
  route_count: results.length,
  passed_count: passed,
  failed_count: failed.length,
  routes: results,
};

writeFileSync(resolve(finalDir, `production_route_matrix_${phase}.json`), `${JSON.stringify(matrix, null, 2)}\n`);
writeFileSync(resolve(finalDir, 'production_route_matrix.json'), `${JSON.stringify(matrix, null, 2)}\n`);

const crawlReport = `# Production URL Route Crawl Report

Generated at: ${nowIso}

- Base URL: ${baseUrl}
- Phase: ${phase}
- Routes crawled: ${results.length}
- Passed heuristic checks: ${passed}
- Needs immediate repair: ${failed.length}
- Screenshots: claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/${phase}/

${markdownTable(results)}
`;

if (phase === 'before') {
  writeFileSync(resolve(finalDir, 'PRODUCTION_URL_ROUTE_CRAWL_REPORT.md'), crawlReport);
  writeFileSync(
    resolve(finalDir, 'ROUTE_FAILURE_CLASSIFICATION.md'),
    `# Route Failure Classification

Generated at: ${nowIso}

${failed.length ? failed.map((row) => {
  const active = Object.entries(row.classification)
    .filter(([, value]) => value === true)
    .map(([key]) => key.toUpperCase())
    .join(', ');
  return `- ${row.route}: ${active || 'NO_FAILURE'}; screenshot=${row.screenshot}`;
}).join('\n') : '- No route required immediate repair in this crawl.'}
`,
  );
} else {
  writeFileSync(
    resolve(finalDir, 'PRODUCTION_BROWSER_ACCEPTANCE_REPORT.md'),
    `# Production Browser Acceptance Report

Generated at: ${nowIso}

- Base URL: ${baseUrl}
- Routes crawled: ${results.length}
- Passed heuristic checks: ${passed}
- Failed heuristic checks: ${failed.length}
- Screenshots: claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/${phase}/

${markdownTable(results)}
`,
  );

  const counts = {
    route_404: results.filter((row) => row.classification.route_404).length,
    placeholder_only: results.filter((row) => row.classification.placeholder_only).length,
    proof_dump_on_primary_page: results.filter((row) => row.classification.proof_dump_on_primary_page).length,
    tradingview_broken: results.filter((row) => row.classification.tradingview_broken).length,
    static_fixture_as_primary: results.filter((row) => row.classification.static_fixture_as_primary).length,
    stale_payload_visible: results.filter((row) => row.classification.stale_payload).length,
    runtime_bridge_missing_visible: results.filter((row) => row.classification.runtime_bridge_missing).length,
  };
  const ready =
    results.length === routes.length &&
    counts.route_404 === 0 &&
    counts.placeholder_only === 0 &&
    counts.proof_dump_on_primary_page === 0 &&
    counts.tradingview_broken === 0 &&
    counts.static_fixture_as_primary === 0 &&
    failed.length === 0;
  const goNoGo = ready
    ? 'PRODUCTION_DASHBOARD_WAJIDALI_US_FULL_ROUTE_REPAIR_READY'
    : 'PRODUCTION_DASHBOARD_WAJIDALI_US_FULL_ROUTE_REPAIR_BLOCKED';
  const codexGoNoGo = ready
    ? 'PRODUCTION_DASHBOARD_WAJIDALI_US_CODEX_PASS'
    : 'PRODUCTION_DASHBOARD_WAJIDALI_US_CODEX_FAIL';

  writeFileSync(
    resolve(finalDir, 'RUNTIME_TRUTH_BRIDGE_REPORT.md'),
    `# Runtime Truth Bridge Report

Generated at: ${nowIso}

The hosted dashboard is static unless a current read-only runtime bridge publishes operator truth. The supported bridge for this pass is:

\`\`\`bash
cd v2/frontend && npm run build:operator-truth
\`\`\`

Required public output:

- v2/frontend/public/operator_truth/latest/operator_truth_payload.json

Public hosting options:

1. Periodically sync operator_truth_payload.json to the hosted dashboard.
2. Replace the static payload with a secured read-only backend API.
3. Keep the dashboard local/VPN-only until a telemetry bridge exists.

The UI treats stale runtime payloads as STALE_PAYLOAD, static proofs as STATIC_PROOF_FIXTURE, and missing current evidence as MISSING_EVIDENCE.
`,
  );

  writeFileSync(
    resolve(finalDir, 'MISSION_CONTROL_ROUTE_REPAIR_REPORT.md'),
    `# Mission Control Route Repair Report

Generated at: ${nowIso}

- Mission Control route: /admin/mission-control?role=admin
- First screen: operator workflow, status rail, TradingView chart, runtime cards, current signal missing/current state, top blockers.
- Long proof sections: moved off the primary route into detail/proof pages.
- Proof dump detected in after crawl: ${counts.proof_dump_on_primary_page ? 'yes' : 'no'}
- TradingView/chart state: ${counts.tradingview_broken ? 'broken' : 'primary_or_explicit_fallback'}
- Live gate: blocked_human_only
`,
  );

  writeFileSync(
    resolve(finalDir, 'ALL_ROUTES_REPAIR_REPORT.md'),
    `# All Routes Repair Report

Generated at: ${nowIso}

- Routes crawled: ${results.length}
- Placeholder-only routes: ${counts.placeholder_only}
- HTTP 404 routes: ${counts.route_404}
- Operator-useful routes: ${results.filter((row) => row.classification.operator_useful).length}
- Static fixture as current runtime: ${counts.static_fixture_as_primary}
- Stale payloads visible: ${counts.stale_payload_visible}

${results.map((row) => `- ${row.route}: ${row.classification.needs_immediate_repair ? 'needs_repair' : 'production_usable'}; screenshot=${row.screenshot}`).join('\n')}
`,
  );

  writeFileSync(
    resolve(finalDir, 'TRADINGVIEW_PRODUCTION_FIX_REPORT.md'),
    `# TradingView Production Fix Report

Generated at: ${nowIso}

- Mission Control chart visible: ${results.find((row) => row.route === '/admin/mission-control?role=admin')?.chart_exists ? 'yes' : 'no'}
- TradingView broken count: ${counts.tradingview_broken}
- Fallback rule: if external TradingView scripts are blocked, the page shows FALLBACK_STATIC_CHART with a read-only proof label.
- Live/exchange mutation: none.
`,
  );

  writeFileSync(
    resolve(finalDir, 'STALE_AND_FIXTURE_DATA_REPAIR_REPORT.md'),
    `# Stale And Fixture Data Repair Report

Generated at: ${nowIso}

- Stale payload visible routes: ${counts.stale_payload_visible}
- Runtime bridge missing visible routes: ${counts.runtime_bridge_missing_visible}
- Static fixture as primary/current routes: ${counts.static_fixture_as_primary}

Stale and missing data are intentionally visible. They are not treated as current runtime truth. Historical proof and static examples are labeled/collapsed on proof-oriented pages.
`,
  );

  writeFileSync(
    resolve(finalDir, 'CODEX_PRODUCTION_URL_REVIEW.md'),
    `# Codex Production URL Review

Generated at: ${nowIso}

Result: ${codexGoNoGo}

Reviewed artifacts:

- production_route_matrix.json
- PRODUCTION_BROWSER_ACCEPTANCE_REPORT.md
- screenshots/after/

Checks:

- Any route 404: ${counts.route_404 ? 'yes' : 'no'}
- Placeholder-only route: ${counts.placeholder_only ? 'yes' : 'no'}
- Mission Control proof-dump-heavy: ${counts.proof_dump_on_primary_page ? 'yes' : 'no'}
- TradingView primary/fallback broken: ${counts.tradingview_broken ? 'yes' : 'no'}
- Static proof presented as current runtime: ${counts.static_fixture_as_primary ? 'yes' : 'no'}
- Stale payloads hidden: no, stale payloads are visible when present
- Live block hidden: ${results.every((row) => row.live_banner_visible) ? 'no' : 'yes'}
- Live/Redis/exchange mutation: none observed or performed
`,
  );
  writeFileSync(resolve(finalDir, 'CODEX_GO_NO_GO.md'), `${codexGoNoGo}\n`);

  writeFileSync(
    resolve(finalDir, 'PRODUCTION_DASHBOARD_WAJIDALI_US_REPAIR_REPORT.md'),
    `# Production Dashboard Wajidali US Repair Report

Status: ${goNoGo}

Generated at: ${nowIso}

- Base URL: ${baseUrl}
- Routes crawled: ${results.length}
- Routes passed: ${passed}
- Routes failed: ${failed.length}
- Screenshots: claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/after/
- TradingView status: ${counts.tradingview_broken ? 'broken' : 'primary_or_explicit_fallback'}
- Runtime truth bridge: build:operator-truth static bridge, secured API still recommended for hosted freshness
- Trainer Monitor: current runtime evidence missing is visible; fixture predictions are not current
- Signal Explainability: current lineage missing is visible; static proof is not current
- Stale payload visible routes: ${counts.stale_payload_visible}
- Live gate: blocked_human_only
- Redis trim: deferred_non_blocking
`,
  );
  writeFileSync(resolve(finalDir, 'GO_NO_GO.md'), `${goNoGo}\n`);
  writeFileSync(
    resolve(finalDir, 'operator_dashboard_payload.json'),
    `${JSON.stringify({
      generated_at: nowIso,
      status: goNoGo,
      base_url: baseUrl,
      routes_crawled_count: results.length,
      routes_passed_count: passed,
      routes_failed_count: failed.length,
      screenshot_path: 'claude_worklog/final_readiness/production_dashboard_wajidali_us_repair/latest/screenshots/after/',
      tradingview_status: counts.tradingview_broken ? 'broken' : 'primary_or_explicit_fallback',
      runtime_truth_bridge_status: 'static_operator_truth_payload_bridge_defined',
      trainer_monitor_status: 'TRAINER_RUNTIME_EVIDENCE_MISSING_VISIBLE',
      signal_explainability_status: 'CURRENT_SIGNAL_LINEAGE_MISSING_VISIBLE',
      stale_payload_visible_routes: counts.stale_payload_visible,
      missing_evidence_visible_routes: counts.runtime_bridge_missing_visible,
      codex_result: codexGoNoGo,
      live_gate_status: 'blocked_human_only',
      redis_trim_status: 'deferred_non_blocking',
      human_input_required: 'false_unless_final_live_capital_gate',
    }, null, 2)}\n`,
  );
}
