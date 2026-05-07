# Planner Turn — Phase 2H.C Codex Marker Reconciliation Flip Open + Phase 2I.A Pre-Staging

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0007_CODEX_AUTOFIX_NON_LIVE_BLOCKERS.md ∩ REQ_0011_PARALLEL_CODEX_REVIEW_AND_AUTOFIX_LANE.md ∩ REQ_0014_CODEX_HUMAN_ATTENTION_AUTONOMOUS_RECOVERY.md ∩ REQ_0015_ENFORCE_CLAUDE_CODE_AND_CODEX_AUTOMATION_GATES.md ∩ REQ_0016_CODEX_NON_LIVE_HUMAN_REPLACEMENT_WATCHDOG.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0019_LEGACY_MONITOR_AUDIT_EVIDENCE_IN_BUILD.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md ∩ REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md
Lane: codex_watchdog (this turn) → paper_backtest_mvp (queued behind)
Profile: Claude Code Max20 consolidated_default
Granularity: one consolidated marker reconciliation flip task already emitted (145); two consolidated 2I.A tasks already emitted (143, 144); zero new task definitions authored in this turn.
Live gate: blocked
Distance to V2_BACKTEST_AND_PAPER_MVP_READY: 4 milestones remaining (REPLAY_BACKTEST_RUNNER_MVP next, then PAPER_MODE_MVP, then SHADOW_MODE_READINESS, then the goal marker).

## Phase 2H.C closure record (composition root)

The Phase 2H.C composition root milestone closed logically across the following on-disk artifacts under `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`:

| File | Marker | Verdict |
|---|---|---|
| 20_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SPEC_READY | spec emitted |
| 21_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES_READY | safety boundaries emitted |
| 22_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_TEST_PLAN.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_TEST_PLAN_READY | test plan emitted |
| 23_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_GO_NO_GO_REQUEST.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_GO_NO_GO_REQUEST_READY | go/no-go request emitted |
| 24_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_GO_NO_GO.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_IMPL_AND_VALIDATION_PASSED | implementation/validation PASS |
| 25_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_REVIEW.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_REVIEW_READY | 51 PASS rows + 1 stale-rubric FAIL row (row 50) |
| 26_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_FAIL | stale single-line marker pending watchdog flip |
| 27_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md | PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM_READY | reconciled verdict PASS |

## Stale-rubric / committed-evidence divergence at row 50

The single FAIL row in file 25 is the placeholder verification expectation that `git ls-files v2/backend/app/domain/execution/` returns zero output lines. The committed working tree returns three lines: `__init__.py`, `intent.py`, and `paper.py`. These three files are pre-existing 015A scaffold placeholders authored at commit `26e49b7 Materialize 015A V2 repo package skeleton`, which file 27 cites with full evidence at lines 19–47:

- `git log --diff-filter=A --oneline -- v2/backend/app/domain/execution/` returns exactly one commit (`26e49b7`).
- `git log --diff-filter=AM --oneline -- v2/backend/app/domain/execution/` returns the same single commit.
- `git diff 26e49b7..HEAD -- v2/backend/app/domain/execution/` returns zero output lines.
- `__init__.py` is zero bytes; `intent.py` is one docstring line `"""Execution intent domain placeholder. Pure module."""`; `paper.py` is one docstring line `"""Paper-execution domain placeholder. Pure module."""`.
- The 2H.C cross-isolation safety boundary at `21_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md:34` forbids any byte change under `v2/backend/app/domain/`, so the 2H.C milestone could not have removed these placeholder files even if doing so were desired.

The divergence is the same stale-rubric premise that occurred in 2H.A (resolved by `10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md`) and in 2H.B (resolved by `19_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_RECONCILIATION_ADDENDUM.md`). The rubric translated an idealized "directory must be empty" premise into a `git ls-files` zero-output expectation that committed evidence cannot satisfy. The 2H.C milestone honored the operative behavior contract (do not modify, use, or rename anything under `v2/backend/app/domain/execution/`) and committed-evidence reconciliation overrides the stale-rubric FAIL line per REQ_0014 / REQ_0015 / REQ_0016 evidence-first reconciliation policy.

## Reconciliation pattern selected: addendum + watchdog marker flip

Phase 2H.A used a single-task reconciliation that both rewrote the 09 marker and emitted the 10 addendum in one Codex dispatch. Phase 2H.B and 2H.C use the two-step pattern: reconciliation addendum first (file 27 already READY with PASS verdict), then a separate minimum-blast-radius watchdog flip task that overwrites file 26 with the single-line PASS marker and emits a separate evidence document at file 28. The two-step pattern preserves the audit chain across reviewer/watchdog roles and keeps the marker flip as a single one-line file overwrite with no other authored content.

## This-turn dispatch decision

Task 145 `claude_worklog/agent_supervisor/tasks/145_paper_execution_ledger_2hc_codex_marker_reconciliation_flip.json` is the immediate next dispatch. The task is already authored, its predecessor marker (`PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM_READY` at file 27) is already on disk, and its sole behavior is to:

1. Re-verify the worktree precondition under the supervisor's worktree-isolation contract.
2. Re-verify the four reconciliation basis preconditions (files 24, 25, 26, 27 contents) and the two precedent-addendum existences (files 10 and 19).
3. Re-verify the six placeholder-integrity commands (`git ls-files` / `git diff --stat` / `git diff 26e49b7..HEAD` over `v2/backend/app/domain/execution/`, `v2/backend/app/domain/paper_execution_ledger/`, `v2/backend/app/composition/paper_execution_ledger/`, and the absence of any `v2/backend/app/composition/paper_execution_ledger.py` flat-file placeholder).
4. Re-run 18 pytest suites covering paper_execution_ledger composition + service + domain, risk_gateway composition + service + domain, orchestrator_decision composition + service + domain, trainer_prediction_output composition + service + domain, trainer_worker_health composition + service + domain, trainer_parity composition + service, and trainer_liveness domain.
5. Re-run the safety-boundary forbidden-token sweep over `v2/backend/app/composition/paper_execution_ledger/` per `21_PHASE_2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_SAFETY_BOUNDARIES.md` lines 86–114, with each token reconstructed at runtime via string concatenation so the evidence document at file 28 does not carry the bare token literals.
6. Only on full success of every preceding verification, perform exactly one mutation: overwrite file 26 with the literal 56-byte body `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` plus a single trailing newline.
7. Emit file 28 (the watchdog evidence document) with the section structure mandated by the task definition and the final marker `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_MARKER_RECONCILIATION_FLIP_READY`.

The flip authority is REQ_0007 + REQ_0014 + REQ_0015 + REQ_0016 + REQ_0021 acting on the formally emitted reconciliation addendum at file 27 plus the identical 2H.A and 2H.B precedents at files 10 and 19.

## Lane lock confirmation (REQ_0018 / REQ_0021)

- `lane`: `codex_watchdog`
- `mvp_relevance`: removes the sole remaining gate (file 26 stale FAIL line) blocking dispatch of tasks 143 and 144. Task 143 implements the Phase 2I.A replay/backtest runner domain value-object surface that opens REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP`. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` reduces from 4 milestones to 3 once Phase 2I.A closes.
- `next_gate`: `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`
- `blocked_by`: harness-managed dirty `claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` excluded from the dispatch worktree by the supervisor's worktree-isolation contract; durable Lane C parallel-capacity readonly-review marker files under `claude_worklog/agent_supervisor/tasks/` excluded by the same contract.

REQ_0018 forbids broad infrastructure expansion. This turn introduces zero new V2 surface, zero new task definitions, zero new specs, and zero new test plans. The only on-disk effect is one PLANNER_TURN document under `claude_worklog/autonomous_control_plane/`, and Codex's subsequent flip task will write only file 26 (one-line overwrite) and file 28 (one new evidence document).

## Phase 2I.A pre-staging (next consolidated milestone, paper_backtest_mvp lane)

Tasks 143 and 144 are already authored under `claude_worklog/agent_supervisor/tasks/`:

- `143_replay_backtest_runner_2ia_domain_implementation.json` (Codex implementation of the 2I.A domain value-object surface).
- `144_replay_backtest_runner_2ia_domain_codex_review.json` (Codex review of the 2I.A authored output).

Both carry `predecessor_required_marker: PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS` at file 26. They will become dispatchable on the supervisor's next clean-worktree cycle once task 145 has flipped file 26.

The 2I.A planning artifacts under `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/` (files 00–05: sub-phase breakdown, legacy evidence review, domain spec, domain test plan, domain safety boundaries, domain go-no-go request) have been emitted in prior turns and remain frozen for the implementation pass; file 23 of the 2H_C predecessor chain confirms that 2I.A scope was pre-planned for activation immediately after the 2H.C codex pass marker materializes.

The 2I.A authored surface is exactly five source files plus one `__init__.py` plus 51 single-test files plus two report files (06 implementation report and 07 GO/NO-GO):

- `v2/backend/app/domain/replay_backtest_runner/__init__.py` re-exports the 13-name public surface.
- `v2/backend/app/domain/replay_backtest_runner/errors.py` defines `ReplayBacktestRunnerDomainError(ValueError)`.
- `v2/backend/app/domain/replay_backtest_runner/run.py` defines `RUN_MODE_REPLAY`, `RUN_MODE_BACKTEST`, `_ALLOWED_RUN_MODES`, and the `ReplayBacktestRun` dataclass with the live_blocked == True invariant.
- `v2/backend/app/domain/replay_backtest_runner/step.py` defines the two step-action constants, the five step-reason mirror constants, the four allowed frozensets, and the `ReplayBacktestStep` dataclass with cross-field invariants and the live_blocked == True invariant.
- `v2/backend/app/domain/replay_backtest_runner/summary.py` defines the `ReplayBacktestSummary` dataclass with three partition-sum equalities and the live_blocked == True invariant.

Task 143 forbids any modification of `v2/backend/app/services/replay_runner.py` (the 015A placeholder must remain unchanged), any population of `v2/backend/app/domain/replay/` or `v2/backend/app/domain/execution/`, any flat-file `v2/backend/app/domain/replay_backtest_runner.py` placeholder introduction, any ledger persistence introduction, any PnL / position sizing / quantity / price / fees / slippage / risk-adjusted-return computation, any replay engine / scheduler / background loop / paper trader process / paper executor / shadow executor / strategy library introduction, and any modification of any 2H.A / 2H.B / 2H.C artifact or any 2I.A planning artifact at 00–05.

Task 144 (Phase 2I.A codex review) carries `requires_clean_worktree: true`, the same worktree-isolation exclusions, and a 49-row rubric covering value-object public surface, frozen invariants, partition-sum equalities, mirror prefix discipline, cross-isolation `git status -s`, the same six placeholder-integrity verifications used by task 145, the full prior-milestone pytest regression set including the new 2I.A suite, the safety-boundary forbidden-token sweep over `v2/backend/app/domain/replay_backtest_runner/`, and the same reconciliation contract for any 015A pre-existing-placeholder rubric divergence (resolution will follow the 2H.A / 2H.B / 2H.C addendum + watchdog flip pattern if needed).

## Legacy evidence anchor (REQ_0019 / REQ_0020)

`claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`, `06_TRAINER_RUNTIME_EVIDENCE.md`, `07_ORCHESTRATOR_TRADER_RUNTIME_EVIDENCE.md`, `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`, `10_RISK_AND_SAFETY_RUNTIME_AUDIT.md`, and `11_FAILURE_MODE_AND_GAP_REGISTER.md`, together with the failure-case register at `claude_worklog/legacy_readonly_audit/08_FAILURE_CASE_REGISTER.md` (notably the LAB hedge-unwind / squeeze case from REQ_0022), establish that the legacy replay/backtest tooling lacked typed lineage value objects, partition-sum aggregate invariants, typed mode discrimination (replay vs backtest), and a hard-locked live-blocked invariant. Aggregate counters drifted silently, replay-anchored decision-explainability could not be reconstructed for LAB-class scenarios, and downstream tooling could interpret a replay summary as a tradable instruction.

The 2I.A value-object surface fixes these gaps at the type level by carrying every lineage identifier from `replay_step_id` back through `paper_trade_id` to `feature_snapshot_id`, enforcing the mirror prefix discipline at the step level, enforcing three partition-sum equalities at the summary level, and enforcing `live_blocked == True` on every value object. The 2I.A surface is the consumable interface for the upcoming 2I.B assembler service, 2I.C composition root, REQ_0017 milestone 6 `PAPER_MODE_MVP`, and REQ_0017 milestone 7 `SHADOW_MODE_READINESS`.

The 2H.C closure itself fixes a different legacy failure: legacy automation routinely stalled when a Codex GO/NO-GO marker file recorded a FAIL verdict that was subsequently adjudicated to PASS by a formally emitted reconciliation addendum, but no scheduler-reachable mechanism flipped the marker line itself. The watchdog marker flip pattern (precedented at 2H.A and 2H.B) discharges that human-attention burden by performing exactly one minimum-blast-radius single-line file overwrite when (and only when) every reconciliation precondition is independently re-verified, and emits a separate evidence document so the audit chain remains complete.

## Hard safety review

- No `/home/wali/Desktop/AI BOT` mutation in this turn or in tasks 145, 143, 144.
- No `red`+`is` read or write at any layer in this turn or in tasks 145, 143, 144.
- No `red`+`is` command in this turn or in tasks 145, 143, 144.
- No live service restart in this turn or in tasks 145, 143, 144.
- No exchange action in this turn or in tasks 145, 143, 144.
- No leverage or margin change in this turn or in tasks 145, 143, 144.
- No live-trading enablement in this turn or in tasks 145, 143, 144.
- No deployment in this turn or in tasks 145, 143, 144.
- No production migration in this turn or in tasks 145, 143, 144.
- No secret exposure or commit in this turn or in tasks 145, 143, 144.
- Live gate remains BLOCKED.

## Output policy compliance (REQ_0007 / REQ_0014 / REQ_0015 / REQ_0016 / REQ_0021)

This planner turn writes exactly one BEGIN_FILE / END_FILE block, all under `claude_worklog/autonomous_control_plane/`, all inside `/home/wali/Desktop/AI BOT REBUILD/`, with no secret values, no `red`+`is` token leakage outside this annotated reference, no harness BEGIN/END framing-marker leakage in any authored body, no standalone END_FILE line in any authored body, and no mutation of any v2/ source or test file, any task definition, any prior-milestone artifact under `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` files 00–27, any 2I.A planning artifact under `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/` files 00–05, or the master planner prompt.

## Next-cycle dispatch sequence

1. Supervisor dispatches task 145 on the next clean-worktree cycle. Task 145 emits file 28 with marker `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_MARKER_RECONCILIATION_FLIP_READY` and overwrites file 26 to read `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`. On any FAIL evidence at file 28 with file 26 unchanged, surface to human attention; the planner re-evaluates whether the 27 reconciliation addendum requires amendment.
2. On task 145 PASS, the supervisor's evidence-reconciliation pass appends the new evidence marker to the canonical list (precedented by the 2H.A / 2H.B reconciliation entries already present in `claude_worklog/tools/reconcile_evidence_status.py`) so any superseded fail-marker recovery tasks under `claude_worklog/agent_supervisor/tasks/codex_recover_fail_marker_*` for file 26 are flagged superseded_by_evidence.
3. Supervisor dispatches task 143 on the next clean-worktree cycle. Task 143 authors the five source files plus the 52-test directory plus files 06 and 07 under `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/`. On `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_PASSED` at file 07, supervisor dispatches task 144. On `PHASE2I_A_REPLAY_BACKTEST_RUNNER_DOMAIN_IMPL_AND_VALIDATION_FAILED`, supervisor dispatches a REQ_0007 / REQ_0014 autofix task scoped to the five authored source files plus the 51 new test files only and re-runs the implementation flow.
4. On task 144 PASS, the planner opens Phase 2I.B (replay/backtest runner assembler service) under a fresh consolidated milestone turn modeled after `PLANNER_TURN_2H_B_OPEN_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE.md`. Phase 2I.B authors the new package `v2/backend/app/services/replay_backtest_runner/` with pure assembler functions consuming 2H paper-execution-ledger entries and 2I.A value objects, with no execution-side mutation, no FastAPI surface, no Redis adapter, no PnL/position sizing, no persistence, and no live behavior. After 2I.B Codex review produces `PHASE2I_B_REPLAY_BACKTEST_RUNNER_ASSEMBLER_SERVICE_CODEX_PASS`, the planner opens 2I.C (replay/backtest runner composition root). After 2I.C composition root closes, REQ_0017 milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` is satisfied and milestone 6 `PAPER_MODE_MVP` opens.
5. The MVP path remains: TRAINER_PREDICTION_OUTPUT_MVP (closed) → ORCHESTRATOR_DECISION_MVP (closed) → RISK_GATEWAY_DEFAULT_DENY_MVP (closed) → PAPER_EXECUTION_LEDGER_MVP (closing on file 26 flip) → REPLAY_BACKTEST_RUNNER_MVP (next, opens on task 145 PASS) → PAPER_MODE_MVP → SHADOW_MODE_READINESS → V2_BACKTEST_AND_PAPER_MVP_READY.

## REQ_0017 scope discipline

This turn introduces zero new V2 surface, zero new specs, zero new test plans, zero new safety boundaries, zero new go-no-go requests, zero new task definitions, zero new evidence-marker entries, and zero new automation tooling. The on-disk effect is exactly one new PLANNER_TURN document under `claude_worklog/autonomous_control_plane/`. Tasks 145, 143, and 144 were authored in prior turns; this turn opens the dispatch decision and pre-stages the consecutive milestone, which is the smallest possible advance toward `V2_BACKTEST_AND_PAPER_MVP_READY` consistent with the lane lock and consolidated_default profile.

PLANNER_TURN_2H_C_CODEX_MARKER_RECONCILIATION_FLIP_OPEN_READY
