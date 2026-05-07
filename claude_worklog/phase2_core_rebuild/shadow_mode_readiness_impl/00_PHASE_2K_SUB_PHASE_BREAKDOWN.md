# Phase 2K Sub-Phase Breakdown — Shadow-Mode Readiness

Phase 2K implements REQ_0017 milestone 7 `SHADOW_MODE_READINESS`. It is the minimum-viable typed precondition surface that lets every downstream V2 consumer state, in one immutable value object, that the runtime has asserted shadow-mode readiness (i.e. all upstream MVP milestones have produced typed surfaces ready for shadow-mode comparison) and that live execution remains blocked at the V2 live-readiness gate. Phase 2K MUST NOT expand into a shadow trader process, a paper trader process, an execution-side surface, a strategy library, a replay engine, a scheduler, a background loop, a FastAPI surface, a router, a model/GPU/checkpoint subsystem, persistent storage, PnL/sizing/quantity/price/fees/slippage computation, an adapter binding, a credential surface, a `shadow_decision_id` lineage row, or any reconfiguration of the existing 2H paper-execution-ledger, 2I replay/backtest-runner, or 2J paper-mode packages.

Each sub-phase is dispatched only after its predecessor's Codex review PASS marker is materialized. Sub-phases land sequentially. No sub-phase opens out of order.

## 2K.A — Shadow-mode-readiness flag domain (next planner turn opens the planning bundle and dispatch)

- Surface: `v2/backend/app/domain/shadow_mode_readiness/` (NEW package; sibling of `v2/backend/app/domain/paper_mode/`, `v2/backend/app/domain/paper_execution_ledger/`, and `v2/backend/app/domain/replay_backtest_runner/`).
- Files written: `__init__.py`, `errors.py`, `flag.py`.
- Public surface: `ShadowModeReadinessDomainError`, `ShadowModeReadinessFlag`, two state constants `SHADOW_MODE_NOT_READY` and `SHADOW_MODE_READY` (full spec authored in the next planner turn at `02_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_SPEC.md`).
- Default constructor value: `SHADOW_MODE_NOT_READY`. The constant `SHADOW_MODE_READY` exists strictly as the typed name for the readiness-asserted posture so downstream consumers can pattern-match on the value without ever importing a shadow-execution surface; it is not a live-enable affordance and it is not a shadow-decision-record affordance. There is NO `SHADOW_MODE_LIVE`, `SHADOW_MODE_LIVE_ENABLED`, or `live_enabled` constant.
- Invariant: every `ShadowModeReadinessFlag` instance carries `live_blocked: bool = True`. Any attempt to construct a flag with `live_blocked == False` raises `ShadowModeReadinessDomainError`. The flag carries no other field besides the state constant and the live-blocked invariant.
- Tests written: `v2/backend/tests/unit/domain/shadow_mode_readiness/` (one zero-byte `__init__.py` plus the single-test files enumerated in `03_PHASE_2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_TEST_PLAN.md` to be authored in the next planner turn). The test suite is sized in the next planner turn's test plan to mirror the 2J.A 26-single-test-file taxonomy: per-module live-affordance-absence tests, per-constant pattern-match tests, per-error-branch raise tests, per-invariant assertion tests, and a duplicate-constant-rejection test.
- Predecessor marker: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` at `claude_worklog/phase2_core_rebuild/paper_mode_impl/25_2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` (PASS at HEAD 5565c25). The supervisor's predecessor-marker check on tasks 156 and 157 is governed by the file's body content.
- Implementation gate: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`.
- Implementation task: `156` (deferred — emitted in the next planner turn so the task JSON references the committed 02 spec without content drift).
- Codex review task: `157` (deferred — same reason).

## 2K.B — Shadow-mode-readiness flag assembler service (later milestone)

- Surface: `v2/backend/app/services/shadow_mode_readiness/` (NEW package).
- Pure function `assemble_shadow_mode_readiness_flag(*, requested_state: str, now_ms_clock: Callable[[], int]) -> ShadowModeReadinessFlag` that takes the requested state string and a `now_ms_clock` callable, validates the state against the two-element constant set, and returns a frozen `ShadowModeReadinessFlag`. The service does NOT call a model, does NOT touch I/O, does NOT touch Redis, does NOT register any FastAPI surface, does NOT log, does NOT read environment variables, does NOT import any shadow-execution surface, does NOT import any live-execution surface, and does NOT introduce any new lineage ID.
- Mirror taxonomy is exhaustive over exactly two values:
  - requested `not_ready` → `ShadowModeReadinessFlag` with `state == SHADOW_MODE_NOT_READY` and `live_blocked == True`
  - requested `ready` → `ShadowModeReadinessFlag` with `state == SHADOW_MODE_READY` and `live_blocked == True`
- Any unrecognized requested state raises a service error before producing a flag. There is NO `live` or `live_enabled` requested-state branch; that branch remains hard-blocked at the V2 live-readiness gate.
- Predecessor marker: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_CODEX_PASS`.

## 2K.C — Shadow-mode-readiness flag composition root (later milestone)

- Surface: `v2/backend/app/composition/shadow_mode_readiness/` (NEW package).
- Pure binder `build_shadow_mode_readiness_runtime(*, now_ms_clock: Callable[[], int]) -> ShadowModeReadinessRuntime` that captures the static `now_ms_clock` callable at build time and returns a slotted single-call `ShadowModeReadinessRuntime` whose one closure adapts the 2K.B service. No persistence; the runtime returns the value object to its caller.
- Predecessor marker: `PHASE2K_B_SHADOW_MODE_READINESS_FLAG_ASSEMBLER_SERVICE_CODEX_PASS`.

## Domain-placeholder reuse decision

`v2/backend/app/services/paper_loop.py` is a one-line scaffold placeholder docstring file. It is left UNCHANGED by Phase 2K. 2K.B opens with `allowed_output_prefixes` scoped to the new `services/shadow_mode_readiness/` package and an explicit `forbidden_output_paths` entry preventing any modification of `paper_loop.py`. The same posture is used at the composition layer if a similar placeholder exists at the time 2K.C opens.

`v2/backend/app/domain/execution/` remains the read-only empty placeholder it has been since 015A; Phase 2K does NOT populate it, does NOT rename it, and does NOT consume it. The new 2K.A package lives at `v2/backend/app/domain/shadow_mode_readiness/` to make the shadow-mode-readiness boundary explicit.

`v2/backend/app/domain/paper_mode/`, `v2/backend/app/domain/paper_execution_ledger/`, and `v2/backend/app/domain/replay_backtest_runner/` are pre-existing closed-milestone packages. Phase 2K does NOT modify, rename, or consume any file in these packages, and does NOT modify their `__init__.py` exports. Phase 2K does NOT modify the corresponding services or composition packages.

## Sequencing rule

If `157` (Codex review of 2K.A) returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the 2K.A authored files only and does not advance to 2K.B. If `157` returns PASS, the planner opens a new turn to author the 2K.B scope and dispatch its tasks.

## Phase exit (closing Phase 2K → opening V2_BACKTEST_AND_PAPER_MVP_READY consolidation)

Phase 2K closes when the 2K.C composition-root Codex pass marker is materialized at `claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/25_2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_GO_NO_GO.md` with body `PHASE2K_C_SHADOW_MODE_READINESS_FLAG_COMPOSITION_ROOT_CODEX_PASS`. At that point REQ_0017 milestone 7 (`SHADOW_MODE_READINESS`) is satisfied and the planner opens the consolidation turn that authors the `V2_BACKTEST_AND_PAPER_MVP_READY` evidence packet under `claude_worklog/phase2_core_rebuild/v2_backtest_and_paper_mvp_ready/` (NEW directory) summarizing the seven satisfied REQ_0017 milestones and the typed surfaces they produced. No live execution behavior, no shadow trader process, no paper trader process, no strategy library, no replay engine, no scheduler, and no FastAPI surface is opened in between.

## REQ_0018 lane and REQ_0020 MVP relevance

- Lane: `paper_backtest_mvp`.
- MVP relevance: Phase 2K is REQ_0017 milestone 7 of 8 on the path to `V2_BACKTEST_AND_PAPER_MVP_READY`. The 2K.A typed flag is the consumable surface every downstream lineage consumer (`paper_trade_id`, `replay_run`, future `shadow_decision_id`) uses to assert that the runtime has asserted shadow-mode readiness without importing a shadow-execution surface and without re-deriving the readiness posture from environment variables or process-global state. Distance to `V2_BACKTEST_AND_PAPER_MVP_READY` at 2K open: one milestone remains (`SHADOW_MODE_READINESS`).
- Blocked by: `PHASE2J_C_PAPER_MODE_RUNTIME_FLAG_COMPOSITION_ROOT_CODEX_PASS` (PASS at HEAD 5565c25).
- Next gate: `PHASE2K_A_SHADOW_MODE_READINESS_FLAG_DOMAIN_IMPL_AND_VALIDATION_PASSED`.

## REQ_0019 / REQ_0020 / REQ_0022 / REQ_0023 / REQ_0024 legacy mapping

- Legacy evidence consulted: see `01_PHASE_2K_LEGACY_EVIDENCE_REVIEW.md`.
- Legacy behavior preserved: read-only adjudication only. No mutation of `/home/wali/Desktop/AI BOT`. No mutation of any prior-milestone artifact.
- Legacy failure addressed: legacy `monitor_trainer_predictions.py`, `monitor_trainer_prices.py`, `monitor_portfolio_primary.py`, and `monitor_portfolio_asjad.py` inspect runtime state without a typed precondition flag, which made it impossible to assert shadow-mode readiness by typed value and was a contributing factor in the LAB hedge-unwind / squeeze failure (REQ_0022) and in the broader failure-class register where decisions were made on stale or partially-initialized runtime state (REQ_0023, REQ_0024). The 2K.A typed flag introduces a typed boundary that downstream consumers can pattern-match on to refuse any shadow-execution path until shadow-mode readiness is asserted, and to refuse any live-execution path always until the V2 live-readiness gate flips. The default value is `SHADOW_MODE_NOT_READY`; the only other constant is `SHADOW_MODE_READY`; there is NO `SHADOW_MODE_LIVE` or `SHADOW_MODE_LIVE_ENABLED` constant in 2K.A, 2K.B, or 2K.C.
- V2 proof gate: the 2K.A unit tests assert that constructing a `ShadowModeReadinessFlag` with any non-`SHADOW_MODE_NOT_READY` / non-`SHADOW_MODE_READY` value raises `ShadowModeReadinessDomainError`; the 2K.A unit tests assert that constructing a `ShadowModeReadinessFlag` with `live_blocked == False` raises `ShadowModeReadinessDomainError`; the 2K.B service tests assert that any unrecognized requested-state string raises a service error before producing a flag; the 2K.C composition-root tests assert that the slotted runtime exposes a single `shadow_mode_readiness_now` attribute that adapts the 2K.B service unchanged and shares the captured `now_ms_clock` closure.

PHASE2K_SHADOW_MODE_READINESS_PHASE_BREAKDOWN_READY
END_FILE: claude_worklog/phase2_core_rebuild/shadow_mode_readiness_impl/00_PHASE_2K_SUB_PHASE_BREAKDOWN.md
