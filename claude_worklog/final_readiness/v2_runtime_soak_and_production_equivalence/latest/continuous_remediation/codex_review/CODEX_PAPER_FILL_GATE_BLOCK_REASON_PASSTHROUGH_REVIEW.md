# Codex Review: SOLUSDT Paper-Fill-Gate Block-Reason Passthrough

Generated: `2026-05-17T05:49:00Z`

GO/NO-GO: `PAPER_FILL_GATE_BLOCK_REASON_PASSTHROUGH_CODEX_PASS`

## Decision

Codex re-reviewed and passes the narrow SOLUSDT paper-fill-gate block-reason passthrough fix after the V2-only active runtime refresh. Current active Redis/runtime/public payloads still prove the block reason propagates from prediction to orchestrator held decision, paper trade-management held intent, comparator, gap matrix, and frontend-rendered fields.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, legacy shutdown, or Redis trim.

## Active Runtime Evidence

### Prediction

Active `v2:prediction:SOLUSDT:1m` reports:

- `paper_fill_allowed=false`
- `paper_fill_gate_status=BLOCKED_BY_TRAINER_OUTPUT_MALFORMED`
- `paper_fill_gate_block_reasons=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
- `selected_action=hold`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

### Orchestrator

Active `v2:orchestrator:decisions` reports:

- `schema_version=v2_orchestrator_decisions_v2`
- `held_by_paper_fill_gate_count=1`
- `held_by_paper_fill_gate[]` includes `SOLUSDT`
- `decision=HELD_BY_PAPER_FILL_GATE`
- `paper_fill_gate_block_reasons=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
- `places_real_order=false`

### Paper Trade Management

Active `v2:paper:intents_held_by_paper_fill_gate` includes `SOLUSDT` with:

- `decision=HELD_BY_PAPER_FILL_GATE`
- `places_real_order=false`
- `paper_fill_gate_block_reasons=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
- `live_gate=blocked_human_only`
- `live_symbols=[]`

Active `v2:paper:ledger` also carries `held_by_paper_fill_gate_count=1` and no accepted SOLUSDT fill.

### Comparator

Active public `production_equivalence_comparison.json` reports:

- `schema_version=v2_production_equivalence_comparison_v2`
- `orchestrator_held_by_paper_fill_gate_count=1`
- `paper_intent_held_by_paper_fill_gate_count=1`
- SOLUSDT `block_reasons_passthrough` note includes:
  - `orchestrator_matches_prediction=true`
  - `paper_intent_matches_prediction=true`
  - `prediction=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
  - `orchestrator_held=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`
  - `paper_intent_held=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`

Codex parsed the comparator note and directly verified the prediction, orchestrator, and paper-intent reason arrays match exactly.

## Gap Matrix And Frontend

The active gap matrix contains the SOLUSDT row:

- `gap_id=paper_fill_gate_blocked_with_reason`
- `cause=v2_paper_fill_gate_blocked`
- `severity=NO_ACTION_REQUIRED_SAFE_BLOCK`
- `paper_fill_gate_block_reasons=["NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK"]`

The P1 passthrough gap is no longer open once active runtime proves the passthrough. Monitor Center renders `paper_fill_gate_block_reasons` inline in the gap matrix row.

## Soak Honesty

`ACTIVE_RUNTIME_REFRESH_AUDIT.json` honestly records the rolling restart:

- pre/post PIDs are recorded for orchestrator, paper trade-management, comparator, and continuous remediation.
- restart window was approximately 2 seconds.
- audit explicitly states the soak observer did not catch the restart window because of its 300-second cadence.
- latest checked soak status: `soak_1h_ready=true`
- latest checked soak status: `soak_6h_ready=false`
- latest checked soak minutes observed: `228.18`
- shutdown remains blocked.

This review treats the refresh as an intentional V2-only runtime refresh, not as proof of shutdown readiness.

## Validation

- Focused tests: `32 passed`
  - `test_v2_paper_fill_gate_block_reason_passthrough.py`
  - `test_v2_continuous_legacy_log_remediation_classification.py`
  - `test_v2_rl_core_p0_2f_trainer_output.py`
- Active runtime reason match: PASS.
- No paper fill created from the held SOLUSDT signal: PASS.
- Paper gate behavior unchanged: PASS.
- No threshold loosening found in reviewed source: PASS.
- Old Redis write scan: PASS; reviewed writes are guarded to `v2:` keys.
- Exchange mutation scan: PASS.
- Approval scan: PASS.

## Safety State

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Non-Approval Items

- Checkpoint weights remain operator-required.
- Production equivalence remains incomplete.
- 6h soak remains pending.
- Legacy still owns production.
- Shutdown remains blocked.
- Live remains blocked.

## Final Decision

`PAPER_FILL_GATE_BLOCK_REASON_PASSTHROUGH_CODEX_PASS`
