import type { PageRbac } from '../../types/page';

// 'admin' (not 'live_approver'): no superadmin/live_approver account exists in
// the auth store and bootstrap can only mint 'admin', so a 'live_approver'
// gate made /admin/evidence unreachable for every real login (final field audit).
const rbac: PageRbac = { minRole: 'admin' };

export default rbac;
