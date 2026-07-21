import type { PageRbac } from '../../types/page';

// minRole 'trader': the sole human operator account is role=trader, and the
// higher-role accounts have no surfaced credential/elevation path in the GUI —
// 'reviewer' here made this required trainer-admin page a practical RBAC
// dead-end. The page is read-only trainer telemetry (refresh only, no mutating
// controls); dangerous settings stay backend-gated behind explicit approval.
const rbac: PageRbac = { minRole: 'trader' };
export default rbac;
