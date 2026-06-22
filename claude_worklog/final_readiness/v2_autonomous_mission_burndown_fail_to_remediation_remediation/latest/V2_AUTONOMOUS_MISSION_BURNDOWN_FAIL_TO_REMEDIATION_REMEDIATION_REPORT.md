# V2 Autonomous Mission Burndown — FAIL-to-Remediation Remediation

GO/NO-GO: `V2_AUTONOMOUS_MISSION_BURNDOWN_FAIL_TO_REMEDIATION_REMEDIATION_READY`

Purpose:
Codex previously failed `V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_READY` because the packet
reported `Codex_FAIL_count_last_hour=1`, `remediations_created_last_hour=0`,
`codex_fail_to_remediation_loop_visible=false`, and a flat blocker count
(`blocker_count_before=4` / `blocker_count_after=4`) without an explicit acceptable
no-burn reason. This remediation closes that loop end-to-end.

This is execution-loop correctness work. It does not approve real trading,
canary, legacy shutdown, Redis trim, exchange mutation, or operator gates.

## Hard Constraints Held

- Safety envelope unchanged (blocked_human_only)
- No live_symbols
- No live approval, no canary approval, no legacy shutdown approval, no Redis trim approval
- Did not modify `/home/wali/Desktop/AI BOT`
- Did not stop legacy, V2 runtime, report center, replay miner, or Codex governors
- Did not write old Redis or call exchange mutation
- Did not enable real trade execution, create approval tokens, or expose raw API keys

## What Changed

### Phase 1 - Codex FAIL mapping

New helper module `claude_worklog/tools/v2_burndown_fail_to_remediation_mapper.py`
classifies every Codex FAIL in the last-hour window to one of the terminal
states:

- `NEW_REMEDIATION_CREATED`
- `EXISTING_REMEDIATION_REFERENCED`
- `DUPLICATE_SUPPRESSED_EXISTING_REMEDIATION`
- `OPERATOR_REQUIRED`
- `UNSAFE_TO_FIX_AUTOMATION_BLOCKED`

Each row carries `codex_fail_id`, `codex_review_path`, `failed_gate`,
`fail_blockers`, `remediation_required`, `remediation_descriptor_created`,
`remediation_descriptor_path`, `existing_remediation_descriptor_path`,
`duplicate_suppressed`, `operator_required`, `unsafe_to_fix`,
`not_automatable_reason`, `next_action`, and `terminal_classification`.

A fresh existing remediation always wins over the unsafe/operator text
heuristic so the closed-loop's own remediation pipeline is trusted; the
mapper only proposes new descriptors when nothing already addresses the FAIL.
The CODEX_REVIEW.md scan is restricted to the `## Blockers` section and
strips lines containing safety-envelope keys so safe reviews are not
misclassified by quoted state echoes.

Output: `codex_fail_to_remediation_map.json`.

### Phase 2 - Flat blocker-count explanation

When `blocker_count_after >= blocker_count_before`, the mapper computes a
`flat_blocker_count_reason` from this allowlist:

- READY-allowed: `ALL_REMAINING_BLOCKERS_OPERATOR_REQUIRED`,
  `ALL_REMAINING_BLOCKERS_EXTERNAL_REQUIRED`,
  `ALL_REMAINING_BLOCKERS_EVENT_DEPENDENT`,
  `ALL_REMAINING_BLOCKERS_POSITION_DEPENDENT`,
  `IMPLEMENTATION_COMPLETED_AWAITING_CODEX_REVIEW`,
  `REMEDIATION_ACTIVE_NOT_COMPLETED`
- BLOCKED: `BLOCKER_UNCHANGED_DUE_CODEX_FAIL`,
  `BLOCKER_UNCHANGED_DUE_FAILED_REMEDIATION`,
  `NO_MEASURABLE_BURNDOWN_THIS_CYCLE_BLOCKED`

Output: `flat_blocker_count_reason.json`.

### Phase 3 - READY gate correction

`v2_autonomous_mission_execution_burndown.run_once` now BLOCKS when any of
these hold:

- A Codex FAIL exists in the last hour without a terminal classification
  (`CODEX_FAIL_WITHOUT_TERMINAL_CLASSIFICATION`)
- `codex_fail_to_remediation_loop_visible` is false while
  `Codex_FAIL_count_last_hour > 0`
  (`CODEX_FAIL_TO_REMEDIATION_LOOP_NOT_VISIBLE`)
- Blocker count is flat and the reason is in the BLOCKED allowlist
  (`FLAT_BLOCKER_COUNT_REASON_BLOCKS_READY:<reason>`)

In particular, `BLOCKER_UNCHANGED_DUE_CODEX_FAIL` and
`BLOCKER_UNCHANGED_DUE_FAILED_REMEDIATION` flat reasons keep the packet
BLOCKED rather than READY.

Output: `burndown_ready_gate_status.json`.

### Phase 4 - Autoseed follow-up

When the current automatable queue is empty and the mission still has
automatable blockers, `run_once` now triggers
`v2_autonomous_mission_backlog_autoseed.seed_tasks(...)` and re-runs the
pool without waiting for an operator prompt. Operator-required and unsafe
blockers are still classified and skipped - the loop only seeds safe L1
remediations.

Output is recorded under `autoseed_followup` in
`mission_execution_burndown_status.json`.

### Phase 5 - Regression tests

`v2/backend/tests/unit/tools/closed_loop_execution/test_autonomous_mission_execution_burndown.py`
now covers:

- Codex FAIL without remediation mapping -> BLOCKED
- Codex FAIL with existing remediation -> `EXISTING_REMEDIATION_REFERENCED`
- Codex FAIL with operator-approval blockers -> `OPERATOR_REQUIRED`
- Codex FAIL with real-trade/canary/shutdown blockers -> `UNSAFE_TO_FIX_AUTOMATION_BLOCKED`
- Flat blocker_count without reason -> `NO_MEASURABLE_BURNDOWN_THIS_CYCLE_BLOCKED` (BLOCKED)
- Flat blocker_count due Codex FAIL -> `BLOCKER_UNCHANGED_DUE_CODEX_FAIL` (BLOCKED)
- Flat blocker_count due `IMPLEMENTATION_COMPLETED_AWAITING_CODEX_REVIEW` -> READY
- Blocker decrease -> READY
- Report-only completions -> not counted as burndown

### Phase 6 - Refreshed payloads

- `claude_worklog/final_readiness/v2_autonomous_mission_execution_burndown/latest/`
  refreshed with new `codex_fail_to_remediation_map.json`,
  `flat_blocker_count_reason.json`, and `burndown_ready_gate_status.json`,
  plus updated `remediation_flow_status.json`, `operator_dashboard_payload.json`,
  and `GO_NO_GO.md` (now `V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_READY`).
- Mirrors in `v2/frontend/public/v2_autonomous_mission_execution_burndown/latest/`.
- This packet at
  `claude_worklog/final_readiness/v2_autonomous_mission_burndown_fail_to_remediation_remediation/latest/`
  and its public mirror.
- Worker pool mission progress payload regenerated by autoseed at
  `claude_worklog/final_readiness/v2_worker_pool_mission_progress/latest/`.

## Current Loop State

One-shot tool result:

- `go_no_go=V2_AUTONOMOUS_MISSION_EXECUTION_BURNDOWN_READY`
- `Codex_FAIL_count_last_hour=4`
- `codex_fail_to_remediation_loop_visible=true`
- `any_unmapped=false`
- `blocker_count_before=4`, `blocker_count_after=4`
- `flat_blocker_count_reason.reason_code=IMPLEMENTATION_COMPLETED_AWAITING_CODEX_REVIEW`
  (`ready_allowed=true`)
- `gate_blockers=[]`

FAIL classifications:

- `codex_review_autoseed_baseline_after_cost_calibration_r15` -> `EXISTING_REMEDIATION_REFERENCED`
- `codex_review_autoseed_observation_gap_feature_source_burndown_r15` -> `EXISTING_REMEDIATION_REFERENCED`
- `codex_review_autoseed_paper_edge_false_negative_gate_reason_enrichment_r14` -> `EXISTING_REMEDIATION_REFERENCED`
- `codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract` -> `OPERATOR_REQUIRED`
  (requires operator-approved checkpoint blob under the protected runtime policy)

## Safety

- Safety envelope unchanged
- No old Redis writes
- No exchange mutation
- Legacy bot untouched
- Operator-required FAILs left to operator decision
- No new approval tokens created
