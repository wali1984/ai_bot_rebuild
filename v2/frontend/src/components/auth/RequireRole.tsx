import { Navigate, useLocation } from 'react-router-dom';
import { canSee, normalizeRole, type RoleLike } from '../../auth/rbac';
import { useAuth } from '../../hooks/useAuth';
import { AccessDenied } from './AccessDenied';
import { AuthGate } from './AuthGate';

export function RequireRole({ children, role }: { children: JSX.Element; role: RoleLike }): JSX.Element {
  const { user, loading } = useAuth();
  const location = useLocation();
  if (loading) return <AuthGate />;
  if (!user) return <Navigate to={`/login?returnTo=${encodeURIComponent(location.pathname)}`} replace />;
  if (!canSee(user.role, role)) return <AccessDenied required={normalizeRole(role)} />;
  return children;
}

