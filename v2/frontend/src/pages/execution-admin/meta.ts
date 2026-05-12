import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'execution-admin',
  title: 'Execution Admin',
  surface: 'admin',
  description: 'Execution router. Paper-only by default; paper-to-live and live keys are L4/L5.',
  navCategory: 'execution',
  dangerousControlIds: ['switch_paper_to_live', 'increase_max_position_size', 'add_live_api_keys'],
};
export default meta;
