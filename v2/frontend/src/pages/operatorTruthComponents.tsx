import { Panel, Metric } from './cockpitComponents';
import type { OperatorTruthPayload, OperatorTruthStatusRow } from './operatorTruthData';
import { statusClass, valueText } from './cockpitData';

const MISSING = 'Evidence missing — cannot explain without guessing.';

function boolStatus(value: boolean): string {
  return value ? 'yes' : 'no';
}

function sourceChip(classification: string): JSX.Element {
  const tone = classification.includes('MISSING') || classification.includes('STALE')
    ? 'solid-warn'
    : classification.includes('STATIC')
      ? 'solid-paper'
      : 'solid-ok';
  return <span className={`chip ${tone}`}>{classification}</span>;
}

export function OperatorTruthLoading({ error }: { error: string | null }): JSX.Element {
  return (
    <Panel id="operator-truth-loading" title="Operator Truth Payload">
      <p className="cockpit-evidence-gap">
        {error ? `Evidence missing - operator truth payload unavailable: ${error}` : 'Loading operator truth payload...'}
      </p>
    </Panel>
  );
}

export function TruthStatusStrip({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const supervisor = payload.supervisor_status;
  const freshness = payload.dashboard_freshness_status;
  return (
    <section className="truth-status-strip" data-testid="operator-truth-status-strip" aria-label="Current operator truth status">
      <Metric label="Live gate" value={payload.live_gate_status} />
      <Metric label="Supervisor" value={supervisor.stale_or_conflicting ? 'SUPERVISOR_STATUS_STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'} />
      <Metric label="Master planner running" value={boolStatus(supervisor.master_planner_running)} />
      <Metric label="Autonomous governor" value={boolStatus(supervisor.autonomous_governor_active)} />
      <Metric label="Active workers" value={String(supervisor.supervisor_processes.length)} />
      <Metric label="Running task" value={supervisor.current_running_task ?? 'none'} />
      <Metric label="Next task" value={payload.current_next_task ?? 'MISSING'} />
      <Metric label="Redis trim" value={payload.redis_trim_status} />
      <Metric label="Stale payloads" value={String(freshness.stale_payload_count)} />
      <Metric label="Missing evidence" value={String(freshness.missing_evidence_count)} />
    </section>
  );
}

export function LegacyRuntimeMonitorPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const runtime = payload.runtime_monitor_status;
  return (
    <Panel id="operator-truth-legacy-runtime" title="Old System / Legacy Runtime Monitor" right={sourceChip('REALTIME_RUNTIME_EVIDENCE')}>
      <div className="cockpit-lineage-grid">
        <div><span>orchestrator</span><strong>{runtime.orchestrator_status}</strong></div>
        <div><span>trainer</span><strong>{runtime.trainer_status}</strong></div>
        <div><span>trader</span><strong>{runtime.trader_status}</strong></div>
        <div><span>active process rows</span><strong>{runtime.active_processes.length}</strong></div>
        <div><span>redis memory pressure</span><strong>{runtime.redis_memory_pressure_status?.status ?? 'MISSING_EVIDENCE'}</strong></div>
        <div><span>evidence source</span><strong>operator_truth_payload.json</strong></div>
      </div>
      <div className="cockpit-card-grid">
        {runtime.active_processes.length ? runtime.active_processes.map((line) => (
          <div className="cockpit-evidence-gap" key={line}>{line}</div>
        )) : <div className="cockpit-evidence-gap">No matching legacy/trainer/trader process rows observed.</div>}
      </div>
    </Panel>
  );
}

export function TrainerPredictionTruthPanel({ payload }: { payload: OperatorTruthPayload; }): JSX.Element {
  const trainer = payload.trainer_monitor_status;
  const latest = trainer.latest_prediction;
  return (
    <Panel id="operator-truth-trainer-prediction" title="Trainer Prediction Monitor Preview" right={sourceChip(trainer.status)}>
      <div className="cockpit-lineage-grid">
        <div><span>status</span><strong>{trainer.status}</strong></div>
        <div><span>payload age seconds</span><strong>{valueText(trainer.payload_age_seconds)}</strong></div>
        <div><span>prediction worker from payload</span><strong>{valueText(trainer.prediction_worker_alive_from_stale_payload)}</strong></div>
        <div><span>latest trainer status from payload</span><strong>{valueText(trainer.latest_trainer_status_from_payload)}</strong></div>
        <div><span>prediction_id</span><strong>{valueText(latest?.prediction_id)}</strong></div>
        <div><span>feature_snapshot_id</span><strong>{valueText(latest?.feature_snapshot_id)}</strong></div>
        <div><span>model/checkpoint</span><strong>{valueText(latest?.model_checkpoint)}</strong></div>
        <div><span>raw / calibrated confidence</span><strong>{valueText(latest?.confidence_raw)} / {valueText(latest?.confidence_calibrated)}</strong></div>
      </div>
      <p className="cockpit-evidence-gap">
        {trainer.status === 'REALTIME_RUNTIME_EVIDENCE'
          ? 'Realtime trainer process evidence is present.'
          : 'TRAINER_RUNTIME_EVIDENCE_MISSING. Static proof predictions are not current trainer output.'}
      </p>
    </Panel>
  );
}

export function SignalLineageTruthPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const signal = payload.signal_lineage_status;
  const latest = signal.latest_signal;
  return (
    <Panel id="operator-truth-signal-lineage" title="Signal Explainability Preview" right={sourceChip(signal.status)}>
      {latest ? (
        <div className="cockpit-lineage-grid">
          {([
            ['signal_id', latest.signal_id],
            ['prediction_id', latest.prediction_id],
            ['feature_snapshot_id', latest.feature_snapshot_id],
            ['orchestrator_decision_id', latest.orchestrator_decision_id],
            ['risk_decision_id', latest.risk_decision_id],
            ['execution_intent_id', latest.execution_intent_id],
            ['orchestrator reason', latest.orchestrator_reason],
            ['risk reason', latest.risk_reason],
            ['result', latest.result],
          ] satisfies Array<[string, unknown]>).map(([label, value]) => (
            <div key={label}>
              <span>{label}</span>
              <strong>{valueText(value)}</strong>
            </div>
          ))}
        </div>
      ) : (
        <p className="cockpit-evidence-gap">{MISSING}</p>
      )}
      {signal.status !== 'REALTIME_RUNTIME_EVIDENCE' ? (
        <p className="cockpit-evidence-gap">Signal lineage preview is {signal.status}; do not treat it as live runtime truth.</p>
      ) : null}
    </Panel>
  );
}

export function WhatIsWorkingPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  const rows = [
    ['realtime monitor', payload.supervisor_status.stale_or_conflicting ? 'STALE_OR_CONFLICTING' : 'CURRENT_SNAPSHOT'],
    ['read-only market feed', payload.proof_artifact_statuses.find((row) => row.label.includes('readonly market'))?.status ?? 'MISSING_EVIDENCE'],
    ['trainer predictions', payload.trainer_monitor_status.status],
    ['signal lineage', payload.signal_lineage_status.status],
    ['risk gateway', payload.source_files.some((path) => path.includes('risk_gateway')) ? 'V2_PROOF_ARTIFACT' : 'MISSING_EVIDENCE'],
    ['paper/shadow', payload.proof_artifact_statuses.find((row) => row.label.includes('paper'))?.status ?? 'MISSING_EVIDENCE'],
    ['website payload freshness', payload.dashboard_freshness_status.stale_payload_count ? 'STALE_PAYLOADS_PRESENT' : 'CURRENT_SNAPSHOT'],
  ];
  return (
    <Panel id="operator-truth-working-status" title="What Is Actually Working?">
      <div className="cockpit-card-grid">
        {rows.map(([label, value]) => (
          <div className="cockpit-exchange-card" key={label}>
            <h3>{label}</h3>
            <strong className={statusClass(value)}>{value}</strong>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function PayloadFreshnessPanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  return (
    <Panel id="operator-truth-payload-freshness" title="Payload Freshness And Evidence Classification">
      <div className="cockpit-market-table" role="table">
        <div className="cockpit-table-row cockpit-table-row--head" role="row">
          <span>Payload</span><span>Class</span><span>Status</span><span>Age</span><span>Realtime</span><span>Static</span><span>Missing</span><span>Source</span>
        </div>
        {payload.dashboard_freshness_status.payload_statuses.map((row) => (
          <div className="cockpit-table-row" role="row" key={row.path}>
            <span>{row.label}</span>
            <span className={statusClass(row.classification)}>{row.classification}</span>
            <span className={statusClass(row.status)}>{row.status}</span>
            <span>{valueText(row.age_seconds)}</span>
            <span>{boolStatus(row.is_realtime)}</span>
            <span>{boolStatus(row.is_static_fixture)}</span>
            <span>{boolStatus(row.missing)}</span>
            <span>{row.path}</span>
          </div>
        ))}
      </div>
    </Panel>
  );
}

export function MissingEvidencePanel({ payload }: { payload: OperatorTruthPayload }): JSX.Element {
  return (
    <Panel id="operator-truth-missing-evidence" title="Exact Missing Evidence And Blockers" right={sourceChip('MISSING_EVIDENCE')}>
      <div className="cockpit-card-grid">
        {payload.current_blockers.map((row) => (
          <div className="cockpit-evidence-gap" key={row.id}>
            <strong>{row.id}</strong>
            <p>{row.severity}: {row.detail}</p>
          </div>
        ))}
      </div>
    </Panel>
  );
}
