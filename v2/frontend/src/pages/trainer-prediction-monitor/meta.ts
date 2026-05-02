import type { PageMeta } from '../../types/page';
const meta: PageMeta = {
  id: 'trainer-prediction-monitor',
  title: 'Trainer Prediction Monitor',
  surface: 'admin',
  description: 'Reads evidence_packets + liveness_confidence_level. Subprocess boundary, no live mutation.',
  navCategory: 'trainer',
  dangerousControlIds: [],
};
export default meta;
