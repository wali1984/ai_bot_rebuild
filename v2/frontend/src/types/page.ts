import type { Role } from '../auth/rbac';
import type { DangerousControlId } from '../constants/dangerousControls';

export type Surface = 'admin' | 'public';

export interface PageMeta {
  id: string;
  title: string;
  surface: Surface;
  description: string;
  navCategory: string;
  dangerousControlIds: ReadonlyArray<DangerousControlId>;
}

export interface PageRbac {
  minRole: Role;
}

export interface PageRoute {
  path: string;
}

export interface PageModule {
  meta: PageMeta;
  rbac: PageRbac;
  route: PageRoute;
  Component: React.ComponentType;
}
