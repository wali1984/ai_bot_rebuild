import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'admin-orchestration',
  title: 'Orchestration',
  surface: 'system',
  description: 'Orchestrator runtime, strategy routing, trader bots, queues, schedules, and dependency state.',
  navCategory: 'orchestration',
  navLabel: 'Orchestration',
  navOrder: 40,
  dangerousControlIds: ['enable_hedge_dca'],
};
export default meta;
