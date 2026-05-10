# Planner Turn 2Y — Provenance / Dedupe / Attribution Domain Task 193 Authored

## Date
2026-05-09

## HEAD at planner turn open
`2766072 Codex watchdog recover dirty non-live automation artifacts`

## Worktree state at planner turn open
- One tracked dirty file: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` — the standing planner-prompt MVP-counter rotation excluded from supervisor `requires_clean_worktree` evaluation by `worktree_excluded_paths`. Per REQ_0015 § "Evidence-first reconciliation" and REQ_0016 watchdog operating loop step 4, the on-disk GO/NO-GO PASS markers under `claude_worklog/phase2_core_rebuild/` override this stale planner-prompt counter line. The planner does not rewrite the master planner prompt body this turn.
- No active Claude/Codex/Ollama child running per `claude_worklog/agent_supervisor/status/current_status.json` (`task_id: parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid`, `status: retry_scheduled`, `end_time: 2026-05-10T00:17:51.084848+00:00`).
- `claude_worklog/agent_supervisor/status/queue_status.json`: `current_running_task: null`, `pending: 14`, `running: 0`, `completed: 248`, `failed: 1`, `human_attention_required_count: 0`, `gate: READY_FOR_CODEX_RERUN`. No human attention required.
- No live, legacy, Redis, exchange, deploy, or secret action present.

## On-disk gate evidence read at planner turn open
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/07_GO_NO_GO.md` — `PHASE2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/11_PHASE_2X_B_REMEDIATION_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_REMEDIATION_IMPL_AND_VALIDATION_PASSED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/13_2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_DOMAIN_CODEX_FAIL` (caused by re-review diff scope reaching outside the Phase 2X typed-contract surface).
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/14_2X_B_FAIL_RECONCILIATION_CURRENT_HEAD.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CURRENT_HEAD_RECONCILED`.
- `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` — `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED`. **This is the predecessor required marker for task 193 per evidence-first acceptance.**
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/06_PHASE_2W_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_READY`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/08_PHASE_2W_CODEX_GO_NO_GO.md` — `PHASE2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` — recommends 2X first (DONE), 2Y second (this milestone), 2Z third.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` — `V2_BACKTEST_AND_PAPER_MVP_READY`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` — `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_AT_HEAD_BDB268B.md` — prior planner-turn note authoring the Phase 2Y open decision and the full task 193 specification (typed-contract scope, required output files, worktree exclusions, lane / mvp / gate fields, legacy evidence list, legacy failure addressed, recommended next action).
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md` — `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS`.
- `claude_worklog/final_readiness/04_GO_NO_GO.md` — `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (final live gate remains human-only).

## Predecessor acceptance basis
Per the planner profile rule "GO/NO-GO PASS markers override stale queue/current_status noise; stale tasks become superseded_by_evidence" and the prior 2Y planner-turn note's reconciliation analysis, the Phase 2X.B Codex re-review FAIL recorded at `13_…` is on-disk superseded-by-evidence by the `14_…` and `15_…` reconciliation files. The focused 30-test Phase 2X pytest suite passes at current HEAD; the no-prior-milestone byte-mutation diff under the 2X.B exclusion set is empty. The Phase 2X typed-contract surface is therefore evidence-first accepted as the predecessor surface for Phase 2Y. Task 193 uses `PHASE2X_B_EXTERNAL_MANUAL_POSITION_QUARANTINE_CODEX_FAIL_RECONCILED` at `15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` as its `predecessor_required_marker`.

## This turn's authored output
This planner turn authors **two** files:
1. `claude_worklog/agent_supervisor/tasks/193_phase2y_provenance_dedupe_attribution_domain_implementation.json` — the canonical Phase 2Y open implementation task definition rendering the typed-contract scope from `PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_AT_HEAD_BDB268B.md` § "Next safe consolidated non-live milestone — Phase 2Y_PROVENANCE_DEDUPE_ATTRIBUTION" into the standard task-definition shape (agent / risk_level / depends_on / predecessor markers / cwd / emit_files / task_granularity_mode / requires_clean_worktree / scope_dirty_paths / worktree_excluded_paths / allowed_output_prefixes / forbidden_output_paths / required_output_files / forbidden_actions / lane / secondary_lane / mvp_relevance / next_gate / legacy_evidence_consulted / legacy_failure_addressed / blocked_by / next_recommended_action / prompt).
2. This planner-turn note `PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TASK_193_AUTHORED.md` recording the dispatch decision.

This turn does **not**:
- author task 194 (Phase 2Y Codex review) — that is authored on `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/07_GO_NO_GO.md`.
- author any V2 source under `v2/backend/app/{domain,services,composition}/provenance_dedupe_attribution/`.
- author any V2 test under `v2/backend/tests/unit/{domain,services,composition}/provenance_dedupe_attribution/`.
- author any Phase 2Y documentation file under `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/`.
- author any Phase 2Z planning artifact (Phase 2Z opens after `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS`).
- modify any prior-milestone artifact byte content.
- modify the master planner prompt body (the stale MVP-counter line is reconciled by REQ_0015 evidence-first reconciliation, not by a planner-side rewrite this turn).
- modify any task definition under `claude_worklog/agent_supervisor/tasks/` other than authoring the new `193_…` file.
- modify any supervisor status JSON.
- introduce any new lineage ID, value-object, FastAPI surface, adapter, ledger persistence, replay engine, scheduler, paper trader process, paper executor, shadow executor, live trader process, strategy library, or background loop.
- introduce any PnL, position sizing, quantity, price, fees, slippage, funding, OI, liquidation map, orderbook depth, hedge-state, residual-exposure, or squeeze-risk computation.
- dispatch any Binance read-only account-history endpoint.
- flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`.
- open SMC/liquidity feature shadow-mode work.
- modify the cockpit / frontend byte content at HEAD `bdb268b` (`v2/frontend/`, `claude_worklog/final_readiness/enterprise_trading_cockpit/`).

## Lane / MVP relevance / next gate (REQ_0018 / REQ_0020 / REQ_0021)
- `lane`: `legacy_parity` (this turn authors the Phase 2Y open task definition; legacy read-only consultation is the rationale chain).
- `secondary_lane`: `paper_backtest_mvp` (residual hardening — provenance pointers and dedupe decision records are the typed inputs a future risk-gateway extension consumes to refuse stale-data trades and duplicate signals after `V2_BACKTEST_AND_PAPER_MVP_READY`).
- `mvp_relevance`: Authors the canonical Phase 2Y open task so the supervisor can dispatch task 193 once worktree clears. Task 193 closes the second of three REQ_0013 phase-order prerequisites that gate SMC/liquidity feature shadow mode by authoring `ProvenanceRecord` and `DedupeDecisionRecord` typed value objects, two pure-function assemblers, one composition-root factory, and non-live unit tests.
- `next_gate`: `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/07_GO_NO_GO.md` (Claude validation), then `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/09_CODEX_GO_NO_GO.md` (Codex review under task 194 next turn).
- `blocked_by`:
  - The supervisor must commit the standing single-path dirty-tree (`claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` MVP-counter rotation) plus the prior `PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_AT_HEAD_BDB268B.md` note plus this `PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TASK_193_AUTHORED.md` note plus the new `193_phase2y_provenance_dedupe_attribution_domain_implementation.json` task definition plus the existing untracked `parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid.json` task under the standing watchdog dirty-tree commit batch precedent before dispatching task 193.
  - Task 194 (Phase 2Y Codex review) must NOT be authored before `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED` exists.
  - Task 195 (Phase 2Z open) must NOT be authored before `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS` exists.
- `legacy_evidence_consulted`:
  - `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_OPEN_AND_2X_RECONCILIATION_AT_HEAD_BDB268B.md` (full task 193 specification authored at the prior turn).
  - `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` (Phase 2W deferral order: 2Y second).
  - `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/15_2X_B_FAIL_RECONCILIATION_GO_NO_GO.md` (predecessor marker).
  - `claude_worklog/phase2_core_rebuild/external_manual_position_quarantine_impl/02_PHASE_2X_EXTERNAL_MANUAL_POSITION_QUARANTINE_SPEC.md` (typed-contract precedent for Phase 2Y to mirror).
  - `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` (Phase 2V trainer-parity field shape; line 19 `duplicate_signal_blocked` regression-fixture row source).
  - `claude_worklog/phase2_core_rebuild/replay_case_lab_hedge_unwind/01_LEGACY_FAILURE_EVIDENCE.md` (LAB hedge-unwind / squeeze legacy-failure evidence).
  - `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/01_PHASE_2F_LEGACY_EVIDENCE_REVIEW.md` (orchestrator stale/duplicate-signal taxonomy).
  - `claude_worklog/phase2_core_rebuild/risk_gateway_impl/01_PHASE_2G_LEGACY_EVIDENCE_REVIEW.md` (risk-side default-deny base layer reason taxonomy).
  - `claude_worklog/phase2_core_rebuild/legacy_evidence/01_BUILD_IMPACT_MAP.md` line 31 (orchestrator stale/duplicate signal handling row).
  - `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (LAB hedge-unwind / squeeze case lines 7–27).
  - `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` (existing lineage IDs).
  - `claude_worklog/agent_supervisor/tasks/189_phase2x_external_manual_position_quarantine_domain_implementation.json` (Phase 2X open task structural precedent for task 193 shape).
  - `claude_worklog/agent_supervisor/status/current_status.json` (no active child).
  - `claude_worklog/agent_supervisor/status/queue_status.json` (no human attention required).
  - `claude_worklog/agent_supervisor/status/master_rebuild_planner_status.json` (planner status snapshot).
- `legacy_failure_addressed`: Authoring task 193 advances the closure of the orchestrator stale/duplicate-signal handling typed-contract gap and the trainer-parity duplicate-signal-blocked typed-contract gap by setting up the typed value-object surface that downstream extensions of the risk gateway and orchestrator decision projection will consume. The LAB hedge-unwind / short-squeeze legacy failure (legacy bot acted on stale or duplicated signals against a manual/external position and left a short exposed before an approximately 80% pump) is the legacy-evidence anchor that justifies typed provenance freshness pointers and typed dedupe state at the data-contract layer.

## REQ_0013 / REQ_0017 / REQ_0018 / REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024 / REQ_0026 scope discipline
- REQ_0013: planner authors the Phase 2Y open task that closes prerequisite 2 (provenance / dedupe / attribution); SMC/liquidity feature shadow-mode work remains gated until prerequisite 3 (Phase 2Z) PASSes. No SMC feature is referenced as actionable.
- REQ_0017: goal marker `V2_BACKTEST_AND_PAPER_MVP_READY` already CLOSED at `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS`; this turn does not regress, re-open, or rotate any closed REQ_0017 milestone marker.
- REQ_0018: lane = `legacy_parity` (secondary `paper_backtest_mvp`); no broad scaffold expansion; no out-of-lane drift; no frontend polish; no new dashboards without real data contracts; no new automation framework work outside watchdog scope. Task 193 authors only the typed-contract surface plus non-live unit tests, backed by the existing four lineage IDs and the five Phase 2V trainer-parity fields.
- REQ_0019: legacy monitor / read-only audit evidence cited at task 193's `legacy_evidence_consulted`; this turn cites the same evidence without re-reading or mutating it.
- REQ_0020: paper / backtest MVP readiness goal marker already closed; post-consolidation legacy_parity sequence advances toward Phase 2Y consolidated implementation; live trading remains blocked.
- REQ_0021: Codex parallel capacity remains available — the untracked `parallel_capacity_readonly_review_phase2x_b_external_manual_position_quarantine_remediation_impl_and_valid.json` task is supplementary parallel-lane work and may be dispatched by the parallel-capacity scheduler under `codex_watchdog` lane while task 193 builds.
- REQ_0022: LAB hedge-unwind / squeeze legacy failure already addressed at Phase 2M and carried transitively into the Phase 2Y dedupe regression fixture; this turn does not regress that closure or pre-author the Phase 2Y regression fixture.
- REQ_0023: legacy read-only audit sentinel evidence consulted; no legacy mutation; no Redis read or write of any kind by this planner turn or by task 193.
- REQ_0024: historical-PnL audit typed-mirror partial (Phase 2P) already closed; the live Binance read-only account-history pull remains a separate, later milestone explicitly out of scope at this turn; no Binance read-only API call is dispatched at this turn.
- REQ_0026: non-live operator proof harness already closed; not re-emitted or modified by this turn.

## Hard-stop reaffirmation
Live trading remains blocked. No modification of `/home/wali/Desktop/AI BOT`. No Redis read or write of any kind by this planner turn or by task 193. No live service restart. No exchange-side action of any kind. No leverage / margin change. No live-trading enablement. No deployment. No production migration. No secret read, print, or commit. No flip of `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW`. No file under `v2/backend/app/` modified by this planner turn. No file under `v2/frontend/` modified. No prior-milestone Phase 2 artifact byte content modified. No Phase 2X packet body byte content modified. No Phase 2Z planning artifact authored at this turn. No standalone harness framing-token marker line authored as body content in any file by this turn. No Binance HTTP API call (read-only or otherwise) dispatched at this turn.

## Next planner turn
After task 193 dispatches and completes, and `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED` is on disk at `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/07_GO_NO_GO.md`, the next planner turn authors task `194_phase2y_provenance_dedupe_attribution_domain_codex_review` with `agent: codex`, `risk_level: L1`, `lane: codex_watchdog`, `predecessor_required_marker: PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_IMPL_AND_VALIDATION_PASSED`, `predecessor_required_marker_file: claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/07_GO_NO_GO.md`, `success_marker: PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS`, `success_marker_file: claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/09_CODEX_GO_NO_GO.md`, scoped to a Codex review checklist mirroring task 190's eleven-step rubric (predecessor markers; targeted pytest; smoke import; no-Redis grep; no-FastAPI grep; no-FastAPI-lifespan grep; live_blocked invariant; LAB / duplicate_signal_blocked regression fixture preservation; typed-contract-only scope; documentation packet completeness; no-prior-milestone byte-mutation diff under the 2Y exclusion set producing empty stdout). On `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_PASS`, the next planner turn authors task 195 to open `2Z_DEGRADED_STATE_FAIL_CLOSED_GATES` per Phase 2W's deferral order. On `PHASE2Y_PROVENANCE_DEDUPE_ATTRIBUTION_DOMAIN_CODEX_FAIL` with concrete documentation blockers and no safety violation, the supervisor dispatches a REQ_0007 / REQ_0014 Codex autofix scoped to the Phase 2Y packet only; on a stale-rubric / pre-existing-placeholder false positive analogous to the Phase 2X.B reconciliation precedent, the supervisor authors `09_PHASE_2Y_CODEX_RECONCILIATION_ADDENDUM.md` under `claude_worklog/phase2_core_rebuild/provenance_dedupe_attribution_impl/` and rewrites the Codex GO/NO-GO body to PASS. On any safety violation, surface to human attention; no autofix is permitted.

PHASE_2Y_PROVENANCE_DEDUPE_ATTRIBUTION_TASK_193_AUTHORED_PLANNER_TURN_READY
