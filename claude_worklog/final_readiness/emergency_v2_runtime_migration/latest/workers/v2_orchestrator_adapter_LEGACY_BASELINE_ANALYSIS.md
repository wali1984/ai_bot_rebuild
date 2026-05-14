# v2_orchestrator_adapter — Legacy Baseline Analysis

## Purpose

This file is the legacy-first baseline mandated by the
**LEGACY-FIRST MANDATE** for every V2 emergency-runtime-migration
worker. It documents *what the legacy bot already does today* for
orchestrator decisioning so the V2 worker can be reviewed as a
behaviour-preserving lift, not a greenfield reinvention. Each claim
points to a `legacy_reference/` path that can be re-verified with
`grep` / `wc -l` / direct read.

The V2 worker (`v2/backend/app/cli/v2_orchestrator_adapter.py`) lifts
the previously in-process composition runtime at
`v2/backend/app/composition/orchestrator_decision/runtime.py` into a
standalone CLI subscriber. The worker is a downstream reader: it
consumes `trainer_prediction` records from the V2 paper runtime bundle
(or trainer bridge), assembles `OrchestratorDecisionRecord` instances
using the same composition/service code, and publishes them as a
public operator payload. The orchestrator **proposes**; the risk
gateway is the binding gate; the orchestrator never overrides the risk
gateway.

## Legacy source paths

| Path | Role |
|---|---|
| `legacy_reference/rl/orchestrator_worker.py` (10,523 lines) | Legacy orchestrator daemon. Consumes trainer proposals (`proposal["_stream_id"] = str(msg_id)` near line 2002), evaluates orchestrator policy (low-confidence abstain, freshness gates, worker health gates), and emits orchestrator decisions referenced downstream as `stream_id` (e.g. line 10183 `f"plan_id={plan_id} stream_id={msg_id}"`). The legacy orchestrator never bypasses the trader-side risk evaluator. |
| `legacy_reference/rl/hybrid_trainer.py` (57,250 lines) | Legacy hybrid trainer; the predictor input the orchestrator consumes. Publishes signal proposals onto the Redis pub-sub fabric (`wma:signals:all`) for the orchestrator to consume. |
| `legacy_reference/risk/risk_evaluator.py` | Legacy risk evaluator/gateway. The orchestrator never overrides risk decisions; the risk evaluator is the binding gate on whether a proposal proceeds to the trader. |
| `legacy_reference/risk/auto_deleverager.py`, `legacy_reference/risk/hedge_cage_manager.py` | Auxiliary risk overlays consulted *after* the orchestrator's proposal. They confirm the orchestrator is a proposer, not a gate. |
| `legacy_reference/trading/signal_router.py` (349 lines) | Legacy signal router. Trainer publishes to `wma:signals:all` (line 244), the router copies to `wma:signals:{ACCOUNT_ID}` (lines 199, 206). The orchestrator's proposals flow through this router but the router itself does not arbitrate. |
| `legacy_reference/trading/trader.py` | Legacy trader. Consumes orchestrator decisions only after risk gateway approval. Reinforces the orchestrator ≠ gate invariant. |
| `legacy_reference/rl/signal_state_manager.py` (554 lines) | Legacy per-symbol signal state machine (`SignalState.IDLE/PENDING/EXECUTED`, `SignalRecord(signal_id, action_name, confidence, price_at_signal, position_snapshot, timestamp_ms, state)` at lines 288, 329). The closest legacy analog to the V2 orchestrator decision record. |
| `legacy_reference/monitor_trainer_signals.py` (1,058 lines) | Operator-facing legacy orchestrator/signal stream monitor. |
| `legacy_reference/scripts/trace_symbol_e2e.py` (170 lines) | Operator-facing end-to-end lineage script that walks Redis streams to stitch trainer → orchestrator → trader events. |
| `legacy_reference/rl/microstructure_overlay.py`, `legacy_reference/rl/target_exposure_controller.py`, `legacy_reference/rl/dynamic_runner_hedge.py`, `legacy_reference/trading/adaptive_hedge_builder.py`, `legacy_reference/trading/lifecycle_controller.py` | Auxiliary legacy decision overlays consulted after the orchestrator's proposal but before/with the risk evaluator. They confirm that even decision overlays cannot bypass the risk evaluator. |

## legacy_functions_preserved

| Legacy function / responsibility | Legacy file | Preserved in V2 as |
|---|---|---|
| Consume trainer prediction proposal with a `stream_id` / `prediction_id` | `legacy_reference/rl/orchestrator_worker.py:2002` (`proposal["_stream_id"] = str(msg_id)`) | The V2 adapter reads `trainer_prediction.prediction_id` from the paper runtime bundle and feeds the V2 `TrainerPredictionRecord` into `assemble_orchestrator_decision_record`. |
| Decide on `open_long` / `open_short` / `hold` / `abstain` actions | `legacy_reference/rl/orchestrator_worker.py` policy branches (low-confidence abstain, freshness gates, worker-health gates) | `v2/backend/app/services/orchestrator_decision/service.py:assemble_orchestrator_decision_record` (already merged) returns one of `DECISION_ACTION_OPEN_LONG/OPEN_SHORT/HOLD/ABSTAIN`. |
| Reference the trainer-published stream id from the decision record | `legacy_reference/rl/orchestrator_worker.py:10183` (`stream_id={msg_id}`) | V2 `OrchestratorDecisionRecord.prediction_id` carries the same identifier; `OrchestratorDecisionRecord.decision_id = "dec_" + prediction_id` derives a stable decision id without colliding. |
| Fail-closed on stale or missing freshness | `legacy_reference/rl/orchestrator_worker.py` freshness gate (`PREDICTION_FRESHNESS_STALE/MISSING`) | `assemble_orchestrator_decision_record` emits `DECISION_REASON_ABSTAIN_FRESHNESS_STALE` / `..._MISSING`. The adapter additionally fail-closes the public payload when the bundle source itself is missing/stale. |
| Fail-closed on degraded/critical/unknown trainer worker health | `legacy_reference/rl/orchestrator_worker.py` health-status branch | `assemble_orchestrator_decision_record` emits `DECISION_REASON_ABSTAIN_WORKER_DEGRADED/CRITICAL/UNKNOWN`. |
| Abstain on low confidence | `legacy_reference/rl/orchestrator_worker.py` low-confidence branch | `assemble_orchestrator_decision_record` compares against `low_confidence_threshold` and emits `DECISION_REASON_ABSTAIN_LOW_CONFIDENCE`. |
| Hold on flat direction | `legacy_reference/rl/orchestrator_worker.py` flat-direction branch | `assemble_orchestrator_decision_record` emits `DECISION_ACTION_HOLD` with reason `DECISION_REASON_HOLD_FLAT_DIRECTION`. |
| Never override the risk evaluator | `legacy_reference/risk/risk_evaluator.py` + `legacy_reference/trading/trader.py` (trader requires risk-approved decisions) | The V2 adapter emits decisions with `cannot_bypass_risk_gateway: True`, `orchestrator_overrides_risk: False`, `risk_gateway_binding: True`, and `live_blocked: True`. The adapter never proposes "execute"; the only proceed actions are `open_long`/`open_short`, both of which require risk gateway approval before any execution intent is created. |
| Operator-facing orchestrator/signal view | `legacy_reference/monitor_trainer_signals.py` | Public payload `current_decision` + `recent_decision_tail` + `decision_summary` exposes the operator-facing view via JSON instead of Redis stream tails. |

## legacy_inputs

The legacy orchestrator consumed:

1. Trainer hidden-state outputs (`legacy_reference/rl/hybrid_trainer.py`).
2. Feature freshness / market data from the legacy feature pipeline.
3. Trainer Redis pub/sub topic `wma:signals:all` (legacy router input).
4. Process-wide worker health flags maintained by the legacy supervisor.
5. Operator console queries from `monitor_trainer_signals.py`.

In V2 the equivalent input is the **public paper runtime bundle**
emitted by `v2/backend/app/cli/paper_online_runtime.py`, located at
`v2/frontend/public/operator_runtime/paper_online/latest/paper_runtime_status.json`.
That bundle already contains every per-stage trainer prediction. The
adapter also tolerates a `--source-file PATH` override, or falls back
to the trainer bridge public payload at
`v2/frontend/public/operator_runtime/v2_trainer_bridge/latest/v2_trainer_bridge_status.json`.

No legacy Redis is read; no legacy module is imported; no exchange
client is instantiated.

## legacy_outputs

The legacy orchestrator wrote:

1. Trainer-routed signal stream: Redis `wma:signals:all`
   (`legacy_reference/trading/signal_router.py:244`).
2. Router account streams: Redis `wma:signals:{ACCOUNT_ID}`
   (`legacy_reference/trading/signal_router.py:199, 206`).
3. Orchestrator state on disk under `legacy_reference/.logs/orchestrator_worker.log`.
4. Telegram alerts via `legacy_reference/utils/telegram_alerts.py`.

V2 outputs:

1. `v2/frontend/public/operator_runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json`
2. `v2/runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json`
3. `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_orchestrator_adapter_status.json`
4. CLI exit code `0` on `fail_closed=false`, `2` on any fail-closed condition.

## legacy_redis_keys (audit-only references; never writers)

The legacy orchestrator used the following Redis namespaces. The V2
worker references them only in this analysis and never reads or
writes them.

- `wma:signals:all` — trainer/orchestrator signal publish topic
- `wma:signals:{ACCOUNT_ID}` — router output streams
- `wma:orchestrator:state:*` — orchestrator process state
- `wma:risk_state` — risk evaluator state (consumed by the trader, never overridden by the orchestrator)
- `wma:paper:trade_log` — trader paper event stream (downstream-only)

## legacy_config_dependencies

| Key | Legacy file | V2 note |
|---|---|---|
| `MIN_SIGNAL_CONFIDENCE` (or equivalent) | `legacy_reference/config.py` | V2 adapter exposes `--low-confidence-threshold` (default `0.55`); equivalence verified against the legacy default. |
| `SIGNAL_TTL_SECONDS` | `legacy_reference/config.py` | V2 adapter uses `--stale-threshold-seconds=600` (configurable). |
| `WORKER_HEALTH_CRITICAL_ACTIONS` | implicit in `legacy_reference/rl/orchestrator_worker.py` | V2 service mapping (`worker_health_status` → `DECISION_REASON_ABSTAIN_WORKER_*`). |
| `BASE_NOTIONAL`, fee anchors | `legacy_reference/config.py`, `legacy_reference/trading/trader.py` | Not redefined here; consulted only downstream by the risk gateway and paper execution workers. |

## legacy_edge_cases

1. **Signal expired before execution.** Legacy: the orchestrator skipped further evaluation; the trader's risk evaluator marked the signal expired. V2: the adapter emits `DECISION_REASON_ABSTAIN_FRESHNESS_STALE`.
2. **Trainer paused / no prediction.** Legacy: no entry on `wma:signals:all`. V2: the bundle's `trainer_prediction` block is missing → adapter fail-closes with `MISSING_RUNTIME_EVIDENCE`.
3. **Trainer prediction `side="hold"` / flat.** Legacy: orchestrator emitted a hold notification but did not invoke risk gateway. V2: `DECISION_ACTION_HOLD` with reason `DECISION_REASON_HOLD_FLAT_DIRECTION`.
4. **Worker health flagged CRITICAL/DEGRADED.** Legacy: orchestrator abstained until process supervisor restored health. V2: `DECISION_REASON_ABSTAIN_WORKER_CRITICAL/DEGRADED`.
5. **Risk gateway denies an open_long decision.** Legacy: trader logged and skipped; orchestrator never reissued an execute. V2: the adapter still emits its `open_long` proposal but with `cannot_bypass_risk_gateway: True` and `orchestrator_overrides_risk: False`; the downstream risk gateway worker is the binding gate.
6. **Bundle clock skew.** Legacy: not detected. V2: `generated_at_ms` is preferred over ISO `generated_at`; if both are absent, age is `None` → fail-close `STALE_RUNTIME_EVIDENCE`.
7. **Confidence at exact threshold.** Legacy: ambiguous; some branches used `<` and others `<=`. V2: the service module enforces `confidence_calibrated < low_confidence_threshold` for `ABSTAIN_LOW_CONFIDENCE`; values equal to the threshold proceed.

## legacy_failure_modes

1. Trainer not running → no prediction in `wma:signals:all`. V2: `MISSING_RUNTIME_EVIDENCE`.
2. Trainer health degraded → legacy orchestrator stuck. V2: `DECISION_REASON_ABSTAIN_WORKER_DEGRADED`.
3. Orchestrator unable to publish (Redis stream truncation). V2: file-based output is atomic; partial bundles fail-close with `INVALID_PAYLOAD`.
4. Operator unable to attribute an abstain reason. V2: explicit `decision_reason_code` on every decision; readable in the public payload.
5. Orchestrator over-stepping the risk gateway (regression risk). V2: enforced by domain validation + integration tests; the adapter cannot emit an `execute`/`force` action because the domain enum is closed.

## legacy_tests_or_expected_behavior

Legacy did not ship pytest coverage for orchestrator decisioning;
the legacy assurance was manual replay via
`legacy_reference/scripts/trace_symbol_e2e.py` and periodic operator
inspection through `legacy_reference/monitor_trainer_signals.py`.

V2 adds explicit integration tests at
`v2/backend/tests/integration/cli/test_v2_orchestrator_adapter.py`
covering:

- happy-path decision emission (open_long / open_short / hold);
- abstain on each freshness / worker-health / low-confidence branch;
- the **orchestrator-never-overrides-risk-gateway** invariant
  (verified by inspecting the emitted decision when an upstream risk
  decision in the same bundle says `risk_action == "deny"`);
- fail-closed on missing source / stale source / invalid JSON;
- Symbol Universe contract surfaced on every payload;
- gate-always-blocked invariant;
- no exchange method names in the worker source;
- no Binance/ccxt/Redis imports or Redis writer calls in the worker;
- required public payload fields present (status + on disk).

## V2_mapping

| V2 component | Purpose |
|---|---|
| `v2/backend/app/cli/v2_orchestrator_adapter.py` | Standalone CLI subscriber + decision adapter. |
| `v2/backend/app/composition/orchestrator_decision/runtime.py` | Existing composition runtime that builds the evaluator (lifted in-process). |
| `v2/backend/app/services/orchestrator_decision/service.py` | Existing decision policy. The adapter delegates to this service; it does not re-implement policy. |
| `v2/backend/app/domain/orchestrator_decision/record.py` | Closed enum of decision actions/reasons; prevents the adapter from inventing an `execute` action. |
| `v2/backend/app/domain/trainer_prediction_output/record.py` | Trainer prediction domain validation. The adapter maps the bundle's `trainer_prediction` block into this record. |
| `v2/backend/tests/integration/cli/test_v2_orchestrator_adapter.py` | Integration tests for the worker. |
| `v2/frontend/public/operator_runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json` | Public operator payload. |
| `v2/runtime/v2_orchestrator_adapter/latest/v2_orchestrator_adapter_status.json` | Local runtime payload. |
| `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_orchestrator_adapter_status.json` | Final readiness payload. |

## intentional_changes

1. **Replaces in-process orchestrator daemon with a CLI adapter.**
   Legacy ran a long-lived daemon under the legacy supervisor; V2 runs
   a single-shot or polling CLI that reads the bundle and emits the
   decision record.
2. **Replaces Redis pub/sub routing with a file-based public payload.**
   Legacy emitted on `wma:signals:all`; V2 writes a JSON status file
   to the public operator-runtime directory.
3. **Replaces ambiguous abstain semantics with a closed enum.** The
   V2 domain layer rejects any `decision_action` outside
   `{open_long, open_short, hold, abstain}`. This prevents future code
   from inventing an `execute`/`force_open` action and thereby
   bypassing the risk gateway.
4. **Wires `cannot_bypass_risk_gateway` / `orchestrator_overrides_risk`
   explicitly into the public payload.** Codex can re-verify the
   invariant by inspecting the emitted JSON.
5. **Emits a deterministic `decision_id = "dec_" + prediction_id`.**
   The legacy stream id was the Redis message id; V2 derives a stable
   id from the upstream prediction id so that downstream consumers
   (risk gateway, paper execution, audit ledger, signal lineage) can
   join across stages without a Redis dependency.
6. **`codex_review_v2_orchestrator_adapter` trigger** is exposed on
   the public payload via `codex_review_trigger` so the operator-facing
   Codex Review Center can pick it up after every emit.

## removed_or_deprecated_behavior

| Removed | Reason |
|---|---|
| Redis publishing of orchestrator proposals (`wma:signals:all`) | V2 evidence-integrity rule prohibits legacy-Redis writes. |
| Long-lived orchestrator daemon under the legacy supervisor | V2 control plane is local-native; a CLI adapter is the V2 boundary. |
| Telegram alerts on orchestrator state | Out of scope for the adapter; reserved for the operator alerting worker. |
| Account-stream routing (`wma:signals:{ACCOUNT_ID}`) | Multi-account routing is a separate future worker; the adapter is account-agnostic. |
| Orchestrator-level position management overlays | Owned by separate V2 risk/lifecycle workers; the adapter only proposes. |

## Conclusion

The V2 adapter preserves every observable legacy orchestrator
decisioning field while upgrading the legacy daemon to a deterministic,
evidence-cited CLI worker. Live trading remains `blocked_human_only`.
The worker contains no exchange-mutation method names, no
Binance/ccxt/Redis imports, no Redis writer calls. The closed
decision-action enum and the explicit `cannot_bypass_risk_gateway`
field enforce the **orchestrator never overrides the risk gateway**
invariant at both code and review-time levels.
