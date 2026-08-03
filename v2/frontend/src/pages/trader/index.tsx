import { TradeTerminal } from '../../components/trade/TradeTerminal';
import { TrainerLaneHealthBanner } from '../../components/trainer/TrainerLaneHealthBanner';

export default function TraderPage(): JSX.Element {
  // The model behind every signal on this terminal is only as good as the
  // trainer lanes feeding it — surface a stopped/stalled trainer here too.
  return (
    <>
      <TrainerLaneHealthBanner />
      <TradeTerminal />
    </>
  );
}
