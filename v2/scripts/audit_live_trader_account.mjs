#!/usr/bin/env node
import { chromium } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const scriptPath = fileURLToPath(import.meta.url);
const scriptDir = path.dirname(scriptPath);
const repoRoot = path.resolve(scriptDir, '..');

loadLocalEnvFile(path.join(repoRoot, '.env.local'));
loadLocalEnvFile(path.join(repoRoot, 'secrets', 'legacy_config.local.py'));

const baseUrl = (process.env.AUDIT_BASE_URL ?? 'https://dashboard.wajidali.us').replace(/\/$/, '');
const auditPhase = process.env.TRADER_AUDIT_PHASE === 'after' ? 'after' : 'before';
const email = process.env.NERVYX_TRADER_EMAIL
  ?? process.env.ALPHAFORGE_INITIAL_TRADER_EMAIL
  ?? 'wajidali1984@hotmail.com';
const password = process.env.NERVYX_TRADER_PASSWORD
  ?? process.env.ALPHAFORGE_INITIAL_TRADER_PASSWORD
  ?? '';
const generatedAt = new Date().toISOString();

const artifactPath = path.join(repoRoot, 'artifacts', `trader-live-${auditPhase}.json`);
const markdownPath = path.join(repoRoot, 'docs', `trader-live-${auditPhase}.md`);
const screenshotRoot = path.join(repoRoot, 'screenshots', `trader-live-${auditPhase}`);

const viewports = [
  { label: '1920x1080', width: 1920, height: 1080 },
  { label: '1440x900', width: 1440, height: 900 },
  { label: '768x1024', width: 768, height: 1024 },
  { label: '390x844', width: 390, height: 844 },
];

const auditPlan = [
  { id: 'account-settings', label: 'Account / Settings', route: '/account-settings', menuPath: ['User menu', 'Account / Settings'] },
  { id: 'dashboard', label: 'Dashboard', route: '/dashboard', menuPath: ['Dashboard'] },
  { id: 'portfolio', label: 'Portfolio', route: '/portfolio', menuPath: ['Portfolio'] },
  { id: 'positions', label: 'Positions', route: '/portfolio', menuPath: ['Portfolio', 'Positions'] },
  { id: 'executions', label: 'Executions', route: '/portfolio/executions', menuPath: ['Portfolio', 'Executions'] },
  { id: 'history', label: 'History', route: '/portfolio/history', fallbackRoutes: ['/history'], menuPath: ['Portfolio', 'History'] },
  { id: 'markets', label: 'Markets', route: '/markets', menuPath: ['Markets'] },
  { id: 'market-btcusdt', label: 'Market BTCUSDT', route: '/market/BTCUSDT', menuPath: ['Markets', 'BTCUSDT'] },
  { id: 'market-ethusdt', label: 'Market ETHUSDT', route: '/market/ETHUSDT', menuPath: ['Markets', 'ETHUSDT'] },
  { id: 'market-solusdt', label: 'Market SOLUSDT', route: '/market/SOLUSDT', menuPath: ['Markets', 'SOLUSDT'] },
  { id: 'trade', label: 'Trade', route: '/trade', menuPath: ['Trade'] },
  { id: 'derivatives', label: 'Derivatives', route: '/derivatives', menuPath: ['Derivatives'] },
  { id: 'signals', label: 'Signals', route: '/signals', menuPath: ['Signals'] },
  { id: 'ai-predictions', label: 'AI Predictions', route: '/ai-predictions', menuPath: ['AI'] },
  { id: 'backtests', label: 'Backtests', route: '/backtests', menuPath: ['Backtests'] },
  { id: 'replay', label: 'Replay', route: '/backtests/replay', fallbackRoutes: ['/replay'], menuPath: ['Backtests', 'Replay'] },
  { id: 'research', label: 'Research', route: '/research', menuPath: ['Research'] },
  { id: 'technical-analysis', label: 'Technical Analysis', route: '/technical-analysis', fallbackRoutes: ['/admin/technical-analysis'], menuPath: ['Research', 'Technical Analysis'] },
  { id: 'alerts', label: 'Alerts', route: '/alerts', menuPath: ['Alerts'] },
];

function loadLocalEnvFile(filePath) {
  if (!fs.existsSync(filePath)) return;
  const text = fs.readFileSync(filePath, 'utf8');
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith('#')) continue;
    const match = line.match(/^(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)$/);
    if (!match) continue;
    const [, key, rawValue] = match;
    if (process.env[key] != null) continue;
    let value = rawValue.trim();
    if (
      (value.startsWith('"') && value.endsWith('"'))
      || (value.startsWith("'") && value.endsWith("'"))
    ) {
      value = value.slice(1, -1);
    }
    process.env[key] = value;
  }
}

function ensureDirs() {
  fs.mkdirSync(path.dirname(artifactPath), { recursive: true });
  fs.mkdirSync(path.dirname(markdownPath), { recursive: true });
  fs.mkdirSync(screenshotRoot, { recursive: true });
}

function relative(filePath) {
  return path.relative(repoRoot, filePath);
}

function sanitizeName(value) {
  return value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '') || 'page';
}

function redactUrl(value) {
  return value.replace(/([?&](?:password|token|access_token|refresh_token)=)[^&]+/gi, '$1[REDACTED]');
}

function compactText(text, max = 260) {
  return text.replace(/\s+/g, ' ').trim().slice(0, max);
}

function numberOrNull(value) {
  return Number.isFinite(value) ? value : null;
}

function writeMarkdown(audit) {
  const routeRows = audit.pages.map((page) => {
    const screenshots = Object.entries(page.screenshots)
      .map(([viewport, file]) => `${viewport}: \`${file}\``)
      .join('<br>');
    return `| ${page.label} | ${page.route} | ${page.navigation.used_direct_fallback ? 'fallback' : 'menu'} | ${page.http_failures.length} | ${page.console_errors.length} | ${page.websockets.length} | ${page.values_rendered.length} | ${page.text_clipping.length} | ${screenshots} |`;
  });

  const lines = [
    `# Trader Live ${auditPhase === 'after' ? 'After' : 'Before'} Audit`,
    '',
    `Generated: ${audit.generated_at}`,
    `Base URL: ${audit.base_url}`,
    `Status: ${audit.status}`,
    '',
    `Login method: ${audit.login.method}`,
    `Authenticated user observed: ${audit.login.authenticated_user_observed ? 'yes' : 'no'}`,
    `Pages audited: ${audit.pages.length}`,
    '',
  ];

  if (audit.status === 'BLOCKED') {
    lines.push('## Blocker', '', audit.blocker ?? 'Production audit blocked.', '');
  }

  lines.push(
    '## Routes',
    '',
    '| Page | Route | Navigation | HTTP failures | Console errors | WebSockets | Values | Clipping | Screenshots |',
    '|---|---|---:|---:|---:|---:|---:|---:|---|',
    ...routeRows,
    '',
    '## Notes',
    '',
    '- This audit uses real backend login only. It does not use `?role=` and does not mock `/api/auth/me`.',
    '- Password values are never printed, stored, logged, or screenshotted by this script.',
    '- Direct route fallback is recorded as a navigation defect when no visible menu path can be clicked.',
    '',
  );

  fs.writeFileSync(markdownPath, `${lines.join('\n')}\n`);
}

function writeAudit(audit) {
  ensureDirs();
  fs.writeFileSync(artifactPath, `${JSON.stringify(audit, null, 2)}\n`);
  writeMarkdown(audit);
}

function blockedAudit(missing) {
  return {
    generated_at: generatedAt,
    audit_phase: auditPhase,
    base_url: baseUrl,
    status: 'BLOCKED',
    blocker: `Required production trader credential environment variables are missing: ${missing.join(', ')}.`,
    credential_env: {
      NERVYX_TRADER_EMAIL: Boolean(email),
      NERVYX_TRADER_PASSWORD: Boolean(password),
    },
    login: {
      method: 'not_attempted',
      authenticated_user_observed: false,
      route: null,
      error: 'missing_required_environment',
    },
    pages: [],
  };
}

function viewportScreenshotPath(pageId, viewportLabel) {
  return path.join(screenshotRoot, `${sanitizeName(pageId)}-${viewportLabel}.png`);
}

async function safeInnerText(locator, timeout = 800) {
  try {
    return compactText(await locator.innerText({ timeout }));
  } catch {
    return '';
  }
}

async function collectVisibleCards(page) {
  return page.locator('[data-field-id], [data-testid*="card"], .card, article, section').evaluateAll((nodes) => (
    nodes
      .filter((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        const style = window.getComputedStyle(element);
        return rect.width > 40 && rect.height > 24 && style.visibility !== 'hidden' && style.display !== 'none';
      })
      .slice(0, 80)
      .map((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return {
          text: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 220),
          test_id: element.getAttribute('data-testid'),
          field_id: element.getAttribute('data-field-id'),
          source: element.getAttribute('data-source'),
          source_type: element.getAttribute('data-source-type'),
          timestamp: element.getAttribute('data-timestamp'),
          age_ms: element.getAttribute('data-age-ms'),
          quality: element.getAttribute('data-quality'),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
  ));
}

async function collectTables(page) {
  return page.locator('table, [role="table"], [data-testid*="table"], [data-testid*="grid"]').evaluateAll((nodes) => (
    nodes
      .filter((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return rect.width > 40 && rect.height > 24;
      })
      .slice(0, 40)
      .map((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        const headers = Array.from(element.querySelectorAll('th, [role="columnheader"]'))
          .map((header) => (header.textContent ?? '').replace(/\s+/g, ' ').trim())
          .filter(Boolean)
          .slice(0, 40);
        const rows = Array.from(element.querySelectorAll('tbody tr, [role="row"]')).length;
        return {
          text: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 320),
          test_id: element.getAttribute('data-testid'),
          headers,
          rows,
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
  ));
}

async function collectChartPanels(page) {
  return page.locator('canvas, svg, [data-testid*="chart"], [class*="chart"], iframe[src*="tradingview"]').evaluateAll((nodes) => (
    nodes
      .filter((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return rect.width > 60 && rect.height > 40;
      })
      .slice(0, 50)
      .map((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 180),
          test_id: element.getAttribute('data-testid'),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
  ));
}

async function collectRenderedValues(page) {
  return page.locator('[data-field-id]').evaluateAll((nodes) => (
    nodes.slice(0, 300).map((node) => {
      const element = node;
      const rect = element.getBoundingClientRect();
      return {
        field_id: element.getAttribute('data-field-id'),
        value: (element.textContent ?? '').replace(/\s+/g, ' ').trim(),
        source: element.getAttribute('data-source'),
        source_type: element.getAttribute('data-source-type'),
        timestamp: element.getAttribute('data-timestamp'),
        age_ms: element.getAttribute('data-age-ms'),
        quality: element.getAttribute('data-quality'),
        width: Math.round(rect.width),
        height: Math.round(rect.height),
      };
    })
  ));
}

async function collectSourceMetadata(page) {
  return page.locator('[data-source], [data-source-type], [data-timestamp], time').evaluateAll((nodes) => (
    nodes.slice(0, 240).map((node) => {
      const element = node;
      return {
        text: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 180),
        field_id: element.getAttribute('data-field-id'),
        source: element.getAttribute('data-source'),
        source_type: element.getAttribute('data-source-type'),
        timestamp: element.getAttribute('data-timestamp') ?? element.getAttribute('datetime'),
        age_ms: element.getAttribute('data-age-ms'),
        quality: element.getAttribute('data-quality'),
      };
    })
  ));
}

async function collectTextClipping(page) {
  return page.locator('body *').evaluateAll((nodes) => (
    nodes
      .filter((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        if (rect.width < 24 || rect.height < 10) return false;
        const style = window.getComputedStyle(element);
        if (style.visibility === 'hidden' || style.display === 'none') return false;
        return element.scrollWidth > element.clientWidth + 2 || element.scrollHeight > element.clientHeight + 2;
      })
      .slice(0, 80)
      .map((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 160),
          test_id: element.getAttribute('data-testid'),
          class_name: String(element.getAttribute('class') ?? '').slice(0, 120),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
          scroll_width: element.scrollWidth,
          scroll_height: element.scrollHeight,
        };
      })
  ));
}

async function collectPanelDimensions(page) {
  return page.locator('main, section, article, [data-testid*="panel"], [data-testid*="card"], [class*="panel"], [class*="card"]').evaluateAll((nodes) => (
    nodes
      .filter((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return rect.width > 80 && rect.height > 40;
      })
      .slice(0, 90)
      .map((node) => {
        const element = node;
        const rect = element.getBoundingClientRect();
        return {
          tag: element.tagName.toLowerCase(),
          text: (element.textContent ?? '').replace(/\s+/g, ' ').trim().slice(0, 120),
          test_id: element.getAttribute('data-testid'),
          class_name: String(element.getAttribute('class') ?? '').slice(0, 120),
          x: Math.round(rect.x),
          y: Math.round(rect.y),
          width: Math.round(rect.width),
          height: Math.round(rect.height),
        };
      })
  ));
}

function classifyNullZeroNan(values, bodyText) {
  const rendered = values.map((value) => ({ field_id: value.field_id, value: value.value }))
    .filter((value) => /(^|[^a-z])(null|undefined|nan|infinity)([^a-z]|$)/i.test(value.value) || /^[-+]?0(?:\.0+)?$/.test(value.value.trim()));
  const textMatches = Array.from(new Set((bodyText.match(/\b(?:null|undefined|NaN|Infinity)\b/g) ?? []))).sort();
  return { rendered, text_matches: textMatches };
}

function dataAgeSummary(values) {
  const ages = values
    .map((value) => Number(value.age_ms))
    .filter((value) => Number.isFinite(value) && value >= 0);
  if (!ages.length) return { min_ms: null, max_ms: null, count: 0 };
  return {
    min_ms: Math.min(...ages),
    max_ms: Math.max(...ages),
    count: ages.length,
  };
}

async function clickVisibleByText(page, text) {
  const candidates = [
    page.getByRole('link', { name: new RegExp(`^${escapeRegExp(text)}$`, 'i') }),
    page.getByRole('button', { name: new RegExp(`^${escapeRegExp(text)}$`, 'i') }),
    page.getByText(new RegExp(`^${escapeRegExp(text)}$`, 'i')),
    page.getByRole('link', { name: new RegExp(escapeRegExp(text), 'i') }),
    page.getByRole('button', { name: new RegExp(escapeRegExp(text), 'i') }),
    page.getByText(new RegExp(escapeRegExp(text), 'i')),
  ];

  for (const locator of candidates) {
    const count = await locator.count().catch(() => 0);
    if (!count) continue;
    const first = locator.first();
    if (!(await first.isVisible().catch(() => false))) continue;
    await first.click({ timeout: 5000 });
    return true;
  }
  return false;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

async function navigateByMenu(page, target) {
  const navigation = {
    requested_menu_path: target.menuPath,
    clicked: [],
    menu_path_found: false,
    used_direct_fallback: false,
    fallback_route: null,
    error: null,
  };

  try {
    for (const step of target.menuPath) {
      if (step === 'User menu') {
        const opened = await page.getByRole('button', { name: /user menu/i }).click({ timeout: 3000 }).then(() => true).catch(() => false);
        if (!opened) throw new Error('user menu button not visible');
        navigation.clicked.push(step);
        await page.waitForTimeout(250);
        continue;
      }
      const clicked = await clickVisibleByText(page, step);
      if (!clicked) throw new Error(`visible menu item not found: ${step}`);
      navigation.clicked.push(step);
      await page.waitForLoadState('domcontentloaded', { timeout: 10_000 }).catch(() => undefined);
      await page.waitForTimeout(700);
    }
    navigation.menu_path_found = true;
  } catch (error) {
    navigation.error = error instanceof Error ? error.message : String(error);
  }

  const acceptableRoutes = [target.route, ...(target.fallbackRoutes ?? [])];
  const currentPath = new URL(page.url()).pathname;
  const matched = acceptableRoutes.some((route) => route.includes(':') ? false : currentPath === route);
  if (!navigation.menu_path_found || !matched) {
    navigation.used_direct_fallback = true;
    navigation.fallback_route = target.route;
    await page.goto(`${baseUrl}${target.route}`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
    await page.waitForTimeout(1600);
  }

  return navigation;
}

async function collectPageAudit(page, target, watchers) {
  const route = redactUrl(page.url().replace(baseUrl, '') || page.url());
  const title = await page.title().catch(() => '');
  const pageTitle = await safeInnerText(page.locator('h1').first()).then((value) => value || title);
  const bodyText = await page.locator('body').innerText({ timeout: 5000 }).catch(() => '');
  const valuesRendered = await collectRenderedValues(page).catch(() => []);
  const sourceMetadata = await collectSourceMetadata(page).catch(() => []);
  const screenshots = {};

  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    await page.waitForTimeout(500);
    const filePath = viewportScreenshotPath(target.id, viewport.label);
    await page.screenshot({ path: filePath, fullPage: true });
    screenshots[viewport.label] = relative(filePath);
  }

  const visibleCards = await collectVisibleCards(page).catch(() => []);
  const visibleChartPanels = await collectChartPanels(page).catch(() => []);
  const visibleTables = await collectTables(page).catch(() => []);
  const textClipping = await collectTextClipping(page).catch(() => []);
  const panelDimensions = await collectPanelDimensions(page).catch(() => []);
  const nullZeroNan = classifyNullZeroNan(valuesRendered, bodyText);
  const dataAge = dataAgeSummary(valuesRendered);
  const staleStatus = {
    stale_text_present: /\bstale\b/i.test(bodyText),
    connecting_text_present: /\bconnecting\b/i.test(bodyText),
    source_offline_text_present: /source offline|offline/i.test(bodyText),
    data_validation_error_text_present: /data validation error/i.test(bodyText),
  };

  return {
    id: target.id,
    label: target.label,
    route,
    menu_path_used: target.menuPath,
    page_title: pageTitle,
    title,
    http_failures: watchers.httpFailures.splice(0),
    console_errors: watchers.consoleErrors.splice(0),
    web_sockets: watchers.websockets.splice(0),
    websockets: watchers.websocketsHistory.slice(),
    messages_received: watchers.wsMessages.splice(0),
    first_frame_time: watchers.firstFrameTime,
    last_frame_time: watchers.lastFrameTime,
    visible_cards: visibleCards,
    visible_chart_panels: visibleChartPanels,
    visible_tables: visibleTables,
    values_rendered: valuesRendered,
    source_metadata: sourceMetadata,
    timestamps_rendered: sourceMetadata.filter((item) => item.timestamp),
    data_age: dataAge,
    stale_status: staleStatus,
    null_zero_nan_values: nullZeroNan,
    text_clipping: textClipping,
    panel_dimensions: panelDimensions,
    card_alignment: summarizeAlignment(panelDimensions),
    screenshots,
  };
}

function summarizeAlignment(panels) {
  const topBuckets = new Map();
  for (const panel of panels) {
    const bucket = Math.round(panel.y / 8) * 8;
    topBuckets.set(bucket, (topBuckets.get(bucket) ?? 0) + 1);
  }
  return {
    panel_count: panels.length,
    shared_top_rows: Array.from(topBuckets.entries())
      .filter(([, count]) => count > 1)
      .map(([y, count]) => ({ y, count }))
      .slice(0, 20),
  };
}

function resetWatchers(watchers) {
  watchers.httpFailures.length = 0;
  watchers.consoleErrors.length = 0;
  watchers.websockets.length = 0;
  watchers.wsMessages.length = 0;
  watchers.firstFrameTime = null;
  watchers.lastFrameTime = null;
}

async function login(page) {
  await page.goto(`${baseUrl}/login?returnTo=${encodeURIComponent('/account-settings')}`, {
    waitUntil: 'domcontentloaded',
    timeout: 45_000,
  });
  await page.getByLabel(/email/i).fill(email, { timeout: 10_000 });
  await page.locator('input[name="password"], #login-password').fill(password, { timeout: 10_000 });
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30_000 }).catch(() => undefined),
    page.getByRole('button', { name: /sign in/i }).click(),
  ]);
  await page.waitForTimeout(1200);

  const me = await page.request.get(`${baseUrl}/api/auth/me`, { timeout: 10_000 }).catch((error) => error);
  if (me instanceof Error || !me.ok()) {
    throw new Error('real backend login did not produce an authenticated /api/auth/me session');
  }
  const payload = await me.json();
  return {
    method: 'login_form',
    authenticated_user_observed: Boolean(payload?.user),
    role: payload?.user?.role ?? null,
    trader_id_present: Boolean(payload?.user?.trader_id),
    account_id_present: Boolean(payload?.user?.paper_account_id),
    exchange_accounts_count: Array.isArray(payload?.user?.exchange_accounts) ? payload.user.exchange_accounts.length : null,
  };
}

async function main() {
  ensureDirs();
  const missing = [
    ['NERVYX_TRADER_EMAIL', email],
    ['NERVYX_TRADER_PASSWORD', password],
  ].filter(([, value]) => !value).map(([name]) => name);

  if (missing.length) {
    const audit = blockedAudit(missing);
    writeAudit(audit);
    console.error(`Trader live audit blocked: missing ${missing.join(', ')}`);
    process.exitCode = 2;
    return;
  }

  const browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1920, height: 1080 },
  });
  const page = await context.newPage();
  const watchers = {
    httpFailures: [],
    consoleErrors: [],
    websockets: [],
    websocketsHistory: [],
    wsMessages: [],
    firstFrameTime: null,
    lastFrameTime: null,
  };

  page.on('console', (message) => {
    if (message.type() === 'error') watchers.consoleErrors.push(message.text().slice(0, 500));
  });
  page.on('pageerror', (error) => watchers.consoleErrors.push(error.message.slice(0, 500)));
  page.on('response', (response) => {
    const status = response.status();
    const url = redactUrl(response.url());
    if (status >= 400 && !/favicon|analytics|googletagmanager|doubleclick/i.test(url)) {
      watchers.httpFailures.push({ url, status, method: response.request().method() });
    }
  });
  page.on('requestfailed', (request) => {
    watchers.httpFailures.push({
      url: redactUrl(request.url()),
      method: request.method(),
      failure: request.failure()?.errorText ?? 'request_failed',
    });
  });
  page.on('websocket', (ws) => {
    const row = { url: redactUrl(ws.url()), opened_at: new Date().toISOString(), closed_at: null };
    watchers.websockets.push(row);
    watchers.websocketsHistory.push(row);
    ws.on('framereceived', (event) => {
      const now = new Date().toISOString();
      watchers.firstFrameTime ??= now;
      watchers.lastFrameTime = now;
      watchers.wsMessages.push({
        url: row.url,
        received_at: now,
        bytes: typeof event.payload === 'string' ? event.payload.length : event.payload.byteLength,
        preview: typeof event.payload === 'string' ? event.payload.slice(0, 240) : '[binary]',
      });
    });
    ws.on('close', () => {
      row.closed_at = new Date().toISOString();
    });
  });

  const audit = {
    generated_at: generatedAt,
    audit_phase: auditPhase,
    base_url: baseUrl,
    status: 'OPEN',
    login: null,
    pages: [],
  };

  try {
    audit.login = await login(page);
    if (audit.login.role !== 'trader') {
      audit.status = 'BLOCKED';
      audit.blocker = `Authenticated account role was ${audit.login.role ?? 'unknown'}, expected trader.`;
    } else {
      for (const target of auditPlan) {
        resetWatchers(watchers);
        const navigation = await navigateByMenu(page, target);
        await page.waitForLoadState('networkidle', { timeout: 5000 }).catch(() => undefined);
        await page.waitForTimeout(1400);
        const pageAudit = await collectPageAudit(page, target, watchers);
        pageAudit.navigation = navigation;
        audit.pages.push(pageAudit);
        console.log(`audited ${target.label}: ${pageAudit.route} values=${pageAudit.values_rendered.length} ws=${pageAudit.websockets.length}`);
      }
      audit.status = 'OPEN';
    }
  } catch (error) {
    audit.status = 'BLOCKED';
    audit.blocker = error instanceof Error ? error.message : String(error);
    audit.login ??= {
      method: 'login_form',
      authenticated_user_observed: false,
      error: audit.blocker,
    };
  } finally {
    await browser.close();
    writeAudit(audit);
  }

  if (audit.status === 'BLOCKED') {
    console.error(`Trader live audit blocked: ${audit.blocker}`);
    process.exitCode = 2;
  }
}

await main();
