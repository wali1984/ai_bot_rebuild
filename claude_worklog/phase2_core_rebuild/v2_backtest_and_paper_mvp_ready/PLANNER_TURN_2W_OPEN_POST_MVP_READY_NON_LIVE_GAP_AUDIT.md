# Planner Turn 2W — Open Post-MVP-Ready Non-Live Gap Audit (Phase 2W)

## Date
2026-05-09

## HEAD at planner turn open
4a9544d Add post MVP lane lock release planner note

## Worktree state at planner turn open
- Dirty: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` only (single tracker-line edit advancing `Current MVP milestone` from `PAPER_EXECUTION_LEDGER_MVP` to `REPLAY_BACKTEST_RUNNER_MVP`). The edit is itself stale per Planner Turn 2L; this planner turn does not mutate the prompt and re-confirms the operator-recommended replacement: `Current MVP milestone: V2_BACKTEST_AND_PAPER_MVP_READY (achieved)`, `Next paper/backtest milestone: none — sequence closed; Lane A residual hardening only`, `Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 0 milestones remaining`.
- All other files clean.
- No active Claude/Codex child running.

## On-disk gate evidence read at planner turn open
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` — `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2L_POST_MVP_READY_LANE_LOCK_RELEASE_AND_NEXT_SAFE_MILESTONE.md` — `PHASE_2L_POST_MVP_READY_LANE_LOCK_RELEASE_AND_NEXT_SAFE_MILESTONE_OPEN`.
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` — `REPLAY_BACKTEST_RUNNER_MVP` satisfied at close of Phase 2I.C.
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/25_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` — `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md` — `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS` (REQ_0006 Stage A trainer parity output contract closed).
- `claude_worklog/final_readiness/04_GO_NO_GO.md` — `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (live gate human-only).
- `claude_worklog/final_readiness/non_live_operational_proof/15_CODEX_GO_NO_GO_OPERATOR_PROOF_HARNESS.md` and `13_OPERATOR_PROOF_HARNESS_GO_NO_GO.md` — REQ_0026 satisfied.
- `claude_worklog/final_readiness/historical_30d_replay_and_paper_proof/latest/GO_NO_GO.md` — `HISTORICAL_30D_REPLAY_AND_PAPER_PROOF_READY`.
- `claude_worklog/final_readiness/continuous_paper_shadow_runtime/latest/GO_NO_GO.md` — `CONTINUOUS_PAPER_SHADOW_RUNTIME_READY`.
- `claude_worklog/final_readiness/autonomous_phase_2v_pickup/latest/GO_NO_GO.md` — `AUTONOMOUS_PHASE_2V_PICKUP_AND_DISPATCH_PROOF_READY`.

## Why this is the next safe non-live planner turn
- The REQ_0017 / REQ_0020 paper/backtest MVP sequence is closed end-to-end. The REQ_0018 prime-directive lane lock is released per Planner Turn 2L. The four approved lanes (`paper_backtest_mvp`, `explainability_ui`, `codex_watchdog`, `legacy_parity`) remain available, and the planner profile rule "every generated task JSON must include lane, mvp_relevance, blocked_by, next_gate, legacy_evidence_consulted, and legacy_failure_addressed" continues to apply.
- The final live-readiness marker `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` is human-only by REQ_0020 stop condition `FINAL_LIVE_GATE_REQUIRES_HUMAN_APPROVAL`. The planner cannot and must not flip it, so the next consolidated milestone must extend the non-live build chain without enabling any live or shadow execution authority and without flipping the live gate.
- Per REQ_0013 phase order, SMC/liquidity feature shadow mode may begin only after (1) external/manual position quarantine, (2) provenance/dedupe/attribution, and (3) degraded-state fail-closed gates. Items (1)–(3) have not yet been opened as their own consolidated milestones. Per Planner Turn 2L, Phase 2W is the chosen audit-only step that selects exactly one of {2X, 2Y, 2Z} as the next consolidated implementation milestone after Phase 2W, on the basis of on-disk evidence rather than ad-hoc opening.

## Phase 2W scope (consolidated, read-only audit, no V2 source, no V2 tests, no execution-side surface)
- Read REQ_0013, REQ_0019, REQ_0022, REQ_0023, REQ_0024 against the on-disk artifact set under `claude_worklog/phase2_core_rebuild/`, `claude_worklog/final_readiness/`, `claude_worklog/legacy_runtime_audit/`, `claude_worklog/legacy_readonly_audit/`, and `claude_worklog/historical_pnl_audit/`.
- Produce `02_PHASE_2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` enumerating, per requirement and per REQ_0013 phase-order prerequisite, which prerequisites are PASS / PARTIAL / NOT_OPENED on disk, with raw evidence pointers per the Evidence Integrity Rule. Each row must carry: requirement ID, prerequisite name, status, raw evidence pointer (file path + line range or marker name), verification command, confidence, missing evidence.
- Produce `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` selecting exactly one consolidated next milestone from the candidate set:
  - **2X_EXTERNAL_MANUAL_POSITION_QUARANTINE** (REQ_0013 prerequisite 1, REQ_0022 hedge-unwind/squeeze residual exposure tie-in) — typed contract + non-live unit tests only, no execution-side surface.
  - **2Y_PROVENANCE_DEDUPE_ATTRIBUTION** (REQ_0013 prerequisite 2) — typed contract + non-live unit tests only, no execution-side surface.
  - **2Z_DEGRADED_STATE_FAIL_CLOSED_GATES** (REQ_0013 prerequisite 3) — typed contract + non-live unit tests only, no execution-side surface.
  Recommendation must include: the chosen milestone, the rationale anchored to on-disk legacy evidence, the legacy failure each candidate addresses, the proof gate the recommended milestone will produce, and the explicit deferral order for the other two candidates.
- Produce `00_PHASE_2W_SCOPE.md`, `01_PHASE_2W_LEGACY_EVIDENCE_REVIEW.md`, `04_PHASE_2W_SAFETY_BOUNDARIES.md`, `05_PHASE_2W_GO_NO_GO_REQUEST.md`, and `06_PHASE_2W_GO_NO_GO.md` (single line `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY` or `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_BLOCKED`).

## Phase 2W explicitly does NOT
- Author any V2 source under `v2/backend/app/domain/`, `v2/backend/app/services/`, `v2/backend/app/composition/`, `v2/backend/app/adapters/`, `v2/backend/app/cli/`, or `v2/backend/app/proof/`.
- Author any new test under `v2/backend/tests/`.
- Touch `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- Introduce any execution-side surface: no paper trader, no shadow trader, no live trader, no replay engine, no scheduler, no background loop, no FastAPI surface, no Redis adapter, no GPU runner, no model-loading subsystem, no strategy library.
- Introduce any new lineage ID beyond those already at `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` and the five Phase 2V trainer-parity fields.
- Modify any prior-milestone artifact byte content.
- Flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` or any other live-gate marker.
- Open SMC/liquidity feature shadow-mode work (REQ_0013) before prerequisites 1–3 are PASS.
- Read or write any Redis key, restart any live service, place or cancel exchange orders, change leverage or margin, enable live trading, deploy, run a production migration, or expose or commit secrets.
- Modify `/home/wali/Desktop/AI BOT`.

## Lane / MVP fields for the Phase 2W milestone task
- `lane`: `legacy_parity` (read-only audit) with secondary `codex_watchdog` (Codex review of the audit itself follows in the next planner turn).
- `mvp_relevance`: Closes the residual non-live build chain decision. Identifies the single next consolidated milestone after `V2_BACKTEST_AND_PAPER_MVP_READY` so REQ_0013 / REQ_0022 / REQ_0023 advance through a deterministic prerequisite order rather than ad-hoc opening of SMC/liquidity feature work that REQ_0013 explicitly forbids until prerequisites 1–3 are PASS. Keeps Lane A residual hardening visible. Aligns with REQ_0020 stop condition "Until then, Codex/Claude must continue non-live build/review/recovery."
- `blocked_by`: nothing on disk — Phase 2W is a clean-slate audit and depends only on already-passed gates listed above and on Planner Turn 2L's open marker `PHASE_2L_POST_MVP_READY_LANE_LOCK_RELEASE_AND_NEXT_SAFE_MILESTONE_OPEN`.
- `next_gate`: `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY` (claude validation) → `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS` (Codex review).
- `legacy_evidence_consulted`: `claude_worklog/legacy_readonly_audit/`, `claude_worklog/legacy_runtime_audit/`, `claude_worklog/historical_pnl_audit/`, `claude_worklog/phase2_core_rebuild/legacy_evidence/`, the eight REQ_0017 milestone GO/NO-GO markers, the Phase 2V CODEX PASS, REQ_0013 / REQ_0019 / REQ_0022 / REQ_0023 / REQ_0024 / REQ_0026 in `claude_worklog/requirements_inbox/`.
- `legacy_failure_addressed`: documents which legacy failure classes the next non-live milestone must address (LAB hedge-unwind / squeeze residual exposure per REQ_0022, manual-position SMC misuse per REQ_0013 § "do not use SMC features to justify DCA, hedging, rescue trades, or risk-adds on manual/external positions", stale-data fail-closed gating per REQ_0013 § "degraded-state fail-closed gates", historical loser pattern per REQ_0024 § "Risk-Gateway Implications"), without enabling any of them.

## Hard non-live boundaries reaffirmed
- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not read or write any Redis key.
- Do not invoke any Redis command.
- Do not restart any live service.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run a production migration.
- Do not expose or commit secrets.
- Do not flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` or any other live-gate marker.
- Final live approval remains human-only.

## Planner-prompt mutation policy this turn
This planner turn authors **one** planning note inside `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/` and **one** consolidated task definition under `claude_worklog/agent_supervisor/tasks/`. It does **not** author any V2 source file, any V2 test file, any prior-milestone artifact byte content, any `claude_worklog/final_readiness/` artifact, any `v2/frontend/public/` artifact, any `claude_worklog/autonomous_control_plane/` file, or any planner-prompt edit. The dirty `claude_master_rebuild_planner_prompt.txt` line edit remains untouched and stays in the operator's queue, and is added to the next task's `worktree_excluded_paths`.

PHASE_2W_OPEN_POST_MVP_READY_NON_LIVE_GAP_AUDIT_OPEN
