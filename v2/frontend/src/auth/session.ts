import type { Role } from './rbac';

export interface SessionState {
  role: Role;
  actorId: string | null;
  csrfToken: string | null;
}

const DEFAULT_SESSION: SessionState = {
  role: 'public',
  actorId: null,
  csrfToken: null,
};

const STORAGE_KEY = 'v2.session.role.shell';
let cached: SessionState = readInitial();
const listeners = new Set<() => void>();

function readInitial(): SessionState {
  if (typeof window === 'undefined') return DEFAULT_SESSION;
  try {
    const url = new URL(window.location.href);
    const queryRole = url.searchParams.get('role') as Role | null;
    if (queryRole) {
      window.sessionStorage.setItem(STORAGE_KEY, queryRole);
      return { ...DEFAULT_SESSION, role: queryRole };
    }
    const stored = window.sessionStorage.getItem(STORAGE_KEY) as Role | null;
    if (stored) return { ...DEFAULT_SESSION, role: stored };
  } catch {
    // sessionStorage unavailable; fall through
  }
  return DEFAULT_SESSION;
}

function emit(): void {
  for (const fn of listeners) fn();
}

export const sessionStore = {
  subscribe(fn: () => void): () => void {
    listeners.add(fn);
    return () => listeners.delete(fn);
  },
  getRole(): Role {
    return cached.role;
  },
  getRoleSnapshot(): Role {
    return cached.role;
  },
  setRole(role: Role): void {
    cached = { ...cached, role };
    try {
      window.sessionStorage.setItem(STORAGE_KEY, role);
    } catch {
      // ignore
    }
    emit();
  },
  setRoleForTest(role: Role): void {
    this.setRole(role);
  },
  clear(): void {
    cached = DEFAULT_SESSION;
    try {
      window.sessionStorage.removeItem(STORAGE_KEY);
    } catch {
      // ignore
    }
    emit();
  },
};
