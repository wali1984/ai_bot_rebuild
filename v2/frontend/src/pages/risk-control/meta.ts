import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'risk-control',
  title: 'Risk Control',
  surface: 'admin',
  description: 'Policy bundles, kill switch, mandatory stop. Mutations require L4/L5 approval.',
  navCategory: 'risk',
  dangerousControlIds: ['disable_kill_switch', 'disable_mandatory_stop', 'increase_daily_loss_limit'],
};
export default meta;
