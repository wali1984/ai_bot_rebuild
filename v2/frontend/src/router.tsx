import { createBrowserRouter, Navigate } from 'react-router-dom';
import { AdminShell } from './components/layout/AdminShell';
import { PublicShell } from './components/layout/PublicShell';
import { ADMIN_PAGES, PUBLIC_PAGES } from './pages/registry';

const adminChildren = ADMIN_PAGES.map((p) => ({
  path: p.route.path,
  element: <p.Component />,
}));

const publicChildren = PUBLIC_PAGES.map((p) => ({
  path: p.route.path,
  element: <p.Component />,
}));

export const router = createBrowserRouter([
  { path: '/', element: <Navigate to="/admin/mission-control" replace /> },
  { element: <PublicShell />, children: publicChildren },
  { element: <AdminShell />, children: adminChildren },
  { path: '*', element: <Navigate to="/admin/mission-control" replace /> },
]);
