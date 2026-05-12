import meta from './meta';
import rbac from './rbac';
import route from './route';
import { CockpitLoading, Panel } from '../cockpitComponents';
import { useCockpitPayload, valueText } from '../cockpitData';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

export default function RiskControlPage(): JSX.Element {
  const { payload, error } = useCockpitPayload();
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const decision = payload?.decisions[0];
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Risk Control" source="V2_PROOF_ARTIFACT / fail-closed policy" status="DANGEROUS CONTROLS DISABLED">
      <SourceRibbon labels={['kill switch default-deny', 'Risk Gateway final authority', 'no ADJUST_LEVERAGE bypass', 'live approval required']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Risk Control" /> : <OperatorTruthLoading error={truthError} />}
      {payload ? (
        <Panel id="risk-control-fail-closed-gates" title="Fail-Closed Risk Gates" right={<span className="chip solid-block">LIVE BLOCKED</span>}>
          <div className="cockpit-lineage-grid">
            {([
              ['live gate', payload.live_gate_status],
              ['account mode', payload.account_mode],
              ['risk_decision_id', decision?.risk_decision_id ?? 'MISSING'],
              ['risk reason', decision?.risk_reason ?? 'Evidence missing - cannot explain without guessing'],
              ['execution_intent_id', decision?.execution_intent_id ?? 'MISSING'],
              ['paper/shadow/live result', decision?.result ?? 'MISSING'],
            ] satisfies Array<[string, unknown]>).map(([label, value]) => (
              <div key={label}>
                <span>{label}</span>
                <strong>{valueText(value)}</strong>
              </div>
            ))}
          </div>
          <div className="cockpit-card-grid">
            {[
              'missing signal_id blocks',
              'missing decision_id blocks',
              'stale signal blocks',
              'duplicate execution blocks',
              'CROSS margin requires explicit approval',
              'leverage increase requires explicit approval',
              'kill switch disable requires explicit approval',
              'mandatory stop disable requires explicit approval',
            ].map((rule) => (
              <div className="cockpit-evidence-gap" key={rule}>{rule}</div>
            ))}
          </div>
        </Panel>
      ) : <CockpitLoading error={error} />}
    </DesignPageShell>
  );
}
