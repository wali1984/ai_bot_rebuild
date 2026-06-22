import { test, chromium } from '@playwright/test';
import { mkdirSync } from 'fs';

const BASE = 'http://localhost:5173';
const OUT = '/tmp/screenshots';
mkdirSync(OUT, { recursive: true });

const PAGES = [
  ['01-dashboard',    '/dashboard'],
  ['02-signals',      '/signals'],
  ['03-ai',           '/ai-predictions'],
  ['04-research',     '/research'],
  ['05-markets',      '/markets'],
  ['06-backtests',    '/backtests'],
  ['07-replay',       '/backtests/replay'],
];

test('screenshot all trader pages', async () => {
  const browser = await chromium.launch({ headless: true });
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  const page = await ctx.newPage();

  const errors: string[] = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push('PAGE_ERR: ' + err.message));

  // Login
  await page.goto(`${BASE}/login`);
  await page.waitForLoadState('networkidle');
  await page.screenshot({ path: `${OUT}/00-login.png` });

  const inputs = await page.$$('input');
  const emailInput = await page.$('input[type="email"]') ?? inputs[0];
  const pwInput = await page.$('input[type="password"]') ?? inputs[1];
  const btn = await page.$('button[type="submit"]') ?? await page.$('button');

  if (emailInput && pwInput) {
    await emailInput.fill('wajidali1984@hotmail.com');
    await pwInput.fill('AlphaForge2026!');
    if (btn) await btn.click(); else await pwInput.press('Enter');
    await page.waitForTimeout(3500);
    console.log('Post-login URL:', page.url());
    await page.screenshot({ path: `${OUT}/00b-after-login.png` });
  }

  for (const [name, path] of PAGES) {
    errors.length = 0;
    await page.goto(`${BASE}${path}`);
    await page.waitForTimeout(6000);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
    const url = page.url();
    const txt = await page.evaluate(() => document.body.innerText.replace(/\s+/g,' ').substring(0, 700));
    console.log(`[${name}] URL: ${url}`);
    console.log(`[${name}] Text: ${txt}`);
    if (errors.length > 0) console.log(`[${name}] ERRORS: ${errors.slice(0,3).join(' || ')}`);
    console.log('---');
  }

  await browser.close();
});
