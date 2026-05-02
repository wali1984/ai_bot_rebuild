import { useSyncExternalStore } from 'react';
import { sessionStore, type SessionState } from './session';

export type Role = 'public' | 'viewer' | 'operator' | 'reviewer' | 'admin' | 'live_approver';

const HIERARCHY: Record<Role, number> = {
  public: 0,
  viewer: 1,
  operator: 2,
  reviewer: 3,
  admin: 4,
  live_approver: 5,
};

export function canSee(actor: Role, required: Role): boolean {
  return HIERARCHY[actor] >= HIERARCHY[required];
}

export function useRoles(): Role {
  return useSyncExternalStore(
    sessionStore.subscribe,
    sessionStore.getRole,
    sessionStore.getRoleSnapshot,
  );
}

export function canSeePage(actor: Role, requiredMin: Role): boolean {
  if (requiredMin === 'public') return true;
  return canSee(actor, requiredMin);
}

export type { SessionState };
