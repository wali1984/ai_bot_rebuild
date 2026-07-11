import { expect, test, type Page } from '@playwright/test';
import { gotoAs } from './_shared';
import { LEGACY_REDIRECTS, PUBLIC_PAGE_PATHS } from './helpers/routeContracts';
import { mockAuth as mockBackendAuth, type TestAuthRole } from './helpers/auth';
import {
  marketFavoriteSymbolSet,
  normalizeWatchlistInput,
  sourceText as portfolioSourceText,
} from '../../src/lib/traderPageHelpers';
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

const AUTH_ME_PATTERN = '**/api/auth/me';

async function setAuth(page: Page, role: TestAuthRole): Promise<void> {
  await page.unroute(AUTH_ME_PATTERN).catch(() => undefined);
  await mockBackendAuth(page, role);
}

async function gotoWithAuth(
  page: Page,
  path: string,
  role: TestAuthRole = 'trader',
  options?: Parameters<Page['goto']>[1],
): Promise<void> {
  await setAuth(page, role);
  await gotoAs(page, path, undefined, options);
  await page.waitForLoadState('domcontentloaded').catch(() => undefined);
  if (role !== 'public' && role !== 'guest' && /\/login(?:\?|$)/.test(page.url())) {
    await page.goto(path, options ?? { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);
  }
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
    expect(MERGED_LEGACY_PATHS['/admin/signal-explainability']).toBeUndefined();
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
    await gotoWithAuth(page, '/', 'public');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

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

    await gotoWithAuth(page, '/dashboard');
    await expect(page.getByTestId('dashboard-websocket-status')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Paper Equity|Paper Fills|Paper Account|Paper\/read-only/i);
    expect(staleApiRequests).toEqual([]);
  });

  test('dashboard first screen exposes canonical control-center truth without fake live approval', async ({ page }) => {
    await page.route('**/api/v2/portfolio**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          data: {
            equity: 3000.68,
            paper_equity_usd: 3000.68,
            paper_realized_pnl_usd: 0.68,
            paper_unrealized_pnl_usd: 0,
            paper_total_pnl_usd: 0.68,
            total_pnl_usd: 0.68,
            paper_session_id: 'paper-session-dashboard',
            pnl_source_key: 'v2:portfolio:state',
            pnl_source_route: '/api/v2/portfolio',
            positions: [],
            mode: 'paper',
            staleness_seconds: 4,
          },
          source: 'redis:v2:portfolio:state',
          source_type: 'redis_live',
          endpoint: '/api/v2/portfolio',
          freshness_status: 'fresh',
          staleness_seconds: 4,
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
        }),
      });
    });
    await page.route('**/api/v2/live-canary/status**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'control_center_live_canary_status_v1',
          source: 'redis:v2:live_canary:status',
          staleness_seconds: 2,
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            generated_utc: '2026-07-09T20:20:00Z',
            why_none: 'NO_A_PLUS_CANDIDATE',
            dry_run: true,
            operator_approval_required: true,
            no_mutation_flags: {
              real_order_attempted: false,
              real_order_submitted: false,
              test_order_submitted: false,
              leverage_changed: false,
              margin_mode_changed: false,
            },
            status_payload: {
              go_no_go: 'V2_24H_LIVE_CANARY_READY_PENDING_CODEX',
              dry_run: true,
              live_enabled: false,
              places_real_order: false,
              routes_to_live: false,
              real_order_attempted: false,
              real_order_submitted: false,
              test_order_submitted: false,
              leverage_changed: false,
              margin_mode_changed: false,
              fail_blockers: ['GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT'],
            },
          },
        }),
      });
    });
    await page.route('**/api/v2/a-plus/inventory**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'control_center_a_plus_inventory_v1',
          source: 'redis:v2:paper:a_plus_gate:status',
          staleness_seconds: 5,
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            paper_session_id: 'paper-session-dashboard',
            evaluated_candidates: 540,
            a_plus_candidates: 0,
            live_ready_rows: 0,
            counts_as_final_a_plus: false,
          },
        }),
      });
    });
    await page.route('**/api/v2/mobile/risk-status**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'mobile_risk_status_v2',
          source: 'mobile_compact_runtime_contract',
          freshness_status: 'fresh',
          data_quality_status: 'fresh',
          staleness_seconds: 3,
          live_gate: { gate: 'blocked_human_only', label: 'OPERATOR GATED', live_trading_enabled: false, places_real_order: false },
          places_real_order: false,
          routes_to_live: false,
          risk_state: 'HALTED_PERFORMANCE',
          top_blockers: ['BUCKET_QUARANTINE_ACTIVE'],
          probation_5_trade_gate: {
            status: 'PROBATION_5_TRADE_GATE_WAITING_OR_BLOCKED',
            source: 'redis:v2:paper:probation_5_trade_gate',
          },
          positive_edge_probation_runtime_status: {
            status: 'PROBATION_PAPER_ENABLED_WAITING_FOR_VALID_POSITIVE_EDGE_SUPPLY',
          },
          real_trader_readiness: {
            live_ready: false,
            order_submitted: false,
            test_order_submitted: false,
          },
          adaptive_hedge_cross_margin: {
            hedge_state: 'NO_HEDGE',
            portfolio_liquidation_buffer_usd: 998.12,
          },
          preemptive_edge_control: {
            advanced_indicators: {
              sweep_risk_can_block_or_reduce: true,
            },
          },
          provider_readiness: {
            coinglass_dashboard_color: 'GREEN',
            moralis_dashboard_color: 'GRAY',
            santiment_status: 'V2_SANTIMENT_PRO_INGESTOR_READY',
            confluence_hedge_required_score: 0.42,
          },
          market_data_freshness: {
            freshness_state: 'MARKET_FEED_CURRENT',
          },
        }),
      });
    });

    await gotoWithAuth(page, '/dashboard', 'trader', { waitUntil: 'domcontentloaded' });
    const panel = page.getByTestId('dashboard-control-center-truth');
    await expect(panel).toBeVisible({ timeout: 20_000 });
    await expect(panel).toContainText(/Runtime Control Center Truth/i);
    await expect(panel).toContainText(/Live status:\s*LIVE BLOCKED/i);
    await expect(panel).toContainText(/A\+ candidates/i);
    await expect(panel).toContainText(/540 evaluated/i);
    await expect(panel).toContainText(/0 live-ready rows/i);
    await expect(panel).toContainText(/Live canary blocker/i);
    await expect(panel).toContainText(/No A Plus Candidate/i);
    await expect(panel).toContainText(/Paper\/probation gate/i);
    await expect(panel).toContainText(/Signed-read status/i);
    await expect(panel).toContainText(/SIGNED READ PRESENT/i);
    await expect(panel).toContainText('paper_equity_usd');
    await expect(panel).toContainText('paper_total_pnl_usd');
    await expect(panel).toContainText('$0.68');
    await expect(panel).toContainText(/Liquidation buffer/i);
    await expect(panel).toContainText('$998.12');
    await expect(panel).toContainText(/Hedge status/i);
    await expect(panel).toContainText(/Squeeze risk/i);
    await expect(panel).toContainText(/SWEEP GUARD ACTIVE/i);
    await expect(panel).toContainText(/Data freshness/i);
    await expect(panel).toContainText(/NO ORDER \/ TEST \/ LEVERAGE \/ MARGIN MUTATION/i);
    await expect(panel).toContainText(/live_gate=Approval Gated/i);
    await expect(panel).toContainText(/providers=CoinGlass:GREEN/i);
    await expect(panel).not.toContainText(/ready to submit live|live order enabled|goal_state|multiple pnl sources/i);
  });

  test('topbar primary navigation stays aligned without module-chip wrapping', async ({ page }) => {
    for (const viewport of [
      { width: 1365, height: 900 },
      { width: 900, height: 900 },
    ]) {
      await page.setViewportSize(viewport);
      await gotoWithAuth(page, '/dashboard');
      await expect(page.getByTestId('topbar')).toBeVisible();
      await expect(page.locator('.topbar-primary-nav__link')).toHaveCount(10);
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
    await gotoWithAuth(page, '/login', 'public');
    await expect(page.getByTestId('page-login')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Simulated trading platform|Live trading permanently disabled/i);
  });

  test('research page hydrates live ticker and adaptive-capital data', async ({ page }) => {
    test.setTimeout(60_000);
    await gotoWithAuth(page, '/research');
    await expect(page.getByTestId('page-market-intelligence')).toContainText(/Live Binance USD-M screener/i, { timeout: 20_000 });
    await expect(page.getByTestId('adaptive-capital-telemetry-panel')).not.toContainText(/CONNECTING/i, { timeout: 45_000 });
    const panelText = await page.getByTestId('adaptive-capital-telemetry-panel').innerText();
    expect(panelText).toMatch(/PASSED|NO_GO|READY|BLOCKED|Pending/i);
    expect(panelText).toMatch(/EVALUATED\s+(?:[1-9][\d,]*|—)/i);
    expect(panelText).toMatch(/UNIVERSE\s+(?:[1-9][\d,]*|—) symbols/i);
    expect(panelText).toMatch(/TF CELLS\s+(?:[1-9][\d,]*|—)\/(?:[1-9][\d,]*|—)/i);
    expect(panelText).not.toMatch(/RESEARCH SIGNAL ACCURACY \+ CAPITAL PRODUCTIVITY\s+CONNECTING/i);
  });

  test('account exchange linking rejects private-looking metadata in the UI', async ({ page }) => {
    await gotoWithAuth(page, '/account-settings');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await page.getByRole('button', { name: /Link account/i }).click();
    await page.getByLabel(/Account label/i).fill('my api secret');

    await expect(page.getByText('Account labels cannot contain private exchange values.')).toBeVisible();
    await expect(page.getByRole('button', { name: /Link Binance account/i })).toBeDisabled();
  });

  test('account settings hides raw trader and workspace account identifiers from main UI', async ({ page }) => {
    await gotoWithAuth(page, '/account-settings');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.getByText(/Trading profile/i)).toBeVisible();
    await expect(page.getByTestId('page-account-settings').getByText(/^Trading workspace$/i)).toBeVisible();
    await expect(page.getByTestId('page-account-settings').getByText(/^Connected$/i)).toHaveCount(2);
    expect(text).not.toMatch(/trader_id|paper_account_id|test-trader|paper-trader|server admin|env var|invalid_watchlist_symbol/i);
  });

  test('settings alias exposes account safety truth without credential or live-routing exposure', async ({ page }) => {
    await page.route('**/api/auth/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'auth_health_v1',
          source: 'auth_user_store_status',
          canonical_owner: '/api/auth/health',
          status: 'ok',
          staleness_seconds: 1,
          freshness_status: 'fresh',
          data_quality_status: 'degraded',
          login_endpoint_available: true,
          auth_store_backend: 'local_file',
          durable_user_store_configured: false,
          production_ready: false,
          contains_secret_values: false,
          raw_credential_value_exposed: false,
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          exchange_mutation_enabled: false,
        }),
      });
    });

    await gotoWithAuth(page, '/settings', 'trader', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/account-settings$/);
    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    const panel = page.getByTestId('account-settings-runtime-safety-panel');
    await expect(panel).toBeVisible();
    await expect(page.getByText(/Account Runtime Safety/i)).toBeVisible();
    await expect(panel).toContainText('/api/auth/health');
    await expect(panel).toContainText(/Online/i);
    await expect(panel).toContainText(/LIVE BLOCKED|approval gated/i);
    await expect(panel).toContainText(/Account scope complete/i);
    await expect(panel).toContainText(/Trader approval confirmed/i);
    await expect(panel).toContainText(/Metadata only/i);
    await expect(panel).toContainText(/places_real_order=NO/i);
    await expect(panel).toContainText(/routes_to_live=NO/i);
    await expect(panel).toContainText(/exchange_mutation_enabled=NO/i);
    await expect(panel).toContainText(/raw_credential_value_exposed=NO/i);
    await expect(panel).toContainText(/contains_secret_values=NO/i);
    await expect(panel).toContainText(/NO LIVE ROUTING OR SECRET EXPOSURE/i);
    await expect(panel).not.toContainText(/api[_ -]?key|api[_ -]?secret|private[_ -]?key|access[_ -]?token|live order enabled|ready to submit live/i);
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

    await gotoAs(page, '/account-settings', 'trader');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.locator('#account-profile').getByText('Unavailable')).toHaveCount(2);
    expect(await page.locator('body').innerText()).not.toContain('—');
  });

  test('account settings disables exchange linking without trader account scope', async ({ page }) => {
    await gotoWithAuth(page, '/account-settings', 'viewer');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.getByText(/Exchange linking requires an assigned trader profile and execution workspace/i)).toBeVisible();
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
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

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
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-account-settings')).toBeVisible();
    await expect(page.getByTestId('page-account-settings').getByText(/Account scope incomplete/i).first()).toBeVisible();
    await expect(page.getByText(/Exchange linking requires an assigned trader profile and execution workspace/i)).toBeVisible();
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
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-trader')).toContainText(/Trading workspace connected/i);
    await expect(page.getByTestId('page-trader')).toContainText(/Exchange account connecting/i);
    expect(text).not.toMatch(/Account scope incomplete/i);
  });

  test('trade route exposes canonical live-canary and A+ readiness without implying live approval', async ({ page }) => {
    await page.route('**/api/v2/live-canary/status', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'control_center_live_canary_status_v1',
          generated_at_utc: '2026-07-09T20:00:00Z',
          generated_at_et: '2026-07-09T16:00:00-04:00',
          source: 'redis:v2:live_canary:status',
          staleness_seconds: 2,
          freshness_status: 'fresh',
          canonical_owner: '/api/v2/live-canary/status',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data_quality_status: 'fresh',
          data: {
            generated_utc: '2026-07-09T20:00:00Z',
            why_none: 'NO_A_PLUS_CANDIDATE',
            selected_a_plus_candidate: null,
            no_mutation_flags: {
              real_order_attempted: false,
              real_order_submitted: false,
              places_real_order: false,
              routes_to_live: false,
              leverage_changed: false,
              margin_mode_changed: false,
            },
            status_payload: {
              go_no_go: 'V2_24H_LIVE_CANARY_READY_PENDING_CODEX',
              dry_run: true,
              live_enabled: false,
              places_real_order: false,
              routes_to_live: false,
              real_order_attempted: false,
              real_order_submitted: false,
              leverage_changed: false,
              margin_mode_changed: false,
              intent_count: 1,
              fail_blockers: ['GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT'],
              intents: [
                {
                  candidate: { symbol: 'BTCUSDT', side: 'long', timeframe: '5m' },
                  fail_blockers: ['GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER'],
                  dry_run: true,
                  live_enabled: false,
                  places_real_order: false,
                  routes_to_live: false,
                  real_order_attempted: false,
                  real_order_submitted: false,
                  leverage_changed: false,
                  margin_mode_changed: false,
                  live_gate: 'blocked_human_only',
                },
              ],
            },
          },
        }),
      });
    });
    await page.route('**/api/v2/a-plus/inventory', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'control_center_a_plus_inventory_v1',
          generated_at_utc: '2026-07-09T20:00:00Z',
          generated_at_et: '2026-07-09T16:00:00-04:00',
          source: 'redis:v2:paper:a_plus_gate:status',
          staleness_seconds: 4,
          freshness_status: 'fresh',
          canonical_owner: '/api/v2/a-plus/inventory',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data_quality_status: 'fresh',
          data: {
            generated_utc: '2026-07-09T20:00:00Z',
            evaluated_candidates: 347,
            a_plus_candidates: 0,
            live_ready_rows: 0,
            counts_as_final_a_plus: false,
            rejected_reason_matrix: {
              microstructure_trust_confirms: 347,
              risk_allows: 172,
            },
            candidate_matrix_preview: [
              {
                symbol: 'BTCUSDT',
                timeframe: '5m',
                side: 'long',
                failed_checks: ['microstructure_trust_confirms'],
                missing_evidence_checks: ['trade_tape_confirms'],
              },
            ],
          },
        }),
      });
    });

    await gotoAs(page, '/trade', 'trader');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page.getByTestId('page-trader')).toBeVisible();
    await expect(page.getByTestId('trade-execution-readiness-panel')).toContainText('/api/v2/live-canary/status');
    await expect(page.getByTestId('trade-execution-readiness-panel')).toContainText('/api/v2/a-plus/inventory');
    await expect(page.getByTestId('trade-execution-readiness-panel')).toContainText(/Why no trade now/i);
    await expect(page.getByTestId('trade-execution-readiness-panel')).toContainText(/no a\+ candidate/i);
    await expect(page.getByTestId('trade-execution-readiness-panel')).toContainText(/LIVE BLOCKED/i);
    await expect(page.getByTestId('trade-execution-readiness-panel')).toContainText(/no real orders, no test orders, no leverage or margin mutation/i);
    await expect(page.getByTestId('trade-execution-readiness-panel')).not.toContainText(/ready to submit live|live order enabled/i);
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

    await gotoWithAuth(page, '/dashboard');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const tradeLink = page.getByTestId('topbar-primary-nav').getByRole('link', { name: /^Trade$/ });
    await expect(tradeLink).toBeVisible();
    await expect(tradeLink).toHaveAttribute('href', '/trade');
    const text = await page.locator('body').innerText();
    expect(text).not.toMatch(/operator|mission control|payload|proof|local role|paper_account_id|trader_id|test-trader|paper-trader|Ingestors:|Redis:/i);
    expect(blockedShellPayloadRequests).toEqual([]);
  });

  test('public and trader nav avoids internal/admin terminology', async ({ page }) => {
    await setAuth(page, 'public');
    for (const route of ['/landing', '/status', '/login', '/trade', '/market/BTCUSDT', '/chart/BTCUSDT']) {
      await gotoAs(page, route);
      await page.waitForLoadState('domcontentloaded').catch(() => undefined);
      const text = await page.locator('body').innerText();
      for (const forbidden of FORBIDDEN_NAV) {
        expect(text, `${route} contains forbidden string ${forbidden}`).not.toMatch(new RegExp(forbidden, 'i'));
      }
      expect(text).not.toMatch(/AI BOT V2|Control Plane/i);
    }
  });

  test('admin nav appears only after backend-confirmed admin role', async ({ page }) => {
    await setAuth(page, 'public');
    await gotoAs(page, '/dashboard');
    await expect(page.getByTestId('admin-nav')).toHaveCount(0);

    await gotoWithAuth(page, '/dashboard', 'admin');
    await expect(page.getByTestId('admin-nav')).toBeVisible();
  });

  test('risk route exposes liquidation hedge squeeze and kill-switch truth', async ({ page }) => {
    await gotoWithAuth(page, '/risk', 'trader', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/risk$/);
    await expect(page.getByTestId('page-risk')).toBeVisible();
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText('/api/v2/mobile/risk-status');
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Liquidation buffer/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Hedge state/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Squeeze risk/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Kill switch/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).toContainText(/Operator approval/i);
    await expect(page.getByTestId('risk-runtime-truth-panel')).not.toContainText(/live order enabled|ready to submit live/i);
  });

  test('audit-ledger route exposes read-only immutable event truth without live-approver access', async ({ page }) => {
    await page.route('**/api/v2/admin/audit/chain', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          generated_at: '2026-07-09T19:40:00Z',
          chain_length: 1,
          last_entry_at: '2026-07-09T19:39:00Z',
          entries: [
            {
              audit_id: 'audit-runtime-proof-1',
              actor: 'system',
              action: 'provider_truth_refresh',
              result: 'success',
              timestamp: '2026-07-09T19:39:00Z',
              reason: 'control_center_read_only_audit',
              evidence: 'sha256:runtime-proof',
            },
          ],
        }),
      });
    });

    await gotoWithAuth(page, '/audit-ledger', 'viewer', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/audit-ledger$/);
    await expect(page.getByTestId('page-audit-ledger')).toBeVisible();
    await expect(page.getByTestId('access-denied')).toHaveCount(0);
    await expect(page.getByTestId('page-audit-ledger')).toContainText('/api/v2/admin/audit/chain');
    await expect(page.getByTestId('page-audit-ledger')).toContainText(/Immutable audit/i);
    await expect(page.getByTestId('page-audit-ledger')).toContainText(/provider_truth_refresh/i);
    await expect(page.getByTestId('page-audit-ledger')).toContainText(/read-only authenticated view/i);
    await expect(page.getByTestId('page-audit-ledger')).not.toContainText(/place live order|send live order|live order enabled/i);
  });

  test('system-health route exposes viewer-safe auth backend redis and live-gate truth', async ({ page }) => {
    await page.route('**/api/auth/health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'auth_health_v1',
          generated_at_utc: '2026-07-09T19:45:00Z',
          generated_at_et: '2026-07-09T15:45:00-04:00',
          source: 'auth_user_store_status',
          status: 'ok',
          staleness_seconds: 0,
          freshness_status: 'fresh',
          canonical_owner: '/api/auth/health',
          data_quality_status: 'degraded',
          login_endpoint_available: true,
          auth_store_backend: 'local_file',
          durable_user_store_configured: false,
          production_ready: false,
          contains_secret_values: false,
          raw_credential_value_exposed: false,
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          session_security: {
            status: 'partial',
            cookie_httponly: true,
            cookie_secure: true,
            cookie_samesite: 'lax',
            revocation_store_kind: 'local_file',
            auth_user_store: { backend: 'local_file', production_ready: false, missing_fields: ['auth_database_url'] },
            revocation_store: { backend: 'local_file', production_ready: false, missing_fields: ['auth_revocation_database_url'] },
          },
          warnings: ['auth_database_backend', 'auth_database_url'],
        }),
      });
    });
    await page.route('**/api/v2/data-health', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          data: {
            overall: 'partial',
            surfaces: [
              {
                name: 'Market data',
                endpoint: '/api/v2/market/overview',
                status: 'ok',
                description: 'Redis live market overview payloads',
                actual_payload_count: 16,
                source_type: 'redis_live',
                stale: false,
                lag_ms: 42,
                missing_fields: [],
              },
            ],
            count: 1,
          },
          source: 'v2_health_check',
          source_type: 'api',
          endpoint: '/api/v2/data-health',
          generated_at_utc: '2026-07-09T19:45:00Z',
          generated_at_et: '2026-07-09T15:45:00-04:00',
          staleness_seconds: 0,
          freshness_status: 'fresh',
          canonical_owner: '/api/v2/data-health',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data_quality_status: 'fresh',
          mode: 'read_only',
        }),
      });
    });
    await page.route('**/api/v2/system/metrics', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'system_metrics_v1',
          data: {
            cpu: { total_pct: 12, core_count: 32, load_1m: 1.2, load_5m: 1.1, load_15m: 1.0 },
            memory: { used_mb: 16384, total_mb: 65536, percent: 25, swap_used_mb: 0, swap_total_mb: 8192 },
            disk: { mount: '/', used_gb: 220, total_gb: 900, percent: 24 },
            network: { recv_bytes_per_sec: 2048, sent_bytes_per_sec: 1024 },
            gpus: [],
            trainer_gpu_view: null,
            history: [],
          },
          source: '/api/v2/system/metrics',
          source_type: 'api',
          endpoint: '/api/v2/system/metrics',
          generated_at_utc: '2026-07-09T19:45:00Z',
          generated_at_et: '2026-07-09T15:45:00-04:00',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data_quality_status: 'fresh',
        }),
      });
    });

    await gotoWithAuth(page, '/system-health', 'viewer', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/system-health$/);
    await expect(page.getByTestId('system-health-page')).toBeVisible();
    await expect(page.getByTestId('access-denied')).toHaveCount(0);
    await expect(page.getByTestId('system-auth-runtime-panel')).toContainText('/api/auth/health');
    await expect(page.getByTestId('system-auth-runtime-panel')).toContainText('/api/v2/data-health');
    await expect(page.getByTestId('system-auth-runtime-panel')).toContainText(/Auth backend/i);
    await expect(page.getByTestId('system-auth-runtime-panel')).toContainText(/Redis feed/i);
    await expect(page.getByTestId('system-auth-runtime-panel')).toContainText(/blocked human only/i);
    await expect(page.getByTestId('system-auth-runtime-panel')).toContainText(/Secrets exposed/i);
    await expect(page.getByTestId('system-health-page')).toContainText(/System Resources/i);
  });

  test('portfolio executions route shows trader-scoped execution activity instead of operator diagnostics', async ({ page }) => {
    await gotoWithAuth(page, '/portfolio/executions');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-executions')).toBeVisible();
    await expect(page.getByText(/Execution stream/i)).toBeVisible();
    await expect(page.getByTestId('page-executions')).toContainText(/Authenticated trader account/i);
    expect(text).not.toMatch(/Live Transport First-Order Hold|Compliant Recovery|Audited Failover|available_margin|order_submission_allowed/i);
  });

  test('portfolio route shows scoped account summary instead of unscoped diagnostics', async ({ page }) => {
    await gotoWithAuth(page, '/portfolio');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-positions')).toBeVisible();
    await expect(page.getByText(/Account Scope/i)).toBeVisible();
    await expect(page.getByText(/Authenticated trader account/i)).toBeVisible();
    expect(text).not.toMatch(/operator_runtime|payload|available_margin|order_submission_allowed|live transport/i);
  });

  test('portfolio route exposes one canonical paper PnL source and required fields', async ({ page }) => {
    await page.route('**/api/v2/portfolio**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          data: {
            equity: 3000.68,
            paper_equity: 3000.68,
            paper_equity_usd: 3000.68,
            paper_balance: 3000.68,
            paper_realized_pnl_usd: 0.68,
            paper_unrealized_pnl_usd: 0,
            paper_total_pnl_usd: 0.68,
            realized_pnl: 0.68,
            realized_pnl_usd: 0.68,
            realized_net_pnl_usd: 0.68,
            unrealized_pnl: 0,
            unrealized_pnl_usd: 0,
            total_pnl_usd: 0.68,
            positions: [],
            mode: 'paper',
            trader_id: 'trader-wajidali1984',
            paper_account_id: 'paper-wajidali1984',
            account_scope: 'authenticated_trader',
            account_specific: true,
            paper_session_id: 'paper-session-canonical',
            data_source: 'v2:portfolio:state',
            pnl_source_key: 'v2:portfolio:state',
            pnl_source_route: '/api/v2/portfolio',
            pnl_source_type: 'CANONICAL_CURRENT_SESSION_RUNTIME',
            source_generated_utc: '2026-07-09T20:05:00Z',
            staleness_seconds: 3,
            freshness_status: 'fresh',
            pnl_conflict_detected: false,
          },
          source: 'redis:v2:portfolio:state',
          source_type: 'redis_live',
          endpoint: '/api/v2/portfolio',
          generated_at_utc: '2026-07-09T20:05:03Z',
          generated_at_et: '2026-07-09T16:05:03-04:00',
          received_at: '2026-07-09T20:05:03Z',
          timestamp: '2026-07-09T20:05:03Z',
          staleness_seconds: 3,
          freshness_status: 'fresh',
          canonical_owner: '/api/v2/portfolio',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data_quality_status: 'fresh',
          stale: false,
          missing_fields: [],
          warnings: [],
          trader_context: {
            scope: 'authenticated_trader',
            trader_id: 'trader-wajidali1984',
            paper_account_id: 'paper-wajidali1984',
            username: 'wajidali1984',
            exchange_accounts: [],
            account_specific: true,
            warnings: [],
          },
          account_scope: {
            scope: 'authenticated_trader',
            trader_id: 'trader-wajidali1984',
            paper_account_id: 'paper-wajidali1984',
            authenticated: true,
            actor_scope_present: true,
            data_account_specific: true,
            data_scope_matches_actor: true,
            scope_verified: true,
            live_trading_enabled: false,
            exchange_mutation_enabled: false,
            warnings: [],
          },
        }),
      });
    });

    await gotoWithAuth(page, '/portfolio', 'trader', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const panel = page.getByTestId('portfolio-canonical-pnl-panel');
    await expect(page.getByTestId('page-positions')).toBeVisible();
    await expect(panel).toContainText(/Canonical Paper PnL/i);
    await expect(panel).toContainText('paper_realized_pnl_usd');
    await expect(panel).toContainText('paper_unrealized_pnl_usd');
    await expect(panel).toContainText('paper_total_pnl_usd');
    await expect(panel).toContainText('paper_equity_usd');
    await expect(panel).toContainText('paper_session_id');
    await expect(panel).toContainText('data_source');
    await expect(panel).toContainText('/api/v2/portfolio');
    await expect(panel).toContainText('v2:portfolio:state');
    await expect(panel).toContainText('paper-session-canonical');
    await expect(panel).toContainText('$0.68');
    await expect(panel).toContainText('$3,000.68');
    await expect(panel).toContainText(/PNL RECONCILED/i);
    await expect(panel).not.toContainText(/multiple pnl sources|conflict detected|goal_state/i);
  });

  test('portfolio history route shows trader-scoped typed history instead of fallback ledger diagnostics', async ({ page }) => {
    await gotoWithAuth(page, '/portfolio/history');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-history')).toBeVisible();
    await expect(page.getByText('Execution history', { exact: true })).toBeVisible();
    await expect(page.getByTestId('page-history')).toContainText(/Authenticated trader account/i);
    expect(text).not.toMatch(/paper ledger tail|legacy signal-history|operator_runtime|CUDA Trainer/i);
  });

  test('signals route shows trader-safe signal evidence instead of admin realtime panels', async ({ page }) => {
    await gotoWithAuth(page, '/signals');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-signals')).toBeVisible();
    await expect(page.getByTestId('page-signals')).toContainText(/Total Signals/i);
    await expect(page.getByTestId('page-signals')).toContainText(/Execution Ready/i);
    await expect(page.getByTestId('adaptive-capital-telemetry-panel')).toBeVisible();
    expect(text).not.toMatch(/runtime monitor payload|all-timeframe prediction matrix|signals-admin|operator|payload|operator_dashboard_payload|\/operator_runtime|\/home\/wali/i);
  });

  test('signals route exposes canonical current signal truth with provider and A+ gating', async ({ page }) => {
    await page.route('**/api/v2/signals/current**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          source: 'Redis paper signal publisher v2:signals:paper:BTCUSDT:5m',
          source_type: 'redis_live',
          endpoint: '/api/v2/signals/current',
          freshness_status: 'fresh',
          staleness_seconds: 2,
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            active_signal: {
              symbol: 'BTCUSDT',
              timeframe: '5m',
              action: 'long',
              side: 'Long',
              proposed_action: 'LONG',
              actionable: false,
              actionable_reason_code: 'PAPER_FILL_GATE_BLOCKED',
              live_gate: 'blocked_human_only',
              generated_at: '2026-07-09T16:25:56-04:00',
              signal_id: 'sig_dashboard_signal_truth',
              prediction_id: 'v2h_dashboard_signal_truth',
              source_freshness: 'CURRENT',
              market_age_seconds: 8,
              exchange_action_taken: false,
              exchange_call_invariant: 'LIVE_TRADING_BLOCKED',
              confidence_calibrated: 0.827,
              confidence: 0.827,
              price_target_after_cost: 63205.89,
              expected_move_after_cost_bps: -1.45,
              data_coverage_percent: 78.2,
              market_state_integrity_score: 100,
              paper_fill_allowed: false,
              risk_result: 'Paper Fill Blocked: expected move after cost below threshold',
              blocked_reason: 'Paper Fill Blocked: expected move after cost below threshold',
            },
            public_paper_signal: true,
            account_specific: false,
          },
        }),
      });
    });
    await page.route('**/api/v2/a-plus/inventory**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          source: 'redis:v2:paper:a_plus_gate:status',
          freshness_status: 'fresh',
          staleness_seconds: 3,
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            evaluated_candidates: 455,
            a_plus_candidates: 0,
            live_ready_rows: 0,
            counts_as_final_a_plus: false,
            paper_session_id: 'paper-session-dashboard-signals',
          },
        }),
      });
    });
    await page.route('**/api/v2/providers/status**', async (route) => {
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          schema_version: 'api_v2_readonly_envelope_v1',
          source: 'redis:provider_runtime_truth',
          freshness_status: 'fresh',
          staleness_seconds: 4,
          data_quality_status: 'fresh',
          live_gate: 'blocked_human_only',
          places_real_order: false,
          routes_to_live: false,
          data: {
            providers: [
              {
                provider: 'coinglass',
                display_name: 'CoinGlass',
                dashboard_color: 'green',
                actual_payload_count: 7,
                feature_count: 35,
                consumer_count: 8,
                heartbeat_only: false,
              },
              {
                provider: 'moralis',
                display_name: 'Moralis',
                dashboard_color: 'gray',
                actual_payload_count: 1,
                feature_count: 10,
                consumer_count: 8,
                heartbeat_only: false,
              },
              {
                provider: 'santiment',
                display_name: 'Santiment / Sanbase',
                dashboard_color: 'green',
                actual_payload_count: 115,
                feature_count: 22,
                consumer_count: 8,
                heartbeat_only: false,
              },
            ],
            places_real_order: false,
            routes_to_live: false,
            live_gate: 'blocked_human_only',
          },
        }),
      });
    });

    await gotoWithAuth(page, '/signals', 'trader', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const panel = page.getByTestId('signals-runtime-truth-panel');
    await expect(panel).toBeVisible({ timeout: 20_000 });
    await expect(panel).toContainText(/Current Signal Runtime Truth/i);
    await expect(panel).toContainText(/BTCUSDT 5m/i);
    await expect(panel).toContainText('/api/v2/signals/current');
    await expect(panel).toContainText(/LIVE BLOCKED/i);
    await expect(panel).toContainText(/places_real_order=NO/i);
    await expect(panel).toContainText(/routes_to_live=NO/i);
    await expect(panel).toContainText(/actionable/i);
    await expect(panel).toContainText(/Paper Fill Gate Blocked/i);
    await expect(panel).toContainText(/paper_fill_allowed/i);
    await expect(panel).toContainText(/LIVE TRADING BLOCKED/i);
    await expect(panel).toContainText(/A\+ candidates/i);
    await expect(panel).toContainText(/455 evaluated/i);
    await expect(panel).toContainText(/0 live-ready/i);
    await expect(panel).toContainText(/why_no_trade=/i);
    await expect(panel).toContainText(/provider_context=/i);
    await expect(panel).toContainText(/CoinGlass:GREEN\/7 actual/i);
    await expect(panel).toContainText(/Moralis:GRAY\/1 actual/i);
    await expect(panel).toContainText(/Santiment \/ Sanbase:GREEN\/115 actual/i);
    await expect(panel).toContainText(/NO ORDER \/ TEST \/ LEVERAGE \/ MARGIN MUTATION/i);
    await expect(panel).not.toContainText(/ready to submit live|live order enabled|goal_state|operator_dashboard/i);
  });

  test('derivatives route shows market analytics with sourced states instead of runtime diagnostics', async ({ page }) => {
    await gotoWithAuth(page, '/derivatives');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-derivatives')).toBeVisible();
    await expect(page.getByRole('heading', { name: 'Derivatives' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Funding Rates' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Liquidations' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Long / Short' })).toBeVisible();
    expect(text).not.toMatch(/liquidation ingestor|wss client|runtime status|operator_dashboard|payload|writes_legacy/i);
  });

  test('alerts route shows professional unavailable state instead of payload telemetry', async ({ page }) => {
    await gotoWithAuth(page, '/alerts');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-alerts')).toBeVisible();
    await expect(page.getByTestId('page-alerts').getByText('Alert API', { exact: true })).toBeVisible();
    await expect(page.getByText(/Alert actions unavailable|Notification delivery unavailable|Alerts available/i)).toBeVisible();
    expect(text).not.toMatch(/operator_runtime|payload|current_blockers|paper_online|source present/i);
  });

  test('ai predictions route shows trader-safe forecast evidence instead of trainer runtime internals', async ({ page }) => {
    await gotoWithAuth(page, '/ai-predictions');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const text = await page.locator('body').innerText();
    await expect(page.getByTestId('page-ai-predictions')).toBeVisible();
    await expect(page.getByText(/AI Predictions/i)).toBeVisible();
    await expect(page.getByText(/Prediction Accuracy \+ Capital Productivity/i)).toBeVisible();
    await expect(page.getByText('RAW MODEL OUTPUT', { exact: true })).toBeVisible();
    await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/PPO/i);
    await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/MASA/i);
    await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/provider features/i);
    await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/Checkpoint ID/i);
    await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/Tensor input dim/i);
    await expect(page.getByTestId('ai-provider-feature-coinglass')).toContainText('CoinGlass');
    await expect(page.getByTestId('ai-provider-feature-moralis')).toContainText('Moralis');
    await expect(page.getByTestId('ai-provider-feature-santiment')).toContainText(/Santiment|Sanbase/);
    await expect(page.getByTestId('runtime-alpha-dynamic-readiness-panel')).toHaveCount(0);
    expect(text).not.toMatch(/operator_dashboard|payload|runtime alpha/i);
  });

  test('model-state route redirects directly to the cleaned AI predictions page', async ({ page }) => {
    await gotoWithAuth(page, '/ai-predictions/model-state', 'trader', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/ai-predictions$/);
    await expect(page.getByTestId('page-ai-predictions')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/Model State|legacy hybrid parity|runtime alpha|operator_dashboard|payload/i);
  });

  test('goal AI aliases expose the trainer brain summary required by route crawl', async ({ page }) => {
    for (const path of ['/ai', '/trainer']) {
      await gotoWithAuth(page, path, 'trader', { waitUntil: 'domcontentloaded' });
      await page.waitForLoadState('domcontentloaded').catch(() => undefined);

      await expect(page).toHaveURL(/\/ai-predictions$/);
      await expect(page.getByTestId('page-ai-predictions')).toBeVisible();
      await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/PPO/i);
      await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/MASA/i);
      await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/provider features/i);
      await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/Checkpoint ID/i);
      await expect(page.getByTestId('ai-trainer-brain-summary')).toContainText(/Tensor input dim/i);
      await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload|runtime alpha/i);
    }
  });

  test('legacy admin model-state alias redirects directly to the admin model-state page', async ({ page }) => {
    await gotoWithAuth(page, '/admin/ai-brain', 'admin', { waitUntil: 'domcontentloaded' });
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/admin\/model-state$/);
    await expect(page.getByTestId('page-ai-brain')).toBeVisible();
    await expect(page.getByTestId('runtime-alpha-dynamic-readiness-panel')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload/i);
  });

  test('legacy paper trading route redirects to the canonical trade terminal', async ({ page }) => {
    await gotoWithAuth(page, '/trade/paper');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/trade$/);
    await expect(page.getByTestId('page-trader')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/CUDA Trainer Paper Signal Lineage|Operator Review|live paper \/ shadow trading loop/i);
  });

  test('legacy market symbols route redirects to the canonical markets screener', async ({ page }) => {
    await gotoWithAuth(page, '/markets/symbols');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/markets$/);
    await expect(page.getByTestId('page-markets')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload|symbol universe worker|live gate/i);
  });

  test('legacy admin market symbols alias redirects directly to the canonical markets screener', async ({ page }) => {
    await gotoWithAuth(page, '/admin/symbols');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/markets$/);
    await expect(page.getByTestId('page-markets')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/operator_dashboard|payload|symbol universe worker|live gate/i);
  });

  test('admin signal explainability stays renderable under backend-confirmed admin role', async ({ page }) => {
    await gotoWithAuth(page, '/admin/signal-explainability', 'admin');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/admin\/signal-explainability$/);
    await expect(page.getByText(/Signal Explainability/i).first()).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/local role|role override/i);
  });

  test('legacy replay route redirects to the cleaned backtests page', async ({ page }) => {
    await gotoWithAuth(page, '/backtests/replay');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/backtests$/);
    await expect(page.getByTestId('page-strategy-backtesting')).toBeVisible();
    await expect(page.getByRole('heading', { name: /Backtest Engine/i })).toBeVisible();
    await expect(page.getByText(/Historical replay of AI signals/i)).toBeVisible();
    await expect(page.getByRole('heading', { name: /Manual Backtest Run/i })).toBeVisible();
    await expect(page.getByRole('heading', { name: /All Results/i })).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/CUDA Actionability|Pipeline Control|operator role|required|payload/i);
  });

  test('legacy admin replay alias redirects directly to the cleaned backtests page', async ({ page }) => {
    await gotoWithAuth(page, '/admin/replay');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/backtests$/);
    await expect(page.getByTestId('page-strategy-backtesting')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/CUDA Actionability|Pipeline Control|operator role|required|payload/i);
  });

  test('legacy admin technical-analysis alias redirects directly to the research page', async ({ page }) => {
    await gotoWithAuth(page, '/admin/technical-analysis');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/technical analysis runtime|operator_dashboard|payload|live gate|\/operator_runtime/i);
  });

  test('research route separates read-only market context from missing research API', async ({ page }) => {
    await gotoWithAuth(page, '/research');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    const body = page.locator('body');
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(body).toContainText(/Live Binance USD-M screener/i);
    await expect(body).toContainText(/WebSocket market data/i);
    await expect(page.getByTestId('adaptive-capital-telemetry-panel')).toBeVisible();
    await expect(body).not.toContainText(/V2_NATIVE|technical_analysis|Redis keys|payload|feature pipeline/i);
  });

  test('legacy technical-analysis route redirects to the cleaned research page', async ({ page }) => {
    await gotoWithAuth(page, '/research/technical-analysis');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(page.getByText(/Live Binance USD-M screener/i)).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/V2_NATIVE|technical_analysis|Redis keys|payload|feature pipeline/i);
  });

  test('legacy admin technical-analysis alias redirects directly to the cleaned research page', async ({ page }) => {
    await gotoWithAuth(page, '/admin/technical-analysis');
    await page.waitForLoadState('domcontentloaded').catch(() => undefined);

    await expect(page).toHaveURL(/\/research$/);
    await expect(page.getByTestId('page-market-intelligence')).toBeVisible();
    await expect(page.locator('body')).not.toContainText(/V2_NATIVE|technical_analysis|Redis keys|payload|feature pipeline/i);
  });
});
