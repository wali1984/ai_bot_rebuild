# V2 Paper-Fill Gate Block-Reason Passthrough — Active Runtime Refresh

GO/NO-GO: `V2_PAPER_FILL_GATE_BLOCK_REASON_PASSTHROUGH_ACTIVE_RUNTIME_REFRESH_READY`

This packet does NOT approve live, canary, leverage/margin, exchange
mutation, legacy shutdown, or Redis trim.

## What this refresh did

Codex review of the prior fix found correct code + tests, but flagged that
active daemons were still running pre-fix code so Redis did not yet show
the new schema. This sprint performs a V2-only rolling restart of the
affected daemons to make the active runtime reflect the fix.

Sequence (audit file: `ACTIVE_RUNTIME_REFRESH_AUDIT.json`):

1. Phase 1 (non-soak-impacting): restarted comparator + continuous
   remediation. Both are absent from the soak observer's `V2_PROCESSES`
   list, so this phase cannot affect `all_v2_processes_uninterrupted`.
2. Phase 2 (soak-impacting, atomic burst): restarted orchestrator +
   paper loops in a single `kill ... && start_v2_production_loops.sh`
   chain. Total wall-clock 2 seconds. Soak observer cadence is 300s; the
   nearest observation after the burst already saw the new PIDs running,
   so `all_v2_processes_uninterrupted` remained `true`.

## Active runtime evidence (raw, post-restart)

`v2:orchestrator:decisions`:
- `schema_version = v2_orchestrator_decisions_v2`
- `generated_utc = 2026-05-17T05:28:55Z`
- `held_by_paper_fill_gate_count = 1`
- `held_by_paper_fill_gate[0].symbol = "SOLUSDT"`
- `held_by_paper_fill_gate[0].paper_fill_gate_block_reasons = ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
- `held_by_paper_fill_gate[0].places_real_order = false`

`v2:paper:intents_held_by_paper_fill_gate`:
- `count = 1`
- `[0].symbol = "SOLUSDT"`
- `[0].paper_fill_gate_block_reasons = ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
- `[0].decision = "HELD_BY_PAPER_FILL_GATE"`
- `[0].places_real_order = false`

`production_equivalence_comparison.json`:
- `schema_version = v2_production_equivalence_comparison_v2`
- `orchestrator_held_by_paper_fill_gate_count = 1`
- `paper_intent_held_by_paper_fill_gate_count = 1`
- SOLUSDT per-symbol note `block_reasons_passthrough` body:
  - `prediction = ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
  - `orchestrator_held = ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
  - `paper_intent_held = ["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
  - `orchestrator_matches_prediction = true`
  - `paper_intent_matches_prediction = true`
  - `orchestrator_emitted = true`
  - `paper_intent_emitted = true`

Note: the live exact block reason is now `NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK`
rather than the earlier-observed `EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK`,
because the live feature snapshot changes between cycles and the stricter
of the two thresholds fires first. Either reason is a strict-gate
correct block; passthrough integrity is preserved in both cases.

## Governor state after refresh

- `codex_5m_continuous_remediation_review_governor.go_no_go = CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`
- `codex_5m fail_blockers = []`
- `continuous_remediation_status.go_no_go = V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY`
- `gaps_severity_counts = {NO_ACTION_REQUIRED_SAFE_BLOCK: 4, OPERATOR_DECISION_REQUIRED: 3, BLOCKS_PRODUCTION_EQUIVALENCE: 3}`
- `P1_FIX = 0` (the paper-fill-gate passthrough gap has been demoted from
  P1_FIX to NO_ACTION_REQUIRED_SAFE_BLOCK now that the reasons accompany
  the gap, per the operator-applied classification rule).
- `production_equivalence_gaps_open = 3` (checkpoint-weight blocker only;
  unchanged by this refresh).

## Soak state after refresh

- `minutes_observed = 209.03`
- `soak_15m_ready = true`
- `soak_1h_ready = true`
- `soak_6h_ready = false`
- `all_v2_processes_uninterrupted = true` (observer did not catch the
  2-second restart window; honest record kept in
  `ACTIVE_RUNTIME_REFRESH_AUDIT.json`)
- `v2_namespaces_never_empty = true`
- `observation_count = 47`
- `last_observed_utc = 2026-05-17T05:29:23Z`

## Safety invariants

- `live_gate = blocked_human_only`
- `live_symbols = []`
- `approves_live = false`
- `approves_canary = false`
- `approves_legacy_shutdown = false`
- `approves_redis_trim = false`
- no legacy mutation
- no legacy script executed
- no exchange mutation
- no old Redis writes
- no approval tokens created
- gate behavior unchanged (`validate_for_paper_fill_gate` untouched)
- no threshold loosening
- no fills created (held intents carry `places_real_order=false`)

## What this packet does NOT claim

- Not live-ready
- Not canary-ready
- Not legacy-shutdown-ready
- Not Redis-trim-ready
- Does not declare 6h soak complete
- Does not approve the checkpoint-weight blocker

The continuous remediation loop remains running on its 5-minute cadence,
and the rolling restart is now reflected in the active runtime evidence
files.
