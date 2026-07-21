import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'monitor-center',
  title: 'Monitor Center',
  surface: 'admin',
  // Honest scope: this surface covers page/route coverage, data surfaces,
  // realtime streams, and build status. It does NOT yet carry the CLAUDE.md
  // monitor-script inventory (no monitor-script registry payload exists) — do
  // not promise it here until that surface ships (final field audit).
  description: 'Page/route coverage, data-surface and realtime-stream health, and build status. Monitor-script inventory not yet wired.',
  navCategory: 'observability',
  dangerousControlIds: [],
};
export default meta;
