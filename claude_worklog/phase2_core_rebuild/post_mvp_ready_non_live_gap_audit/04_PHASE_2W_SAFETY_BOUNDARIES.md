# Phase 2W — Safety Boundaries

## Hard non-live boundaries
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
- Do not invoke any Binance HTTP API or any other live exchange API.
- Do not perform any network call.
- Do not perform any wall-clock read.
- Do not perform any environment-variable read.
- Do not perform any subprocess invocation.
- Do not perform any heavyweight ML import.

## Forbidden actions
- Authoring V2 source under `v2/backend/app/domain/`, `v2/backend/app/services/`, `v2/backend/app/composition/`, `v2/backend/app/adapters/`, `v2/backend/app/cli/`, or `v2/backend/app/proof/`.
- Authoring V2 tests under `v2/backend/tests/`.
- Modifying any prior-milestone artifact byte content under `claude_worklog/phase2_core_rebuild/` outside `post_mvp_ready_non_live_gap_audit/`.
- Modifying `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`.
- Committing the dirty `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` line edit.
- Committing the planner-authored `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2W_OPEN_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` note (operator commits separately).
- Introducing or committing any standalone `END_FILE` marker line in any authored file body.
- Wrapping any required output in markdown fences.

## Forbidden output paths
- `v2/**`
- `claude_worklog/tools/**`
- `claude_worklog/autonomous_control_plane/**`
- `claude_worklog/agent_supervisor/**`
- `claude_worklog/security/**`
- `claude_worklog/requirements_inbox/**`
- `claude_worklog/historical_pnl_audit/**`
- `claude_worklog/legacy_readonly_audit/**`
- `claude_worklog/legacy_runtime_audit/**`
- `claude_worklog/final_readiness/**`
- Any `claude_worklog/phase2_core_rebuild/**` subdirectory other than `post_mvp_ready_non_live_gap_audit/`
- `/home/wali/Desktop/AI BOT/**`
- Any `.env` or secrets file
- Any new lineage-ID definition file beyond `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` and the five Phase 2V trainer-parity fields

## No-execution-side-surface clause (explicit)
Phase 2W introduces no execution-side surface. Specifically: no paper trader process, no paper executor, no shadow trader process, no shadow executor, no live trader process, no replay engine, no scheduler, no background loop, no FastAPI surface, no Redis adapter, no GPU runner, no model-loading subsystem, and no strategy library. The recommended next consolidated milestone (2X per `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md`) inherits the same no-execution-side-surface posture; only typed value objects, a pure-function service layer, a composition-root factory, and non-live unit tests are in scope for 2X.

## No-new-lineage-ID clause (explicit)
Phase 2W introduces no new lineage ID beyond those already present at `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` (`feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`, `risk_decision_id`, `paper_trade_id`, `execution_intent_id`) and the five Phase 2V trainer-parity fields (`model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness` at `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/02_PHASE_2V_TRAINER_LINEAGE_PARITY_FIELDS_SPEC.md` lines 1–46). The 2X recommendation in `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md` mirrors only the existing lineage IDs and adds no new ID.

## Live-gate-stays-blocked-and-human-only clause (explicit)
`FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` (file `claude_worklog/final_readiness/04_GO_NO_GO.md`) remains blocked and human-only by REQ_0020 stop condition `FINAL_LIVE_GATE_REQUIRES_HUMAN_APPROVAL`. Phase 2W does not flip it, does not substitute for it, does not introduce a new live-gate marker, and does not author any artifact under `claude_worklog/final_readiness/`. The 2X recommendation likewise inherits the live-gate-stays-blocked-and-human-only posture; the typed surfaces 2X authors enforce `live_blocked is True` at the value-object layer so any caller constructing a record with `live_blocked == False` fails closed at construction time.

## No-byte-mutation-outside-this-directory clause (explicit)
Phase 2W mutates no byte outside `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/`. The only authored files are the seven required output files at `00_PHASE_2W_SCOPE.md`, `01_PHASE_2W_LEGACY_EVIDENCE_REVIEW.md`, `02_PHASE_2W_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md`, `03_PHASE_2W_NEXT_CONSOLIDATED_MILESTONE_RECOMMENDATION.md`, `04_PHASE_2W_SAFETY_BOUNDARIES.md`, `05_PHASE_2W_GO_NO_GO_REQUEST.md`, `06_PHASE_2W_GO_NO_GO.md`. The dirty `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` line edit and the planner-authored `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/PLANNER_TURN_2W_OPEN_POST_MVP_READY_NON_LIVE_GAP_AUDIT.md` note are explicitly excluded from the Phase 2W commit and from any byte mutation by Phase 2W.

PHASE_2W_SAFETY_BOUNDARIES_READY
