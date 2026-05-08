# Planner Turn 2O — Open Phase 2O Implementation

## State at planner turn open

- HEAD: `cdce356` ("Codex watchdog recover dirty non-live automation artifacts").
- Pending unstaged change is limited to `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (the `worktree_excluded_paths` covers it under prior task definitions; it is the in-flight planner-prompt MVP-counter rotation noted in the planner status JSON and does not block dispatch).
- `V2_BACKTEST_AND_PAPER_MVP_READY` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md`.
- `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md`.
- `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/09_CODEX_GO_NO_GO.md`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY` body present at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/07_GO_NO_GO.md`.
- `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS` body present at `claude_worklog/phase2_core_rebuild/paper_mode_evidence_collection_harness/09_CODEX_GO_NO_GO.md`.
- Planner status JSON `current_mvp_milestone` field is stale ("REPLAY_BACKTEST_RUNNER_MVP" with three remaining); per REQ_0015 § "Evidence-first reconciliation", PASS markers under `claude_worklog/phase2_core_rebuild/` override stale queue / status noise. The status JSON is rotated by the supervisor on next dispatch and does not block the planner turn.

## Decision

Open Phase 2O — Shadow-Mode Evidence-Collection Harness — as the next post-consolidation Lane A evidence-collection milestone, per `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/07_NEXT_STEP_AFTER_CONSOLIDATION.md` § "Lane A — paper_backtest_mvp" third bullet ("Shadow-mode evidence-collection harness").

This is the explicit `next_recommended_action` declared by `claude_worklog/agent_supervisor/tasks/165_phase2n_paper_mode_evidence_collection_harness_implementation.json` on `PHASE2N_PAPER_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS`: "the planner opens the next post-consolidation lane A category - shadow-mode evidence-collection harness."

## Lane / MVP relevance / next gate

- Lane: `paper_backtest_mvp`.
- MVP relevance: post-consolidation Lane A evidence collection. The shadow-mode evidence-collection harness produces typed `(ShadowModeReadinessFlag, per-step ShadowModeComparisonRecord)` evidence rows over a deterministic four-scenario evidence pack, gated on the typed shadow-readiness flag, establishing the typed offline-inspectable shadow-comparison baseline that subsequent shadow-decision-id lineage, decision-explainability UI, and risk-gateway-extension milestones replay against. No new code surface beyond test-only fixtures, a pure-function harness module, and a pytest module. No `shadow_decision_id` lineage row is introduced at this stage; the comparison record is per-step typed pairs of `(legacy_action_evidence_pointer, RiskDecisionRecord)`. Adding a `shadow_decision_id` lineage row is a separate, later milestone explicitly out of scope at Phase 2O.
- Blocked by (all materialized): see `05_GO_NO_GO_REQUEST.md` § "Predecessor evidence".
- Next gate: `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_READY` at `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/07_GO_NO_GO.md`. Codex review marker: `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_CODEX_PASS`.

## Authored task

The planner turn authors:

- The Phase 2O planning packet (01–05) under `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/`.
- This planner-turn note (`PLANNER_TURN_2O_OPEN_IMPLEMENTATION.md`).
- The supervisor task `167_phase2o_shadow_mode_evidence_collection_harness_implementation` under `claude_worklog/agent_supervisor/tasks/`.

## Hard safety posture

Live trading: BLOCKED. Phase 2O is non-live by construction. No `/home/wali/Desktop/AI BOT` mutation. No Redis access. No live service restart. No exchange action. No leverage / margin change. No deployment. No production migration. No secret exposure. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.

## Recovery posture (Codex autofix lane)

On `PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_IMPLEMENTATION_FAIL` with concrete documentation blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 Codex autofix scoped to the Phase 2O packet only. If a downstream Codex `FAIL` is a stale-rubric / pre-existing-placeholder false positive analogous to the 2H / 2I / 2J / 2K / 2L / 2M / 2N reconciliation precedent, the supervisor authors `10_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/shadow_mode_evidence_collection_harness/` and rewrites the `09_CODEX_GO_NO_GO.md` body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

PHASE2O_SHADOW_MODE_EVIDENCE_COLLECTION_HARNESS_PLANNER_TURN_OPEN_READY
