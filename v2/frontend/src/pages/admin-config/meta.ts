import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'admin-config',
  title: 'Configuration',
  surface: 'admin',
  description: 'Versioned config: diff, rollback, validation, and dangerous-control toggle gating.',
  navCategory: 'config',
  navLabel: 'Configuration',
  navOrder: 80,
  dangerousControlIds: ['enable_live_trading', 'enable_adjust_leverage', 'switch_paper_to_live', 'enable_cross_margin'],
};
export default meta;
