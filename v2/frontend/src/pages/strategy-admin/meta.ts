import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'strategy-admin',
  title: 'Strategy Admin',
  surface: 'admin',
  description: 'Strategy registration and lifecycle. Hedge/DCA toggles are L4.',
  navCategory: 'trainer',
  dangerousControlIds: ['enable_hedge_dca'],
};
export default meta;
