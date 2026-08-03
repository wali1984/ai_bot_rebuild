import type { PageRbac } from '../../types/page';
// 'trader' (read-only visibility): the documented operating login is the
// trader account; a 'reviewer' gate made this surface a daily-ops dead-end.
// All mutating/live actions remain backend-gated (require_admin + human
// approval); LIVE TRADING stays BLOCKED regardless of page visibility.
const rbac: PageRbac = { minRole: 'trader' };
export default rbac;
