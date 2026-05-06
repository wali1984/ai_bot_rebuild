# Planner Turn — Phase 2H.A Codex FAIL Evidence Reconciliation

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0007_CODEX_AUTOFIX_NON_LIVE_BLOCKERS.md ∩ REQ_0011_PARALLEL_CODEX_REVIEW_AND_AUTOFIX_LANE.md ∩ REQ_0014_CODEX_HUMAN_ATTENTION_AUTONOMOUS_RECOVERY.md ∩ REQ_0015_ENFORCE_CLAUDE_CODE_AND_CODEX_AUTOMATION_GATES.md ∩ REQ_0016_CODEX_NON_LIVE_HUMAN_REPLACEMENT_WATCHDOG.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md ∩ REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md
Lane: codex_watchdog
Profile: Claude Code Max20 consolidated_default
Granularity: single consolidated reconciliation task
Live gate: blocked

## Stale-rubric-premise / committed-evidence divergence detected

The previous planner turn dispatched `134_paper_execution_ledger_2ha_domain_codex_review.json`. Codex completed the review and emitted both `08_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_REVIEW.md` and `09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md`. The 09 marker body records `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_FAIL`.

Inspection of `08_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_REVIEW.md` shows that 48 of 49 rubric rows are PASS with cited evidence, all six pytest suites are green (`paper_execution_ledger 30 passed`, `risk_gateway 32 passed`, `orchestrator_decision 34 passed`, `trainer_prediction_output 31 passed`, `trainer_worker_health 28 passed`, `trainer_liveness 52 passed`), `py_compile` exits 0, the 19-token forbidden-token sweep returns zero matches per token, three fresh-subprocess import-isolation checks exit 0 with no output, the cross-isolation `git status -s` is clean outside the additive 2H.A scope, and the post-emission `git status -s` shows only the 08 and 09 review artifacts.

The single FAIL row is the placeholder verification step: `git ls-files v2/backend/app/domain/execution/` returned three lines (`__init__.py`, `intent.py`, `paper.py`) when the rubric expected zero. The rubric premise is "the 2H.A milestone MUST NOT have populated v2/backend/app/domain/execution/" derived from `02_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_SPEC.md:15` ("The pre-existing empty `v2/backend/app/domain/execution/` directory is NOT modified, NOT used, and NOT renamed by 2H.A").

Committed-evidence reconciliation:

- `git log --diff-filter=A --oneline -- v2/backend/app/domain/execution/` returns exactly one commit: `26e49b7 Materialize 015A V2 repo package skeleton`. The three placeholder files were authored at the 015A scaffold milestone, not by 2H.A.
- `git log --diff-filter=AM --oneline -- v2/backend/app/domain/execution/` returns the same single commit. No commit between `26e49b7` and the 2H.A commits has added or modified any file under `v2/backend/app/domain/execution/`.
- The three placeholder files are docstring-only modules: `__init__.py` is zero bytes; `intent.py` is the single line `"""Execution intent domain placeholder. Pure module."""`; `paper.py` is the single line `"""Paper-execution domain placeholder. Pure module."""`. None contains executable code, no imports, no constants, no FastAPI surface, no Redis dependency, and no live behavior.
- The cross-isolation diff in `08:154-168` shows the post-emission `git status -s` enumerates only `08_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_REVIEW.md` and `09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md`. The 2H.A milestone diff does not touch any file under `v2/backend/app/domain/execution/`.

The spec premise at `02:15` was incomplete: it described the directory as "empty" when in fact it has carried three pre-existing 015A docstring-only placeholders since commit `26e49b7`. The 2H.A milestone honored the spec's behavior contract — it did not modify, use, or rename anything under `v2/backend/app/domain/execution/` — but the rubric translated the incomplete spec premise into a `git ls-files` zero-output expectation that committed evidence cannot satisfy.

Per REQ_0014 / REQ_0015 / REQ_0016 evidence-first reconciliation policy ("GO/NO-GO PASS markers override stale queue/current_status noise; stale tasks become superseded_by_evidence"), the next milestone is to reconcile the stale 09 FAIL marker against the committed 015A pre-existing placeholder evidence and the cross-isolation diff that confirms 2H.A scope-cap compliance. The reconciliation does not retro-author 2H.A artifacts 00–07 and does not modify the placeholder files; it only rewrites the 09 marker, emits a corrected addendum at 10, emits a reconciliation report and GO/NO-GO under `automation_reliability/`, and appends one `EVIDENCE_MARKERS` entry to `claude_worklog/tools/reconcile_evidence_status.py`.

## Lane lock confirmation (REQ_0018)

- `lane`: `codex_watchdog`
- `mvp_relevance`: Reconciliation closes Phase 2H.A and unblocks dispatch of Phase 2H.B (paper execution ledger assembler service). Without this reconciliation, the `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` gate marker is missing and 2H.B cannot open. Phase 2H closes REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP`. The reconciliation is the smallest concrete advance toward `V2_BACKTEST_AND_PAPER_MVP_READY` available right now.
- `next_gate`: `PHASE2H_A_EVIDENCE_RECONCILIATION_PASSED`
- `blocked_by`: harness-managed dirty `claude_master_rebuild_planner_prompt.txt` cleanup by Codex watchdog under REQ_0014 / REQ_0016 / REQ_0007 (excluded from dispatch worktree per supervisor worktree-isolation contract).

REQ_0018 forbids broad infrastructure expansion. This reconciliation does not introduce any new V2 surface; it overwrites one stale marker file, emits two new reconciliation report files, emits one corrected-rubric addendum file, and appends one evidence-marker entry. No source file under `v2/backend/app/domain/paper_execution_ledger/`, `v2/backend/tests/unit/domain/paper_execution_ledger/`, or `v2/backend/app/domain/execution/` is modified.

## Legacy evidence anchor (REQ_0019 / REQ_0020)

The legacy runtime audits at `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` and `11_FAILURE_MODE_AND_GAP_REGISTER.md` describe legacy paper-side recording without typed mirror invariants and without a deterministic cross-check between the rubric the live audit applied to the bot and the actual on-disk state of the bot. The legacy failure addressed by this turn is the absence of a deterministic recovery loop for stale-rubric-vs-committed-evidence drift: under the legacy bot, an audit rubric authored against an idealized assumption could persist a FAIL verdict indefinitely after the underlying assumption was contradicted by the actual file system, leaving downstream gates blocked even though the evidence of correctness was already on disk. The 2H.A reconciliation surface is the V2 proof that committed evidence overrides stale-premise rubric noise.

## Consolidated task emitted this turn

- `claude_worklog/agent_supervisor/tasks/135_paper_execution_ledger_2ha_codex_fail_evidence_reconciliation.json`

The reconciliation work is intentionally consolidated into one Codex dispatch:

1. Verify worktree precondition (clean dispatch worktree under the supervisor's worktree-isolation contract).
2. Verify the 134 review marker file `08_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_REVIEW.md` exists and contains the final marker `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_REVIEW_READY`.
3. Verify the 134 review marker file `09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md` exists and currently contains `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_FAIL`.
4. Verify 015A pre-existing placeholder evidence: `git log --diff-filter=A --oneline -- v2/backend/app/domain/execution/` returns exactly one commit `26e49b7 Materialize 015A V2 repo package skeleton`; `git log --diff-filter=AM --oneline -- v2/backend/app/domain/execution/` returns the same single commit; the three files are exactly `__init__.py`, `intent.py`, and `paper.py` and nothing else; `wc -c v2/backend/app/domain/execution/__init__.py` returns `0`; `intent.py` and `paper.py` each contain exactly one line whose body is a single docstring with no imports.
5. Verify the 2H.A diff does not modify any file under `v2/backend/app/domain/execution/` by running `git log --oneline -- v2/backend/app/domain/execution/` against every commit since `26e49b7` and confirming exactly one entry.
6. Re-run the full validation set against the committed working tree: `py_compile` of the three `paper_execution_ledger` source files, six pytest suites (paper_execution_ledger, risk_gateway, orchestrator_decision, trainer_prediction_output, trainer_worker_health, trainer_liveness), and three fresh-subprocess import-isolation checks. ALL must exit 0 before any marker rewrite.
7. Re-run the 19-token forbidden-token sweep over `v2/backend/app/domain/paper_execution_ledger/` and confirm zero matches per token.
8. Re-run the cross-isolation `git status -s` and confirm zero non-empty lines (the dispatch worktree must be clean except for the harness-managed planner-prompt entry which is excluded).
9. Overwrite `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md` with the single line `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` and trailing newline. No other content.
10. Emit `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md` with the corrected 49-row rubric reading: rows 1–48 PASS as recorded by 134 with citations preserved, row "Placeholder verification" reinterpreted under the 015A pre-existing evidence (placeholder dir was never empty post-`26e49b7`; the rubric expectation that `git ls-files v2/backend/app/domain/execution/` returns zero output is unsatisfiable on the committed tree; the spec premise at `02:15` is incomplete; the 2H.A milestone honored the spec behavior contract by leaving the directory unmodified, which is the contract that actually matters).
11. Emit `claude_worklog/phase2_core_rebuild/automation_reliability/135_2H_A_EVIDENCE_RECONCILIATION_REPORT.md` with: stale-rubric divergence summary, 015A committed-state evidence (the three-file enumeration plus the single git log entry plus the byte counts plus the docstring contents), 2H.A diff isolation evidence (zero modifications to `v2/backend/app/domain/execution/`), validation re-run results (each command with exit 0), forbidden-token sweep results (zero matches per token), cross-isolation diff (zero non-empty lines), marker rewrite summary (one rewrite at 09, one new file at 10), `reconcile_evidence_status.py` append summary (line count delta plus `py_compile` exit 0 plus stdout summary from running the script).
12. Emit `claude_worklog/phase2_core_rebuild/automation_reliability/135_2H_A_EVIDENCE_RECONCILIATION_GO_NO_GO.md` with the single line `PHASE2H_A_EVIDENCE_RECONCILIATION_PASSED` and trailing newline.
13. Append one `EVIDENCE_MARKERS` entry to `claude_worklog/tools/reconcile_evidence_status.py` (insert at the TOP of the list immediately after the opening `[` so it takes precedence in iteration): `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` -> `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md` -> supersedes `134_paper_execution_ledger_2ha_domain_codex_review`. Run `.venv/bin/python -m py_compile claude_worklog/tools/reconcile_evidence_status.py` and capture exit 0.
14. Run `.venv/bin/python claude_worklog/tools/reconcile_evidence_status.py` and capture stdout. The resulting `claude_worklog/agent_supervisor/status/evidence_reconciliation_status.json` MUST contain the new marker under `found_markers` and `134_paper_execution_ledger_2ha_domain_codex_review` under `superseded_tasks`. Do NOT author this status JSON directly; let the script write it.

The dispatch keeps consolidated_default profile: no per-step microsplit. If validation reveals an actual regression in the committed code, the task writes FAILED markers, surfaces to human attention, and a separate REQ_0007 / REQ_0014 autofix task will be opened in the next planner turn.

## Dirty-tree dispatch hold

`git status --porcelain` reports a single dirty file: `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt`. This file is the harness-managed planner prompt path. The planner does NOT modify that file in this turn. Task 135 carries `requires_clean_worktree: true` and the supervisor's worktree-isolation contract excludes the planner-prompt path from the dispatch worktree, so dispatch can proceed once the watchdog has reconciled the dirty entry under REQ_0014 / REQ_0016 / REQ_0007. The planner does not advance dispatch in this turn.

## REQ_0017 scope discipline

The reconciliation introduces zero new V2 surface. No FastAPI route, no Redis access, no composition root, no risk-gateway logic, no execution surface, no model evaluation, no new lineage ID, no PnL or position sizing or quantity or price or fees or slippage, no ledger persistence (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis), no paper executor, no shadow executor, no replay runner, no paper trader process, no service-layer assembler, no composition-root binder, no strategy library, no logic at the value-object layer beyond what is already committed. The only writes are one marker overwrite (09), three new files (10, 135 report, 135 GO/NO-GO), and one deterministic single-entry append to `reconcile_evidence_status.py`. This is the smallest possible advance toward `V2_BACKTEST_AND_PAPER_MVP_READY` consistent with the lane lock.

## Non-live safety

- No `/home/wali/Desktop/AI BOT` mutation.
- No Redis read or write at any layer.
- No live service restart.
- No exchange action.
- No leverage or margin change.
- No live trading enable.
- No deployment.
- No production migration.
- No secret exposure or commit.
- Live gate remains blocked.

## Forbidden in task 135

- Any modification of `v2/backend/app/domain/paper_execution_ledger/` source files.
- Any modification of `v2/backend/tests/unit/domain/paper_execution_ledger/` test files.
- Any modification of any file under `v2/backend/app/domain/execution/` (the 015A placeholders MUST remain byte-for-byte unchanged).
- Any modification of any 2G.A, 2G.B, 2G.C, 2F.A, 2F.B, 2F.C, 2E1, 2E2, or 2E3 source or test file.
- Any modification of any 2H.A planning artifact at 00, 01, 02, 03, 04, 05, 06, 07, or 08 (the 09 overwrite is the single allowed exception).
- Any modification of `v2/backend/app/services/paper_loop.py`.
- Any modification of the master planner prompt.
- Any modification of any task definition under `claude_worklog/agent_supervisor/tasks/`.
- Any rewrite of the `EVIDENCE_MARKERS` list ordering or any non-2H.A entry.
- Any removal of an existing `EVIDENCE_MARKERS` entry.
- Any modification of any def, class, helper function, constant, or import in `reconcile_evidence_status.py` beyond the deterministic single-entry append.
- Any harness BEGIN/END framing-marker leakage in any authored body.
- Any standalone `END_FILE` line in any authored body.

## Next milestone after 2H.A reconciliation closes

When `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` is materialized in `09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md` and `reconcile_evidence_status.py` carries the new entry and `evidence_reconciliation_status.json` lists `134_paper_execution_ledger_2ha_domain_codex_review` as `superseded_by_evidence`, the planner opens Phase 2H.B (paper execution ledger assembler service) under a fresh consolidated milestone turn. 2H.B authors the new package `v2/backend/app/services/paper_execution_ledger/` with a pure `assemble_paper_execution_ledger_entry` function consuming a 2G domain `RiskDecisionRecord` and a `now_ms_clock` callable, with no execution-side mutation, no FastAPI surface, no Redis adapter, no PnL/position sizing, no persistence, and no live behavior. After 2H.B Codex review produces `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`, the planner opens 2H.C (paper execution ledger composition root). After 2H.C composition root closes, REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` is satisfied and milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` opens.

PLANNER_TURN_2H_A_CODEX_FAIL_EVIDENCE_RECONCILIATION_OPEN_READY
