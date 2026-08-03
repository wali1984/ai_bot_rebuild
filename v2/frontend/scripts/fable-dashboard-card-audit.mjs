#!/usr/bin/env node
// Authenticated dashboard core-card audit: renders /dashboard and reports each
// KPI tile's displayed value + data-quality, plus any "Data validation error" text.
import { chromium } from '@playwright/test';

const BASE = process.env.AUDIT_BASE_URL ?? 'http://127.0.0.1:5173';
const EMAIL = process.env.AUDIT_EMAIL ?? process.env.DASHBOARD_TEST_USERNAME ?? '';
const PASSWORD = process.env.AUDIT_PASSWORD ?? process.env.DASHBOARD_TEST_PASSWORD ?? '';
const ROUTES = (process.env.AUDIT_ROUTES ?? '/dashboard').split(',');
const SHOT_DIR = process.env.AUDIT_SHOT_DIR ?? '/tmp/claude-1000/-home-wali-Desktop-AI-BOT-REBUILD/6cd44337-8ecb-430c-91fa-0cb1451eb4c1/scratchpad';

if (!EMAIL || !PASSWORD) {
  console.log(JSON.stringify({
    loginOk: false,
    blocked_by: 'missing AUDIT_EMAIL/AUDIT_PASSWORD or DASHBOARD_TEST_USERNAME/DASHBOARD_TEST_PASSWORD',
    credential_values_redacted: true,
    results: [],
  }, null, 1));
  process.exit(2);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1660, height: 1100 } });
const page = await context.newPage();
const consoleErrors = [];
const failedRequests = [];
page.on('console', (msg) => { if (msg.type() === 'error') consoleErrors.push(msg.text().slice(0, 200)); });
page.on('response', (resp) => {
  if (resp.status() >= 400 && resp.url().includes('/api/')) {
    failedRequests.push(`${resp.status()} ${resp.url().replace(BASE, '')}`.slice(0, 160));
  }
});

// Login via API to set session cookie
const loginResp = await page.request.post(`${BASE}/api/auth/login`, {
  data: { email: EMAIL, password: PASSWORD },
});
const loginOk = loginResp.ok();
const loginBody = loginOk ? await loginResp.json() : null;
if (loginBody?.access_token) {
  await page.addInitScript((token) => {
    try { window.localStorage.setItem('ai_bot_v2.auth_token', token); } catch {}
  }, loginBody.access_token);
}

const results = [];
for (const route of ROUTES) {
  const t0 = Date.now();
  await page.goto(`${BASE}${route}`, { waitUntil: 'domcontentloaded', timeout: 45000 });
  await page.waitForTimeout(9000);
  const loadMs = Date.now() - t0;
  const audit = await page.evaluate(() => {
    const cards = [];
    for (const el of document.querySelectorAll('[data-field-id]')) {
      cards.push({
        field: el.getAttribute('data-field-id'),
        quality: el.getAttribute('data-quality'),
        sourceType: el.getAttribute('data-source-type'),
        text: (el.textContent || '').trim().slice(0, 60),
      });
    }
    const body = document.body.innerText || '';
    const valErrors = (body.match(/Data validation error/g) || []).length;
    const offline = (body.match(/Source offline/g) || []).length;
    const noRecords = (body.match(/No records for this period/g) || []).length;
    // capture KPI tiles by label
    const kpis = [];
    for (const tile of document.querySelectorAll('.nervyx-dashboard__kpis > *')) {
      kpis.push((tile.innerText || '').replace(/\n+/g, ' | ').slice(0, 140));
    }
    return { cards, valErrors, offline, noRecords, kpis, bodyLen: body.length };
  });
  const shot = `${SHOT_DIR}/audit${route.replaceAll('/', '_')}.png`;
  await page.screenshot({ path: shot, fullPage: false });
  results.push({ route, loadMs, ...audit });
}

console.log(JSON.stringify({ loginOk, consoleErrors: consoleErrors.slice(0, 8), failedRequests: [...new Set(failedRequests)].slice(0, 12), results }, null, 1));
await browser.close();
