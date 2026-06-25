import { test, expect, type Page } from '@playwright/test';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const testDir = path.dirname(fileURLToPath(import.meta.url));
const repoRoot = path.resolve(testDir, '..', '..', '..');
const artifactBefore = path.join(repoRoot, 'artifacts', 'trader-cross-page-before.json');
const artifactAfter = path.join(repoRoot, 'artifacts', 'trader-cross-page-after.json');
const baseUrl = (process.env.AUDIT_BASE_URL ?? process.env.PLAYWRIGHT_BASE_URL ?? 'https://dashboard.wajidali.us').replace(/\/$/, '');
const traderEmail = process.env.NERVYX_TRADER_EMAIL ?? 'wajidali1984@hotmail.com';
const traderPassword = process.env.NERVYX_TRADER_PASSWORD ?? '';

interface FieldObservation {
  page: string;
  route: string;
  fieldId: string;
  value: string;
  source: string | null;
  sourceType: string | null;
  timestamp: string | null;
  ageMs: string | null;
  quality: string | null;
}

const routePlan: Array<{ page: string; route: string; expectedFields: string[] }> = [
  { page: 'Account Settings', route: '/account-settings', expectedFields: ['account.equity'] },
  { page: 'Dashboard', route: '/dashboard', expectedFields: ['account.equity', 'account.available_balance', 'account.unrealized_pnl', 'account.open_position_count', 'signal.id', 'signal.confidence', 'position.risk_status'] },
  { page: 'Portfolio', route: '/portfolio', expectedFields: ['account.equity', 'account.available_balance', 'account.unrealized_pnl', 'account.open_position_count', 'position.risk_status'] },
  { page: 'Positions', route: '/portfolio', expectedFields: ['account.unrealized_pnl', 'account.open_position_count', 'position.risk_status'] },
  { page: 'Markets', route: '/markets', expectedFields: ['market.last_price', 'market.mark_price', 'market.index_price'] },
  { page: 'Market BTCUSDT', route: '/market/BTCUSDT', expectedFields: ['market.last_price', 'market.mark_price', 'market.index_price'] },
  { page: 'Trade', route: '/trade', expectedFields: ['account.available_balance', 'market.last_price', 'market.mark_price', 'market.index_price', 'signal.id', 'position.risk_status'] },
  { page: 'Signals', route: '/signals', expectedFields: ['signal.id', 'signal.confidence'] },
  { page: 'AI Predictions', route: '/ai-predictions', expectedFields: ['signal.id', 'signal.confidence'] },
];

const comparisons = [
  { name: 'account equity', fieldId: 'account.equity', pages: ['Dashboard', 'Portfolio', 'Account Settings'] },
  { name: 'available balance', fieldId: 'account.available_balance', pages: ['Dashboard', 'Portfolio', 'Trade'] },
  { name: 'unrealized PnL', fieldId: 'account.unrealized_pnl', pages: ['Dashboard', 'Portfolio', 'Positions'] },
  { name: 'position count', fieldId: 'account.open_position_count', pages: ['Dashboard', 'Portfolio', 'Positions'] },
  { name: 'market last price', fieldId: 'market.last_price', pages: ['Markets', 'Market BTCUSDT', 'Trade'] },
  { name: 'market mark price', fieldId: 'market.mark_price', pages: ['Markets', 'Market BTCUSDT', 'Trade'] },
  { name: 'market index price', fieldId: 'market.index_price', pages: ['Markets', 'Market BTCUSDT', 'Trade'] },
  { name: 'active signal', fieldId: 'signal.id', pages: ['Dashboard', 'Signals', 'AI Predictions', 'Trade'] },
  { name: 'signal confidence', fieldId: 'signal.confidence', pages: ['Dashboard', 'Signals', 'AI Predictions'] },
  { name: 'risk status', fieldId: 'position.risk_status', pages: ['Dashboard', 'Portfolio', 'Positions', 'Trade'] },
];

test.setTimeout(120_000);

function writeArtifact(payload: unknown): void {
  fs.mkdirSync(path.dirname(artifactBefore), { recursive: true });
  const target = process.env.TRADER_CONSISTENCY_PHASE === 'after' ? artifactAfter : artifactBefore;
  fs.writeFileSync(target, `${JSON.stringify(payload, null, 2)}\n`);
}

async function login(page: Page): Promise<void> {
  expect(traderPassword, 'NERVYX_TRADER_PASSWORD must be set in the Playwright environment').not.toBe('');
  await page.goto(`${baseUrl}/login?returnTo=${encodeURIComponent('/dashboard')}`, { waitUntil: 'domcontentloaded' });
  await page.getByLabel(/email/i).fill(traderEmail);
  await page.locator('input[name="password"], #login-password').fill(traderPassword);
  await Promise.all([
    page.waitForURL((url) => !url.pathname.startsWith('/login'), { timeout: 30_000 }),
    page.getByRole('button', { name: /sign in/i }).click(),
  ]);
}

async function collectFields(page: Page, pageName: string, route: string, expectedFields: string[]): Promise<FieldObservation[]> {
  await page.goto(`${baseUrl}${route}`, { waitUntil: 'domcontentloaded', timeout: 45_000 });
  await page.waitForLoadState('networkidle', { timeout: 5_000 }).catch(() => undefined);
  await page.locator('[data-field-id]').first().waitFor({ state: 'attached', timeout: 10_000 }).catch(() => undefined);
  for (const fieldId of expectedFields) {
    await page.locator(`[data-field-id="${fieldId}"]`).first().waitFor({ state: 'attached', timeout: 12_000 }).catch(() => undefined);
  }
  await page.waitForTimeout(1_000);
  return page.locator('[data-field-id]').evaluateAll((nodes, pageInfo) => (
    nodes.map((node) => {
      const element = node as HTMLElement;
      return {
        page: pageInfo.pageName,
        route: pageInfo.route,
        fieldId: element.getAttribute('data-field-id') ?? '',
        value: (element.textContent ?? '').replace(/\s+/g, ' ').trim(),
        source: element.getAttribute('data-source'),
        sourceType: element.getAttribute('data-source-type'),
        timestamp: element.getAttribute('data-timestamp'),
        ageMs: element.getAttribute('data-age-ms'),
        quality: element.getAttribute('data-quality'),
      };
    })
  ), { pageName, route });
}

function comparableValue(value: string): string {
  return value.replace(/[$,%\s]/g, '').trim().toUpperCase();
}

test('trader canonical fields are consistent across deployed pages', async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: Array<{ url: string; method: string; failure: string | null }> = [];
  const navigationErrors: Array<{ page: string; route: string; error: string }> = [];
  page.on('console', (message) => {
    if (message.type() === 'error') consoleErrors.push(message.text());
  });
  page.on('requestfailed', (request) => {
    failedRequests.push({
      url: request.url(),
      method: request.method(),
      failure: request.failure()?.errorText ?? null,
    });
  });

  await login(page);

  const observations: FieldObservation[] = [];
  for (const target of routePlan) {
    try {
      observations.push(...await collectFields(page, target.page, target.route, target.expectedFields));
    } catch (error) {
      navigationErrors.push({
        page: target.page,
        route: target.route,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }

  const mismatches: unknown[] = [];
  const missing: unknown[] = [];
  for (const comparison of comparisons) {
    const rows = comparison.pages.map((pageName) => observations.find((row) => row.page === pageName && row.fieldId === comparison.fieldId));
    if (rows.some((row) => !row)) {
      missing.push({ comparison: comparison.name, fieldId: comparison.fieldId, pages: comparison.pages, found: rows.filter(Boolean).map((row) => row?.page) });
      continue;
    }
    const values = rows.map((row) => comparableValue(row?.value ?? ''));
    const unique = [...new Set(values)];
    if (unique.length > 1) {
      mismatches.push({ comparison: comparison.name, fieldId: comparison.fieldId, rows });
    }
  }

  const artifact = {
    generated_at: new Date().toISOString(),
    base_url: baseUrl,
    phase: process.env.TRADER_CONSISTENCY_PHASE ?? 'before',
    observation_count: observations.length,
    comparisons,
    missing,
    mismatches,
    navigation_errors: navigationErrors,
    console_errors: consoleErrors,
    failed_requests: failedRequests,
    release_blocker: missing.length > 0 || mismatches.length > 0 || navigationErrors.length > 0 || consoleErrors.length > 0 || failedRequests.length > 0,
  };
  writeArtifact(artifact);

  expect(consoleErrors).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(navigationErrors).toEqual([]);
  expect(missing).toEqual([]);
  expect(mismatches).toEqual([]);
});
