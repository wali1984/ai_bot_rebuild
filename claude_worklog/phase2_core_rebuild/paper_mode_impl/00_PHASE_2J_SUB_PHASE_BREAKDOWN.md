# Phase 2J Sub-Phase Breakdown — Paper Mode MVP

Phase 2J implements REQ_0017 milestone 6 `PAPER_MODE_MVP`. It is the minimum-viable typed boundary that lets every downstream V2 consumer state, in one immutable value object, that the runtime is operating in paper mode and that live execution remains blocked at the V2 live-readiness gate. Phase 2J MUST NOT expand into a live trader process, a paper trader process, an execution-side surface, a strategy library, a FastAPI surface, a router, a scheduler, a background loop, a model/GPU/checkpoint subsystem, persistent storage, PnL/sizing/quantity/price computation, an adapter binding, a credential surface, or any reconfiguration of the existing 2H paper-execution-ledger or 2I replay/backtest-runner packages.

Each sub-phase is dispatched only after its predecessor's Codex review PASS marker is materialized. Sub-phases land sequentially. No sub-phase opens out of order.

## 2J.A — Paper-mode runtime-flag domain (this opening turn pre-stages the planning bundle only)

- Surface: `v2/backend/app/domain/paper_mode/` (NEW package; sibling of `v2/backend/app/domain/paper_execution_ledger/` and `v2/backend/app/domain/replay_backtest_runner/`).
- Files written: `__init__.py`, `errors.py`, `flag.py`.
- Public surface: `PaperModeDomainError`, `PaperModeFlag`, two mode constants `PAPER_MODE_PAPER` and `PAPER_MODE_LIVE_BLOCKED` (see `02` spec).
- Default constructor value: `PAPER_MODE_PAPER`. The constant `PAPER_MODE_LIVE_BLOCKED` exists strictly as the typed name for the live-blocked posture so downstream consumers can pattern-match on the value without ever importing a live-execution surface; it is not a live-enable affordance.
- Tests written: `v2/backend/tests/unit/domain/paper_mode/` (one zero-byte `__init__.py` plus the single-test files enumerated in `03_PHASE_2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_TEST_PLAN.md`).
- Predecessor marker: `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/replay_backtest_runner_impl/25_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_GO_NO_GO.md`. Reconciliation precedent applies per the 2H.C / 2I.C addendum pattern; an addendum at `26_2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_RECONCILIATION_ADDENDUM.md` may be the artifact that flips the marker body. The 2J.A implementation task MUST NOT dispatch until the marker body reads `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- Implementation gate: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`.
- Implementation task: `150` (deferred — emitted in the post-flip planner turn so the task JSON references the committed spec without content drift).
- Codex review task: `151` (deferred — same reason).

## 2J.B — Paper-mode runtime-flag assembler service (later milestone)

- Surface: `v2/backend/app/services/paper_mode/` (NEW package).
- Pure function `assemble_paper_mode_flag(*, requested_mode: str, now_ms_clock: Callable[[], int]) -> PaperModeFlag` that takes the requested mode string and a `now_ms_clock` callable, validates the mode against the two-element constant set, and returns a frozen `PaperModeFlag`. The service does NOT call a model, does NOT touch I/O, does NOT touch Redis, does NOT register any FastAPI surface, does NOT log, does NOT read environment variables, does NOT import any live-execution surface, and does NOT introduce any new lineage ID.
- Mirror taxonomy is exhaustive over exactly two values:
  - requested `paper` → `PaperModeFlag` with `mode == PAPER_MODE_PAPER` and `live_blocked == True`
  - requested `live_blocked` → `PaperModeFlag` with `mode == PAPER_MODE_LIVE_BLOCKED` and `live_blocked == True`
- Any unrecognized requested mode raises a service error before producing a flag. There is NO `live` or `live_enabled` requested-mode branch; that branch remains hard-blocked at the V2 live-readiness gate.
- Predecessor marker: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_CODEX_PASS`.

## 2J.C — Paper-mode runtime-flag composition root (later milestone)

- Surface: `v2/backend/app/composition/paper_mode/` (NEW package).
- Pure binder `build_paper_mode_runtime(*, now_ms_clock: Callable[[], int]) -> PaperModeRuntime` that captures the static `now_ms_clock` callable at build time and returns a slotted single-call `PaperModeRuntime` whose one closure adapts the 2J.B service. No persistence; the runtime returns the value object to its caller.
- Predecessor marker: `PHASE2J_B_PAPER_MODE_RUNTIME_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.

## Domain-placeholder reuse decision

`v2/backend/app/services/paper_loop.py` is a one-line scaffold placeholder docstring file. It is left UNCHANGED by Phase 2J. 2J.B opens with `allowed_output_prefixes` scoped to the new `services/paper_mode/` package and an explicit `forbidden_output_paths` entry preventing any modification of `paper_loop.py`. The same posture is used at the composition layer if a similar placeholder exists at the time 2J.C opens.

`v2/backend/app/domain/execution/` remains the read-only empty placeholder it has been since 015A; Phase 2J does NOT populate it, does NOT rename it, and does NOT consume it. The new 2J.A package lives at `v2/backend/app/domain/paper_mode/` to make the paper-mode boundary explicit.

## Sequencing rule

If `151` (Codex review of 2J.A) returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the 2J.A authored files only and does not advance to 2J.B. If `151` returns PASS, the planner opens a new turn to author the 2J.B scope and dispatch its tasks.

## Phase exit (closing Phase 2J → opening REQ_0017 milestone 7)

Phase 2J closes when the 2J.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 6 (`PAPER_MODE_MVP`) is satisfied and the planner opens REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`). No live execution behavior, no live trader process, no paper trader process, no strategy library, no replay engine, no scheduler, and no FastAPI surface is opened in between.

## REQ_0018 lane and REQ_0020 MVP relevance

- Lane: `paper_backtest_mvp`.
- MVP relevance: Phase 2J is REQ_0017 milestone 6 of 8 on the path to `V2_BACKTEST_AND_PAPER_MVP_READY`. The 2J.A typed flag is the consumable surface every downstream lineage consumer (`paper_trade_id`, `replay_run`, future `shadow_decision_id`) uses to assert that the runtime is paper-mode without importing a live-execution surface and without re-deriving the live-blocked posture from environment variables. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2J open: two milestones remain (`PAPER_MODE_MVP` and `SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2I_C_REPLAY_BACKTEST_RUNNER_COMPOSITION_ROOT_CODEX_PASS`.
- Next gate: `PHASE2J_A_PAPER_MODE_RUNTIME_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 legacy mapping

- Legacy evidence consulted: see `01_PHASE_2J_LEGACY_EVIDENCE_REVIEW.md`.
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact.
- Legacy failure addressed: legacy `trader.py` and `rl.orchestrator_worker` carried implicit live-mode posture through environment variables and per-call argument passing, which made it impossible to assert the live-blocked posture by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) where the protective-leg close happened in a code path that did not type-check the runtime mode. The 2J.A typed flag introduces a typed boundary that downstream consumers can pattern-match on to refuse any live-execution path until the V2 live-readiness gate flips. The default value is `PAPER_MODE_PAPER`; the only other constant is `PAPER_MODE_LIVE_BLOCKED`; there is NO `live_enabled` constant in 2J.A, 2J.B, or 2J.C.
- V2 proof gate: the 2J.A unit tests assert that constructing a `PaperModeFlag` with any non-paper / non-live-blocked value raises `PaperModeDomainError`; the 2J.B service tests assert that any unrecognized requested-mode string raises a service error before producing a flag; the 2J.C composition-root tests assert that the slotted runtime exposes a single `paper_mode_now` attribute that adapts the 2J.B service unchanged and shares the captured `now_ms_clock` closure.

PHASE2J_PAPER_MODE_MVP_PHASE_BREAKDOWN_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_mode_impl/00_PHASE_2J_SUB_PHASE_BREAKDOWN.md
