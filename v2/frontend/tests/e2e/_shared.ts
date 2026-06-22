import type { Page } from '@playwright/test';
import type { RoleLike } from '../../src/auth/rbac';

export async function gotoAs(
  page: Page,
  path: string,
  role?: RoleLike,
  options?: Parameters<Page['goto']>[1],
): Promise<void> {
  const url = new URL(path, 'http://127.0.0.1');
  // 'public' and 'guest' are the unauthenticated default; don't add a query param that would
  // change the URL and break URL-assertion tests expecting a clean canonical path.
  if (role && role !== 'public' && role !== 'guest') {
    url.searchParams.set('role', role);
  }
  await page.goto(url.pathname + url.search, options);
}

export const ADMIN_PAGE_PATHS = [
  '/admin/permanent-migration',
  '/admin/mission-control',
  '/admin/monitor-center',
  '/admin/coverage-system-atlas',
  '/admin/script-registry',
  '/admin/trainer-prediction-monitor',
  '/admin/signal-explainability',
  '/admin/symbols',
  '/admin/signals',
  '/admin/executions',
  '/admin/positions',
  '/admin/risk-control',
  '/admin/exchange-manager',
  '/admin/external-manual-position-quarantine',
  '/admin/config-admin',
  '/admin/strategy-admin',
  '/admin/trainer-admin',
  '/admin/orchestrator-admin',
  '/admin/execution-admin',
  '/admin/paper-trading',
  '/admin/replay',
  '/admin/audit-ledger',
  '/admin/system-health',
  '/admin/live-readiness',
  '/admin/claude-admin-ai',
  '/admin/ollama-local-assistant',
  '/admin/codex-review-center',
  '/admin/build-validation-status',
  '/admin/operator-proof-dashboard',
  '/admin/mobile-iphone-readiness',
] as const;

export const PUBLIC_PAGE_PATHS = ['/', '/status', '/login'] as const;

export const ALL_PAGE_PATHS = [...PUBLIC_PAGE_PATHS, ...ADMIN_PAGE_PATHS] as const;

export const REVIEWER_ONLY_ADMIN_PATHS = [
  '/admin/coverage-system-atlas',
  '/admin/script-registry',
  '/admin/risk-control',
  '/admin/config-admin',
  '/admin/exchange-manager',
  '/admin/strategy-admin',
  '/admin/trainer-admin',
  '/admin/orchestrator-admin',
  '/admin/execution-admin',
  '/admin/audit-ledger',
  '/admin/live-readiness',
  '/admin/claude-admin-ai',
  '/admin/ollama-local-assistant',
  '/admin/codex-review-center',
  '/admin/mobile-iphone-readiness',
] as const;

export const VIEWER_VISIBLE_ADMIN_PATHS = [
  '/admin/permanent-migration',
  '/admin/mission-control',
  '/admin/monitor-center',
  '/admin/trainer-prediction-monitor',
  '/admin/signal-explainability',
  '/admin/symbols',
  '/admin/signals',
  '/admin/executions',
  '/admin/positions',
  '/admin/external-manual-position-quarantine',
  '/admin/paper-trading',
  '/admin/replay',
  '/admin/system-health',
  '/admin/build-validation-status',
  '/admin/operator-proof-dashboard',
] as const;

export const PAGES_WITH_DANGEROUS_CONTROLS: ReadonlyArray<{ path: string; controls: ReadonlyArray<string> }> = [
  { path: '/admin/risk-control', controls: ['disable_kill_switch', 'disable_mandatory_stop', 'increase_daily_loss_limit'] },
  { path: '/admin/config-admin', controls: ['enable_live_trading', 'enable_adjust_leverage', 'switch_paper_to_live', 'enable_cross_margin'] },
  { path: '/admin/strategy-admin', controls: ['enable_hedge_dca'] },
  { path: '/admin/execution-admin', controls: ['switch_paper_to_live', 'increase_max_position_size', 'add_live_api_keys'] },
  { path: '/admin/live-readiness', controls: ['enable_live_trading', 'increase_leverage'] },
];
