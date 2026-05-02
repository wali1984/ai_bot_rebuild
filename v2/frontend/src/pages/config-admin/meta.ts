import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'config-admin',
  title: 'Config Admin',
  surface: 'admin',
  description: 'Versioned config. Live-trading and margin toggles require L4/L5.',
  navCategory: 'admin',
  dangerousControlIds: [
    'enable_live_trading',
    'enable_adjust_leverage',
    'switch_paper_to_live',
    'enable_cross_margin',
  ],
};
export default meta;
