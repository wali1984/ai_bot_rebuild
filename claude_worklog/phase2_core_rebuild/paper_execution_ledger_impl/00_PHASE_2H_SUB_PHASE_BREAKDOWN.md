# Phase 2H Sub-Phase Breakdown — Paper Execution Ledger MVP

Phase 2H implements REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP`. It is the minimum-viable paper-side mirror surface needed to feed `REPLAY_BACKTEST_RUNNER_MVP` (REQ_0017 milestone 5), `PAPER_MODE_MVP` (milestone 6), and `SHADOW_MODE_READINESS` (milestone 7). Phase 2H MUST NOT expand into a paper trader process, a PnL/position-sizing subsystem, an execution-side surface, a FastAPI surface, a strategy library, a replay/backtest runner, any model/GPU/checkpoint subsystem, or any persistent ledger storage.

Each sub-phase is dispatched only after its predecessor's Codex review PASS marker is materialized. Sub-phases land sequentially. No sub-phase opens out of order.

## 2H.A — Paper execution ledger domain (this turn)

- Surface: `v2/backend/app/domain/paper_execution_ledger/`.
- Files written: `__init__.py`, `errors.py`, `record.py`.
- Public surface: `PaperExecutionLedgerDomainError`, `PaperExecutionLedgerEntry`, two ledger-action constants, five ledger-reason constants (see 02 spec).
- Tests written: `v2/backend/tests/unit/domain/paper_execution_ledger/` (30 test files plus a zero-byte `__init__.py`, enumerated in `03_PHASE_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_TEST_PLAN.md`).
- Predecessor marker: `PHASE2G_C_RISK_GATEWAY_COMPOSITION_ROOT_CODEX_PASS`.
- Implementation gate: `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_IMPL_AND_VALIDATION_PASSED`.
- Codex gate: `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`.
- Implementation task: `133`. Codex review task: `134`.

## 2H.B — Paper execution ledger assembler service (later milestone)

- Surface: `v2/backend/app/services/paper_execution_ledger/` (new package).
- Pure function `assemble_paper_execution_ledger_entry(*, risk_decision: RiskDecisionRecord, now_ms_clock: Callable[[], int]) -> PaperExecutionLedgerEntry` that takes a validated `RiskDecisionRecord` and a `now_ms_clock` callable, and returns a frozen `PaperExecutionLedgerEntry`. The function does NOT call a model, does NOT touch I/O, does NOT touch Redis, does NOT compute PnL or position sizing, does NOT carry quantity/price/fees, and does NOT register any FastAPI surface. The mirror taxonomy maps exhaustively:
  - risk action `allow` with reason `allow_proceed_long` → ledger-action `record_allow` / reason `mirror_allow_proceed_long`
  - risk action `allow` with reason `allow_proceed_short` → ledger-action `record_allow` / reason `mirror_allow_proceed_short`
  - risk action `deny` with reason `deny_orchestrator_held` → ledger-action `record_deny` / reason `mirror_deny_orchestrator_held`
  - risk action `deny` with reason `deny_orchestrator_abstained` → ledger-action `record_deny` / reason `mirror_deny_orchestrator_abstained`
  - risk action `deny` with reason `deny_default` → ledger-action `record_deny` / reason `mirror_deny_default`
- The `paper_trade_id` format and the `paper_trade_id` derivation from `risk_decision_id` are decided by 2H.B. 2H.A only validates the resulting string.
- 2H.B is mirror-only by construction: there are exactly five exhaustive branches and any unrecognized risk-action / risk-reason pair raises a service error before producing an entry. The new lineage ID `paper_trade_id` is the canonical identifier consumed by 2H.C and by the future REQ_0017 milestone 5 replay/backtest runner.
- Predecessor marker: `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`.
- Implementation task: future. Codex review task: future.

### Services-layer naming-collision concern

`v2/backend/app/services/paper_loop.py` is a one-line placeholder docstring file. Creating a new `v2/backend/app/services/paper_execution_ledger/` package does NOT collide with that file (different identifier). 2H.A does NOT modify the placeholder. 2H.B opens with allowed_output_prefixes scoped to the new package only and an explicit `forbidden_output_paths` entry preventing any modification of `paper_loop.py`. The same posture is used at the composition layer if a similar placeholder exists at the time 2H.C opens.

The pre-existing empty `v2/backend/app/domain/execution/` directory is separately read-only and is NOT modified, NOT renamed, and NOT used by Phase 2H. The new domain package lives at `v2/backend/app/domain/paper_execution_ledger/` to make the paper/ledger boundary explicit and to leave room for a future live-side execution surface (which remains hard-blocked at the V2 live-readiness gate).

## 2H.C — Paper execution ledger composition root (later milestone)

- Surface: `v2/backend/app/composition/paper_execution_ledger/` (new package).
- Pure binder `build_paper_execution_ledger_recorder(*, now_ms_clock: Callable[[], int]) -> PaperExecutionLedgerRecorder` that captures the static `now_ms_clock` callable at build time and returns a single-call recorder that adapts the 2H.B service. No persistence; the recorder returns the entry to its caller.
- Predecessor marker: `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS`.
- Implementation task: future. Codex review task: future.

## Sequencing rule

If `134` (Codex review of 2H.A) returns FAIL with concrete blockers and no safety violation, the planner enqueues a remediation autofix task under REQ_0007 / REQ_0014 scoped to the 2H.A authored files only and does not advance to 2H.B. If `134` returns PASS, the planner opens a new turn to author the 2H.B scope and dispatch its tasks.

## Phase exit (closing Phase 2H → opening REQ_0017 milestone 5)

Phase 2H closes when the 2H.C composition-root Codex pass marker is materialized. At that point REQ_0017 milestone 4 (`PAPER_EXECUTION_LEDGER_MVP`) is satisfied and the planner opens REQ_0017 milestone 5 (`REPLAY_BACKTEST_RUNNER_MVP`). No live execution behavior, no paper trader process, and no strategy library is opened in between.

PHASE2H_PAPER_EXECUTION_LEDGER_MVP_PHASE_BREAKDOWN_READY
END_FILE: claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/00_PHASE_2H_SUB_PHASE_BREAKDOWN.md
