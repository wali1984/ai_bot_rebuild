import { mkdirSync } from 'fs';
import { test } from '@playwright/test';
import { mockAuth } from './helpers/auth';

const BASE = process.env.PLAYWRIGHT_BASE_URL ?? 'http://127.0.0.1:5173';
const OUT = '/tmp/screenshots';
mkdirSync(OUT, { recursive: true });

const PAGES = [
  ['01-dashboard', '/dashboard'],
  ['02-signals', '/signals'],
  ['03-ai', '/ai-predictions'],
  ['04-research', '/research'],
  ['05-markets', '/markets'],
  ['06-backtests', '/backtests'],
  ['07-replay', '/backtests/replay'],
] as const;

test('screenshot all trader pages', async ({ page }) => {
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  const errors: string[] = [];
  page.on('console', (msg) => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', (err) => errors.push('PAGE_ERR: ' + err.message));

  await page.goto(`${BASE}/login`);
  await page.waitForLoadState('domcontentloaded');
  await page.screenshot({ path: `${OUT}/00-login.png` });

  await mockAuth(page, 'trader');

  for (const [name, routePath] of PAGES) {
    errors.length = 0;
    await page.goto(`${BASE}${routePath}`);
    await page.waitForLoadState('domcontentloaded');
    await page.locator('body').waitFor({ state: 'visible' });
    await page.waitForTimeout(1500);
    await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: true });
    const url = page.url();
    const text = await page.evaluate(() => document.body.innerText.replace(/\s+/g, ' ').substring(0, 700));
    console.log(`[${name}] URL: ${url}`);
    console.log(`[${name}] Text: ${text}`);
    if (errors.length > 0) console.log(`[${name}] ERRORS: ${errors.slice(0, 3).join(' || ')}`);
    console.log('---');
  }
});
