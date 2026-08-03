import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'admin-execution',
  title: 'Execution',
  surface: 'admin',
  description: 'Execution router: fills, rejects, latency, slippage, reconciliation, and paper lifecycle admin.',
  navCategory: 'execution',
  navLabel: 'Execution',
  navOrder: 60,
  dangerousControlIds: ['switch_paper_to_live', 'increase_max_position_size', 'add_live_api_keys'],
};
export default meta;
