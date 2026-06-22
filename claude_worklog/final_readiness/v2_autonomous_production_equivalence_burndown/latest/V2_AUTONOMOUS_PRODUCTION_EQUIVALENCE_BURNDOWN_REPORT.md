# V2 Autonomous Production-Equivalence Burndown — Controller Ready Report

Generated: refresh via
`claude_worklog/tools/v2_autonomous_production_equivalence_burndown_controller.py`.

GO/NO-GO: `V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_READY`

## What was built

1. **Phase 0 — Runtime preservation preflight.** The controller runs a
   read-only Redis preflight on every cycle, verifying:
   - Redis reachable,
   - `v2:*` namespace non-empty (multi-cursor SCAN),
   - heartbeats present for `v2:trainer:heartbeat`,
     `v2:paper:position_history:heartbeat`,
     `v2:market:liquidations:heartbeat`,
   - `live_gate` is unset or equals `blocked_human_only`,
   - `live_symbols` is unset or empty,
   - remaining-dim queue is the remediated one
     (`go_no_go == V2_FULL_OBSERVATION_REMAINING_DIM_EXECUTION_QUEUE_REMEDIATED_READY`).
   If any check fails the cycle terminates with
   `V2_AUTONOMOUS_PRODUCTION_EQUIVALENCE_BURNDOWN_CONTROLLER_BLOCKED`.

2. **Phase 1 — Queue remediation.** Patched
   `tools/v2_full_observation_remaining_dim_classifier.py`:
   - removed the broad `portfolio_state` parent bucket from
     `V2_BUILDABLE_NOW` (it now classifies as
     `NOT_REQUIRED_FOR_CURRENT_V2_MODEL_PATH`),
   - added the two missing exact source bindings
     (`portfolio_state.v2_orchestrator_keys_written_count` →
     `v2:orchestrator:decisions`,
     `position_context.v2_pre_trade_allowed_rate` →
     `v2:risk:decisions`),
   - added a per-field `field_metadata_by_group` table providing
     `field_id`, `scope`, `exact_v2_source_keys`,
     `expected_payload_field`, `stale_or_missing_behavior`,
     `implementation_target_function`, `tests_required` for every
     next-10 task,
   - introduced a strict-source contract gate; GO_NO_GO flips to
     `…_REMEDIATION_BLOCKED` if any task carries a generic hint, if the
     broad `portfolio_state` bucket is emitted as buildable, or if the
     aggregate dim total does not reconcile to 5733.
   Verified results after remediation:
   - aggregate_total_observed = 5733,
   - aggregate_total_check = PASS,
   - strict_source_contract_pass = True,
   - generic_source_hint_hits = 0,
   - portfolio_state_broad_bucket_emitted = False,
   - V2_BUILDABLE_NOW = 16, V2_LANE_EXISTS_PAYLOAD_ABSENT = 18.

3. **Phase 2 — Autonomous executor.** New script
   `claude_worklog/tools/v2_autonomous_production_equivalence_burndown_controller.py`.
   Modes: `--once` (default), `--loop`, `--status`, `--dry-run`.
   Selection rules: highest-ranked `V2_BUILDABLE_NOW` task with exact
   source binding, no operator decision required, no external provider
   required, no policy / checkpoint block, no in-flight duplicate.
   The controller refuses to drive any task whose category is in
   `HARD_GATED_CATEGORIES` (external sources, operator decisions, paid
   alt-data, event-dependent liquidation WSS, position-dependent labels,
   payload-absent lanes, legacy V3 trailing dims, policy / checkpoint
   blocked, not-required-for-current-V2-model-path).

4. **Phase 3 — Implementation rule.** Each emitted Claude task carries
   a strict prompt:
   - modify only V2 files,
   - consume only the exact V2 source key(s) listed in the queue
     metadata,
   - emit explicit missing source labels when the payload is absent,
   - never zero-fill, never claim checkpoint compatibility, never claim
     policy architecture parity,
   - add the required tests, refresh
     `full_observation_builder_status`, write an implementation report,
   - final GO marker
     `V2_FULL_OBSERVATION_<SLUG>_BURNDOWN_READY_PARTIAL_PROGRESS` or
     `…_BURNDOWN_BLOCKED`.

5. **Phase 4 — Codex review routing.** Each Claude task is paired with
   a `codex_review_v2_full_observation_<slug>.json` descriptor that
   requires Codex to verify exact-source consumption, real
   generated-dim increase, no zero-fill, no claim drift, no old Redis
   writes, no exchange mutation, no approvals, live blocked. Decision
   strings are fixed: `…_BURNDOWN_CODEX_PASS` or
   `…_BURNDOWN_CODEX_FAIL`. On FAIL the controller's next cycle
   detects the unresolved item and emits a focused remediation task.

6. **Phase 5 — Stop conditions.** Loop mode terminates early when:
   no buildable exact-source tasks remain, runtime preflight fails,
   every candidate is duplicate-suppressed (waiting on in-flight), or
   the next gate is operator-only.

7. **Phase 6 — Hands-off scope.** Controller never schedules: policy
   architecture port, checkpoint loading, live / canary, shutdown
   acceptance, paid alt-data, old Redis migration / trimming, external
   onchain / token metrics adoption, automatic Symbol Universe
   adoption.

8. **Phase 7 — Operator truth.** Controller writes
   `autonomous_burndown_status.json` to
   `claude_worklog/final_readiness/v2_autonomous_production_equivalence_burndown/latest/`
   and mirrors `operator_dashboard_payload.json` to
   `v2/frontend/public/v2_autonomous_production_equivalence_burndown/latest/`.

## First cycle result

- Selected: `portfolio_state.v2_orchestrator_keys_written_count`
  (3 dims, source `v2:orchestrator:decisions`).
- Emitted Claude task:
  `claude_worklog/agent_supervisor/tasks/198_claude_fix_v2_full_observation_portfolio_state_v2_orchestrator_keys_written_count.json`.
- Emitted Codex task:
  `claude_worklog/agent_supervisor/tasks/199_codex_review_v2_full_observation_portfolio_state_v2_orchestrator_keys_written_count.json`.

## Second cycle result (duplicate suppression validated)

- First candidate skipped because of in-flight duplicate (198/199).
- Selected next:
  `portfolio_state.portfolio_trainer_heartbeat_age_seconds`
  (3 dims, source `v2:trainer:heartbeat`).
- Emitted Claude task:
  `claude_worklog/agent_supervisor/tasks/200_claude_fix_v2_full_observation_portfolio_state_portfolio_trainer_heartbeat_age_seconds.json`.
- Emitted Codex task:
  `claude_worklog/agent_supervisor/tasks/201_codex_review_v2_full_observation_portfolio_state_portfolio_trainer_heartbeat_age_seconds.json`.
- duplicate_suppression_count = 1.

## Safety

- live_gate = blocked_human_only.
- live_symbols = [].
- No exchange call, no Redis write outside `v2:*` namespaces, no
  approval token created, no live/canary/shutdown markers, no policy
  architecture started, no checkpoint claim, no legacy bot touched.
- All forbidden actions enumerated in each emitted task's
  `forbidden_actions` list.

## Operator entry point

```
python3 claude_worklog/tools/v2_autonomous_production_equivalence_burndown_controller.py --once
python3 claude_worklog/tools/v2_autonomous_production_equivalence_burndown_controller.py --status
python3 claude_worklog/tools/v2_autonomous_production_equivalence_burndown_controller.py --loop \
    --loop-interval-seconds 300 --loop-max-cycles 6
```

`--loop-max-cycles` defaults to 1 so the operator must explicitly raise
the cap to drive multiple selections per invocation. This keeps the
controller cooperative with the existing continuous remediation
governor and the supervisor.
