export const PUBLIC_PAGE_PATHS = ['/', '/landing', '/status', '/status-simple', '/login'] as const;

export const TRADER_PAGE_PATHS = [
  '/dashboard',
  '/account-settings',
  '/markets',
  '/markets/symbols',
  '/market/BTCUSDT',
  '/chart/BTCUSDT',
  '/trade',
  '/trade/paper',
  '/derivatives',
  '/signals',
  '/ai-predictions',
  '/ai-predictions/model-state',
  '/portfolio',
  '/portfolio/executions',
  '/portfolio/history',
  '/backtests',
  '/backtests/replay',
  '/research',
  '/research/technical-analysis',
  '/alerts',
] as const;

export const ADMIN_PAGE_PATHS = [
  '/system',
  '/system/control-center',
  '/system/ingestors',
  '/system/trainer',
  '/system/orchestrator',
  '/system/risk-controllers',
  '/system/strategy-controls',
  '/system/execution',
  '/system/exchanges',
  '/system/config',
  '/system/logs',
  '/system/users',
] as const;

export const SUPERADMIN_PAGE_PATHS = [
  '/system/readiness',
  '/system/reports',
  '/system/audit-ledger',
  '/system/scripts',
  '/system/build-validation',
  '/system/coverage',
  '/system/migrations',
  '/system/ai-tools',
  '/system/position-quarantine',
  '/system/evidence',
] as const;

export const ALL_PAGE_PATHS = [
  ...PUBLIC_PAGE_PATHS,
  ...TRADER_PAGE_PATHS,
  ...ADMIN_PAGE_PATHS,
  ...SUPERADMIN_PAGE_PATHS,
] as const;

export const REVIEWER_ONLY_ADMIN_PATHS = [
  '/system/readiness',
  '/system/reports',
  '/system/audit-ledger',
  '/system/scripts',
  '/system/build-validation',
  '/system/coverage',
  '/system/migrations',
  '/system/ai-tools',
] as const;

export const VIEWER_VISIBLE_ADMIN_PATHS = [
  '/dashboard',
  '/markets',
  '/trade',
  '/signals',
  '/ai-predictions',
  '/portfolio',
  '/backtests',
  '/research',
] as const;

export const PAGES_WITH_DANGEROUS_CONTROLS = [
  {
    path: '/system/risk-controllers',
    controls: ['disable_kill_switch', 'disable_mandatory_stop', 'increase_daily_loss_limit'],
  },
  {
    path: '/system/config',
    controls: ['enable_live_trading', 'enable_adjust_leverage', 'switch_paper_to_live', 'enable_cross_margin'],
  },
  {
    path: '/system/strategy-controls',
    controls: ['enable_hedge_dca'],
  },
  {
    path: '/system/execution',
    controls: ['switch_paper_to_live', 'increase_max_position_size', 'add_live_api_keys'],
  },
  {
    path: '/system/readiness',
    controls: ['enable_live_trading', 'increase_leverage'],
  },
] as const;

export const LEGACY_REDIRECTS = {
  '/landing-legacy': '/landing',
  '/mission-control': '/dashboard',
  '/admin/mission-control': '/dashboard',
  '/operator-proof': '/admin/evidence',
  '/markets/symbols': '/markets',
  '/admin/symbols': '/markets',
  '/trade/paper': '/trade',
  '/admin/paper-trading': '/trade',
  '/ai-predictions/model-state': '/ai-predictions',
  '/admin/ai-brain': '/admin/model-state',
  '/admin/trainer-prediction-monitor': '/ai-predictions',
  '/admin/signal-explainability': '/signals',
  '/admin/signals': '/signals',
  '/admin/executions': '/portfolio/executions',
  '/admin/positions': '/portfolio',
  '/admin/market-intelligence': '/research',
  '/backtests/replay': '/backtests',
  '/admin/replay': '/backtests',
  '/admin/strategy-backtesting': '/backtests',
  '/research/technical-analysis': '/research',
  '/admin/technical-analysis': '/research',
  '/admin/liquidation-bridge': '/derivatives',
  '/trader': '/trade',
  '/history': '/portfolio/history',
} as const;
