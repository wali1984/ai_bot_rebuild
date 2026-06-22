import type { PageMeta } from '../../types/page';

const meta: PageMeta = {
  id: 'trader-legacy-alias',
  title: 'Trader Alias',
  surface: 'app',
  description: 'Hidden compatibility alias that redirects /trader to the canonical /trade route.',
  navCategory: 'execution',
  hideFromNav: true,
  dangerousControlIds: [],
};

export default meta;
