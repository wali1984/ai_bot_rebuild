import type { Page } from '@playwright/test';

export type TestAuthRole = 'public' | 'guest' | 'viewer' | 'trader' | 'admin' | 'superadmin' | 'reviewer';

const ROLE_EMAIL: Record<Exclude<TestAuthRole, 'public' | 'guest'>, string> = {
  viewer: 'viewer@test.alphaforge.local',
  trader: 'wajidali1984@hotmail.com',
  admin: 'admin@test.alphaforge.local',
  superadmin: 'superadmin@test.alphaforge.local',
  reviewer: 'admin-reviewer@test.alphaforge.local',
};

function backendRole(role: TestAuthRole): 'viewer' | 'trader' | 'admin' | 'superadmin' | null {
  if (role === 'public' || role === 'guest') return null;
  if (role === 'reviewer') return 'admin';
  return role;
}

export async function mockAuth(page: Page, role: TestAuthRole): Promise<void> {
  const resolvedRole = backendRole(role);

  await page.route('**/api/auth/me', async (route) => {
    if (!resolvedRole) {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Authentication required' }),
      });
      return;
    }

    const email = ROLE_EMAIL[role === 'reviewer' ? 'reviewer' : resolvedRole];
    const isTrader = resolvedRole === 'trader';
    const traderId = isTrader ? 'trader-wajidali1984' : null;
    const paperAccountId = isTrader ? 'paper-wajidali1984' : null;
    const user = {
      id: isTrader ? 'user-wajidali1984' : `test-${resolvedRole}`,
      trader_id: traderId,
      username: isTrader ? 'wajidali1984' : `test_${resolvedRole}`,
      email,
      role: resolvedRole,
      paper_account_id: paperAccountId,
      exchange_accounts: isTrader
        ? [
          {
            id: 'binance-wajidali1984',
            trader_id: traderId,
            paper_account_id: paperAccountId,
            exchange: 'binance',
            label: 'Wajid Ali Binance Futures',
            account_type: 'usd_m_futures',
            mode: 'read_only',
            read_only: true,
            live_trading_enabled: false,
            status: 'credential_source_pending',
            credential_status: {
              credential_scope: 'backend_only_readonly',
              source_type: 'environment_reference',
              configured: false,
              status: 'credential_source_pending',
              read_only_required: true,
              live_trading_enabled: false,
              binding_blocked_reason: null,
              raw_credential_value_exposed: false,
              checked_at: '2026-06-14T00:00:00Z',
            },
            created_at: '2026-06-14T00:00:00Z',
            updated_at: '2026-06-14T00:00:00Z',
          },
        ]
        : [],
      watchlist: isTrader ? ['BTCUSDT', 'ETHUSDT', 'BNBUSDT'] : ['BTCUSDT', 'ETHUSDT'],
      alert_preferences: {},
      is_active: true,
      created_at: '2026-06-13T00:00:00Z',
      updated_at: '2026-06-13T00:00:00Z',
      last_login: '2026-06-13T00:00:00Z',
    };

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ user }),
    });
  });

  await page.route('**/api/auth/logout', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });

  await page.route('**/api/auth/refresh', async (route) => {
    if (!resolvedRole) {
      await route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Authentication required' }),
      });
      return;
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ ok: true }),
    });
  });
}
