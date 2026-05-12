#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { existsSync, mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

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

const routes = [
  '/',
  '/landing',
  '/admin',
  '/admin/mission-control?role=admin',
  '/admin/monitor-center?role=admin',
  '/admin/coverage-system-atlas?role=admin',
  '/admin/script-registry?role=admin',
  '/admin/trainer-prediction-monitor?role=admin',
  '/admin/signal-explainability?role=admin',
  '/admin/symbols?role=admin',
  '/admin/signals?role=admin',
  '/admin/executions?role=admin',
  '/admin/positions?role=admin',
  '/admin/risk-control?role=admin',
  '/admin/exchange-manager?role=admin',
  '/admin/external-manual-position-quarantine?role=admin',
  '/admin/config-admin?role=admin',
  '/admin/strategy-admin?role=admin',
  '/admin/trainer-admin?role=admin',
  '/admin/orchestrator-admin?role=admin',
  '/admin/execution-admin?role=admin',
  '/admin/paper-trading?role=admin',
  '/admin/replay?role=admin',
  '/admin/audit-ledger?role=admin',
  '/admin/system-health?role=admin',
  '/admin/live-readiness?role=admin',
  '/admin/claude-admin-ai?role=admin',
  '/admin/ollama-local-assistant?role=admin',
  '/admin/codex-review-center?role=admin',
  '/admin/build-validation-status?role=admin',
  '/admin/operator-proof-dashboard?role=admin',
  '/admin/mobile-iphone-readiness?role=admin',
];

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

function classifyRoute(route, status, text, consoleErrors, networkErrors, liveBannerVisible, chartExists) {
  const lower = text.toLowerCase();
  const is404 = status === 404 || lower.includes('error: http_404') || lower.includes('404');
  const placeholderOnly =
    !is404 &&
    text.length < 650 &&
    /(evidence missing|missing evidence|coming soon|placeholder|no payload|not available)/i.test(text);
  const proofDumpHeavy =
    route.includes('operator-proof-dashboard')
      ? false
      : /phase 3|redis memory|system atlas|historical 30d|proof artifact|xtrim|minid|decision packet/i.test(text) &&
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
  const needsImmediateRepair =
    is404 ||
    placeholderOnly ||
    proofDumpHeavy ||
    staticFixtureAsCurrent ||
    evidenceGapOnly ||
    brokenChart ||
    consoleErrors.length > 0 ||
    networkErrors.some((error) => !/tradingview|favicon|analytics|googletagmanager/i.test(error.url));
  const operatorUseful = liveBannerVisible && !is404 && !placeholderOnly && !evidenceGapOnly;

  return {
    route_404: is404,
    route_redirect_wrong: route === '/' && !/mission-control/.test(text) && !/mission-control/.test(route),
    stale_payload: stalePayload,
    static_fixture_as_primary: staticFixtureAsCurrent,
    evidence_gap_only: evidenceGapOnly,
    proof_dump_on_primary_page: proofDumpHeavy,
    tradingview_broken: brokenChart,
    console_error: consoleErrors.length > 0,
    network_error: networkErrors.length > 0,
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
}
