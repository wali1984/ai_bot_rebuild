#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const frontendRoot = resolve(import.meta.dirname, '..');
const repoRoot = resolve(frontendRoot, '..', '..');
const finalDir = resolve(repoRoot, 'claude_worklog', 'final_readiness', 'production_website_public_route_rebuild', 'latest');
const baseUrl = (process.env.PRODUCTION_CRAWL_BASE_URL ?? 'https://dashboard.wajidali.us').replace(/\/$/, '');
const phase = process.env.PRODUCTION_CRAWL_PHASE ?? 'before';
const screenshotDir = resolve(finalDir, 'screenshots', phase);
const nowIso = new Date().toISOString();

const routes = [
  '/',
  '/landing',
  '/status',
  '/login',
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

function routeToName(route) {
  return `${route.replaceAll('/', '_').replaceAll('?', '_').replaceAll('=', '_').replaceAll('&', '_') || 'root'}.png`;
}

function compact(text, length = 2200) {
  return text.replace(/\s+/g, ' ').trim().slice(0, length);
}

function duplicates(items) {
  const seen = new Set();
  const dupes = new Set();
  for (const item of items.map((value) => value.trim()).filter(Boolean)) {
    const key = item.toLowerCase();
    if (seen.has(key)) dupes.add(item);
    seen.add(key);
  }
  return Array.from(dupes).slice(0, 20);
}

function classify({ route, status, finalUrl, text, headings, consoleErrors, networkErrors, liveBannerVisible, chartExists, internalLinks, linkFailures, dangerousControls }) {
  const excerpt = text.slice(0, 5000);
  const route404 = status === 404 || /\b(error:\s*http_404|not found|cannot get)\b/i.test(text.slice(0, 600));
  const placeholderOnly = !route404 && text.length < 900 && /(placeholder|coming soon|not implemented|no payload|evidence missing|missing evidence)/i.test(text);
  const evidenceGapOnly = !placeholderOnly && text.length < 1800 && /(MISSING_EVIDENCE|CURRENT_SIGNAL_LINEAGE_MISSING|TRAINER_RUNTIME_EVIDENCE_MISSING|Evidence missing)/.test(text);
  const proofDumpPrimary = /Phase 3|historical 30d|hist_pred_|hist_dec_|hist_risk_|sig_btc_001|Redis trim|XTRIM|static proof/i.test(excerpt)
    && text.length > 6200
    && !/Proof Archive Offloaded|Static proof examples|Historical proof.*not current|Operator Proof Dashboard/i.test(excerpt);
  const histAsCurrent = /(hist_pred_|hist_dec_|hist_risk_|sig_btc_001)/.test(excerpt) && !/Static proof examples|Historical proof|not current|collapsed|Proof Archive/i.test(excerpt);
  const staleHidden = /STALE_PAYLOAD|stale payload|SUPERVISOR_STATUS_STALE_OR_CONFLICTING/i.test(text) && !/Payload Freshness|stale.*warning|stale.*visible|not current/i.test(text);
  const currentTruthVisible = /PAPER_RUNTIME_ONLINE_ACTIVE|V2_PAPER_TRAINER_WRAPPER_CURRENT|REALTIME_RUNTIME_EVIDENCE|LEGACY_LIVE_BRIDGE|V2_LIVE_OBSERVER_SHADOW_TWIN|pred_paper_tick_/i.test(text);
  const sourceFreshnessVisible = /(source|freshness|generated|age|REALTIME_RUNTIME_EVIDENCE|READONLY_MARKET_FEED|V2_PROOF_ARTIFACT|STATIC_PROOF_FIXTURE)/i.test(text);
  const duplicateHeadings = duplicates(headings);
  const chartBroken = route.includes('mission-control') && !chartExists;
  const actionableConsoleErrors = consoleErrors.filter((row) => !/favicon|tradingview|analytics|ResizeObserver|chrome-extension/i.test(row));
  const actionableNetworkErrors = networkErrors.filter((row) => !/favicon|tradingview|analytics|doubleclick|googletagmanager|chrome-extension/i.test(row.url ?? row));
  const dangerousControlEnabled = dangerousControls.some((row) => row.enabled && /(enable live|activate live|place order|cancel order|change leverage|cross margin|api key)/i.test(row.text));
  const linkFailureCount = linkFailures.filter((row) => row.status === null || row.status >= 400).length;
  const needsRepair = route404
    || placeholderOnly
    || evidenceGapOnly
    || proofDumpPrimary
    || histAsCurrent
    || staleHidden
    || chartBroken
    || duplicateHeadings.length > 4
    || actionableConsoleErrors.length > 0
    || actionableNetworkErrors.length > 0
    || dangerousControlEnabled
    || linkFailureCount > 0
    || !sourceFreshnessVisible
    || (route.startsWith('/admin') && !liveBannerVisible);
  return {
    production_ready: !needsRepair,
    route_404: route404,
    final_url: finalUrl,
    placeholder_only: placeholderOnly,
    evidence_gap_only: evidenceGapOnly,
    proof_dump_primary: proofDumpPrimary,
    static_fixture_as_current: histAsCurrent,
    stale_payload_hidden: staleHidden,
    current_runtime_truth_visible: currentTruthVisible,
    source_freshness_visible: sourceFreshnessVisible,
    live_block_banner_visible: liveBannerVisible,
    chart_exists: chartExists,
    chart_broken: chartBroken,
    duplicate_headings: duplicateHeadings,
    nav_link_count: internalLinks.length,
    link_failure_count: linkFailureCount,
    console_error_count: actionableConsoleErrors.length,
    network_error_count: actionableNetworkErrors.length,
    dangerous_control_enabled: dangerousControlEnabled,
    needs_repair: needsRepair,
  };
}

function markdown(rows) {
  return [
    '| Route | HTTP | Ready | Current truth | Source/freshness | Chart | Live banner | Placeholder | Proof dump | Static current | Link fails | Console | Network | Screenshot |',
    '|---|---:|---|---|---|---|---|---|---|---|---:|---:|---:|---|',
    ...rows.map((row) => `| ${row.route} | ${row.http_status ?? 'n/a'} | ${row.classification.production_ready ? 'yes' : 'no'} | ${row.classification.current_runtime_truth_visible ? 'yes' : 'no'} | ${row.classification.source_freshness_visible ? 'yes' : 'no'} | ${row.classification.chart_exists ? 'yes' : 'no'} | ${row.classification.live_block_banner_visible ? 'yes' : 'no'} | ${row.classification.placeholder_only ? 'yes' : 'no'} | ${row.classification.proof_dump_primary ? 'yes' : 'no'} | ${row.classification.static_fixture_as_current ? 'yes' : 'no'} | ${row.classification.link_failure_count} | ${row.classification.console_error_count} | ${row.classification.network_error_count} | ${row.screenshot} |`),
  ].join('\n');
}

mkdirSync(screenshotDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 980 },
});
const results = [];
const linkCache = new Map();

async function checkLink(href) {
  if (linkCache.has(href)) return linkCache.get(href);
  let row;
  try {
    const response = await context.request.get(href, { timeout: 12_000, maxRedirects: 4 });
    row = { href, status: response.status(), final_url: response.url(), error: null };
  } catch (error) {
    row = { href, status: null, final_url: null, error: error instanceof Error ? error.message.slice(0, 240) : String(error) };
  }
  linkCache.set(href, row);
  return row;
}

for (const route of routes) {
  const page = await context.newPage();
  const consoleErrors = [];
  const networkErrors = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text().slice(0, 500));
  });
  page.on('pageerror', (error) => consoleErrors.push(error.message.slice(0, 500)));
  page.on('requestfailed', (request) => {
    networkErrors.push({ url: request.url(), method: request.method(), failure: request.failure()?.errorText ?? 'unknown' });
  });
  const url = `${baseUrl}${route}`;
  let response = null;
  let navigationError = null;
  try {
    response = await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForTimeout(2200);
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }
  const title = await page.title().catch(() => '');
  const text = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  const headings = await page.locator('h1,h2,h3').evaluateAll((nodes) => nodes.map((node) => node.textContent ?? '')).catch(() => []);
  const liveBannerVisible = await page.getByTestId('live-block-banner').isVisible().catch(async () => /blocked_human_only|LIVE TRADING:\s*BLOCKED/i.test(text));
  const chartExists = await page.locator('[data-testid="readonly-market-chart"], [data-testid="tradingview-widget"], iframe[src*="tradingview"], canvas, svg.cockpit-chart, [data-chart-mode="FALLBACK_STATIC_CHART"]').first().isVisible().catch(() => false);
  const anchors = await page.locator('a[href]').evaluateAll((nodes) => nodes.map((node) => ({
    text: (node.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 120),
    href: (node).href,
  }))).catch(() => []);
  const internalLinks = anchors
    .filter((link) => link.href && link.href.startsWith(baseUrl))
    .filter((link, index, all) => all.findIndex((item) => item.href === link.href) === index)
    .slice(0, 80);
  const linkFailures = [];
  for (const link of internalLinks.slice(0, 35)) {
    const checked = await checkLink(link.href);
    if (checked.status === null || checked.status >= 400) linkFailures.push({ ...checked, text: link.text });
  }
  const dangerousControls = await page.locator('button, [role="button"], input[type="button"], input[type="submit"]').evaluateAll((nodes) => nodes.map((node) => ({
    text: (node.textContent || node.getAttribute('value') || node.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim().slice(0, 180),
    disabled: Boolean(node.disabled || node.getAttribute('aria-disabled') === 'true'),
    enabled: !(node.disabled || node.getAttribute('aria-disabled') === 'true'),
  }))).catch(() => []);
  const screenshot = `screenshots/${phase}/${routeToName(route)}`;
  await page.screenshot({ path: resolve(finalDir, screenshot), fullPage: true }).catch(() => {});
  const status = response?.status() ?? null;
  const finalUrl = page.url();
  const classification = classify({
    route,
    status,
    finalUrl,
    text,
    headings,
    consoleErrors,
    networkErrors,
    liveBannerVisible,
    chartExists,
    internalLinks,
    linkFailures,
    dangerousControls,
  });
  results.push({
    route,
    requested_url: url,
    final_url: finalUrl,
    http_status: status,
    title,
    screenshot,
    console_errors: [...new Set(consoleErrors)],
    network_errors: networkErrors,
    navigation_error: navigationError,
    visible_text_excerpt: compact(text),
    headings,
    duplicate_headings: classification.duplicate_headings,
    internal_links: internalLinks,
    link_failures: linkFailures,
    dangerous_controls: dangerousControls,
    classification,
  });
  console.log(`${phase} ${route} ${status ?? 'n/a'} ready=${classification.production_ready ? 'yes' : 'no'} repair=${classification.needs_repair ? 'yes' : 'no'} links=${classification.link_failure_count}`);
  await page.close();
}

await browser.close();

const failed = results.filter((row) => !row.classification.production_ready || row.classification.needs_repair);
const matrix = {
  generated_at: nowIso,
  base_url: baseUrl,
  phase,
  route_count: results.length,
  passed_count: results.length - failed.length,
  failed_count: failed.length,
  link_checked_count: linkCache.size,
  routes: results,
};

writeFileSync(resolve(finalDir, `production_route_matrix_${phase}.json`), `${JSON.stringify(matrix, null, 2)}\n`);
writeFileSync(resolve(finalDir, `PRODUCTION_ROUTE_CRAWL_${phase.toUpperCase()}_REPORT.md`), `# Production Route Crawl — ${phase}\n\nGenerated at: ${nowIso}\n\n- Base URL: ${baseUrl}\n- Routes: ${results.length}\n- Passed: ${matrix.passed_count}\n- Failed or needs repair: ${matrix.failed_count}\n- Internal links checked: ${matrix.link_checked_count}\n- Screenshots: \`claude_worklog/final_readiness/production_website_public_route_rebuild/latest/screenshots/${phase}/\`\n\n${markdown(results)}\n`);
if (phase === 'after') {
  writeFileSync(resolve(finalDir, 'production_route_matrix.json'), `${JSON.stringify(matrix, null, 2)}\n`);
  writeFileSync(resolve(finalDir, 'PRODUCTION_ROUTE_CRAWL_REPORT.md'), `# Production Route Crawl\n\nGenerated at: ${nowIso}\n\nAfter-repair crawl against ${baseUrl}.\n\n${markdown(results)}\n`);
}
