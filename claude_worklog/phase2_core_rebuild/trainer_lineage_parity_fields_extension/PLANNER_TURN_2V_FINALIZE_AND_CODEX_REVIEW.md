# Planner Turn 2V — Finalize Phase 2V Trainer Lineage Parity Fields Extension and Open Codex Review

## Date
2026-05-09

## HEAD
73f25cf Add Phase 2V trainer lineage parity task packet

## Context — what task 185 actually accomplished and what is still open

Task `185_phase2v_trainer_lineage_parity_fields_extension_implementation` ran to `status: completed` in the supervisor (`start_time 2026-05-09T19:26:37Z`, `end_time 2026-05-09T19:46:15Z`) and materialized the six required output files via BEGIN_FILE blocks:

- `v2/backend/app/proof/non_live_operational_proof.py` — `ProofScenario` extended with the five trainer parity fields (`model_version`, `checkpoint_id`, `confidence_raw`, `confidence_calibrated`, `trainer_worker_liveness`); `_base_lineage` emits them on every projection row; existing `confidence` field preserved as the `confidence_calibrated` alias; `GENERATED_AT` literal preserved.
- `claude_worklog/tools/build_autonomous_live_readiness_builder.py` — `build_trainer_gate` reworked to read the five parity fields from `decision_explainability_result.json`, with an in-memory `build_non_live_proof()` fallback; `_trainer_report` updated with success-path reason text and marker line.
- `v2/backend/tests/unit/proof/test_non_live_operational_proof_artifacts.py` — `test_required_lineage_fields_are_present` extended to require the five new fields on every scenario row.
- `v2/backend/tests/unit/proof/test_trainer_lineage_parity_fields_coverage.py` (new) — three deterministic tests using `importlib.util` and only `TRAINER` / `PUBLIC_TRAINER` overrides per Step 4 of the spec.
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/06_IMPLEMENTATION_REPORT.md` — implementation report.
- `claude_worklog/phase2_core_rebuild/trainer_lineage_parity_fields_extension/07_GO_NO_GO.md` — milestone gate.

But the supervisor run record shows `auto_commit.attempted: false`, the worktree is dirty with the seven Phase 2V artifacts, and three concrete loose ends remain:

1. `06_IMPLEMENTATION_REPORT.md` and `07_GO_NO_GO.md` were emitted with markdown fence leakage from the BEGIN_FILE materialization — `06` opens with a `` ```markdown `` line and ends with a closing `` ``` `` line; `07` has the marker followed by a stray `` ``` `` line. `07_GO_NO_GO.md` must be exactly one marker line so that operator marker scans (`sed -n '1p'`) succeed.
2. Step 5 (run `PYTHONPATH=. python3 -m pytest v2/backend/tests/unit/proof -q`) and Step 6 (run `PYTHONPATH=. python3 claude_worklog/tools/build_autonomous_live_readiness_builder.py`) of the 185 prompt did not execute — the implementation report itself states "Edit/Bash were sandboxed to deny in this turn, so pytest and the builder must be executed by the harness/operator after materialization".
3. As a direct consequence, `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md` and `v2/frontend/public/trainer_lineage_and_readiness/latest/GO_NO_GO.md` still contain `TRAINER_LINEAGE_AND_READINESS_BLOCKED` and `trainer_lineage_coverage.json` still lists the five parity fields under `gaps`. The marker flip the milestone exists to deliver has not yet landed on disk.

## Why this is the next safe non-live milestone

Per the planner profile (`Claude Code Max20 consolidated default`, `task_granularity_mode: consolidated_default`), per REQ_0007 (`Codex autofix non-live blockers`), REQ_0010 (`safe path remap autorecovery` — markdown fence leakage on a milestone GO_NO_GO is a known recoverable safe-remap class), REQ_0014 (`Codex autonomous recovery for non-live human attention`), REQ_0016 (`Codex non-live human-replacement watchdog`), REQ_0021 (`parallel capacity scheduler` — Claude child inactive + git dirty → Codex must classify, recover, validate, commit), and REQ_0025 (`Codex high-utilization review queue`), the safe next consolidated step is to dispatch Codex in the `codex_watchdog` lane to finalize Phase 2V end-to-end in a single task: strip the fence leakage on `06` and `07`, run pytest, run the builder, verify the marker flip on both the runtime and frontend mirrors, perform the adversarial Codex review the original 185 plan called for at `186`, and emit the Codex review artifacts.

Splitting fence-cleanup, marker flip, and Codex review into three serial tasks would micro-split a recovery without precedent and would consume three dispatch cycles where one suffices. Per the planner prompt rule "Use consolidated milestone tasks by default; keep split-task fallback for recovery only", the targeted recovery is exactly the one consolidated Codex task below.

This work also satisfies Lane A (`paper_backtest_mvp`) MVP relevance: flipping `TRAINER_LINEAGE_AND_READINESS_BLOCKED → READY` is the only remaining `BLOCKED` final-readiness marker per `PLANNER_TURN_2V_OPEN_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION.md`, and unblocks the live-gate review's prediction-lineage evidence chain that downstream `REPLAY_BACKTEST_RUNNER_MVP`, `PAPER_MODE_MVP`, and `SHADOW_MODE_READINESS` consume.

## Decision

Open task `186_phase2v_codex_finalize_and_review` as a single consolidated Codex watchdog finalization + adversarial review task in the `codex_watchdog` lane:

- Codex strips the markdown fence leakage from `06_IMPLEMENTATION_REPORT.md` (delete the leading `` ```markdown `` line and trailing `` ``` `` line if present) and rewrites `07_GO_NO_GO.md` to exactly one line: `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_READY_FOR_CODEX_REVIEW` followed by a single trailing newline.
- Codex runs `PYTHONPATH=. python3 -m pytest v2/backend/tests/unit/proof -q` and confirms 18 tests pass.
- Codex runs `PYTHONPATH=. python3 claude_worklog/tools/build_autonomous_live_readiness_builder.py` and confirms stdout includes `TRAINER_LINEAGE_AND_READINESS_READY` and the runtime + frontend mirrors regenerate.
- Codex verifies `claude_worklog/final_readiness/trainer_lineage_and_readiness/latest/GO_NO_GO.md` and `v2/frontend/public/trainer_lineage_and_readiness/latest/GO_NO_GO.md` contain exactly `TRAINER_LINEAGE_AND_READINESS_READY`, that the corresponding `trainer_lineage_coverage.json` carries `marker: "TRAINER_LINEAGE_AND_READINESS_READY"`, `gaps: []`, and `coverage[<five parity fields>] == true`, and that `live_gate_status: "blocked_human_only"` and `live_ready: false` are preserved.
- Codex performs the adversarial review of the Phase 2V implementation: ProofScenario field shape, `_base_lineage` emission completeness across all five projections (`replay_backtest_result.scenarios`, `paper_ledger_result.events`, `risk_gateway_result.decisions`, `decision_explainability_result.explanations`, `shadow_comparison_result.comparisons`), `confidence` alias preservation, builder coverage logic, fallback path safety, no new imports inside the proof module, no wall-clock / file I/O / network / env-var helpers inside the proof module, no `mock`/`patch`/`monkeypatch` in the new test, `GENERATED_AT` and `live_gate_status` strings unchanged, no execution-side surface, no new lineage IDs beyond the five named fields, and no live/Redis/legacy/exchange/deploy/secret behavior.
- Codex emits `08_CODEX_REVIEW.md` (review report) and `09_CODEX_GO_NO_GO.md` (single line: `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS` or `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_FAIL`).
- Codex commits the cleaned `06`/`07`, the four runtime mirror files, the three frontend mirror files, the new `08`/`09` files, and the four already-dirty implementation files (`non_live_operational_proof.py`, `build_autonomous_live_readiness_builder.py`, the two test files) as a single commit. The dirty `claude_master_rebuild_planner_prompt.txt` and `build_autonomous_live_readiness_builder.py` already-staged-by-185 lines remain in scope.

## Lane / MVP fields

- `lane`: `codex_watchdog`
- `mvp_relevance`: Closes the only remaining `BLOCKED` final-readiness marker (`TRAINER_LINEAGE_AND_READINESS`) so the live-gate review's prediction-lineage evidence chain is complete; unblocks the next paper-backtest milestone `REPLAY_BACKTEST_RUNNER_MVP`; is the targeted single-task recovery for the post-185 dirty tree per consolidated_default mode.
- `blocked_by`: dirty Phase 2V worktree with markdown fence leakage on `06`/`07`, missing pytest run, missing builder run, unflipped `TRAINER_LINEAGE_AND_READINESS_BLOCKED` marker on disk and frontend mirror, missing Codex review artifacts.
- `next_gate`: `PHASE2V_TRAINER_LINEAGE_PARITY_FIELDS_EXTENSION_CODEX_PASS`.

## Hard non-live boundaries reaffirmed

- Do not modify `/home/wali/Desktop/AI BOT`.
- Do not read or write any Redis key.
- Do not restart any live service.
- Do not place or cancel exchange orders.
- Do not change leverage or margin.
- Do not enable live trading.
- Do not deploy.
- Do not run production migrations.
- Do not expose or commit secrets.
- Do not flip the final live-readiness gate (`FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains the operator-only live gate).
- Final live approval remains human-only.

PHASE_2V_FINALIZE_AND_CODEX_REVIEW_OPEN
