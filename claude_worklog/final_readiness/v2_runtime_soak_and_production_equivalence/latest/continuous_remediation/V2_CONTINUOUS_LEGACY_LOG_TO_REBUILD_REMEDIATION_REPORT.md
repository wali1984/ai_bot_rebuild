# V2 Continuous Legacy-Log to Rebuild Remediation Report

Status: V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_READY

Generated alongside `GO_NO_GO.md` in the same directory. All paths in this
report are repo-relative and read-only with respect to legacy.

## Safety posture (unchanged)

- live_gate=blocked_human_only
- live_symbols=[]
- approves_live=false
- approves_canary=false
- approves_legacy_shutdown=false
- approves_redis_trim=false
- shutdown_recommendation=BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE
- no_legacy_mutation=true
- no_old_redis_writes=true
- no_exchange_mutation=true
- no_legacy_script_executed=true

Verification commands (raw):
- Approval-token absence: `ls claude_worklog/approvals/` (only standing
  non-live approvals present; no live/canary/shutdown/redis_trim tokens).
- Old-key write scan: `python3 /tmp/_safe_scan.py` -> `old_key_write_hits=0`.
- Exchange-mutation scan over the new modules:
  `python3 /tmp/_safe_scan.py` -> `mutation_hits=1`, and the one match is the
  literal `"change leverage or margin"` string inside the `forbidden_actions`
  list in the remediation tool (a guard description, not an action).

## Phases addressed

This sprint addresses all nine phases of the task contract:

1. Read-only watch of legacy logs and monitor scripts.
2. V2-vs-legacy comparison surfaces per-symbol mismatch causes.
3. Mismatch causes are converted to narrow remediation gaps.
4. Each gap has a paired Claude fix task + Codex review task auto-written.
5. Safe V2 gaps can be auto-applied (gap-ID allow list); checkpoint-blocker
   gaps route to operator/Codex without auto-apply.
6. Continuous scheduler runs the loop on a 5-minute cadence in soak.
7. Frontend truth payload surfaces observer + remediation status fields.
8. Soak continues uninterrupted in parallel.
9. Final READY token + report emitted without claiming live or shutdown.

## Runtime: V2 chain of loops

V2 processes confirmed running (parallel, paper-only):

- `v2.backend.app.cli.v2_native_ingestors_live_loop`
- `v2.backend.app.cli.v2_feature_pipeline_native_loop`
- `v2.backend.app.cli.v2_rl_core_inference_loop`
- `v2.backend.app.cli.v2_orchestrator_arbitration_loop`
- `v2.backend.app.cli.v2_trade_management_paper_loop`
- `v2.backend.app.cli.v2_production_payload_freshness_refresher`
- `v2.backend.app.cli.v2_production_replacement_soak_observer`
- `v2.backend.app.cli.v2_production_equivalence_comparator`
- `v2.backend.app.cli.v2_legacy_log_intelligence_observer`
- `claude_worklog/tools/v2_production_replacement_runtime_guard.py`
- `claude_worklog/tools/v2_legacy_v2_production_comparator.py`
- `claude_worklog/tools/v2_continuous_legacy_log_to_rebuild_remediation.py`

Confirmation: `pgrep -af "v2.backend.app.cli|v2_continuous_legacy_log|v2_legacy_v2_production_comparator|v2_production_replacement_runtime_guard"` -> 12 PIDs.

## Soak posture

- minutes_observed: 57.42
- soak_15m_ready: true
- soak_1h_ready: false (will become true after ~60 minutes)
- soak_6h_ready: false (will become true after ~360 minutes)
- all_v2_processes_uninterrupted: true
- v2_runtime_running: true
- v2_writes_v2_redis: true
- v2_total_redis_key_count: 35

## Continuous remediation result (one cycle)

Generated at: `2026-05-17T02:57:46Z` (see continuous_remediation_status.json).

- gaps_total: 6
- gaps_severity_counts: BLOCKS_PRODUCTION_EQUIVALENCE=3, P1_FIX=3
- claude_codex_task_pairs: 6 (existing single pair re-claimed across symbols)
- monitor_script_count: 3
- remediation_hints_emitted: 6

All 6 gaps map to `trainer_missing_checkpoint_weight_shape_contract`
(BTCUSDT, ETHUSDT, SOLUSDT x 2 causes). This is the expected blocker family
during the current paper-only soak: legacy trainer opens directional
positions while V2 holds because V2 has no approved checkpoint weight blob
loaded. The remediation routes the operator to provide
`CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED` (or accept the paper-only
limitation), with the paired Codex task confirming no auto-apply was made.

## Auto-apply policy in this loop

- `_AUTO_FIX_FORBIDDEN_GAP_IDS = {trainer_missing_checkpoint_weight_shape_contract, live_only_blocker_not_auto_fixable}`
- For all current gaps `auto_apply_allowed_by_this_loop=false`.
- The loop does not mutate V2 source for forbidden gaps; it only writes the
  Claude+Codex paired task pair so the operator/Codex chain can act.
- The loop never executes legacy scripts; it only static-inspects them.

## Frontend truth fields newly surfaced

`v2/frontend/public/operator_runtime/frontend_truth/latest/frontend_truth_payload.json`:

- `legacy_log_observer_running` = true
- `continuous_remediation_loop_running` = true
- `latest_legacy_log_summary` = `{trainer_present, orchestrator_present, monitor_script_count, remediation_hints_count}`
- `latest_remediation_summary` = `{gaps_total, gaps_severity_counts, claude_codex_task_pairs}`

Refreshed at: `2026-05-17T03:01:41Z` (this run).

## Validation

- pytest: `v2/backend/tests/integration/cli/test_v2_legacy_log_intelligence_observer.py` -> 7 passed (typo resolution, missing path, tail-bytes-only-new, truncation reset, trainer parser, orchestrator parser, inspect monitor script).
- JSON files validate as JSON (`json.loads` reads succeed in this run's commands).
- No exchange-mutation calls in any of: observer service, observer CLI,
  continuous remediation tool. The single textual match is a guard-string in
  `forbidden_actions`.
- No old Redis write patterns (`prediction:` / `signals:` / `trainer:` /
  `orchestrator:` / `features:` / `paper:` / `risk:`) detected in new modules.
- Approvals dir contains only standing non-live tokens; no
  live/canary/shutdown/redis_trim approval tokens were created.

## Artifacts produced this sprint

- `claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/GO_NO_GO.md`
- `claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/V2_CONTINUOUS_LEGACY_LOG_TO_REBUILD_REMEDIATION_REPORT.md`
- `claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/continuous_remediation_status.json`
- `claude_worklog/final_readiness/v2_runtime_soak_and_production_equivalence/latest/continuous_remediation/legacy_log_v2_gap_matrix.json`
- `v2/frontend/public/operator_runtime/legacy_log_intelligence/latest/legacy_log_intelligence_status.json`
- `claude_worklog/agent_supervisor/tasks/claude_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract.json`
- `claude_worklog/agent_supervisor/tasks/codex_review_fix_v2_gap_trainer_missing_checkpoint_weight_shape_contract.json`

## What this report does NOT claim

- It does NOT claim live readiness.
- It does NOT claim legacy shutdown readiness.
- It does NOT claim Redis trim readiness.
- It does NOT claim 1h/6h soak completion.
- It does NOT modify legacy in any way.
- It does NOT execute legacy monitor scripts.

The continuous remediation loop is now an evidence-producing observer in
parallel with the running soak, and will continue to emit narrow Claude+Codex
task pairs whenever new mismatch causes appear.
