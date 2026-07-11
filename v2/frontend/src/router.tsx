import { lazy } from 'react';
import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AdminShell } from './components/layout/AdminShell';
import { PublicShell } from './components/layout/PublicShell';
import { TraderShell } from './components/layout/TraderShell';
import { ADMIN_PAGES, PUBLIC_PAGES, APP_PAGES } from './pages/registry';
import { MERGED_LEGACY_PATHS } from './pages/productNavigation';

const PublicLandingPage = lazy(() => import('./pages/public-landing-v2'));

const adminChildren = ADMIN_PAGES.map((p) => ({
  path: p.route.path,
  element: <p.Component />,
}));
const publicChildren = PUBLIC_PAGES.map((p) => ({
  path: p.route.path,
  element: <p.Component />,
}));
const appChildren = APP_PAGES.map((p) => ({
  path: p.route.path,
  element: <p.Component />,
}));

// All legacy → canonical redirects are driven by MERGED_LEGACY_PATHS in productNavigation.ts.
// Do not add one-off hardcoded redirects here — add them to MERGED_LEGACY_PATHS instead.
const legacyRedirectRoutes = Object.entries(MERGED_LEGACY_PATHS).map(([from, to]) => ({
  path: from,
  element: <Navigate to={to} replace />,
}));

export const router = createBrowserRouter([
  { path: '/', element: <PublicShell />, children: [{ index: true, element: <PublicLandingPage /> }] },
  ...legacyRedirectRoutes,
  { element: <PublicShell />, children: publicChildren },
  { element: <TraderShell />, children: appChildren },
  { element: <AdminShell />, children: adminChildren },
  { path: '*', element: <Navigate to="/landing" replace /> },
]);
