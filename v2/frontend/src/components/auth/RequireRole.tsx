import { Navigate, useLocation } from 'react-router-dom';
import { canSee, normalizeRole, useRoles, type RoleLike } from '../../auth/rbac';
import { useAuth } from '../../hooks/useAuth';
import { AccessDenied } from './AccessDenied';
import { AuthGate } from './AuthGate';

export function RequireRole({ children, role }: { children: JSX.Element; role: RoleLike }): JSX.Element {
  const { user, loading } = useAuth();
  const sessionRole = useRoles();
  const location = useLocation();
  if (loading) return <AuthGate />;
  const effectiveRole = user?.role ? normalizeRole(user.role) : sessionRole;
  if (!canSee(effectiveRole, role)) {
    if (!user && effectiveRole === 'public') {
      return <Navigate to={`/login?returnTo=${encodeURIComponent(location.pathname)}`} replace />;
    }
    return <AccessDenied required={normalizeRole(role)} />;
  }
  return children;
}
