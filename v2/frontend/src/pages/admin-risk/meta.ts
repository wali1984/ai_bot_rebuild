import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'admin-risk',
  title: 'Risk & Readiness',
  surface: 'admin',
  description: 'Risk rules, kill switch, live-readiness wizard, position quarantine, override management, and mobile readiness.',
  navCategory: 'risk',
  navLabel: 'Risk & Readiness',
  navOrder: 50,
  dangerousControlIds: [
    'enable_live_trading',
    'increase_leverage',
    'disable_kill_switch',
    'disable_mandatory_stop',
    'increase_daily_loss_limit',
  ],
};
export default meta;
