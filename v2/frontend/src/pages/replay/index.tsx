import { useEffect, useState } from 'react';
import meta from './meta';
import rbac from './rbac';
import route from './route';
import { Metric, Panel } from '../cockpitComponents';
import { DesignPageShell, SourceRibbon } from '../designShell';
import { useOperatorTruthPayload } from '../operatorTruthData';
import { OperatorTruthLoading, RouteTruthSummary } from '../operatorTruthComponents';

interface ReplaySummary {
  generated_at?: string;
  historical_audit_status?: string;
  live_gate_status?: string;
  mode?: string;
  period_days?: number;
  scenario_count?: number;
  v2_block_count?: number;
  v2_paper_pnl_fixture_sum?: string;
  estimated_loss_avoided_by_v2?: string;
}

function useReplaySummary(): ReplaySummary | null {
  const [summary, setSummary] = useState<ReplaySummary | null>(null);
  useEffect(() => {
    let active = true;
    fetch('/historical_30d_replay_and_paper_proof/latest/historical_30d_summary.json', { cache: 'no-store' })
      .then((response) => response.ok ? response.json() as Promise<ReplaySummary> : null)
      .then((next) => { if (active) setSummary(next); })
      .catch(() => { if (active) setSummary(null); });
    return () => { active = false; };
  }, []);
  return summary;
}

export default function ReplayPage(): JSX.Element {
  const { payload: truthPayload, error: truthError } = useOperatorTruthPayload();
  const summary = useReplaySummary();
  return (
    <DesignPageShell meta={meta} rbac={rbac} route={route} eyebrow="Replay" source="STATIC_PROOF_FIXTURE / historical replay" status="OFFLINE DETERMINISTIC PROOF ONLY">
      <SourceRibbon labels={['deterministic replay', 'static proof fixture', 'not continuous runtime', 'not live readiness']} />
      {truthPayload ? <RouteTruthSummary payload={truthPayload} title="Replay" /> : <OperatorTruthLoading error={truthError} />}
      <Panel id="replay-historical-proof-status" title="Historical Replay Proof Status" right={<span className="chip solid-paper">STATIC_PROOF_FIXTURE</span>}>
        <div className="cockpit-analytics-grid">
          <Metric label="Mode" value={summary?.mode ?? 'MISSING_EVIDENCE'} />
          <Metric label="Generated" value={summary?.generated_at ?? 'MISSING_EVIDENCE'} />
          <Metric label="Period days" value={summary?.period_days ?? 'MISSING_EVIDENCE'} />
          <Metric label="Scenarios" value={summary?.scenario_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="V2 blocks" value={summary?.v2_block_count ?? 'MISSING_EVIDENCE'} />
          <Metric label="Fixture paper PnL" value={summary?.v2_paper_pnl_fixture_sum ?? 'MISSING_EVIDENCE'} />
          <Metric label="Estimated avoided loss" value={summary?.estimated_loss_avoided_by_v2 ?? 'MISSING_EVIDENCE'} />
          <Metric label="Live gate" value={summary?.live_gate_status ?? 'blocked_human_only'} />
        </div>
        <p className="cockpit-evidence-gap">
          Replay output is historical/static proof. It must not be presented as current paper/shadow runtime or live readiness evidence.
        </p>
      </Panel>
    </DesignPageShell>
  );
}
