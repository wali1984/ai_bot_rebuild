import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { fetchCurrentUser, loginWithPassword, logoutSession, type AuthUser, type LoginRequest } from '../api/auth';

interface AuthContextValue {
  user: AuthUser | null;
  loading: boolean;
  error: string | null;
  refresh: () => Promise<void>;
  login: (request: LoginRequest) => Promise<void>;
  logout: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

const anonymousAuthContext: AuthContextValue = {
  user: null,
  loading: false,
  error: null,
  refresh: async () => undefined,
  login: async () => undefined,
  logout: async () => undefined,
};

function shouldSkipInitialAuthProbe(): boolean {
  if (typeof window === 'undefined') return false;
  const pathname = window.location.pathname;
  return pathname === '/'
    || pathname === '/landing'
    || pathname === '/login'
    || pathname === '/status'
    || pathname === '/status-simple';
}

export function AuthProvider({ children }: { children: ReactNode }): JSX.Element {
  const [user, setUser] = useState<AuthUser | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    const nextUser = await fetchCurrentUser();
    setUser(nextUser);
    setLoading(false);
  }, []);

  useEffect(() => {
    if (shouldSkipInitialAuthProbe()) {
      setLoading(false);
      return;
    }
    void refresh();
  }, [refresh]);

  const login = useCallback(async (request: LoginRequest) => {
    setError(null);
    try {
      const response = await loginWithPassword(request);
      setUser(response.user);
    } catch (err) {
      const message = err instanceof Error ? err.message : 'Sign in failed';
      setError(message);
      throw err;
    }
  }, []);

  const logout = useCallback(async () => {
    await logoutSession();
    setUser(null);
  }, []);

  const value = useMemo<AuthContextValue>(() => ({ user, loading, error, refresh, login, logout }), [error, loading, login, logout, refresh, user]);

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth(): AuthContextValue {
  const context = useContext(AuthContext);
  if (!context) throw new Error('useAuth must be used within AuthProvider');
  return context;
}

export function useOptionalAuth(): AuthContextValue {
  return useContext(AuthContext) ?? anonymousAuthContext;
}
