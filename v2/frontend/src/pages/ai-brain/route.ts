import type { PageRoute } from '../../types/page';

// Keep in sync with PAGE_OVERRIDES['ai-brain'].path in productNavigation.ts —
// the override is what actually mounts this page. The old raw path '/ai-brain'
// was dead metadata: the override rewrote it to /admin/model-state at registry
// resolution, so '/ai-brain' fell through the '*' catch-all to /landing.
const route: PageRoute = { path: '/admin/model-state' };

export default route;
