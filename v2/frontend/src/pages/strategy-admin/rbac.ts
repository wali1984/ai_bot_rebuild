import type { PageRbac } from '../../types/page';

// minRole 'trader': the sole human operator account is role=trader; 'reviewer'
// here would keep this page a practical dead-end even after the '/admin/traders'
// redirect shadow was removed. The page is a read-only governor/entry-freeze/
// A+ funnel/risk-profile view (no mutating controls); the dangerous
// enable_hedge_dca control remains backend-gated behind explicit human approval.
const rbac: PageRbac = { minRole: 'trader' };
export default rbac;
