import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'live-readiness',
  title: 'Live Readiness',
  surface: 'admin',
  description: 'GO inputs for live mode. L4/L5 buttons disabled until criteria met.',
  navCategory: 'risk',
  dangerousControlIds: ['enable_live_trading', 'increase_leverage'],
};
export default meta;
