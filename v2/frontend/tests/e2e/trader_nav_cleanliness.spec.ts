import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';
import { LEGACY_REDIRECTS, PUBLIC_PAGE_PATHS } from './helpers/routeContracts';
import { marketFavoriteSymbolSet } from '../../src/pages/markets';
import { normalizeWatchlistInput } from '../../src/pages/account-settings';
import { sourceText as portfolioSourceText } from '../../src/pages/positions';
import { MERGED_LEGACY_PATHS } from '../../src/pages/productNavigation';

const FORBIDDEN_NAV = [
  'admin',
  'operator',
  'war room',
  'mission control',
  'codex',
  'claude',
  'ollama',
  'build',
  'coverage',
  'migration',
  'scripts',
  'logs',
  'payload',
  'proof',
  'local role',
] as const;

async function mockAuth(page: Page, role: 'admin' | null): Promise<void> {
  await page.route('**/api/auth/me', async (route) => {
    if (!role) {
      await route.fulfill({ status: 401, contentType: 'application/json', body: JSON.stringify({ detail: 'authentication_required' }) });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        user: {
          id: 'admin-id',
          trader_id: 'admin-trader',
          username: 'admin',
          email: 'admin@example.com',
          role,
          paper_account_id: null,
          exchange_accounts: [],
          watchlist: [],
          alert_preferences: {},
          is_active: true,
          created_at: '2026-06-13T00:00:00Z',
          updated_at: '2026-06-13T00:00:00Z',
          last_login: null,
        },
      }),
    });
  });
}

test.describe('trader nav cleanliness', () => {
  test('markets favorites prefer authenticated trader watchlist values', () => {
    expect([...marketFavoriteSymbolSet(['ethusdt', 'SOLUSDT', 'bad/symbol', 'ETHUSDT'])]).toEqual(['ETHUSDT', 'SOLUSDT']);
    expect(marketFavoriteSymbolSet([]).has('BTCUSDT')).toBe(true);
  });

  test('account watchlist input normalizes symbols before save', () => {
    expect(normalizeWatchlistInput(' ethusdt, BTCUSDT bad/symbol ETHUSDT xrpUSDT ')).toEqual(['ETHUSDT', 'BTCUSDT', 'XRPUSDT']);
  });

  test('portfolio source copy does not mislabel trader-scoped data as fallback', () => {
    expect(portfolioSourceText('Trader account source')).toBe('Trader account source');
    expect(portfolioSourceText('/api/v2/portfolio')).toBe('Trader account source');
    expect(portfolioSourceText('Trader-specific account source required')).toBe('Trader-specific account source required');
    expect(portfolioSourceText('Fallback account data withheld')).toBe('Fallback account data withheld');
    expect(portfolioSourceText('unavailable')).toBe('Data source unavailable');
  });

  test('shared route contract lists canonical trader redirects for legacy app aliases', () => {
    expect(LEGACY_REDIRECTS['/admin/mission-control']).toBe('/dashboard');
    expect(LEGACY_REDIRECTS['/admin/signal-explainability']).toBe('/signals');
    expect(LEGACY_REDIRECTS['/admin/signals']).toBe('/signals');
    expect(LEGACY_REDIRECTS['/admin/executions']).toBe('/portfolio/executions');
    expect(LEGACY_REDIRECTS['/admin/positions']).toBe('/portfolio');
    expect(LEGACY_REDIRECTS['/admin/market-intelligence']).toBe('/research');
    expect(LEGACY_REDIRECTS['/admin/strategy-backtesting']).toBe('/backtests');
    expect(LEGACY_REDIRECTS['/admin/technical-analysis']).toBe('/research');
    expect(LEGACY_REDIRECTS['/admin/liquidation-bridge']).toBe('/derivatives');
    expect(LEGACY_REDIRECTS['/admin/replay']).toBe('/backtests');
    expect(LEGACY_REDIRECTS['/trader']).toBe('/trade');
    expect(LEGACY_REDIRECTS['/history']).toBe('/portfolio/history');
    for (const [legacyPath, canonicalPath] of Object.entries(LEGACY_REDIRECTS)) {
      expect(MERGED_LEGACY_PATHS[legacyPath]).toBe(canonicalPath);
    }
  });

  test('shared route contract tracks canonical public home and mounted landing route', () => {
    expect(PUBLIC_PAGE_PATHS).toContain('/');
    expect(PUBLIC_PAGE_PATHS).toContain('/landing');
    expect(PUBLIC_PAGE_PATHS).toContain('/status-simple');
    expect(LEGACY_REDIRECTS['/landing-legacy']).toBe('/landing');
    expect(MERGED_LEGACY_PATHS['/landing-legacy']).toBe('/landing');
    expect(MERGED_LEGACY_PATHS['/status-simple']).toBeUndefined();
  });

  test('canonical public home renders safely while mounted landing remains available', async ({ page }) => {
    await gotoAs(page, '/', 'public');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/$/);
    await expect(page.locator('body')).not.toContainText(/operator|mission control|war room|payload|local role|role override/i);
  });

  test('dashboard exposes websocket status and avoids stale paper status APIs', async ({ page }) => {
    const staleApiRequests: string[] = [];
    await page.route('**/api/v2/paper/status**', async (route) => {
      staleApiRequests.push(route.request().url());
      await route.abort();
    });
    await page.route('**/api/v2/paper/fills**', async (route) => {
      staleApiRequests.push(route.request().url());
      await route.abort();
    });

    await gotoAs(page, '/dashboard', 'trader');
    await expect(page.getByTestId('dashboard-websocket-status')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Paper Equity|Paper Fills|Paper Account|Paper\/read-only/i);
    expect(staleApiRequests).toEqual([]);
  });

  test('topbar primary navigation stays aligned without module-chip wrapping', async ({ page }) => {
    for (const viewport of [
      { width: 1365, height: 900 },
      { width: 900, height: 900 },
    ]) {
      await page.setViewportSize(viewport);
      await gotoAs(page, '/dashboard', 'trader');
      await expect(page.getByTestId('topbar')).toBeVisible();
      await expect(page.locator('.live-block-banner')).toHaveCount(0);
      await expect(page.getByTestId('topbar')).not.toContainText(/SENSE|EXECUTE|CORE|REPLAY|OBSERVE|Live trading platform/i);

      const linkBoxes = await page.locator('.topbar-primary-nav__link').evaluateAll((links) => links.map((link) => {
        const rect = link.getBoundingClientRect();
        return {
          text: link.textContent?.replace(/\s+/g, ' ').trim() ?? '',
          top: rect.top,
          right: rect.right,
          bottom: rect.bottom,
          left: rect.left,
          height: rect.height,
          whiteSpace: window.getComputedStyle(link).whiteSpace,
        };
      }));

      expect(linkBoxes.length).toBeGreaterThan(8);
      for (const link of linkBoxes) {
        expect(link.text).toMatch(/Dashboard|Markets|Trade|Derivatives|Signals|AI|Portfolio|Backtests|Research|Alerts/);
        expect(link.height).toBeLessThanOrEqual(38);
        expect(link.whiteSpace).toBe('nowrap');
      }

      for (let index = 0; index < linkBoxes.length - 1; index += 1) {
        const current = linkBoxes[index];
        const next = linkBoxes[index + 1];
        const sameRow = Math.abs(current.top - next.top) < 2;
        if (sameRow) {
          expect(current.right, `${current.text} overlaps ${next.text} at ${viewport.width}px`).toBeLessThanOrEqual(next.left + 1);
        } else {
          expect(current.bottom, `${current.text} vertically collides with ${next.text} at ${viewport.width}px`).toBeLessThanOrEqual(next.top + 1);
        }
      }
    }
  });

  test('login page does not expose simulated-disabled product copy', async ({ page }) => {
    await gotoAs(page, '/login', 'public');
    await expect(page.getByTestId('page-login')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Simulated trading platform|Live trading permanently disabled/i);
  });

  test('research page hydrates live ticker and adaptive-capital data', async ({ page }) => {
    test.setTimeout(60_000);
    await gotoAs(page, '/research', 'trader');
    await expect(page.getByTestId('market-ticker-strip')).toContainText(/BTC/i, { timeout: 20_000 });
    await expect(page.getByTestId('adaptive-capital-telemetry-panel')).not.toContainText(/CONNECTING/i, { timeout: 45_000 });
    const panelText = await page.getByTestId('adaptive-capital-telemetry-panel').innerText();
    expect(panelText).toMatch(/PASSED|NO_GO|READY/i);
    expect(panelText).toMatch(/EVALUATED\s+[1-9][\d,]*/i);
    expect(panelText).toMatch(/UNIVERSE\s+[1-9][\d,]* symbols/i);
    expect(panelText).toMatch(/TF CELLS\s+[1-9][\d,]*\/[1-9][\d,]*/i);
    expect(panelText).not.toMatch(/RESEARCH SIGNAL ACCURACY \+ CAPITAL PRODUCTIVITY\s+CONNECTING/i);
  });

  test('account exchange linking rejects private-looking metadata in the UI', async ({ page }) => {
    await gotoAs(page, '/account-settings', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await page.getByRole('button', { name: /Link account/i }).click();
    await page.getByLabel(/Account label/i).fill('my api secret');

    await expect(page.getByText('Account labels cannot contain private exchange values.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Link Binance account/i })).toBeDisabled();
  });

  test('account settings hides raw trader and paper account identifiers from main UI', async ({ page }) => {
    await gotoAs(page, '/account-settings', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.getByText(/Trading profile/i)).toBeVisible();
    await expect(page.getByTestId('page-account-settings').getByText(/^Paper workspace$/i)).toBeVisible();
    await expect(page.getByTestId('page-account-settings').getByText(/Paper \/ read-only/i)).toBeVisible();
    expect(text).not.toMatch(/trader_id|paper_account_id|test-trader|paper-trader|server admin|env var|invalid_watchlist_symbol/i);
  });

  test('account settings uses explicit unavailable labels for missing profile fields', async ({ page }) => {
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'profile-missing',
            trader_id: 'profile-trader',
            username: null,
            email: null,
            role: 'trader',
            paper_account_id: 'profile-paper',
            exchange_accounts: [],
            watchlist: [],
            alert_preferences: {},
            is_active: true,
            created_at: '2026-06-13T00:00:00Z',
            updated_at: '2026-06-13T00:00:00Z',
            last_login: null,
          },
        }),
      });
    });

    await gotoAs(page, '/account-settings');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.locator('#account-profile').getByText('Unavailable')).toHaveCount(2);
    expect(await page.locator('body').innerText()).not.toContain('—');
  });

  test('account settings disables exchange linking without trader account scope', async ({ page }) => {
    await gotoAs(page, '/account-settings', 'viewer');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.getByText(/Exchange linking requires an assigned trader profile and paper workspace/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Link account/i })).toBeDisabled();
  });

  test('account settings disables exchange linking for scoped viewer until trader approval', async ({ page }) => {
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'viewer-scoped',
            trader_id: 'viewer-trader-scope',
            username: 'viewer_scoped',
            email: 'viewer-scoped@test.alphaforge.local',
            role: 'viewer',
            paper_account_id: 'viewer-paper-scope',
            exchange_accounts: [],
            watchlist: [],
            alert_preferences: {},
            is_active: true,
            created_at: '2026-06-13T00:00:00Z',
            updated_at: '2026-06-13T00:00:00Z',
            last_login: '2026-06-13T00:00:00Z',
          },
        }),
      });
    });

    await gotoAs(page, '/account-settings');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByText(/Trader approval is required before linking an exchange account/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Link account/i })).toBeDisabled();
    expect(text).not.toMatch(/trader_role_required/i);
  });

  test('account settings fails closed for signed-in trader with incomplete paper scope', async ({ page }) => {
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'test-trader-incomplete',
            trader_id: 'test-trader-incomplete',
            username: 'test_trader_incomplete',
            email: 'trader-incomplete@test.alphaforge.local',
            role: 'trader',
            paper_account_id: null,
            exchange_accounts: [],
            watchlist: [],
            alert_preferences: {},
            is_active: true,
            created_at: '2026-06-13T00:00:00Z',
            updated_at: '2026-06-13T00:00:00Z',
            last_login: '2026-06-13T00:00:00Z',
          },
        }),
      });
    });

    await gotoAs(page, '/account-settings');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.getByTestId('page-account-settings').getByText(/Account scope incomplete/i)).toBeVisible();
    await expect(page.getByText(/Exchange linking requires an assigned trader profile and paper workspace/i)).toBeVisible();
    await expect(page.getByRole('button', { name: /Link account/i })).toBeDisabled();
    expect(text).not.toMatch(/Account scope: Authenticated trader account/i);
  });

  test('trader context distinguishes complete paper scope from missing exchange metadata', async ({ page }) => {
    await page.route('**/api/auth/me', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          user: {
            id: 'trader-no-exchange',
            trader_id: 'trader-no-exchange',
            username: 'trader_no_exchange',
            email: 'trader-no-exchange@test.alphaforge.local',
            role: 'trader',
            paper_account_id: 'paper-no-exchange',
            exchange_accounts: [],
            watchlist: [],
            alert_preferences: {},
            is_active: true,
            created_at: '2026-06-13T00:00:00Z',
            updated_at: '2026-06-13T00:00:00Z',
            last_login: '2026-06-13T00:00:00Z',
          },
        }),
      });
    });

    await gotoAs(page, '/trade');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByText(/Authenticated trader account/i)).toBeVisible();
    await expect(page.getByTestId('page-trader').getByText(/Exchange account unavailable/i).first()).toBeVisible();
    expect(text).not.toMatch(/Account scope incomplete/i);
  });

  test('public trader shell exposes chart navigation without internal terms', async ({ page }) => {
    const blockedShellPayloadRequests: string[] = [];
    for (const pattern of [
      '**/operator_runtime/v2_runtime_truth/**',
      '**/operator_runtime/paper_online/**',
      '**/operator_runtime/v2_system_observability/**',
      '**/operator_runtime/v2_portfolio_state/**',
      '**/operator_runtime/v2_tonight_readiness/**',
    ]) {
      await page.route(pattern, async (route) => {
        blockedShellPayloadRequests.push(route.request().url());
        await route.abort();
      });
    }

    await gotoAs(page, '/dashboard', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const chartLink = page.getByRole('link', { name: /^Chart$/ });
    await expect(chartLink).toBeVisible();
    await expect(chartLink).toHaveAttribute('href', '/chart/BTCUSDT');
    const text = await page.locator('body').innerText();
    await expect(page.getByText(/Paper workspace: Paper workspace connected/i)).toBeVisible();
    expect(text).not.toMatch(/operator|mission control|payload|proof|local role|paper_account_id|trader_id|test-trader|paper-trader|Ingestors:|Redis:/i);
    expect(blockedShellPayloadRequests).toEqual([]);
  });

  test('public and trader nav avoids internal/admin terminology', async ({ page }) => {
    await mockAuth(page, null);
    for (const route of ['/landing', '/status', '/login', '/trade', '/market/BTCUSDT', '/chart/BTCUSDT']) {
      await gotoAs(page, route);
      await page.waitForLoadState('networkidle').catch(() => undefined);
      const text = await page.locator('body').innerText();
      for (const forbidden of FORBIDDEN_NAV) {
        expect(text, `${route} contains forbidden string ${forbidden}`).not.toMatch(new RegExp(forbidden, 'i'));
      }
      expect(text).not.toMatch(/AI BOT V2|Control Plane/i);
    }
  });

  test('admin nav appears only after backend-confirmed admin role', async ({ page }) => {
    await mockAuth(page, null);
    await gotoAs(page, '/dashboard');
    await expect(page.getByTestId('admin-nav')).toHaveCount(0);

    await page.unroute('**/api/auth/me');
    await mockAuth(page, 'admin');
    await gotoAs(page, '/dashboard');
    await expect(page.getByTestId('admin-nav')).toBeVisible();
  });

  test('portfolio executions route shows trader-scoped paper activity instead of operator diagnostics', async ({ page }) => {
    await gotoAs(page, '/portfolio/executions', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-executions')).toBeVisible();
    await expect(page.getByText(/Paper Execution Account/i)).toBeVisible();
    await expect(page.getByTestId('page-executions').getByText(/Paper \/ read-only/i)).toBeVisible();
    expect(text).not.toMatch(/Live Transport First-Order Hold|Compliant Recovery|Audited Failover|available_margin|order_submission_allowed/i);
  });

  test('portfolio route shows scoped paper account summary instead of unscoped diagnostics', async ({ page }) => {
    await gotoAs(page, '/portfolio', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-positions')).toBeVisible();
    await expect(page.getByText(/Trader Account Scope/i)).toBeVisible();
    await expect(page.getByText(/Paper Portfolio Summary/i)).toBeVisible();
    await expect(page.getByTestId('page-positions').getByText(/Paper \/ read-only/i)).toBeVisible();
    expect(text).not.toMatch(/operator_runtime|payload|available_margin|order_submission_allowed|live transport/i);
  });

  test('portfolio history route shows trader-scoped typed history instead of fallback ledger diagnostics', async ({ page }) => {
    await gotoAs(page, '/portfolio/history', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-history')).toBeVisible();
    await expect(page.getByText(/Paper History Account/i)).toBeVisible();
    await expect(page.getByTestId('page-history').getByText(/Paper \/ read-only/i)).toBeVisible();
    expect(text).not.toMatch(/paper ledger tail|legacy signal-history|operator_runtime|CUDA Trainer/i);
  });

  test('signals route shows trader-safe signal evidence instead of admin realtime panels', async ({ page }) => {
    await gotoAs(page, '/signals', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    const summary = page.getByTestId('cockpit-signals-active-summary');
    await expect(page.getByTestId('page-signals')).toBeVisible();
    await expect(summary).toBeVisible();
    await expect(page.getByTestId('cockpit-signals-evidence')).toBeVisible();
    const summaryText = await summary.innerText();
    expect(summaryText).toMatch(/Active Signal Summary/i);
    expect(summaryText).toMatch(/Signal feed/i);
    expect(summaryText).not.toMatch(/Signal source/i);
    expect(text).not.toMatch(/runtime monitor payload|all-timeframe prediction matrix|signals-admin|operator|payload|operator_dashboard_payload|\/operator_runtime|\/home\/wali/i);
  });

  test('derivatives route shows market analytics with missing-source states instead of runtime diagnostics', async ({ page }) => {
    await gotoAs(page, '/derivatives', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-liquidation-bridge')).toBeVisible();
    await expect(page.getByText(/Derivatives Snapshot/i)).toBeVisible();
    await expect(page.getByText(/Derivative Data Gaps/i)).toBeVisible();
    await expect(page.getByText(/Liquidation stream/i).first()).toBeVisible();
    await expect(page.getByText(/Liquidation levels/i).first()).toBeVisible();
    await expect(page.getByText(/Partial derivatives source|Stale derivatives source|Current derivatives source|Data source unavailable/i).first()).toBeVisible();
    expect(text).not.toMatch(/liquidation ingestor|wss client|runtime status|operator_dashboard|payload|writes_legacy/i);
  });

  test('alerts route shows professional paper/unavailable state instead of payload telemetry', async ({ page }) => {
    await gotoAs(page, '/alerts', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-alerts')).toBeVisible();
    await expect(page.getByText(/Alert Readiness/i)).toBeVisible();
    await expect(page.getByText(/Alert actions unavailable|Notification delivery unavailable|Paper alerts available/i)).toBeVisible();
    expect(text).not.toMatch(/operator_runtime|payload|current_blockers|paper_online|source present/i);
  });

  test('ai predictions route shows trader-safe forecast evidence instead of trainer runtime internals', async ({ page }) => {
    await gotoAs(page, '/ai-predictions', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-trainer-prediction-monitor')).toBeVisible();
    await expect(page.getByText(/Current Prediction/i)).toBeVisible();
    await expect(page.getByText(/Prediction Evidence/i)).toBeVisible();
    await expect(page.getByText(/Paper forecast evidence only/i)).toBeVisible();
    await expect(page.getByText(/not strategy-performance evidence/i)).toBeVisible();
    await expect(page.getByTestId('runtime-alpha-dynamic-readiness-panel')).toHaveCount(0);
    expect(text).not.toMatch(/operator_dashboard|payload|runtime alpha|checkpoint/i);
  });

  test('model-state route redirects directly to the cleaned AI predictions page', async ({ page }) => {
    await gotoAs(page, '/ai-predictions/model-state', 'trader', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/ai-predictions$/);
    await expect(page.getByTestId('page-trainer-prediction-monitor')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Model State|legacy hybrid parity|runtime alpha|checkpoint|operator_dashboard|payload/i);
  });

  test('legacy admin model-state alias redirects directly to the admin model-state page', async ({ page }) => {
    await gotoAs(page, '/admin/ai-brain', 'admin', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/admin\/model-state$/);
    await expect(page.getByTestId('page-ai-brain')).toBeVisible();
    await expect(page.getByTestId('runtime-alpha-dynamic-readiness-panel')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload/i);
  });

  test('legacy paper trading route redirects to the canonical trade terminal', async ({ page }) => {
    await gotoAs(page, '/trade/paper', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/trade$/);
    await expect(page.getByTestId('page-trader')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/CUDA Trainer Paper Signal Lineage|Operator Review|live paper \/ shadow trading loop/i);
  });

  test('legacy market symbols route redirects to the canonical markets screener', async ({ page }) => {
    await gotoAs(page, '/markets/symbols', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/markets$/);
    await expect(page.getByTestId('page-markets')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload|symbol universe worker|live gate/i);
  });

  test('legacy admin market symbols alias redirects directly to the canonical markets screener', async ({ page }) => {
    await gotoAs(page, '/admin/symbols', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/markets$/);
    await expect(page.getByTestId('page-markets')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload|symbol universe worker|live gate/i);
  });

  test('legacy admin signal explainability alias redirects directly to the trader-safe signals page', async ({ page }) => {
    await gotoAs(page, '/admin/signal-explainability', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/signals$/);
    await expect(page.getByTestId('page-signals')).toBeVisible();
    await expect(page.getByTestId('cockpit-signals-active-summary')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Signal Explainability|Static proof examples|orchestrator reason|operator|payload|\/operator_runtime/i);
  });

  test('legacy replay route redirects to the cleaned backtests page', async ({ page }) => {
    await gotoAs(page, '/backtests/replay', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/backtests$/);
    await expect(page.getByTestId('page-strategy-backtesting')).toBeVisible();
    await expect(page.getByText(/Backtest engine unavailable/i)).toBeVisible();
    await expect(page.getByText(/Paper account context only/i)).toBeVisible();
    await expect(page.getByText(/not backtest results/i)).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/CUDA Actionability|Pipeline Control|operator role|required|payload/i);
  });

  test('legacy admin replay alias redirects directly to the cleaned backtests page', async ({ page }) => {
    await gotoAs(page, '/admin/replay', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/backtests$/);
    await expect(page.getByTestId('page-strategy-backtesting')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/CUDA Actionability|Pipeline Control|operator role|required|payload/i);
  });

  test('legacy admin technical-analysis alias redirects directly to the research page', async ({ page }) => {
    await gotoAs(page, '/admin/technical-analysis', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/technical analysis runtime|operator_dashboard|payload|live gate|\/operator_runtime/i);
  });

  test('research route separates read-only market context from missing research API', async ({ page }) => {
    await gotoAs(page, '/research', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    const body = page.locator('body');
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(body).toContainText(/Research source pending/i);
    await expect(body).toContainText(/Research API/i);
    await expect(body).toContainText(/Data source unavailable/i);
    await expect(body).toContainText(/Market context/i);
    await expect(body).not.toContainText(/Data source checked/i);
    await expect(body).not.toContainText(/V2_NATIVE|technical_analysis|Redis keys|payload|feature pipeline/i);
  });

  test('legacy technical-analysis route redirects to the cleaned research page', async ({ page }) => {
    await gotoAs(page, '/research/technical-analysis', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(page.getByText(/Research workbench incomplete/i)).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/V2_NATIVE|technical_analysis|Redis keys|payload|feature pipeline/i);
  });

  test('legacy admin technical-analysis alias redirects directly to the cleaned research page', async ({ page }) => {
    await gotoAs(page, '/admin/technical-analysis', 'trader');
    await page.waitForLoadState('networkidle').catch(() => undefined);

    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/V2_NATIVE|technical_analysis|Redis keys|payload|feature pipeline/i);
  });
});
