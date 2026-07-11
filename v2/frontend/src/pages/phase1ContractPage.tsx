import { ageClass, fmtAge, usePayloadFile } from '../hooks/usePayloadFile';
import type { PageMeta, PageRbac, PageRoute } from '../types/page';
import { Panel } from './cockpitComponents';
import { valueText } from './cockpitData';
import { DesignPageShell, SourceRibbon } from './designShell';

interface PayloadRef {
  label: string;
  path: string;
  required: boolean;
  staleAfterSeconds: number;
}

const LIVE_GATE_RUNTIME_PATH = '/operator_runtime/v2_live_gate_runtime/latest/live_gate_runtime_state.json';

interface LiveGateRuntimePayload {
  live_gate?: string;
  live_order_submit_allowed?: boolean;
  live_blocked?: boolean;
  live_blocker?: string;
  places_real_order?: boolean;
}

function resolveGateChipClass(p: LiveGateRuntimePayload | null | undefined): string {
  if (!p) return 'chip solid-warn';
  // Even if gate is approval-recorded, treat as blocked when submit is not allowed
  const submitOk = p.live_order_submit_allowed === true && p.live_blocked !== true && p.places_real_order !== false;
  return submitOk ? 'chip solid-live' : 'chip solid-block';
}

function resolveGateLabel(p: LiveGateRuntimePayload | null | undefined): string {
  if (!p) return 'approval gated';
  if (p.live_order_submit_allowed === false || p.live_blocked === true) {
    return p.live_blocker ?? 'BLOCKED';
  }
  return p.live_gate ?? 'approval gated';
}

interface ContractPageProps {
  meta: PageMeta;
  rbac: PageRbac;
  route: PageRoute;
  eyebrow: string;
  status: string;
  sourceLabels: string[];
  placeholderStates: string[];
  payloads: PayloadRef[];
  bridgeKeys: string[];
  notes: string[];
}

function PayloadStateRow({ payload }: { payload: PayloadRef }): JSX.Element {
  const { error, ageSeconds, loading } = usePayloadFile<Record<string, unknown>>(
    payload.path,
    30_000,
  );
  const state = error
    ? 'MISSING_PAYLOAD'
    : ageSeconds !== null && ageSeconds > payload.staleAfterSeconds
      ? 'STALE'
      : loading
        ? 'LOADING'
        : 'OK';
  return (
    <div className="cockpit-table-row" role="row">
      <span>{payload.label}</span>
      <span>{payload.required ? 'required' : 'optional'}</span>
      <span className={`chip solid-${ageClass(ageSeconds, payload.staleAfterSeconds)}`}>{state}</span>
      <span>{fmtAge(ageSeconds)}</span>
      <span><code>{payload.path}</code></span>
    </div>
  );
}

export function Phase1ContractPage({
  meta,
  rbac,
  route,
  eyebrow,
  status,
  sourceLabels,
  placeholderStates,
  payloads,
  bridgeKeys,
  notes,
}: ContractPageProps): JSX.Element {
  const { data: liveGateRuntime } = usePayloadFile<LiveGateRuntimePayload>(LIVE_GATE_RUNTIME_PATH, 8_000);
  return (
    <DesignPageShell
      meta={meta}
      rbac={rbac}
      route={route}
      eyebrow={eyebrow}
      source={sourceLabels.join(' / ')}
      status={status}
    >
      <SourceRibbon labels={sourceLabels} />
      <Panel id={`${meta.id}-safety`} title="Safety State" right={<span className={resolveGateChipClass(liveGateRuntime)}>{resolveGateLabel(liveGateRuntime)}</span>}>
        <div className="cockpit-card-grid">
          {[
            'This contract page shows live telemetry without order submission.',
            'Legacy shutdown is blocked.',
            'Candidate symbols are not adopted automatically.',
            'Recovery requires proof of edge before scaling.',
            'No fake readiness.',
          ].map((line) => (
            <div className="cockpit-evidence-gap" key={line}>{line}</div>
          ))}
        </div>
      </Panel>

      <Panel id={`${meta.id}-payload-contract`} title="Payload Contract" right={<span className="chip">READ ONLY</span>}>
        <div className="cockpit-market-table" role="table">
          <div className="cockpit-table-row cockpit-table-row--head" role="row">
            <span>Payload</span>
            <span>Need</span>
            <span>State</span>
            <span>Freshness</span>
            <span>Path</span>
          </div>
          {payloads.map((payload) => (
            <PayloadStateRow key={payload.path} payload={payload} />
          ))}
        </div>
      </Panel>

      <Panel id={`${meta.id}-placeholder-contract`} title="Placeholder Contract" right={<span className="chip solid-warn">HONEST PARTIAL</span>}>
        <div className="cockpit-card-grid">
          {placeholderStates.map((state) => (
            <div className="cockpit-evidence-gap" key={state}>{state}</div>
          ))}
        </div>
        {notes.map((note) => (
          <p className="cockpit-evidence-note" key={note}>{note}</p>
        ))}
      </Panel>

      <Panel id={`${meta.id}-bridge-contract`} title="Bridge Contract" right={<span className="chip">NO FRONTEND REDIS</span>}>
        <div className="cockpit-card-grid">
          {bridgeKeys.map((key) => (
            <div className="cockpit-evidence-gap" key={key}><code>{key}</code></div>
          ))}
        </div>
        <p className="cockpit-evidence-note">
          Frontend pages consume public JSON payloads or backend bridge contracts only; this page does not read Redis directly.
        </p>
      </Panel>
    </DesignPageShell>
  );
}
