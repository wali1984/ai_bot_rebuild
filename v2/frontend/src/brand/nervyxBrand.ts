import { nervyxTokens } from './generated/nervyx-tokens';

export const NERVYX_BRAND = {
  productName: 'NERVYX ONE',
  descriptor: 'Adaptive Market Intelligence',
  tagline: 'Sense. Decide. Adapt.',
  secondaryLine: 'One system. Every market state.',
  paperStatus: 'One system. Every market state.',
  liveBlockedLabel: 'Approval gated',
  assets: {
    logoOnMidnight: '/brand/nervyx-one-logo-horizontal-on-midnight.svg',
    logoOnLight: '/brand/nervyx-one-logo-horizontal-on-light.svg',
    stackedLight: '/brand/nervyx-one-logo-stacked-light.svg',
    stackedDark: '/brand/nervyx-one-logo-stacked-dark.svg',
    symbolGradient: '/brand/nervyx-one-symbol-gradient.svg',
    symbolWhite: '/brand/nervyx-one-symbol-white.svg',
    symbolBlack: '/brand/nervyx-one-symbol-black.svg',
    socialBanner: '/brand/nervyx-one-social-banner.png',
  },
  tokens: nervyxTokens,
} as const;

export type NervyxModuleId =
  | 'sense'
  | 'core'
  | 'shift'
  | 'guard'
  | 'replay'
  | 'execute'
  | 'observe';

export const NERVYX_MODULES: Record<NervyxModuleId, { displayName: string; description: string }> = {
  sense: nervyxTokens.manifest.modules.sense,
  core: nervyxTokens.manifest.modules.core,
  shift: nervyxTokens.manifest.modules.shift,
  guard: nervyxTokens.manifest.modules.guard,
  replay: nervyxTokens.manifest.modules.replay,
  execute: nervyxTokens.manifest.modules.execute,
  observe: nervyxTokens.manifest.modules.observe,
};

export function moduleForCategory(category: string | undefined): NervyxModuleId {
  switch (category) {
    case 'dashboard':
    case 'market':
    case 'markets':
    case 'derivatives':
    case 'ingestors':
    case 'signals':
      return 'sense';
    case 'predictions':
    case 'trainer':
    case 'ai':
    case 'ai-tools':
    case 'build-code-review':
      return 'core';
    case 'orchestrator':
    case 'strategy':
    case 'traders':
      return 'shift';
    case 'risk':
    case 'risk-controllers':
    case 'readiness':
    case 'quarantine':
    case 'external-manual-position-quarantine':
    case 'live-readiness':
      return 'guard';
    case 'execution':
    case 'trading':
    case 'trade':
    case 'portfolio':
    case 'account':
    case 'exchanges':
      return 'execute';
    case 'analytics':
    case 'backtests':
    case 'replay':
    case 'history':
    case 'evidence':
      return 'replay';
    case 'observability':
    case 'overview':
    case 'control-center':
    case 'admin':
    case 'mobile':
    case 'audit':
    case 'audit-ledger':
    case 'coverage':
    case 'scripts':
    case 'build-validation':
    case 'reports':
    case 'logs':
    case 'config':
    case 'users':
    case 'executive-summary':
    default:
      return 'observe';
  }
}

export function themeForSurface(surface: 'public' | 'admin'): 'midnight-neural' | 'ops-terminal' {
  return surface === 'admin' ? 'ops-terminal' : 'midnight-neural';
}

export function moduleColorVar(module: NervyxModuleId): string {
  return `var(--nervyx-${module})`;
}
