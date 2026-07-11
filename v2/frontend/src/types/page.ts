import type { ComponentType, LazyExoticComponent } from 'react';
import type { Role } from '../auth/rbac';
import type { DangerousControlId } from '../constants/dangerousControls';

export type Surface = 'admin' | 'public' | 'app' | 'system';

export interface PageMeta {
  id: string;
  title: string;
  surface: Surface;
  description: string;
  navCategory: string;
  dangerousControlIds: ReadonlyArray<DangerousControlId>;
  /** Optional display label override for navigation menus */
  navLabel?: string;
  /** Optional sort order within navCategory */
  navOrder?: number;
  /** Exclude from auto-generated navigation lists */
  hideFromNav?: boolean;
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
  Component: ComponentType | LazyExoticComponent<ComponentType>;
}
