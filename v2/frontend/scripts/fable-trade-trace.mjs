import { chromium } from '@playwright/test';
const BASE = process.env.AUDIT_BASE_URL ?? 'http://127.0.0.1:5173';
const EMAIL = process.env.AUDIT_EMAIL ?? process.env.DASHBOARD_TEST_USERNAME ?? '';
const PASSWORD = process.env.AUDIT_PASSWORD ?? process.env.DASHBOARD_TEST_PASSWORD ?? '';

if (!EMAIL || !PASSWORD) {
  console.log(JSON.stringify({
    loginOk: false,
    blocked_by: 'missing AUDIT_EMAIL/AUDIT_PASSWORD or DASHBOARD_TEST_USERNAME/DASHBOARD_TEST_PASSWORD',
    credential_values_redacted: true,
    audit: null,
    reqs: [],
  }, null, 1));
  process.exit(2);
}

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1660, height: 1100 } });
const page = await context.newPage();
const reqs = [];
page.on('response', async (resp) => {
  const u = resp.url();
  if (u.includes('/api/')) reqs.push({ t: Date.now(), status: resp.status(), url: u.replace(BASE, '').slice(0, 90) });
});
const login = await page.request.post(`${BASE}/api/auth/login`, { data: { email: EMAIL, password: PASSWORD } });
if (!login.ok()) {
  console.log(JSON.stringify({
    loginOk: false,
    loginStatus: login.status(),
    credential_values_redacted: true,
    audit: null,
    reqs: [],
  }, null, 1));
  await browser.close();
  process.exit(2);
}
const body = await login.json();
await page.addInitScript((token) => { try { window.localStorage.setItem('ai_bot_v2.auth_token', token); } catch {} }, body.access_token);
const t0 = Date.now();
await page.goto(`${BASE}/trade`, { waitUntil: 'domcontentloaded' });
await page.waitForTimeout(24000);
const audit = await page.evaluate(() => {
  const cards = [];
  for (const el of document.querySelectorAll('[data-field-id]')) {
    cards.push({ field: el.getAttribute('data-field-id'), quality: el.getAttribute('data-quality'), text: (el.textContent || '').trim().slice(0, 40) });
  }
  return { cards, valErrors: (document.body.innerText.match(/Data validation error/g) || []).length };
});
console.log(JSON.stringify({ audit, reqs: reqs.map(r => ({ ms: r.t - t0, status: r.status, url: r.url })) }, null, 1));
await browser.close();
