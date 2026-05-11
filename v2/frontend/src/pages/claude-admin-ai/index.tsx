import meta from './meta';
import rbac from './rbac';
import route from './route';
import { AutonomousGovernorPanel, CockpitLoading, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';

export default function ClaudeAdminAiPage(): JSX.Element {
  const { autonomousGovernor, error } = useCockpitPayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Claude Admin AI" source="AUTONOMOUS_GOVERNOR_PAYLOAD / non-live only" status="CANNOT ENABLE LIVE TRADING">
      <SourceRibbon labels={['Claude primary builder', 'Codex parallel auditor', 'Ollama draft-only helper', 'final live gate human-only']} />
      {autonomousGovernor ? <AutonomousGovernorPanel payload={autonomousGovernor} /> : <CockpitLoading error={error} />}
      <Panel id="claude-admin-ai-safety-contract" title="Admin AI Safety Contract" right={<span className="chip solid-block">No capital action</span>}>
        <div className="cockpit-card-grid">
          {[
            'Admin AI cannot enable live trading.',
            'Admin AI cannot create or activate live API keys.',
            'Admin AI cannot place, cancel, or close exchange orders.',
            'Admin AI cannot change leverage, margin mode, or position mode.',
            'Admin AI must preserve visible live-block and GO/NO-GO state.',
          ].map((rule) => (
            <div className="cockpit-evidence-gap" key={rule}>{rule}</div>
          ))}
        </div>
      </Panel>
    </DesignPageShell>
  );
}
