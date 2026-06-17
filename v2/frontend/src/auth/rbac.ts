import { useSyncExternalStore } from 'react';
import { sessionStore, type SessionState } from './session';

export type Role = 'public' | 'viewer' | 'trader' | 'operator' | 'reviewer' | 'admin' | 'live_approver';

// Covers legacy AuthRole values ('guest', 'superadmin') that arrive from the backend
export type RoleLike = Role | 'guest' | 'superadmin';

const HIERARCHY: Record<Role, number> = {
  public: 0,
  viewer: 1,
  trader: 2,
  operator: 3,
  reviewer: 4,
  admin: 5,
  live_approver: 6,
};

export function normalizeRole(r: RoleLike): Role {
  if (r === 'guest') return 'public';
  if (r === 'superadmin') return 'live_approver';
  return r;
}

export function canSee(actor: RoleLike, required: RoleLike): boolean {
  return HIERARCHY[normalizeRole(actor)] >= HIERARCHY[normalizeRole(required)];
}

export function useRoles(): Role {
  return useSyncExternalStore(
    sessionStore.subscribe,
    sessionStore.getRole,
    sessionStore.getRoleSnapshot,
  );
}

export function canSeePage(actor: RoleLike, requiredMin: RoleLike): boolean {
  if (requiredMin === 'public' || requiredMin === 'guest') return true;
  return canSee(actor, requiredMin);
}

/**
 * Pages visible to the 'viewer' role (read-only access).
 * Viewer can see markets, signals, dashboard, AI predictions.
 * Viewer CANNOT see: trade terminal, portfolio, executions, history, alerts management.
 */
export const VIEWER_ACCESSIBLE_PATHS = new Set([
  '/dashboard',
  '/markets',
  '/market',
  '/signals',
  '/ai-predictions',
  '/status',
  '/login',
  '/',
]);

export function isViewerAccessible(path: string): boolean {
  if (VIEWER_ACCESSIBLE_PATHS.has(path)) return true;
  // Dynamic paths like /market/:symbol
  if (path.startsWith('/market/')) return true;
  return false;
}

export type { SessionState };
