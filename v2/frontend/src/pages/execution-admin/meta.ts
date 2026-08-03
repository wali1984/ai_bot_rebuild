import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'execution-admin',
  title: 'Execution Admin',
  surface: 'admin',
  description: 'Execution router. Operator-gated by default; live transport and live keys are L4/L5.',
  navCategory: 'execution',
  dangerousControlIds: ['switch_paper_to_live', 'increase_max_position_size', 'add_live_api_keys'],
};
export default meta;
