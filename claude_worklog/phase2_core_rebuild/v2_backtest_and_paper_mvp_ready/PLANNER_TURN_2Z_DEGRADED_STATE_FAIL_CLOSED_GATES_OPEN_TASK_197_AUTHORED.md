# Planner Turn 2Z — Open Phase 2Z Degraded-State Fail-Closed Gates Domain and Author Task 197

## Date
2026-05-10

## HEAD at planner turn open
`927fc65 Codex watchdog recover dirty non-live automation artifacts`

This is the head reached by the Codex watchdog's three consecutive recovery cycles that closed out the Phase 2Y.B END_FILE leakage and dirty-tree backlog described across the four prior `PLANNER_TURN_2Y_REINVOKED_*` notes. The recent commit chain visible in `git log --oneline -8`:

```
927fc65 Codex watchdog recover dirty non-live automation artifacts
c50805e Codex watchdog recover dirty non-live automation artifacts
1769f8a Codex watchdog recover dirty non-live automation artifacts
7c94d6e Add Codex parallel review batch results
ba2c70e Create Codex parallel review batch
9df524a Export Redis liquidations stream with verified manifest
c653745 Add Codex parallel review batch results
22fbb14 Create Codex parallel review batch
```

## Worktree state at planner turn open
`git status --porcelain` returns one path only:

```
 M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt
```

The single dirty path is the operator-managed planner-prompt rotation. It is excluded from this turn's task by `worktree_excluded_paths` and is not staged in this turn.

## On-disk gate evidence read at planner turn open
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md` — `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED`. The Phase 2Y typed-contract surface is now reconciled and the only remaining REQ_0013 prerequisite is degraded-state fail-closed gates (REQ_0013 prerequisite 3 of 3).
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/14_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_CURRENT_HEAD.md` — current-head reconciliation per Steps A–F.
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/07_GO_NO_GO.md` — `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/11_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_AUTOFIX_VALIDATION_GO_NO_GO.md` — `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_AUTOFIX_VALIDATED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED`. Phase 2X (REQ_0013 prerequisite 1 of 3) is closed.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` — Phase 2W deferral order: 2X first, 2Y second, 2Z last. With 2X and 2Y both reconciled, 2Z is now due.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/08_PHASE_2W_CODEX_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` — `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md` — `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS`.
- `claude_worklog/final_readiness/04_GO_NO_GO.md` — `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (human-only; not flipped by this turn).

## Why this is the next safe non-live planner turn
- The REQ_0017 / REQ_0020 paper-backtest MVP sequence is closed end-to-end and `V2_BACKTEST_AND_PAPER_MVP_READY` plus `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` are PASS on disk. The REQ_0018 prime-directive lane lock is released per Planner Turn 2L.
- REQ_0013 § "Required phase order" enumerates six prerequisites. Items 1 (external/manual position quarantine) and 2 (provenance/dedupe/attribution) are both reconciled on disk. Item 3 (degraded-state fail-closed gates) is the next prerequisite. Items 4–6 (SMC/liquidity feature shadow mode, paper validation, risk-gated filter) remain blocked behind item 3.
- Phase 2W explicitly defers 2Z to third position because the degraded-state record consumes per-source provenance pointers from Phase 2Y. With Phase 2Y typed-surface reconciled, Phase 2Z's typed surface can mirror it cleanly.
- No active Claude/Codex child is running. Git is clean except for the operator-managed planner-prompt path that is in `worktree_excluded_paths`. The Codex parallel-review batch at HEAD `7c94d6e` is fully drained and committed.
- Per REQ_0020 stop condition: "Until then, Codex/Claude must continue non-live build/review/recovery." The next consolidated non-live milestone must therefore be a non-live extension that does not introduce live or shadow execution authority. Phase 2Z is exactly such an extension: typed contract + non-live unit tests only.

## Phase 2Z scope summary
Phase 2Z authors the third REQ_0013 prerequisite as a consolidated typed-contract milestone authoring (a) the typed value-object layer at `v2/backend/app/domain/degraded_state_fail_closed_gates/`, (b) the pure-function service layer at `v2/backend/app/services/degraded_state_fail_closed_gates/`, (c) the composition-root layer at `v2/backend/app/composition/degraded_state_fail_closed_gates/`, (d) the non-live unit tests at `v2/backend/tests/unit/{domain,services,composition}/degraded_state_fail_closed_gates/`, and (e) the eight Phase 2Z documentation files at `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/`.

The typed value objects are:
- Module-level state constants: `DEGRADED_SOURCE_OK`, `DEGRADED_SOURCE_STALE`, `DEGRADED_SOURCE_MISSING`, `DEGRADED_SOURCE_UNUSED`. All four states keep `live_blocked` invariantly True at the consuming record layer.
- `DegradedStateRecord` — frozen, slotted dataclass with `degraded_state_id` (deterministic derivation `f'degraded_state:{decision_id}'` truncated to 128 chars), per-source state fields for the four REQ_0013 § "Required freshness / DQ gates" sources (`smc_state`, `smc_age_ms`, `liq_state`, `liq_age_ms`, `oi_state`, `oi_age_ms`, `orderbook_state`, `orderbook_age_ms`), a derived `fail_closed: bool` invariant equal to True iff any per-source state is `DEGRADED_SOURCE_STALE` or `DEGRADED_SOURCE_MISSING`, the four existing lineage IDs (`decision_id`, `prediction_id`, `feature_snapshot_id`, `risk_decision_id`) mirrored from upstream `RiskDecisionRecord`, the five Phase 2V trainer-parity fields (`model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness`), and `live_blocked: bool == True`.

The pure-function service is `assemble_degraded_state_record(*, upstream_record, smc_state, smc_age_ms, liq_state, liq_age_ms, oi_state, oi_age_ms, orderbook_state, orderbook_age_ms, trainer_model_version, trainer_checkpoint_id, trainer_confidence_raw, trainer_confidence_calibrated, trainer_worker_liveness)` returning a `DegradedStateRecord` with the per-source state validation, the deterministic `degraded_state_id` derivation, the derived `fail_closed` flag, and the four mirrored lineage IDs.

The composition root is `build_degraded_state_fail_closed_gates_runtime(*, now_ms_clock: Callable[[], int])` returning a `DegradedStateFailClosedGatesRuntime` exposing one `degraded_state_now` closure that delegates to the assembler. The closure invokes the captured `now_ms_clock` zero times per call, mirroring the Phase 2X.B / 2Y reconciled clock policy because the typed record carries its own per-source `*_age_ms` and decision-id-derived `degraded_state_id`.

Out of scope: no execution-side surface, no paper trader, no shadow trader, no live trader, no replay engine, no scheduler, no background loop, no FastAPI surface, no Redis adapter, no GPU runner, no model-loading subsystem, no strategy library, no new lineage ID, no live-gate flip, no Phase 2Y / Phase 2X / prior-milestone byte mutation, no SMC/liquidity feature shadow-mode work.

## Lane / MVP relevance / next gate (REQ_0011 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0018 / REQ_0020 / REQ_0021 / REQ_0025)
- `lane`: `legacy_parity` (typed-contract preservation of the REQ_0013 § "Required freshness / DQ gates" deterministic feature gates against the legacy bot's stale/missing/unused failure modes documented at `claude_worklog/phase2_core_rebuild/legacy_evidence/02_CURRENT_LEGACY_FAILURE_SIGNALS.md`).
- `secondary_lane`: `paper_backtest_mvp` (Phase 2Z is the third REQ_0013 prerequisite; the SMC/liquidity feature shadow-mode milestones it gates feed paper/backtest expectancy after `V2_BACKTEST_AND_PAPER_MVP_READY`).
- `mvp_relevance`: closes the third of three REQ_0013 prerequisites that gate SMC/liquidity feature shadow mode. With 2X and 2Y reconciled and 2Z PASS, the three REQ_0013 prerequisites are all closed and the planner may then open SMC/liquidity feature shadow-mode work in shadow-only mode (`smc_shadow_enabled = true`, `smc_affects_execution = false` per REQ_0013 § "Initial implementation mode"). The `DegradedStateRecord` is the typed surface that downstream extensions of the orchestrator and risk gateway pattern-match on to emit deny reason codes such as `deny_smc_stale`, `deny_liq_missing`, `deny_oi_stale`, `deny_orderbook_missing` before allowing any open/close/hedge/reduce action.
- `next_gate`: `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/07_GO_NO_GO.md` (claude validation) → `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_PASS` at `09_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_GO_NO_GO.md` (Codex review next planner turn).
- `predecessor_required_marker`: `PHASE2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILED` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/15_2Y_B_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL_RECONCILIATION_GO_NO_GO.md`.
- `blocked_by`: nothing on disk.
- `legacy_evidence_consulted`: REQ_0013 § "Required freshness / DQ gates" lines 121–129 and § "Required behavior" lines 133–137 (`claude_worklog/requirements_inbox/REQ_0013_SMC_LIQUIDITY_SHADOW_FEATURES.md`); REQ_0019 / REQ_0023 read-only legacy audit posture; the Phase 2X and Phase 2Y predecessor markers; the Phase 2W deferral order; the LAB hedge-unwind / squeeze residual exposure failure case at `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md`; and the Phase 2V trainer-parity fields extension closure marker.
- `legacy_failure_addressed`: closes the orchestrator/risk-gateway "stale-data invisibility" and "degraded-source action" failure classes (REQ_0013 lines 121–137 and `claude_worklog/phase2_core_rebuild/legacy_evidence/02_CURRENT_LEGACY_FAILURE_SIGNALS.md`) by authoring a typed `DegradedStateRecord` value object that downstream extensions of the risk gateway and orchestrator decision projection pattern-match on. The legacy bot lacked typed per-source freshness pointers (so stale or missing source data was not detected deterministically, allowing trades on degraded-state inputs); the LAB hedge-unwind / short-squeeze case at `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` lines 7–27 illustrates the cost of acting on inputs whose freshness was not deterministically gated. Phase 2Z authors only the typed-contract surface plus non-live unit tests; the downstream risk-gateway extension that consumes per-source state and emits typed deny reason codes is a future Phase 2Z-follow-up milestone outside this turn's scope.

## This turn's authored output
This planner turn authors **two** files:

1. This planner-turn narrative note `PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED.md` recording the Phase 2Z open snapshot.

2. The Phase 2Z domain implementation task definition `claude_worklog/agent_supervisor/tasks/197_phase2z_degraded_state_fail_closed_gates_domain_implementation.json` instructing local Claude Code to author the consolidated Phase 2Z typed-contract milestone (typed value objects, pure-function service, composition root, non-live unit tests, eight Phase 2Z docs) and emit the `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` marker on success.

This turn does **not**:
- author or modify any V2 source under `v2/` or any V2 test under `v2/backend/tests/`.
- author any Phase 2Z documentation file under `claude_worklog/phase2_core_rebuild/degraded_state_fail_closed_gates_impl/` (those are authored by task 197).
- author any Phase 2Y, Phase 2X, or any prior-milestone byte mutation.
- modify the master planner prompt body.
- modify any other task definition under `claude_worklog/agent_supervisor/tasks/`.
- modify any supervisor status JSON under `claude_worklog/agent_supervisor/status/`.
- modify any committed Codex parallel-review report or GO/NO-GO file under `claude_worklog/codex_parallel_reviews/`.
- introduce any new lineage ID, value-object surface, FastAPI surface, adapter, ledger persistence, replay engine, scheduler, paper trader process, paper executor, shadow executor, live trader process, strategy library, or background loop.
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation.
- dispatch any Binance read-only account-history endpoint or any other live exchange API.
- flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- open SMC/liquidity feature shadow-mode work (REQ_0013 prerequisites must all reach PASS first; Phase 2Z is the last of the three).
- override any prior planner turn's narrative or task-authoring decisions.

## Recommended next planner action
After task 197 dispatch and emit:
- On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `07_GO_NO_GO.md`: the next planner turn authors task 198 to dispatch the Codex review of the Phase 2Z implementation under the `codex_watchdog` lane. On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_CODEX_PASS`, the three REQ_0013 prerequisites are all PASS and the planner may then open SMC/liquidity feature shadow-mode work in shadow-only mode under REQ_0013 § "Initial implementation mode".
- On `PHASE2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_DOMAIN_IMPL_AND_VALIDATION_BLOCKED`: the next planner turn inspects `06_IMPLEMENTATION_REPORT.md` for the precise per-row blocker list and authors a targeted Codex autofix recovery task constrained to the same allowed_output_prefixes per REQ_0007 / REQ_0014.

## Hard non-live boundaries reaffirmed
- No live trading.
- No legacy mutation under `/home/wali/Desktop/AI BOT`.
- No Redis read or write or delete.
- No live service restart.
- No exchange order, leverage, or margin change.
- No deployment, no production migration.
- No secret exposure or commit.
- Final live-readiness gate `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains human-only and is not flipped by this turn or by task 197.
- No SMC/liquidity feature shadow-mode work opened (REQ_0013 prerequisites incomplete until 2Z PASS).
- No interference with the committed Codex parallel-review batch artifacts at HEAD `7c94d6e` or any prior committed Codex parallel-review output.
- No re-emission of task 196 (already drained and reconciled on disk).
- No speculative authoring of task 198 (Codex review) ahead of the 2Z PASS marker.

PLANNER_TURN_2Z_DEGRADED_STATE_FAIL_CLOSED_GATES_OPEN_TASK_197_AUTHORED_READY
