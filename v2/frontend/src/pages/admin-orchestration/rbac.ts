import type { PageRbac } from '../../types/page';

// minRole 'trader': the sole human operator account is role=trader, and the
// higher-role admin account has no surfaced credential/elevation path in the
// GUI — 'admin' here made this required orchestration page a practical RBAC
// dead-end. The page renders orchestrator runtime state read-only (tab
// switching only, no mutating controls); dangerous controls (e.g.
// enable_hedge_dca) remain backend-gated behind explicit human approval.
const rbac: PageRbac = { minRole: 'trader' };
export default rbac;
