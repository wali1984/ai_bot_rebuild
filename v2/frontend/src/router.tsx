import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AdminShell } from './components/layout/AdminShell';
import { PublicShell } from './components/layout/PublicShell';
import { TraderShell } from './components/layout/TraderShell';
import { ADMIN_PAGES, PUBLIC_PAGES, APP_PAGES } from './pages/registry';
import { MERGED_LEGACY_PATHS } from './pages/productNavigation';
import PublicLandingPage from './pages/public-landing-v2';

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

// Paths already handled by hardcoded routes above — skip them in the generated set
const HARDCODED_REDIRECT_PATHS = new Set([
  '/admin/risk-control',
  '/admin/orchestrator-admin',
  '/admin/system-health',
  '/market',
  '/trader',
]);

const legacyRedirectRoutes = Object.entries(MERGED_LEGACY_PATHS)
  .filter(([from]) => !HARDCODED_REDIRECT_PATHS.has(from))
  .map(([from, to]) => ({ path: from, element: <Navigate to={to} replace /> }));

export const router = createBrowserRouter([
  { path: '/', element: <PublicShell />, children: [{ index: true, element: <PublicLandingPage /> }] },
  { path: '/admin/risk-control', element: <Navigate to="/admin/risk" replace /> },
  { path: '/admin/orchestrator-admin', element: <Navigate to="/admin/orchestrator" replace /> },
  { path: '/admin/system-health', element: <Navigate to="/admin/system" replace /> },
  { path: '/market', element: <Navigate to="/markets" replace /> },
  { path: '/trader', element: <Navigate to="/trade" replace /> },
  ...legacyRedirectRoutes,
  { element: <PublicShell />, children: publicChildren },
  { element: <TraderShell />, children: appChildren },
  { element: <AdminShell />, children: adminChildren },
  { path: '*', element: <Navigate to="/landing" replace /> },
]);
