import { lazy } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AdminShell } from './components/layout/AdminShell';
import { RequireRole } from './components/auth/RequireRole';
import { PublicShell } from './components/layout/PublicShell';
import { TraderShell } from './components/layout/TraderShell';
import { RouteErrorBoundary } from './components/RouteErrorBoundary';
import { ADMIN_PAGES, PUBLIC_PAGES, APP_PAGES } from './pages/registry';
import { MERGED_LEGACY_PATHS } from './pages/productNavigation';

const PublicLandingPage = lazy(() => import('./pages/public-landing-v2'));

function pageElement(page: (typeof ADMIN_PAGES)[number]): JSX.Element {
  const element = <page.Component />;
  return page.rbac.minRole === 'public'
    ? element
    : <RequireRole role={page.rbac.minRole}>{element}</RequireRole>;
}

const adminChildren = ADMIN_PAGES.map((p) => ({
  path: p.route.path,
  element: pageElement(p),
}));
const publicChildren = PUBLIC_PAGES.map((p) => ({
  path: p.route.path,
  element: pageElement(p),
}));
const appChildren = APP_PAGES.map((p) => ({
  path: p.route.path,
  element: pageElement(p),
}));

// All legacy → canonical redirects are driven by MERGED_LEGACY_PATHS in productNavigation.ts.
// Do not add one-off hardcoded redirects here — add them to MERGED_LEGACY_PATHS instead.
const legacyRedirectRoutes = Object.entries(MERGED_LEGACY_PATHS).map(([from, to]) => ({
  path: from,
  element: <Navigate to={to} replace />,
}));

// errorElement on every shell so a route/lazy-chunk failure is caught by the
// RouteErrorBoundary (auto-reloads on a stale chunk after redeploy) instead of
// React Router's blank "Unexpected Application Error!" default.
const errorElement = <RouteErrorBoundary />;

export const router = createBrowserRouter([
  { path: '/', element: <PublicShell />, errorElement, children: [{ index: true, element: <PublicLandingPage /> }] },
  ...legacyRedirectRoutes,
  { element: <PublicShell />, errorElement, children: publicChildren },
  { element: <TraderShell />, errorElement, children: appChildren },
  { element: <AdminShell />, errorElement, children: adminChildren },
  { path: '*', element: <Navigate to="/landing" replace /> },
]);
