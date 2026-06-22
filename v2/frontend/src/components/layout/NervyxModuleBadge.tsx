import type { CSSProperties } from 'react';
import { NERVYX_MODULES, moduleColorVar, type NervyxModuleId } from '../../brand/nervyxBrand';

interface NervyxModuleBadgeProps {
  moduleId: NervyxModuleId;
  compact?: boolean;
}

export function NervyxModuleBadge({ moduleId, compact = false }: NervyxModuleBadgeProps): JSX.Element {
  const module = NERVYX_MODULES[moduleId];
  return (
    <span
      className={compact ? 'nervyx-module-badge nervyx-module-badge--compact' : 'nervyx-module-badge'}
      data-nervyx-module={moduleId}
      title={module.description}
      style={{ '--nervyx-module-color': moduleColorVar(moduleId) } as CSSProperties}
    >
      {compact ? module.displayName.replace('NERVYX ', '') : module.displayName}
    </span>
  );
}
