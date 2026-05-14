# v2_risk_gateway_runtime_worker — LEGACY BASELINE ANALYSIS

Anchor document required by the LEGACY-FIRST MANDATE for the V2 risk gateway
runtime worker port. Every claim below cites a legacy file under
`legacy_reference/risk/` or the existing V2 library code under
`v2/backend/app/services/risk_gateway/` and
`v2/backend/app/composition/risk_gateway/`.

## legacy_source_paths

| path | role |
|---|---|
| `legacy_reference/risk/shared_risk_gate.py` | Pre-execution shared gate; `check_risk_gate(...)` returns a `RiskGateResult(passed, block_code, block_reason, meta)`; called by every risk-adding execution path (orchestrator, trader hedges, URC). |
| `legacy_reference/risk/adaptive_gate.py` | Adaptive Market-Condition Gate (Feb 2026) replacing timer-based anti-churn. Emits `GateVerdict(allow, code, reason, sizing_mult, delay_seconds, meta)`. |
| `legacy_reference/risk/risk_state_machine.py` | 3-state risk state machine (`NORMAL` / `STRESSED` / `EMERGENCY`) with breach persistence across restarts. |
| `legacy_reference/risk/halt_manager.py` | Halt and breaker management. |
| `legacy_reference/risk/kill_switch.py` | Kill switch with global allowlist (`ORCH_STALLED,SYSTEMIC_EMERGENCY,REDIS_DOWN,MARKET_DATA_DOWN,INFRA_EMERGENCY`) and TTL-bounded Redis key (`wma:kill_switch`). |
| `legacy_reference/risk/margin_governor.py` | Margin governor. |
| `legacy_reference/risk/auto_deleverager.py` | Auto-deleverager state. |
| `legacy_reference/risk/global_breadth.py` | Global breadth gate. |
| `legacy_reference/risk/microstructure_toxicity.py` | Toxicity gate. |
| `legacy_reference/risk/market_state_contract.py` | Market state contract gate. |
| `legacy_reference/risk/reversal_detector.py` | Reversal blocking. |
| `legacy_reference/risk/intelligent_close_guard.py` | Reduce-only and close-guard rules. |
| `legacy_reference/risk/reduce_only_latch.py` | Reduce-only latch. |
| `legacy_reference/risk/phase_controller.py` | Phase controller (size scaling under stress). |
| `legacy_reference/risk/risk_budget_allocator.py` | Risk-budget allocator: cadence + max symbols. |
| `legacy_reference/risk/trainer_alignment.py` | Trainer-vs-execution alignment gate. |
| `legacy_reference/risk/trainer_intent.py` | Trainer intent gate. |
| `legacy_reference/risk/hedge_cage_manager.py` | Hedge cage (paired-side risk). |
| `legacy_reference/risk/ltf_reversal.py` | LTF reversal gate. |
| `legacy_reference/risk/market_regime.py` | Regime contributor consumed by the state machine. |

The V2 library equivalents already present in the repository (these are the
target consumer of this CLI worker):

| v2 path | role |
|---|---|
| `v2/backend/app/services/risk_gateway/service.py` | `assemble_risk_decision_record(decision, now_ms_clock)` — pure function that converts an `OrchestratorDecisionRecord` into a `RiskDecisionRecord`. |
| `v2/backend/app/composition/risk_gateway/runtime.py` | `build_risk_decision_evaluator(now_ms_clock)` — builds a keyword-only callable that wraps `assemble_risk_decision_record`. |
| `v2/backend/app/domain/risk_gateway/record.py` | `RiskDecisionRecord` dataclass with strict validators; `live_blocked` must be `True`. |
| `v2/backend/app/domain/orchestrator_decision/record.py` | `OrchestratorDecisionRecord` dataclass — input contract for the gate. |

## legacy_functions_preserved

- `check_risk_gate(...)` block-codes → mapped to V2 `RiskDecisionRecord.risk_reason_code` via the existing `assemble_risk_decision_record` service mapping (the V2 service already collapses orchestrator action+reason into the V2 reason-code set: `allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_held`, `deny_orchestrator_abstained`, `deny_default`).
- `RiskGateResult.passed` (bool) → V2 `RiskDecisionRecord.risk_action ∈ {allow, deny}`.
- `AdaptiveGate.evaluate(...)` allow/deny semantics → consumed upstream of the V2 gate by the orchestrator and folded into `OrchestratorDecisionRecord.decision_action` (`abstain_*`) before the gate sees it. The V2 gate is therefore the *terminal* allow/deny stamp, not a re-computation of the adaptive gate.
- `risk_state_machine` breach persistence → not invoked by this CLI worker (it is upstream of the orchestrator decision); the worker only stamps decisions and never resets breach streaks.
- `kill_switch.KILL_SWITCH_KEY = "wma:kill_switch"` → **never written** by the V2 worker (V2 must not write old Redis keys per CLAUDE.md). This worker emits a `legacy_kill_switch_key_references` field for audit only.

## legacy_inputs

- `redis_client` (legacy) ↔ V2 input is a JSON `OrchestratorDecisionRecord` payload (file, stdin, or V2 public payload fallback).
- `account_id`, `symbol`, `action`, `is_risk_add`, `is_reduce`, `hedge_intent`, `source`, `last_open_ts`, `margin_ratio_pct`, `margin_used_pct` (legacy) → V2 collapses these into the orchestrator decision fields: `decision_action ∈ {open_long, open_short, hold, abstain}` and `decision_reason_code`.
- `redis.get("risk_budget:state:{account_id}")` (legacy) → not read by V2 worker.
- `redis.get("reversal:global")` (legacy) → not read by V2 worker.
- `redis.get("toxicity:{symbol}")` (legacy) → not read by V2 worker.
- `redis.get("market:state:contract")` (legacy) → not read by V2 worker.

## legacy_outputs

- Legacy returns a `RiskGateResult(passed, block_code, block_reason, meta)`.
- V2 emits `RiskDecisionRecord(risk_decision_id, decision_id, prediction_id, feature_snapshot_id, symbol, risk_decision_ts_ms, risk_action, risk_reason_code, input_decision_action, input_decision_reason_code, live_blocked=True)`.
- V2 worker also emits a public-payload status JSON with a fail-closed gate field permanently set to `blocked_human_only`.

## legacy_redis_keys (read-only references; NEVER writers in V2)

| legacy key | role | V2 treatment |
|---|---|---|
| `wma:kill_switch` (+ `:{account}`, `:{symbol}` scopes) | Kill-switch flag, set by `risk/kill_switch.set_kill_switch`. | NEVER written. Listed under `legacy_kill_switch_key_references` for audit. |
| `risk_budget:state:{account_id}` | RBA cadence + max-symbols state. | NEVER read or written by this worker; folded into orchestrator decision upstream. |
| `reversal:global` | Global reversal block flag. | NEVER read or written. |
| `toxicity:{symbol}` | Microstructure toxicity gate. | NEVER read or written. |
| `market:state:contract` | Market data health/expand gate. | NEVER read or written. |
| `regime:{symbol}` | Regime feed for state machine. | NEVER read or written. |

The V2 worker holds **no Redis client**. There is no `redis` import in
`v2/backend/app/cli/v2_risk_gateway_runtime_worker.py`. A unit test asserts
`"import redis"` and `"from redis"` are absent from the worker source.

## legacy_config_dependencies

- `config.SHARED_RISK_GATE_ENABLED` (default `True`) — legacy flag; V2 gate is **always on**.
- `config.RISK_STATE_MACHINE_ENABLED` (default `True`) — legacy; not used by V2 worker (state machine is upstream).
- `os.getenv("KILL_SWITCH_GLOBAL_ALLOWLIST", ...)` — legacy; V2 worker does not consume kill-switch.
- `os.getenv("KILL_SWITCH_TTL_SECONDS", 180)` — legacy; V2 worker does not consume kill-switch.
- `os.getenv("ADAPTIVE_GATE_*", ...)` (spread, liquidity, volatility, fast_move, trend, imbalance, funding, manipulation, edge_fees) — legacy adaptive gate flags; the V2 orchestrator handles these upstream and emits an abstain decision; the gate only stamps the abstain into `deny_orchestrator_abstained`.

The V2 worker reads **only** its own CLI flags and an input JSON payload.

## legacy_edge_cases

| edge case | legacy behavior | V2 behavior |
|---|---|---|
| missing `redis_client` | `check_risk_gate` returns `RiskGateResult(passed=True)` (fail-open) | V2 worker **fail-closes**: missing input → `current_gate_state == blocked_human_only`, `missing_runtime_evidence=True`, `risk_action=deny`, `risk_reason_code=deny_default`. **This is a deliberate divergence from legacy fail-open behavior.** |
| `is_reduce=True and not is_risk_add` | legacy short-circuits to `passed=True` | V2 worker is upstream of execution; the orchestrator decides `hold`/`abstain` and the V2 gate stamps it. No reduce-only short-circuit in V2 because the gate doesn’t see reduces. |
| account-level margin breach (legacy step 0) | `block_code="ACCOUNT_MARGIN_BREACH"` | V2 orchestrator emits `abstain_*` upstream; V2 gate stamps `deny_orchestrator_abstained`. |
| global reversal active | `block_code="GLOBAL_REVERSAL"` | folded into orchestrator `abstain_*` → V2 stamps `deny_orchestrator_abstained`. |
| toxicity high | `block_code="TOXICITY_HIGH"` | folded into orchestrator `abstain_*` → V2 stamps `deny_orchestrator_abstained`. |
| feature staleness | adaptive_gate `delay_seconds > 0` or block | orchestrator emits `abstain_freshness_stale` or `abstain_freshness_missing` → V2 stamps `deny_orchestrator_abstained`. |
| low confidence | trainer-side filter | orchestrator emits `abstain_low_confidence` → V2 stamps `deny_orchestrator_abstained`. |
| worker degraded/critical/unknown | upstream gates | orchestrator emits `abstain_worker_degraded` / `abstain_worker_critical` / `abstain_worker_unknown` → V2 stamps `deny_orchestrator_abstained`. |
| `now_ms` non-int / negative | n/a (legacy uses `time.time()`) | V2 service raises `RiskGatewayServiceError` → worker classifies as `clock_unavailable` and fail-closes. |
| `decision_id` > 125 chars | n/a | V2 service raises `decision_id_too_long_for_risk_decision_id_derivation` → worker fail-closes. |
| live trading enable request | legacy supported a `LIVE_TRADING_ENABLED` env flag | V2 worker **has no codepath** that can unblock the gate. Tests assert `LIVE_GATE_STATUS == "blocked_human_only"` and the public payload contains a `gate_always_blocked_invariant: true` field. |

## legacy_failure_modes

- Legacy gate fail-opens when `redis_client` is unavailable. **V2 worker reverses this**: missing input or unreachable orchestrator decision source → fail-closed deny + `missing_runtime_evidence=true`.
- Legacy kill-switch keys can be set externally and read by every risk-add path. V2 worker emits the legacy key names under `legacy_kill_switch_key_references` for audit-only visibility; no V2 writer exists for those keys.

## legacy_tests_or_expected_behavior

- Existing V2 unit tests cover the service:
  - `v2/backend/tests/unit/services/risk_gateway/test_assemble_risk_decision_record_*` (assemble service tests).
  - `v2/backend/tests/unit/composition/risk_gateway/test_evaluator_*` (composition tests).
- This worker port adds **integration tests at the CLI seam**:
  1. `test_happy_path_open_long_stamps_allow_proceed_long_but_gate_stays_blocked_human_only`
  2. `test_low_confidence_abstain_stamps_deny_orchestrator_abstained`
  3. `test_stale_feature_abstain_stamps_deny_orchestrator_abstained`
  4. `test_missing_input_payload_fails_closed_with_missing_runtime_evidence`
  5. `test_gate_always_blocked_invariant_holds_for_every_decision_action`
  6. `test_worker_has_no_old_redis_writer_codepath`
  7. `test_worker_has_no_real_exchange_codepath`
  8. `test_symbol_universe_contract_required_in_public_payload`
  9. `test_legacy_kill_switch_key_references_listed_for_audit_only`
  10. `test_required_public_payload_fields_present`
  11. `test_legacy_bot_shutdown_classifies_missing_runtime_evidence`

## V2_mapping

| legacy concept | V2 concept |
|---|---|
| `RiskGateResult.passed` | `RiskDecisionRecord.risk_action ∈ {allow, deny}` |
| `RiskGateResult.block_code` | `RiskDecisionRecord.risk_reason_code` (collapsed set: `allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_held`, `deny_orchestrator_abstained`, `deny_default`) |
| `RiskGateResult.block_reason` | derived from `input_decision_action` + `input_decision_reason_code` in the public payload |
| `RiskGateResult.meta` | not propagated by the V2 record (out of scope for this port) |
| Redis key reads | replaced by `OrchestratorDecisionRecord` field reads |
| Redis key writes | **forbidden** in V2 worker |
| `LIVE_TRADING_ENABLED` env flag | absent in V2 worker (`LIVE_GATE_STATUS = "blocked_human_only"` constant; no code path mutates it) |

## intentional_changes

1. **Fail-closed on missing input.** Legacy fails open when its Redis client is missing; V2 fails closed. Rationale: CLAUDE.md "Default status: LIVE TRADING: BLOCKED" and "fail-closed on missing fields" are absolute.
2. **No exchange mutation codepath.** Worker source asserts via test `test_worker_has_no_real_exchange_codepath`.
3. **No legacy Redis writes.** Worker contains no `redis` import; asserted by `test_worker_has_no_old_redis_writer_codepath`.
4. **No approval-token creation.** Worker has no `create_approval_token`, `set_kill_switch`, or "unblock" path.
5. **Symbol Universe Contract enforced.** Worker reads scope via `SymbolUniverseService` and tags `symbol_universe_public_payload_status` (`PRESENT` or `MISSING_SYMBOL_UNIVERSE_PUBLIC_PAYLOAD`). Worker does not hardcode the 25 symbols as the full universe.
6. **Trainer-parity inputs are MISSING_RUNTIME_EVIDENCE when legacy bot is shut down.** When no orchestrator decision source is present and `--allow-missing-runtime-evidence` is set (the default for this worker because the legacy bot is shut down), the worker emits `missing_runtime_evidence=true` with no synthesized data.

## removed/deprecated behavior

| removed | reason |
|---|---|
| Legacy Redis writers (`wma:kill_switch*`) | CLAUDE.md forbids "write to old Redis keys". |
| Fail-open default on missing client | Replaced by fail-closed deny + `missing_runtime_evidence=true`. |
| `meta` propagation from `RiskGateResult` | Not part of V2 `RiskDecisionRecord` contract. |
| In-worker invocation of the adaptive gate, state machine, kill switch | These are upstream of the orchestrator decision. The gate is the terminal stamp, not a re-implementation. |

## raw_evidence_pointers

- `legacy_reference/risk/shared_risk_gate.py:59` (`def check_risk_gate(`)
- `legacy_reference/risk/shared_risk_gate.py:47` (`class RiskGateResult`)
- `legacy_reference/risk/kill_switch.py:10` (`KILL_SWITCH_KEY = "wma:kill_switch"`)
- `legacy_reference/risk/risk_state_machine.py:68` (`class RiskState(str, Enum)`)
- `legacy_reference/risk/adaptive_gate.py:36` (`@dataclass class GateVerdict`)
- `v2/backend/app/services/risk_gateway/service.py:25` (`assemble_risk_decision_record`)
- `v2/backend/app/composition/risk_gateway/runtime.py:15` (`build_risk_decision_evaluator`)
- `v2/backend/app/domain/risk_gateway/record.py:56` (`class RiskDecisionRecord`)
- `v2/backend/app/domain/orchestrator_decision/record.py:73` (`class OrchestratorDecisionRecord`)
- `v2/backend/app/services/symbol_universe/service.py:24` (`LEGACY_ACTIVE_SYMBOLS_25`)

## confidence

- legacy mapping: HIGH (sources read end-to-end; `assemble_risk_decision_record` already encodes the legacy reason-code collapse).
- V2 worker behavior: HIGH (worker is a thin CLI shim over the existing V2 library; all branches tested).
- fail-closed posture: HIGH (single constant `LIVE_GATE_STATUS = "blocked_human_only"` is the only gate state in the source).

## missing_evidence

- None. Every claim above is anchored to a specific legacy file or V2 library file already in-tree.
