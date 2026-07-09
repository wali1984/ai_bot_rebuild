import type { PageMeta, PageModule, PageRoute, Surface } from '../types/page';

export interface ProductPageOverride {
  title?: string;
  navLabel?: string;
  description?: string;
  surface?: Surface;
  navCategory?: string;
  navOrder?: number;
  hideFromNav?: boolean;
  path?: string;
}

// ─── Trader primary navigation ────────────────────────────────────────────────
export const PRIMARY_NAV_ORDER = [
  'dashboard',
  'markets',
  'trade',
  'derivatives',
  'signals',
  'predictions',
  'portfolio',
  'backtests',
  'research',
  'alerts',
  'account',
] as const;

export const PRIMARY_NAV_LABELS: Record<string, string> = {
  dashboard: 'Dashboard',
  markets: 'Markets',
  trade: 'Trade',
  derivatives: 'Derivatives',
  signals: 'Signals',
  predictions: 'AI',
  portfolio: 'Portfolio',
  backtests: 'Backtests',
  research: 'Research',
  alerts: 'Alerts',
  account: 'Account',
};

// ─── Admin navigation — 10 primary + 3 secondary ──────────────────────────────
// Enforced maximum: 10 primary entries visible in the main nav.
// Secondary (logs, audit, tools) appear below a divider; tools is superadmin-only.
export const SYSTEM_NAV_ORDER = [
  'overview',      // 1
  'data',          // 2
  'intelligence',  // 3
  'orchestration', // 4
  'risk',          // 5
  'execution',     // 6
  'exchanges',     // 7
  'config',        // 8
  'users',         // 9
  'reports',       // 10
  // Secondary
  'logs',
  'audit',
  'tools',
] as const;

export const SYSTEM_NAV_LABELS: Record<string, string> = {
  overview: 'Overview',
  data: 'Data',
  intelligence: 'Intelligence',
  orchestration: 'Orchestration',
  risk: 'Risk & Readiness',
  execution: 'Execution',
  exchanges: 'Exchanges',
  config: 'Configuration',
  users: 'Users',
  reports: 'Reports',
  logs: 'Logs',
  audit: 'Audit',
  tools: 'Developer Tools',
};

export const SYSTEM_NAV_SECONDARY = new Set<string>(['logs', 'audit', 'tools']);
export const SYSTEM_NAV_SUPERADMIN_ONLY = new Set<string>(['audit', 'tools']);

// ─── Page overrides ──────────────────────────────────────────────────────────
// Maps page-module id → canonical route/surface/nav placement.
// New consolidated pages (admin-overview, admin-data, etc.) are registered as
// first-class page modules in registry.ts — they own the canonical paths.
// Hidden specialist pages remain deep-linkable for operator evidence and tests;
// MERGED_LEGACY_PATHS only handles old aliases that do not own a page module.
export const PAGE_OVERRIDES: Record<string, ProductPageOverride> = {

  // ── Trader app pages ────────────────────────────────────────────────────────
  'mission-control': {
    title: 'Dashboard',
    navLabel: 'Dashboard',
    description: 'Trader home for market state, active signals, portfolio risk, and readiness.',
    surface: 'system',
    navCategory: 'dashboard',
    navOrder: 10,
    hideFromNav: true,
    path: '/admin/mission-control',
  },
  markets: {
    title: 'Markets',
    navLabel: 'Markets',
    description: 'AI-powered market screener with derivatives, funding, liquidation, signal, and data coverage columns.',
    surface: 'public',
    navCategory: 'markets',
    navOrder: 10,
    path: '/markets',
  },
  symbols: {
    title: 'Symbols',
    navLabel: 'Symbols',
    description: 'Symbol universe, favorites, exchange availability, and tradability coverage.',
    surface: 'app',
    navCategory: 'markets',
    navOrder: 20,
    hideFromNav: true,
    path: '/markets/symbols',
  },
  market: {
    title: 'Market Detail',
    navLabel: 'Market Detail',
    description: 'Symbol detail with chart, derivatives, signals, predictions, order flow, and source coverage.',
    surface: 'public',
    navCategory: 'markets',
    navOrder: 30,
    path: '/market/:symbol?',
  },
  trader: {
    title: 'Trade',
    navLabel: 'Trade',
    description: 'Modular realtime trading terminal with chart, book, tape, order ticket, positions, executions, and risk pre-check.',
    surface: 'app',
    navCategory: 'trade',
    navOrder: 10,
    path: '/trade',
  },
  'paper-trading': {
    title: 'Execution Runtime',
    navLabel: 'Execution Runtime',
    description: 'Execution account reporting and fill-gate evidence inside the trading workflow.',
    surface: 'app',
    navCategory: 'trade',
    navOrder: 20,
    hideFromNav: true,
    path: '/trade/paper',
  },
  'liquidation-bridge': {
    title: 'Derivatives',
    navLabel: 'Derivatives',
    description: 'Liquidations, funding, OI, long/short, basis, and exchange comparison coverage.',
    surface: 'app',
    navCategory: 'derivatives',
    navOrder: 10,
    path: '/derivatives',
  },
  signals: {
    title: 'Signals',
    navLabel: 'Signals',
    description: 'Evidence-first active, pending, expired, rejected, and executed signal stream.',
    surface: 'app',
    navCategory: 'signals',
    navOrder: 10,
    path: '/signals',
  },
  'ai-predictions': {
    title: 'AI Predictions',
    navLabel: 'AI',
    description: 'Trainer model predictions, confidence scores, model health, and feature importance.',
    surface: 'app',
    navCategory: 'predictions',
    navOrder: 10,
    path: '/ai-predictions',
  },
  positions: {
    title: 'Portfolio',
    navLabel: 'Portfolio',
    description: 'Positions, balances, exposure, PnL, liquidation risk, and user-facing risk state.',
    surface: 'app',
    navCategory: 'portfolio',
    navOrder: 10,
    path: '/portfolio',
  },
  executions: {
    title: 'Executions',
    navLabel: 'Executions',
    description: 'Orders, fills, rejected orders, slippage, fees, venue response status, and strategy context.',
    surface: 'app',
    navCategory: 'portfolio',
    navOrder: 20,
    path: '/portfolio/executions',
  },
  history: {
    title: 'History',
    navLabel: 'History',
    description: 'Account, trade, signal, and portfolio history with symbol, strategy, exchange, and mode filters.',
    surface: 'app',
    navCategory: 'portfolio',
    navOrder: 30,
    path: '/portfolio/history',
  },
  'strategy-backtesting': {
    title: 'Backtests',
    navLabel: 'Backtests',
    description: 'Strategy replay, equity curve, drawdown, expectancy, and trade-by-trade evidence.',
    surface: 'app',
    navCategory: 'backtests',
    navOrder: 10,
    path: '/backtests',
  },
  replay: {
    title: 'Replay',
    navLabel: 'Replay',
    description: 'Trader-facing signal and strategy replay for review.',
    surface: 'app',
    navCategory: 'backtests',
    navOrder: 20,
    path: '/replay',
  },
  'market-intelligence': {
    title: 'Research',
    navLabel: 'Research',
    description: 'Market intelligence, alt-data coverage, technical context, and source freshness.',
    surface: 'app',
    navCategory: 'research',
    navOrder: 10,
    path: '/research',
  },
  'technical-analysis': {
    title: 'Technical Analysis',
    navLabel: 'Technical Analysis',
    description: 'Chart overlays, indicators, support/resistance, trend regime, and volatility context.',
    surface: 'app',
    navCategory: 'analytics',
    navOrder: 20,
    path: '/technical-analysis',
  },
  alerts: {
    title: 'Alerts',
    navLabel: 'Alerts',
    description: 'Price, OI, liquidation, funding, signal, risk, and system alert coverage.',
    surface: 'app',
    navCategory: 'alerts',
    navOrder: 10,
    path: '/alerts',
  },
  'account-settings': {
    title: 'Account Settings',
    navLabel: 'Account',
    description: 'Profile, linked exchange accounts, watchlist, and password management for the signed-in trader.',
    surface: 'app',
    navCategory: 'account',
    navOrder: 10,
    path: '/account-settings',
  },

  // ── Legacy absorbed admin pages — hidden from nav, redirected by MERGED_LEGACY_PATHS ───

  // These keep their original paths but are hidden from nav.
  // The canonical pages at /admin, /admin/data, etc. are new page modules registered in registry.ts.

  'system-health': {
    title: 'System Health',
    surface: 'app',
    navCategory: 'dashboard',
    hideFromNav: true,
    path: '/system-health',
  },
  'admin-war-room': {
    title: 'Ops Center',
    surface: 'system',
    navCategory: 'overview',
    hideFromNav: true,
    path: '/admin/war-room',
  },
  'monitor-center': {
    title: 'Monitor Center',
    surface: 'admin',
    navCategory: 'data',
    hideFromNav: true,
    path: '/admin/monitor-center',
  },
  ingestors: {
    title: 'Ingestors',
    surface: 'admin',
    navCategory: 'data',
    hideFromNav: true,
    path: '/admin/ingestors',
  },
  'trainer-admin': {
    title: 'Trainer',
    surface: 'system',
    navCategory: 'intelligence',
    hideFromNav: true,
    path: '/admin/trainer-admin',
  },
  'trainer-prediction-monitor': {
    title: 'Trainer Prediction Monitor',
    surface: 'admin',
    navCategory: 'intelligence',
    hideFromNav: true,
    path: '/admin/trainer-prediction-monitor',
  },
  'ai-brain': {
    title: 'Model State',
    surface: 'system',
    navCategory: 'intelligence',
    hideFromNav: true,
    path: '/admin/model-state',
  },
  'signal-explainability': {
    title: 'Signal Explainability',
    surface: 'admin',
    navCategory: 'intelligence',
    hideFromNav: true,
    path: '/admin/signal-explainability',
  },
  'orchestrator-admin': {
    title: 'Orchestrator',
    surface: 'system',
    navCategory: 'orchestration',
    hideFromNav: true,
    path: '/admin/orchestrator',
  },
  'strategy-admin': {
    title: 'Traders',
    surface: 'admin',
    navCategory: 'orchestration',
    hideFromNav: true,
    path: '/admin/traders',
  },
  'risk-control': {
    title: 'Risk Controllers',
    surface: 'admin',
    navCategory: 'risk',
    hideFromNav: true,
    path: '/admin/risk-control',
  },
  'live-readiness': {
    title: 'Live Readiness',
    surface: 'admin',
    navCategory: 'risk',
    hideFromNav: true,
    path: '/admin/live-readiness',
  },
  'mobile-iphone-readiness': {
    title: 'Mobile Readiness',
    surface: 'system',
    navCategory: 'risk',
    hideFromNav: true,
    path: '/admin/mobile-iphone-readiness',
  },
  'external-manual-position-quarantine': {
    title: 'Position Quarantine',
    surface: 'admin',
    navCategory: 'risk',
    hideFromNav: true,
    path: '/admin/external-manual-position-quarantine',
  },
  'execution-admin': {
    title: 'Execution Control',
    navLabel: 'Execution',
    surface: 'admin',
    navCategory: 'execution',
    navOrder: 10,
    hideFromNav: true,
    path: '/admin/execution-admin',
  },
  'exchange-manager': {
    title: 'Exchanges',
    surface: 'admin',
    navCategory: 'exchanges',
    hideFromNav: true,
    path: '/admin/exchange-manager',
  },
  'config-admin': {
    title: 'Config Admin',
    surface: 'admin',
    navCategory: 'config',
    hideFromNav: true,
    path: '/admin/config-admin',
  },
  'user-status': {
    title: 'Simple Status',
    surface: 'public',
    navCategory: 'status',
    hideFromNav: true,
    path: '/status-simple',
  },
  'report-center': {
    title: 'Reports',
    surface: 'system',
    navCategory: 'reports',
    hideFromNav: true,
    path: '/admin/report-center',
  },
  'executive-status': {
    title: 'Executive Summary',
    surface: 'admin',
    navCategory: 'reports',
    hideFromNav: true,
    path: '/admin/executive-status',
  },
  'operator-proof-dashboard': {
    title: 'Evidence',
    surface: 'admin',
    navCategory: 'reports',
    hideFromNav: true,
    path: '/admin/evidence',
  },
  'logs-errors': {
    title: 'Logs / Errors',
    surface: 'system',
    navCategory: 'logs',
    hideFromNav: true,
    path: '/admin/logs-errors',
  },
  'audit-ledger': {
    title: 'Audit Ledger',
    surface: 'system',
    navCategory: 'audit',
    hideFromNav: true,
    path: '/admin/audit-ledger',
  },
  'script-registry': {
    title: 'Scripts',
    surface: 'system',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/script-registry',
  },
  'build-validation-status': {
    title: 'Build Validation',
    surface: 'admin',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/build-validation-status',
  },
  'coverage-system-atlas': {
    title: 'Coverage',
    surface: 'system',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/coverage-system-atlas',
  },
  'permanent-migration': {
    title: 'Migrations',
    surface: 'system',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/permanent-migration',
  },
  'claude-admin-ai': {
    title: 'Claude Admin AI',
    surface: 'system',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/claude-admin-ai',
  },
  'ollama-local-assistant': {
    title: 'Ollama Local Assistant',
    surface: 'system',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/ollama-local-assistant',
  },
  'codex-review-center': {
    title: 'Codex Review Center',
    surface: 'system',
    navCategory: 'tools',
    hideFromNav: true,
    path: '/admin/codex-review-center',
  },
};

// ─── Legacy redirect table ────────────────────────────────────────────────────
// Every entry maps a legacy/old route to its canonical admin destination.
// The router creates <Navigate replace /> for each entry.
export const MERGED_LEGACY_PATHS: Record<string, string> = {
  // Overview consolidation
  '/admin/war-room': '/admin',
  '/admin/system': '/admin',
  '/admin/system-health': '/admin',

  // Data consolidation
  '/admin/ingestors': '/admin/data',

  // Intelligence consolidation
  '/admin/trainer': '/admin/intelligence',
  '/admin/model-state': '/admin/intelligence',
  '/admin/ai-brain': '/admin/intelligence',

  // Orchestration consolidation
  '/admin/orchestrator': '/admin/orchestration',
  '/admin/orchestrator-admin': '/admin/orchestration',
  '/admin/traders': '/admin/orchestration',
  '/admin/strategy-admin': '/admin/orchestration',

  // Risk & Readiness consolidation
  '/admin/risk-control': '/admin/risk',
  '/admin/readiness': '/admin/risk',
  '/admin/live-readiness': '/admin/risk',
  '/admin/readiness/mobile': '/admin/risk',
  '/admin/mobile-iphone-readiness': '/admin/risk',

  // Execution — canonical rename
  '/admin/execution-admin': '/admin/execution',

  // Exchanges — canonical rename
  '/admin/exchange-manager': '/admin/exchanges',

  // Configuration — canonical rename
  '/admin/config-admin': '/admin/config',

  // Reports consolidation
  '/admin/report-center': '/admin/reports',
  '/admin/operator-proof-dashboard': '/admin/evidence',

  // Logs — canonical rename
  '/admin/logs-errors': '/admin/logs',

  // Audit — canonical rename
  '/admin/audit-ledger': '/admin/audit',

  // Developer Tools consolidation
  '/admin/scripts': '/admin/tools',
  '/admin/script-registry': '/admin/tools',
  '/admin/build-validation': '/admin/tools',
  '/admin/build-validation-status': '/admin/tools',
  '/admin/coverage': '/admin/tools',
  '/admin/coverage-system-atlas': '/admin/tools',
  '/admin/migrations': '/admin/tools',
  '/admin/permanent-migration': '/admin/tools',
  '/admin/ai-tools': '/admin/tools',
  '/admin/claude-admin-ai': '/admin/tools',
  '/admin/ollama-local-assistant': '/admin/tools',

  // /system/* legacy namespace
  '/system': '/admin',
  '/system/control-center': '/admin',
  '/system/health': '/admin',
  '/system/executive-summary': '/admin/executive-status',
  '/system/build-code-review': '/admin/codex-review-center',
  '/system/risk-controllers': '/admin/risk',
  '/system/exchanges': '/admin/exchanges',
  '/system/position-quarantine': '/admin/risk',
  '/system/config': '/admin/config',
  '/system/logs': '/admin/logs',
  '/system/model-state': '/admin/intelligence',
  '/system/trainer': '/admin/intelligence',
  '/system/orchestrator': '/admin/orchestration',
  '/system/execution': '/admin/execution',
  '/system/audit-ledger': '/admin/audit',
  '/system/readiness': '/admin/risk',
  '/system/ai-tools': '/admin/tools',
  '/system/reports': '/admin/reports',
  '/system/build-validation': '/admin/tools',
  '/system/evidence': '/admin/reports',
  '/system/readiness/mobile': '/admin/risk',
  '/system/strategy-controls': '/admin/orchestration',
  '/system/ingestors': '/admin/data',

  // Trader/public legacy
  '/mission-control': '/dashboard',
  '/admin/mission-control': '/dashboard',
  '/operator-proof': '/admin/reports',
  '/ai': '/ai-predictions',
  '/ai-predictions/model-state': '/ai-predictions',
  '/symbols': '/markets',
  '/admin/symbols': '/markets',
  '/markets/symbols': '/markets',
  '/admin/market-intelligence': '/research',
  '/admin/signals': '/signals',
  '/executions': '/portfolio/executions',
  '/admin/executions': '/portfolio/executions',
  '/admin/positions': '/portfolio',
  '/admin/technical-analysis': '/technical-analysis',
  '/research/technical-analysis': '/technical-analysis',
  '/admin/liquidation-bridge': '/derivatives',
  '/admin/strategy-backtesting': '/backtests',
  '/admin/paper-trading': '/trade',
  '/trade/paper': '/trade',
  '/admin/replay': '/backtests',
  '/backtests/replay': '/backtests',
  '/trader': '/trade',
  '/history': '/portfolio/history',
  '/landing-legacy': '/landing',
  '/market': '/markets',
};

export function resolvePageModule(page: PageModule): PageModule {
  const override = PAGE_OVERRIDES[page.meta.id];
  if (!override) return page;
  const meta: PageMeta = {
    ...page.meta,
    title: override.title ?? page.meta.title,
    navLabel: override.navLabel ?? page.meta.navLabel,
    description: override.description ?? page.meta.description,
    surface: override.surface ?? page.meta.surface,
    navCategory: override.navCategory ?? page.meta.navCategory,
    navOrder: override.navOrder ?? page.meta.navOrder,
    hideFromNav: override.hideFromNav ?? page.meta.hideFromNav,
  };
  const route: PageRoute = { path: override.path ?? page.route.path };
  return { ...page, meta, route };
}
