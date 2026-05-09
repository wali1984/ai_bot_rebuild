# Phase 2W — Post-MVP-Ready Non-Live Gap Audit Scope

## Date
2026-05-09

## Lane / MVP fields
- Lane: `legacy_parity` (primary, read-only audit) with secondary `codex_watchdog` (Codex review of this audit follows in the next planner turn).
- MVP relevance: closes the residual non-live build chain decision after `V2_BACKTEST_AND_PAPER_MVP_READY` by selecting exactly one consolidated next non-live milestone from the candidate set `{2X_EXTERNAL_MANUAL_POSITION_QUARANTINE, 2Y_PROVENANCE_DEDUPE_ATTRIBUTION, 2Z_DEGRADED_STATE_FAIL_CLOSED_GATES}` on the basis of on-disk evidence rather than ad-hoc opening.
- Aligns with REQ_0020 stop condition `FINAL_LIVE_GATE_REQUIRES_HUMAN_APPROVAL` ("Until then, Codex/Claude must continue non-live build/review/recovery.").

## Audit-only nature of Phase 2W
Phase 2W is a consolidated read-only audit and decision artifact. Phase 2W authors:
- this scope file,
- one structured legacy-evidence-review table,
- one structured post-MVP-ready non-live gap audit table,
- one next-consolidated-milestone recommendation,
- one safety-boundaries enumeration,
- one GO/NO-GO request rubric,
- one single-line GO/NO-GO marker file.

Phase 2W authors no V2 source, no V2 test, no execution-side surface, no new lineage ID, no live-gate flip, and no byte mutation outside `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/`.

## Three candidate consolidated milestones evaluated
- **2X_EXTERNAL_MANUAL_POSITION_QUARANTINE** — REQ_0013 prerequisite 1 (external/manual position quarantine), with a tie-in to REQ_0022 LAB hedge-unwind / squeeze residual exposure. Typed contract + non-live unit tests only. No execution-side surface, no new lineage ID, no live-gate flip.
- **2Y_PROVENANCE_DEDUPE_ATTRIBUTION** — REQ_0013 prerequisite 2 (provenance, dedupe, attribution). Typed contract + non-live unit tests only. No execution-side surface, no new lineage ID, no live-gate flip.
- **2Z_DEGRADED_STATE_FAIL_CLOSED_GATES** — REQ_0013 prerequisite 3 (degraded-state fail-closed gates). Typed contract + non-live unit tests only. No execution-side surface, no new lineage ID, no live-gate flip.

## Explicit non-actions for Phase 2W
- Authors no V2 source under `v2/backend/app/domain/`, `v2/backend/app/services/`, `v2/backend/app/composition/`, `v2/backend/app/adapters/`, `v2/backend/app/cli/`, or `v2/backend/app/proof/`.
- Authors no V2 test under `v2/backend/tests/`.
- Authors no execution-side surface: no paper trader, no shadow trader, no live trader, no replay engine, no scheduler, no background loop, no FastAPI surface, no Redis adapter, no GPU runner, no model-loading subsystem, no strategy library.
- Introduces no new lineage ID beyond those already at `claude_worklog/v2_requirements/03_PREDICTION_SIGNAL_DECISION_ID_CHAIN.md` and the five Phase 2V trainer-parity fields (`model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness`).
- Does not flip `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` or any other live-gate marker; the live-readiness gate remains blocked and human-only.
- Mutates no prior-milestone artifact byte. Touches no file outside `claude_worklog/phase2_core_rebuild/post_mvp_ready_non_live_gap_audit/`.
- Touches no file under `claude_worklog/autonomous_control_plane/`, `claude_worklog/agent_supervisor/`, `claude_worklog/security/`, `claude_worklog/requirements_inbox/`, `claude_worklog/historical_pnl_audit/`, `claude_worklog/legacy_readonly_audit/`, `claude_worklog/legacy_runtime_audit/`, `claude_worklog/final_readiness/`, `claude_worklog/tools/`, or any sibling subdirectory of `claude_worklog/phase2_core_rebuild/`.
- Performs no network call, no wall-clock read, no environment-variable read, no subprocess invocation, and no heavyweight ML import.
- Reads or writes no Redis key, restarts no live service, places or cancels no exchange orders, changes no leverage or margin, enables no live trading, deploys nothing, runs no production migration, exposes or commits no secrets, calls no Binance HTTP API or any other live exchange API, and does not modify `/home/wali/Desktop/AI BOT`.
- Does not open SMC/liquidity feature shadow-mode work (REQ_0013) before prerequisites 1, 2, and 3 are PASS.

## Prerequisites confirmed PASS on disk at Phase 2W open
- `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/205_2E3C_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2E3C_TRAINER_PREDICTION_OUTPUT_COMPOSITION_ROOT_CODEX_PASS` (TRAINER_PREDICTION_OUTPUT_MVP).
- `claude_worklog/phase2_core_rebuild/orchestrator_decision_impl/25_2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2F_C_ORCHESTRATOR_DECISION_COMPOSITION_ROOT_CODEX_PASS` (ORCHESTRATOR_DECISION_MVP).
- `claude_worklog/phase2_core_rebuild/risk_gateway_impl/25_2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS` (RISK_GATEWAY_DEFAULT_DENY_MVP).
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` (PAPER_EXECUTION_LEDGER_MVP).
- `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` (REPLAY_BACKTEST_RUNNER_MVP).
- `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` (PAPER_MODE_MVP).
- `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/25_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` body `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS` (SHADOW_MODE_READINESS).
- `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/06_GO_NO_GO.md` body `V2_BACKTEST_AND_PAPER_MVP_READY` and `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/10_GO_NO_GO_CODEX.md` body `V2_BACKTEST_AND_PAPER_MVP_READY_CODEX_PASS` (consolidation milestone 8).
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/11_CODEX_REREVIEW_AFTER_VENV_PYTEST_GO_NO_GO.md` body `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS` (REQ_0006 Stage A trainer parity output contract closed).

PHASE_2W_SCOPE_READY
