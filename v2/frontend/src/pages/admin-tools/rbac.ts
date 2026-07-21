import type { PageRbac } from '../../types/page';
// 'admin' (not 'live_approver'): the backend gates these endpoints with
// require_admin and the auth store has no superadmin/live_approver account,
// so a 'live_approver' page gate was an unreachable RBAC dead-end for every
// real login (final field audit).
const rbac: PageRbac = { minRole: 'admin' };
export default rbac;
