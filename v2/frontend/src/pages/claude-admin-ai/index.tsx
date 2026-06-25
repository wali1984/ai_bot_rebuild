import meta from './meta';
import rbac from './rbac';
import route from './route';
import { AutonomousGovernorPanel, CockpitLoading, Panel } from '../cockpitComponents';
import { useCockpitPayload } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload, usePaperOnlineRuntimePayload } from '../operatorTruthData';
import { OperatorTruthLoading, PaperOnlineRuntimeStatusPanel, RouteTruthSummary } from '../operatorTruthComponents';

export default function ClaudeAdminAiPage(): JSX.Element {
  const { autonomousGovernor, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const { payload: paperRuntime } = usePaperOnlineRuntimePayload();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Claude Admin AI" source="AUTONOMOUS_GOVERNOR_PAYLOAD / non-live only" status="CANNOT ENABLE EXCHANGE EXECUTION">
      <SourceRibbon labels={['Claude primary builder', 'Codex parallel auditor', 'Ollama draft-only helper', 'final live gate human-only']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Claude Admin AI" /> : <OperatorTruthLoading error={truthError} />}
      <PaperOnlineRuntimeStatusPanel payload={paperRuntime} />
      <Panel id="claude-admin-ai-query-surface" title="Operator Evidence Query Surface" right={<span className="chip">live evidence</span>}>
        <div className="cockpit-two-col">
          <label className="field-stack">
            <span>Question</span>
            <textarea
              aria-label="Claude Admin AI question"
              placeholder="Ask: Is trainer current? Why was this signal blocked? What is blocking live?"
              rows={5}
            />
          </label>
          <div className="cockpit-evidence-list">
            {[
              'Answers must cite operator truth, execution runtime, risk decisions, audit ledger, or build status.',
              'If evidence is missing, the assistant must say evidence missing and name the source needed.',
              'Live enablement, exchange keys, leverage, margin, and order actions remain disabled.',
            ].map((rule) => (
              <div className="cockpit-evidence-row" key={rule}>
                <span>{rule}</span>
                <strong>enforced</strong>
              </div>
            ))}
          </div>
        </div>
        <div className="control-grid">
          {['Is trainer current?', 'Why was latest signal blocked?', 'What data is stale?', 'What is blocking live?'].map((prompt) => (
            <button className="secondary-button" type="button" key={prompt}>
              {prompt}
            </button>
          ))}
        </div>
      </Panel>
      {autonomousGovernor ? <AutonomousGovernorPanel payload={autonomousGovernor} /> : <CockpitLoading error={error} />}
      <Panel id="claude-admin-ai-safety-contract" title="Admin AI Safety Contract" right={<span className="chip solid-block">No capital action</span>}>
        <div className="cockpit-card-grid">
          {[
            'Admin AI cannot enable live order routing.',
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
