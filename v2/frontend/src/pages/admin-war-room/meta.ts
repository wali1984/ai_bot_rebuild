import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'admin-war-room',
  title: 'Automation',
  surface: 'admin',
  description:
    'Admin-only view of the V2 8h war-room daemon. Wires real cycle history, gap matrix, blocker matrix, Codex queue, legacy log observer, safety scan, raw payload explorer.',
  navCategory: 'admin',
  dangerousControlIds: [],
};
export default meta;
