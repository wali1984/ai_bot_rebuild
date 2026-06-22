import { usePayloadFile, fmtAge, ageClass } from '../../hooks/usePayloadFile';
import { Metric, Panel } from '../../pages/cockpitComponents';

const MAJOR_MOVE_PATH =
  '/operator_runtime/v2_major_move_replay_future_window_completion_trainer_docs_and_website_wiring/latest/operator_dashboard_payload.json';
const ROOT_CAUSE_PATH =
  '/operator_runtime/v2_major_move_replay_future_window_completion_trainer_docs_and_website_wiring/latest/major_move_false_negative_root_cause_status.json';
const REPLAY_RESULT_PATH =
  '/operator_runtime/v2_major_move_replay_future_window_completion_trainer_docs_and_website_wiring/latest/btc_eth_sol_major_move_replay_result.json';
const STOP_LINE_PATH =
  '/operator_runtime/v2_stop_the_line_trainer_feedback_actionability_and_major_move_recovery/latest/operator_dashboard_payload.json';

interface MajorMoveDashboardPayload {
  gate?: string;
  status?: string;
  generated_est?: string;
  blockers?: string[];
  future_window_evidence_complete?: boolean;
  trainer_docs_status?: string;
  feedback_status?: string;
  website_status?: string;
  durable_checkpoint_loadable?: boolean;
  paper_runtime_grid_aligned?: boolean;
  live_order_submitted?: boolean;
  test_order_called?: boolean;
  exchange_leverage_mutation?: boolean;
  exchange_margin_mode_mutation?: boolean;
  old_redis_write?: boolean;
  fixed_runtime_sizing?: boolean;
  guaranteed_profit_claimed?: boolean;
  guaranteed_10k_claimed?: boolean;
}

interface RootCausePayload {
  btc_root_cause?: string[];
  eth_root_cause?: string[];
  sol_root_cause?: string[];
  common_root_cause?: string[];
  future_window_evidence_complete?: boolean;
  root_cause_confidence?: string;
}

interface ReplayResultPayload {
  btc_would_have_created_paper_candidate?: boolean;
  eth_would_have_created_paper_candidate?: boolean;
  sol_would_have_created_paper_candidate?: boolean;
  paper_entry_allowed?: boolean;
  paper_entry_block_reason?: string[];
  expected_paper_pnl_after_cost?: Record<string, number | null>;
}

interface StopLinePayload {
  status_marker?: string;
  generated_utc?: string;
  consumable_trainer_feedback_count?: number;
  quarantined_feedback_count?: number;
  trainer_feedback_total_rows?: number;
  strategy_no_trade_count?: number;
  prediction_rows_count?: number;
  paper_candidate_count?: number;
  paper_fill_allowed_count?: number;
  stale_prediction_rows?: number;
  router_block_reasons?: Record<string, number>;
  allocator_block_reasons?: Record<string, number>;
  one_hour_smoke_status?: string;
  real_soak_status?: string;
  monthly_10k_feasibility_status?: string;
}

function readable(value: unknown, fallback = 'evidence pending'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'boolean') return value ? 'yes' : 'no';
  return String(value).replace(/_/g, ' ').toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
}

function listText(values: string[] | undefined, fallback = 'none reported'): string {
  return values?.length ? values.join(' · ') : fallback;
}

function bps(value: number | null | undefined): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${value.toFixed(2)} bps` : 'evidence pending';
}

function tone(data: MajorMoveDashboardPayload | null): 'ok' | 'warn' | 'block' {
  if (!data) return 'warn';
  if (data.status === 'READY') return 'ok';
  if (data.status === 'BLOCKED') return 'block';
  return 'warn';
}

export function MajorMoveReplayStatusPanel({ compact = false }: { compact?: boolean }): JSX.Element {
  const { data, ageSeconds, error } = usePayloadFile<MajorMoveDashboardPayload>(MAJOR_MOVE_PATH, 30_000);
  const { data: rootCause } = usePayloadFile<RootCausePayload>(ROOT_CAUSE_PATH, 30_000);
  const { data: replay } = usePayloadFile<ReplayResultPayload>(REPLAY_RESULT_PATH, 30_000);
  const { data: stopLine } = usePayloadFile<StopLinePayload>(STOP_LINE_PATH, 30_000);
  const blockers = data?.blockers ?? [];
  const expectedPnl = replay?.expected_paper_pnl_after_cost ?? {};

  return (
    <Panel
      id="major-move-replay-status"
      title={compact ? 'Major Move Replay' : 'BTC / ETH / SOL Major-Move Replay Truth'}
      right={<span className={`chip solid-${tone(data)}`}>{readable(data?.status)}</span>}
    >
      <div className="cockpit-analytics-grid">
        <Metric label="Gate" value={data?.gate ?? 'evidence pending'} />
        <Metric label="Source age" value={fmtAge(ageSeconds)} detail={ageClass(ageSeconds, 120)} />
        <Metric label="Future labels" value={readable(data?.future_window_evidence_complete)} />
        <Metric label="Root cause confidence" value={readable(rootCause?.root_cause_confidence)} />
        <Metric label="Trainer docs" value={readable(data?.trainer_docs_status)} />
        <Metric label="Feedback fields" value={readable(data?.feedback_status)} />
        <Metric label="Website wiring" value={readable(data?.website_status)} />
        <Metric label="Checkpoint loadable" value={readable(data?.durable_checkpoint_loadable)} />
        <Metric label="Full CUDA grid" value={readable(data?.paper_runtime_grid_aligned)} />
        <Metric label="Paper entry allowed" value={readable(replay?.paper_entry_allowed)} />
        <Metric label="BTC replay PnL" value={bps(expectedPnl.BTCUSDT)} />
        <Metric label="ETH replay PnL" value={bps(expectedPnl.ETHUSDT)} />
        <Metric label="SOL replay PnL" value={bps(expectedPnl.SOLUSDT)} />
        <Metric
          label="Trainer feedback"
          value={`${stopLine?.consumable_trainer_feedback_count ?? 0}/${stopLine?.trainer_feedback_total_rows ?? 0}`}
          detail={`${stopLine?.quarantined_feedback_count ?? 0} quarantined`}
        />
        <Metric
          label="No-trade rows"
          value={`${stopLine?.strategy_no_trade_count ?? 0}/${stopLine?.prediction_rows_count ?? 0}`}
          detail={`${stopLine?.paper_candidate_count ?? 0} execution candidates · ${stopLine?.paper_fill_allowed_count ?? 0} fill allowed`}
        />
        <Metric label="Stale predictions" value={String(stopLine?.stale_prediction_rows ?? 0)} />
        <Metric label="1h smoke" value={readable(stopLine?.one_hour_smoke_status)} />
        <Metric label="12h soak" value={readable(stopLine?.real_soak_status)} />
        <Metric label="10k feasibility" value={readable(stopLine?.monthly_10k_feasibility_status)} />
      </div>
      {!compact ? (
        <>
          <div className="cockpit-card-grid">
            <div className="cockpit-evidence-gap">
              <strong>BTC root cause</strong>
              <p>{listText(rootCause?.btc_root_cause)}</p>
            </div>
            <div className="cockpit-evidence-gap">
              <strong>ETH root cause</strong>
              <p>{listText(rootCause?.eth_root_cause)}</p>
            </div>
            <div className="cockpit-evidence-gap">
              <strong>SOL root cause</strong>
              <p>{listText(rootCause?.sol_root_cause)}</p>
            </div>
          </div>
          <p className={blockers.length ? 'cockpit-evidence-gap' : 'cockpit-evidence-note'}>
            {blockers.length ? `Remaining blockers: ${blockers.join(' · ')}` : 'No remaining major-move replay blockers in the current artifact.'}
          </p>
          <p className="cockpit-evidence-note">
            This panel is replay/runtime evidence only. It does not authorize live orders, test-orders, leverage changes, margin changes, or guaranteed-profit claims.
          </p>
          {stopLine ? (
            <p className="cockpit-evidence-note">
              Stop-line recovery: {readable(stopLine.status_marker)}. Router blocks: {listText(Object.keys(stopLine.router_block_reasons ?? {}))}. Allocator blocks: {listText(Object.keys(stopLine.allocator_block_reasons ?? {}))}.
            </p>
          ) : null}
        </>
      ) : null}
      {error ? <p className="cockpit-evidence-gap">Major-move replay payload unavailable: {error}</p> : null}
    </Panel>
  );
}
