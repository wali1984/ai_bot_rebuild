#!/usr/bin/env node
import { chromium } from '@playwright/test';
import { mkdirSync, writeFileSync } from 'node:fs';
import { resolve } from 'node:path';

const frontendRoot = resolve(import.meta.dirname, '..');
const repoRoot = resolve(frontendRoot, '..', '..');
const finalDir = resolve(repoRoot, 'claude_worklog', 'final_readiness', 'tonight_live_like_paper_shadow', 'latest');
const baseUrl = (process.env.TONIGHT_CRAWL_BASE_URL ?? 'http://127.0.0.1:5173').replace(/\/$/, '');
const phase = process.env.TONIGHT_CRAWL_PHASE ?? 'local';
const screenshotDir = resolve(finalDir, 'screenshots', phase);
const nowIso = new Date().toISOString();

const routes = [
  '/',
  '/admin',
  '/admin/mission-control?role=admin',
  '/admin/monitor-center?role=admin',
  '/admin/script-registry?role=admin',
  '/admin/trainer-prediction-monitor?role=admin',
  '/admin/signal-explainability?role=admin',
  '/admin/symbols?role=admin',
  '/admin/signals?role=admin',
  '/admin/executions?role=admin',
  '/admin/positions?role=admin',
  '/admin/risk-control?role=admin',
  '/admin/exchange-manager?role=admin',
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

function compact(text, length = 1800) {
  return text.replace(/\s+/g, ' ').trim().slice(0, length);
}

function classify(route, status, finalUrl, text, consoleErrors, networkErrors, liveBannerVisible, chartExists) {
  const lower = text.toLowerCase();
  const route404 = status === 404 || /\berror:\s*http_404\b|not found/i.test(text.slice(0, 300));
  const placeholderOnly = !route404 && text.length < 700 && /(placeholder|coming soon|no payload|evidence missing|missing evidence|not implemented)/i.test(text);
  const evidenceGapOnly = !placeholderOnly && text.length < 1800 && /(MISSING_EVIDENCE|CURRENT_SIGNAL_LINEAGE_MISSING|TRAINER_RUNTIME_EVIDENCE_MISSING|Evidence missing)/.test(text);
  const proofDumpPrimary =
    /Phase 3|historical 30d|hist_pred_|sig_btc_001|Redis trim|XTRIM|static proof/i.test(text) &&
    route.includes('mission-control') &&
    text.length > 5500 &&
    !/Proof Archive Offloaded|Historical proofs.*no longer rendered on the Mission Control first screen/i.test(text);
  const histAsCurrent = /(hist_pred_|hist_dec_|hist_risk_|sig_btc_001)/.test(text) && !/Static proof examples|Historical proof|not current|collapsed/i.test(text);
  const stalePrimary = /STALE_PAYLOAD|stale payload|SUPERVISOR_STATUS_STALE_OR_CONFLICTING/i.test(text) && !/stale.*warning|Payload Freshness/i.test(text);
  const currentPaperVisible = /PAPER_RUNTIME_ONLINE_ACTIVE|V2_PAPER_TRAINER_WRAPPER_CURRENT|REALTIME_RUNTIME_EVIDENCE|pred_paper_tick_/i.test(text);
  const legacyBridgeVisible = /V2_LIVE_OBSERVER_SHADOW_TWIN|LEGACY_LIVE_BRIDGE|Legacy Live Observer|V2_SHADOW_TWIN|legacy observer/i.test(text);
  const liveControlsVisible = /(enable live|activate live|place order|cancel order|change leverage)/i.test(text) && !/(disabled|blocked|approval|required|cannot|forbidden)/i.test(text);
  const chartBroken = route.includes('mission-control') && !chartExists && !/FALLBACK_STATIC_CHART|READONLY_MARKET_FEED|TradingView/i.test(text);
  const actionableConsoleErrors = consoleErrors.filter((row) => !/favicon|tradingview|analytics|ResizeObserver/i.test(row));
  const actionableNetworkErrors = networkErrors.filter((row) => !/favicon|tradingview|analytics|doubleclick|googletagmanager/i.test(row.url ?? row));
  const needsRepair = route404 || placeholderOnly || evidenceGapOnly || proofDumpPrimary || histAsCurrent || chartBroken || liveControlsVisible || actionableConsoleErrors.length > 0 || actionableNetworkErrors.length > 0;
  return {
    production_ready: !needsRepair && liveBannerVisible,
    route_404: route404,
    route_redirect_wrong: (route === '/' || route === '/admin') && !/mission-control|admin\/mission-control/i.test(finalUrl + text),
    placeholder_only: placeholderOnly,
    evidence_gap_only: evidenceGapOnly,
    proof_dump_primary: proofDumpPrimary,
    stale_payload_primary: stalePrimary,
    static_fixture_as_current: histAsCurrent,
    current_paper_runtime_visible: currentPaperVisible,
    legacy_bridge_visible: legacyBridgeVisible,
    chart_exists: chartExists,
    chart_broken: chartBroken,
    live_block_banner_visible: liveBannerVisible,
    live_controls_visible: liveControlsVisible,
    console_error_count: actionableConsoleErrors.length,
    network_error_count: actionableNetworkErrors.length,
    operator_useful: !needsRepair && liveBannerVisible,
    needs_repair: needsRepair,
  };
}

function markdown(rows) {
  return [
    '| Route | HTTP | Ready | Live banner | Paper current | Legacy bridge | Placeholder | Stale primary | Static current | Needs repair | Screenshot |',
    '|---|---:|---|---|---|---|---|---|---|---|---|',
    ...rows.map((row) => `| ${row.route} | ${row.http_status ?? 'n/a'} | ${row.classification.production_ready ? 'yes' : 'no'} | ${row.classification.live_block_banner_visible ? 'yes' : 'no'} | ${row.classification.current_paper_runtime_visible ? 'yes' : 'no'} | ${row.classification.legacy_bridge_visible ? 'yes' : 'no'} | ${row.classification.placeholder_only ? 'yes' : 'no'} | ${row.classification.stale_payload_primary ? 'yes' : 'no'} | ${row.classification.static_fixture_as_current ? 'yes' : 'no'} | ${row.classification.needs_repair ? 'yes' : 'no'} | ${row.screenshot} |`),
  ].join('\n');
}

mkdirSync(screenshotDir, { recursive: true });

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  ignoreHTTPSErrors: true,
  viewport: { width: 1440, height: 1000 },
});
const results = [];

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
    await page.waitForTimeout(1600);
  } catch (error) {
    navigationError = error instanceof Error ? error.message : String(error);
  }
  const title = await page.title().catch(() => '');
  const text = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  const liveBannerVisible = await page.getByTestId('live-block-banner').isVisible().catch(async () => /blocked_human_only|LIVE TRADING:\s*BLOCKED/i.test(text));
  const chartExists = await page.locator('[data-testid="tradingview-widget"], iframe[src*="tradingview"], canvas, [data-chart-mode="FALLBACK_STATIC_CHART"]').first().isVisible().catch(() => false);
  const screenshot = `screenshots/${phase}/${routeToName(route)}`;
  await page.screenshot({ path: resolve(finalDir, screenshot), fullPage: true }).catch(() => {});
  const status = response?.status() ?? null;
  const finalUrl = page.url();
  const classification = classify(route, status, finalUrl, text, consoleErrors, networkErrors, liveBannerVisible, chartExists);
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
    classification,
  });
  console.log(`${phase} ${route} ${status ?? 'n/a'} ready=${classification.production_ready ? 'yes' : 'no'} repair=${classification.needs_repair ? 'yes' : 'no'}`);
  await page.close();
}

await browser.close();

const failed = results.filter((row) => row.classification.needs_repair || !row.classification.production_ready);
const matrix = {
  generated_at: nowIso,
  base_url: baseUrl,
  phase,
  route_count: results.length,
  passed_count: results.length - failed.length,
  failed_count: failed.length,
  routes: results,
};
writeFileSync(resolve(finalDir, `website_route_acceptance_matrix_${phase}.json`), `${JSON.stringify(matrix, null, 2)}\n`);
writeFileSync(resolve(finalDir, `WEBSITE_ROUTE_ACCEPTANCE_MATRIX_${phase.toUpperCase()}.md`), `# Website Route Acceptance Matrix — ${phase}\n\nGenerated at: ${nowIso}\n\n- Base URL: ${baseUrl}\n- Routes: ${results.length}\n- Passed: ${matrix.passed_count}\n- Failed or needs repair: ${matrix.failed_count}\n- Screenshots: \`claude_worklog/final_readiness/tonight_live_like_paper_shadow/latest/screenshots/${phase}/\`\n\n${markdown(results)}\n`);
if (phase === 'public') {
  writeFileSync(resolve(finalDir, 'website_route_acceptance_matrix.json'), `${JSON.stringify(matrix, null, 2)}\n`);
  writeFileSync(resolve(finalDir, 'WEBSITE_ROUTE_ACCEPTANCE_MATRIX.md'), `# Website Route Acceptance Matrix\n\nGenerated at: ${nowIso}\n\nPublic route crawl result. Local matrix is stored separately when run with \`TONIGHT_CRAWL_PHASE=local\`.\n\n${markdown(results)}\n`);
}
