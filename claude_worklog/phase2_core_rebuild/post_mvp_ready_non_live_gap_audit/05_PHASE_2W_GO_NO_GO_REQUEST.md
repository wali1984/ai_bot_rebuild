# Phase 2W — GO/NO-GO Request

## Rubric to flip 06_PHASE_2W_GO_NO_GO.md to PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY

The operator and Codex must verify, in order, every rubric row below. If every row PASSes, flip `06_PHASE_2W_GO_NO_GO.md` to `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`. If any row FAILs, flip to `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_BLOCKED` and leave the precise per-row blocker list inside `02_PHASE_2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md`.

| # | Rubric row | Verification | Pass criterion |
| --- | --- | --- | --- |
| 1 | Every row of `02_PHASE_2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` carries a non-empty raw evidence pointer (file path + line range or marker name). | `grep -nE "^\| (REQ_[0-9]+) " claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/02_PHASE_2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` then per row inspect the fourth column for a non-empty file-path / marker pointer. | Every row's raw-evidence-pointer column is non-empty and references a real file path, line range, or marker name. |
| 2 | The chosen milestone in `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` is one of `{2X_EXTERNAL_MANUAL_POSITION_QUARANTINE, 2Y_PROVENANCE_DEDUPE_ATTRIBUTION, 2Z_DEGRADED_STATE_FAIL_CLOSED_GATES}`. | `grep -n "Chosen milestone" claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md`. | The chosen-milestone line names exactly one of the three candidates. |
| 3 | The rationale in `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` references at least three on-disk evidence pointers per row. | `grep -nE "claude_worklog/.*\.md" claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md`. | The "Rationale" block enumerates at least three distinct file-path-anchored evidence rows; each rationale row carries at least three file-path / line-range / marker pointers. |
| 4 | No V2 source or V2 test or `claude_worklog/final_readiness/` or `claude_worklog/autonomous_control_plane/` or `claude_worklog/agent_supervisor/` or `claude_worklog/requirements_inbox/` or `claude_worklog/legacy_readonly_audit/` or `claude_worklog/legacy_runtime_audit/` or `claude_worklog/historical_pnl_audit/` byte was modified. | `git diff --name-only` and `git status` at Phase 2W commit time. | The diff list contains exactly the seven authored files inside `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/`; no path matches any forbidden output prefix. |
| 5 | No execution-side surface was introduced. | `grep -nE "paper_trader\|shadow_trader\|live_trader\|replay_engine\|scheduler\|background_loop\|fastapi\|redis_adapter\|gpu_runner\|model_loader\|strategy_library" claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/`. | No authored Phase 2W file introduces any of these surfaces (only typed-contract names appear, and only in the recommendation context). |
| 6 | No new lineage ID was introduced. | `grep -nE "_id\s+::" claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/` and cross-check against `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` plus the five Phase 2V trainer-parity fields. | Any lineage ID referenced in Phase 2W matches an existing entry; no new ID is introduced. |
| 7 | The live gate remains blocked and human-only. | `head -2 claude_worklog/final_readiness/04_GO_NO_GO.md` (expected body `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`). | The marker file body is unchanged from the body recorded in `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2W_OPEN_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` line 21. |
| 8 | No markdown fence wrapper was left on any required output. | `grep -n '^\`\`\`' claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/` (expected: no match). | No file body begins or ends with a markdown fence. |
| 9 | `06_PHASE_2W_GO_NO_GO.md` contains exactly one non-empty line. | `wc -l claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md` and `grep -c '.' claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md`. | Exactly one non-empty line (the marker body) followed by a single trailing newline; no fence; no second non-empty line. |

## Self-audit performed in this turn
Each row of the rubric above is satisfied by the seven Phase 2W files authored in this turn:
- Row 1: every row of `02_PHASE_2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` carries a non-empty raw evidence pointer.
- Row 2: the chosen milestone in `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` is `2X_EXTERNAL_MANUAL_POSITION_QUARANTINE`.
- Row 3: the rationale in `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` references at least three on-disk evidence pointers per rationale row.
- Row 4: no path outside `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/` is mutated by Phase 2W.
- Row 5: no execution-side surface is introduced; the recommendation explicitly bounds 2X to typed contract + non-live unit tests only.
- Row 6: no new lineage ID is introduced; only existing IDs and the five Phase 2V trainer-parity fields are mirrored.
- Row 7: the live gate is not flipped by Phase 2W; `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains blocked and human-only.
- Row 8: no markdown fence wrapper is left on any authored file.
- Row 9: `06_PHASE_2W_GO_NO_GO.md` contains exactly one non-empty line.

PHASE_2W_GO_NO_GO_REQUEST_READY
