import { PAGES } from '../../../src/pages/registry';
import { MERGED_LEGACY_PATHS } from '../../../src/pages/productNavigation';

/**
 * Route-test contracts derived from the mounted registry.
 *
 * The previous hand-maintained arrays drifted behind the router: active pages
 * were omitted while redirect sources were still labelled canonical. Keep the
 * browser inventory coupled to the same registry and redirect map used by the
 * application so a final sweep cannot silently miss a mounted surface.
 */

function isRedirectSource(path: string): boolean {
  return Object.prototype.hasOwnProperty.call(MERGED_LEGACY_PATHS, path);
}

function materializeDynamicPath(path: string): string {
  if (path === '/market/:symbol?') return '/market/BTCUSDT';
  if (path === '/chart/:symbol?') return '/chart/BTCUSDT';
  if (path === '/markets/ingestors/:name?') return '/markets/ingestors';
  return path;
}

export const ACTIVE_ROUTE_MODULES = PAGES.filter((page) => !isRedirectSource(page.route.path));

export const PUBLIC_PAGE_PATHS: ReadonlyArray<string> = [
  '/',
  ...ACTIVE_ROUTE_MODULES
    .filter((page) => page.meta.surface === 'public')
    .map((page) => materializeDynamicPath(page.route.path)),
];

export const TRADER_PAGE_PATHS: ReadonlyArray<string> = ACTIVE_ROUTE_MODULES
  .filter((page) => page.meta.surface === 'app')
  .map((page) => materializeDynamicPath(page.route.path));

export const ADMIN_PAGE_PATHS: ReadonlyArray<string> = ACTIVE_ROUTE_MODULES
  .filter(
    (page) =>
      (page.meta.surface === 'admin' || page.meta.surface === 'system')
      && page.rbac.minRole !== 'live_approver',
  )
  .map((page) => materializeDynamicPath(page.route.path));

export const SUPERADMIN_PAGE_PATHS: ReadonlyArray<string> = ACTIVE_ROUTE_MODULES
  .filter(
    (page) =>
      (page.meta.surface === 'admin' || page.meta.surface === 'system')
      && page.rbac.minRole === 'live_approver',
  )
  .map((page) => materializeDynamicPath(page.route.path));

export const ALL_PAGE_PATHS: ReadonlyArray<string> = [
  ...PUBLIC_PAGE_PATHS,
  ...TRADER_PAGE_PATHS,
  ...ADMIN_PAGE_PATHS,
  ...SUPERADMIN_PAGE_PATHS,
];

export const PAGE_MIN_ROLE_BY_PATH: Readonly<Record<string, string>> = Object.freeze({
  '/': 'public',
  ...Object.fromEntries(
    ACTIVE_ROUTE_MODULES.map((page) => [
      materializeDynamicPath(page.route.path),
      page.rbac.minRole,
    ]),
  ),
});

export const REVIEWER_ONLY_ADMIN_PATHS: ReadonlyArray<string> = ACTIVE_ROUTE_MODULES
  .filter((page) => page.rbac.minRole === 'reviewer')
  .map((page) => materializeDynamicPath(page.route.path));

export const VIEWER_VISIBLE_ADMIN_PATHS: ReadonlyArray<string> = ACTIVE_ROUTE_MODULES
  .filter(
    (page) =>
      (page.meta.surface === 'admin' || page.meta.surface === 'system')
      && page.rbac.minRole === 'viewer',
  )
  .map((page) => materializeDynamicPath(page.route.path));

export const PAGES_WITH_DANGEROUS_CONTROLS: ReadonlyArray<{
  path: string;
  controls: ReadonlyArray<string>;
}> = ACTIVE_ROUTE_MODULES
  .filter((page) => page.meta.dangerousControlIds.length > 0)
  .map((page) => ({
    path: materializeDynamicPath(page.route.path),
    controls: page.meta.dangerousControlIds,
  }));

export const LEGACY_REDIRECTS: Readonly<Record<string, string>> = MERGED_LEGACY_PATHS;
