import type { PageRbac } from '../../types/page';

// minRole 'trader': the sole human operator account is role=trader, and the
// higher-role admin account has no surfaced credential/elevation path in the
// GUI — 'admin' here made this required read-only model-state page a practical
// RBAC dead-end. The page renders telemetry only (no mutating controls);
// dangerous settings stay backend-gated behind explicit human approval.
const rbac: PageRbac = { minRole: 'trader' };

export default rbac;
