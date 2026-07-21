/**
 * Routing invariants — no browser required.
 *
 * Invariants:
 * 1. No resolved page path is also a redirect source in MERGED_LEGACY_PATHS.
 * 2. All MERGED_LEGACY_PATHS redirect targets resolve to a known page path or
 *    to another path that itself is a known page path (one-level chain allowed).
 * 3. Resolved page paths are unique across all surfaces.
 * 4. Known dead-end redirect targets do not exist (e.g. /admin/codex).
 */

import { test, expect } from '@playwright/test';
import { MERGED_LEGACY_PATHS } from '../../src/pages/productNavigation';

/**
 * Ground-truth resolved page paths after PAGE_OVERRIDES are applied.
 * Update this list whenever a page is added, renamed, or removed.
 */
const RESOLVED_PAGE_PATHS = new Set<string>([
  // Public surface
  '/landing',
  '/landing-v2',
  '/status',
  '/status-simple',
  '/login',
  '/markets',
  '/markets/ingestors',
  '/market/:symbol?',
  // App surface
  '/dashboard',
  '/trade',
  '/trade/paper',
  '/markets/symbols',
  '/derivatives',
  '/signals',
  '/ai-predictions',
  '/portfolio',
  '/portfolio/executions',
  '/portfolio/history',
  '/risk',
  '/audit-ledger',
  '/live-canary',
  '/backtests',
  '/backtests/replay',
  '/research',
  '/research/technical-analysis',
  '/alerts',
  '/account-settings',
  '/chart/:symbol?',
  // Admin surface
  '/admin',
  '/admin/data',
  '/admin/intelligence',
  '/admin/orchestration',
  '/admin/system',
  '/admin/monitor-center',
  '/admin/coverage',
  '/admin/scripts',
  '/admin/signal-explainability',
  '/admin/trainer-admin',
  '/admin/trainer-prediction-monitor',
  '/admin/ingestors',
  '/admin/trainer',
  '/admin/orchestrator',
  '/admin/risk',
  '/admin/live-readiness',
  '/admin/exchanges',
  '/admin/external-manual-position-quarantine',
  '/admin/config',
  '/admin/traders',
  '/admin/execution',
  '/admin/audit',
  '/admin/readiness',
  '/admin/readiness/mobile',
  '/admin/logs',
  '/admin/build-validation',
  '/admin/ai-tools',
  '/admin/migrations',
  '/admin/evidence',
  '/admin/reports',
  '/admin/tools',
  '/admin/users',
  '/admin/model-state',
  '/technical-analysis',
  // System surface
  '/admin/codex-review-center',
  '/admin/executive-status',
]);

/** Paths that are intentionally dead redirect targets (removed from MERGED_LEGACY_PATHS) */
const KNOWN_DEAD_TARGETS = new Set<string>([
  '/admin/codex',
]);

/**
 * hideFromNav pages that are intentionally shadowed by redirects.
 * The redirect prevents direct URL access; the page only exists as a component.
 * Per task spec: "dead but intended/harmless".
 */
const INTENTIONALLY_SHADOWED = new Set<string>([
  // '/trade/paper' removed 2026-07-21: the shadowing redirect was dropped, the
  // Execution Runtime page is reachable again.
  '/markets/symbols',
  '/backtests/replay',
  '/research/technical-analysis',
  '/admin/system',
  '/admin/coverage',
  '/admin/scripts',
  '/admin/ingestors',
  '/admin/trainer',
  '/admin/orchestrator',
  '/admin/traders',
  '/admin/readiness',
  '/admin/readiness/mobile',
  '/admin/build-validation',
  '/admin/ai-tools',
  '/admin/migrations',
  '/admin/model-state',
]);

test.describe('Routing invariants (no browser)', () => {
  test('no resolved page path is a redirect source (except intentionally-shadowed hideFromNav)', () => {
    const redirectSources = new Set(Object.keys(MERGED_LEGACY_PATHS));
    const shadowed: string[] = [];
    for (const pagePath of RESOLVED_PAGE_PATHS) {
      if (redirectSources.has(pagePath) && !INTENTIONALLY_SHADOWED.has(pagePath)) {
        shadowed.push(pagePath);
      }
    }
    expect(shadowed, `These page paths are shadowed by a redirect: ${shadowed.join(', ')}`).toHaveLength(0);
  });

  test('all redirect targets resolve to a known page path', () => {
    const redirectSources = new Set(Object.keys(MERGED_LEGACY_PATHS));
    const unresolved: string[] = [];
    for (const [from, to] of Object.entries(MERGED_LEGACY_PATHS)) {
      // Target must be a real page OR another redirect source (one-level chain)
      if (!RESOLVED_PAGE_PATHS.has(to) && !redirectSources.has(to)) {
        unresolved.push(`${from} → ${to}`);
      }
    }
    expect(unresolved, `Redirect targets that don't resolve: ${unresolved.join('; ')}`).toHaveLength(0);
  });

  test('known dead-end targets are not used as redirect targets', () => {
    const dead: string[] = [];
    for (const [from, to] of Object.entries(MERGED_LEGACY_PATHS)) {
      if (KNOWN_DEAD_TARGETS.has(to)) {
        dead.push(`${from} → ${to}`);
      }
    }
    expect(dead, `Redirects pointing to non-existent paths: ${dead.join('; ')}`).toHaveLength(0);
  });

  test('MERGED_LEGACY_PATHS does not shadow monitor-center', () => {
    expect(MERGED_LEGACY_PATHS['/admin/monitor-center']).toBeUndefined();
  });

  test('MERGED_LEGACY_PATHS does not shadow signal-explainability', () => {
    expect(MERGED_LEGACY_PATHS['/admin/signal-explainability']).toBeUndefined();
  });

  test('MERGED_LEGACY_PATHS does not shadow external-manual-position-quarantine', () => {
    expect(MERGED_LEGACY_PATHS['/admin/external-manual-position-quarantine']).toBeUndefined();
  });

  test('MERGED_LEGACY_PATHS does not shadow executive-status', () => {
    expect(MERGED_LEGACY_PATHS['/admin/executive-status']).toBeUndefined();
  });

  test('MERGED_LEGACY_PATHS does not shadow codex-review-center', () => {
    expect(MERGED_LEGACY_PATHS['/admin/codex-review-center']).toBeUndefined();
  });

  test('system build-code-review redirects to the real page path', () => {
    expect(MERGED_LEGACY_PATHS['/system/build-code-review']).toBe('/admin/codex-review-center');
  });

  test('system executive-summary redirects to the real page path', () => {
    expect(MERGED_LEGACY_PATHS['/system/executive-summary']).toBe('/admin/executive-status');
  });

  test('/dashboard is not a redirect source', () => {
    expect(MERGED_LEGACY_PATHS['/dashboard']).toBeUndefined();
  });

  test('/admin is not a redirect source', () => {
    expect(MERGED_LEGACY_PATHS['/admin']).toBeUndefined();
  });

  test('Phase 5 website aliases resolve to runtime truth surfaces', () => {
    expect(MERGED_LEGACY_PATHS['/ai']).toBe('/ai-predictions');
    expect(MERGED_LEGACY_PATHS['/system/model-state']).toBe('/admin/intelligence');
    expect(MERGED_LEGACY_PATHS['/risk']).toBeUndefined();
    expect(MERGED_LEGACY_PATHS['/live-canary']).toBeUndefined();
    expect(MERGED_LEGACY_PATHS['/admin/live-readiness']).toBeUndefined();
  });
});
