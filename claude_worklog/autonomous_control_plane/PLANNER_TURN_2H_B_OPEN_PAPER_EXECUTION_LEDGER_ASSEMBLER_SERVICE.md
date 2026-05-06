# Planner Turn — Open Phase 2H.B Paper Execution Ledger Assembler Service

Date: 2026-05-06
Active requirement: REQ_0006_PHASE2_IMPLEMENT_TRAINER_PARITY_SERVICE.md ∩ REQ_0017_FORCE_PAPER_BACKTEST_MVP_TRACK.md ∩ REQ_0018_PLANNER_LANE_LOCK_AND_PARALLEL_BUILD_POLICY.md ∩ REQ_0020_FULL_AUTONOMOUS_LEGACY_MAPPED_PAPER_BACKTEST_PERFORMANCE_TARGET.md ∩ REQ_0021_PARALLEL_CAPACITY_SCHEDULER_FOR_CLAUDE_CODEX.md
Lane: paper_backtest_mvp
Profile: Claude Code Max20 consolidated_default
Granularity: single consolidated implementation task (one supervisor task authoring three source files plus 28 sibling tests plus 1 zero-byte test package marker plus impl report and impl marker)
Live gate: blocked

## Predecessor evidence

Phase 2H.A (paper execution ledger domain) closed under evidence-first reconciliation:

- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/09_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_GO_NO_GO.md` carries `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS`.
- `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/10_2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_RECONCILIATION_ADDENDUM.md` carries the reconciled 49-row rubric reading.
- `claude_worklog/phase2_core_rebuild/automation_reliability/codex_recover_fail_marker_claude_worklog_phase2_core_rebuild_automation_reliability_135_2h_a_evidence_reco_GO_NO_GO.md` carries `CODEX_FAIL_MARKER_RECOVERY_READY`.
- `v2/backend/app/domain/paper_execution_ledger/` contains the value-object surface (`PaperExecutionLedgerEntry`, the 9-name `__all__`, the cross-field one-to-one mapping rules between `ledger_action`/`input_risk_action` and `ledger_reason_code`/`input_risk_reason_code`).

## Lane lock confirmation (REQ_0018 / REQ_0020)

- `lane`: `paper_backtest_mvp`
- `mvp_relevance`: 2H.B is the second of three Phase 2H sub-phases needed to satisfy REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP`. Without 2H.B, the 2H.A value-object layer has no derivation surface that converts a 2G `RiskDecisionRecord` into a `PaperExecutionLedgerEntry`, the 2H.C composition root has nothing to compose, and downstream replay/backtest runner (REQ_0017 milestone 5) has no typed paper-ledger intent. 2H.B is the smallest concrete advance toward `V2_BACKTEST_AND_PAPER_MVP_READY` available right now.
- `next_gate`: `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED`
- `blocked_by`: `PHASE2H_A_PAPER_EXECUTION_LEDGER_DOMAIN_CODEX_PASS` (satisfied per the recovery report and `09` marker).

REQ_0018 forbids broad infrastructure expansion. 2H.B introduces zero new V2 surface beyond the new package `v2/backend/app/services/paper_execution_ledger/` and the matching test directory `v2/backend/tests/unit/services/paper_execution_ledger/`. No FastAPI route, no Redis adapter, no composition root, no execution side mutation, no PnL or position sizing or quantity or price or fees or slippage, no ledger persistence (no SQL, no SQLite, no JSON file, no Parquet, no CSV, no Redis), no paper executor, no shadow executor, no replay runner, no paper trader process. The service surface is one pure derivation function `assemble_paper_execution_ledger_entry(*, decision: RiskDecisionRecord, now_ms_clock: Callable[[], int]) -> PaperExecutionLedgerEntry`.

## Legacy evidence anchor (REQ_0019 / REQ_0020)

The legacy bot's signal-to-execution path (`claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`) records a consistent gap: paper-side outcomes were stored as untyped log emissions side-by-side with live emissions, with no explicit cross-check that a paper-mirror entry was the deterministic image of an upstream risk decision. The legacy failure addressed by 2H.B is the absence of a typed mirror invariant between a `RiskDecisionRecord` and the paper-ledger entry that "mirrors" it — under the legacy bot, the risk-side allow/deny verdict and the paper-side record_allow/record_deny verdict could diverge silently.

2H.B closes this gap by mapping every value of the 2G.A `_ALLOWED_RISK_REASONS` frozenset (5 members: `allow_proceed_long`, `allow_proceed_short`, `deny_orchestrator_abstained`, `deny_orchestrator_held`, `deny_default`) exhaustively onto the corresponding `PAPER_LEDGER_REASON_MIRROR_*` value, with a defensive fallback that raises `PaperExecutionLedgerServiceError("unrecognized_risk_reason_code", ...)` for any unrecognized input. The `live_blocked` field is the literal Python boolean `True` at every call site. The 2H.A cross-field invariants (`record_allow ↔ mirror_allow_*` reason prefix, `record_deny ↔ mirror_deny_*` reason prefix, one-to-one mapping between `ledger_reason_code` and `input_risk_reason_code`, one-to-one mapping between `ledger_action` and `input_risk_action`) provide the V2 proof that any 2H.B-produced entry passes the 2H.A `__post_init__` gauntlet.

## Consolidated task emitted this turn

- `claude_worklog/agent_supervisor/tasks/136_paper_execution_ledger_2hb_assembler_service_implementation.json`

The task authors three source files plus 28 sibling test files plus a zero-byte test package marker plus the impl report and impl marker. No Codex review task is emitted yet; the planner emits the 137 review task in the next turn only after `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` is materialized at `16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md`.

## Codex parallel lane (REQ_0011 / REQ_0021)

While task 136 dispatches, Codex may run the queued read-only review task `parallel_capacity_readonly_review_codex_fail_marker_recovery_ready.json` against the latest committed 2H.A reconciliation evidence under `claude_worklog/phase2_core_rebuild/automation_reliability/`. That review is read-only and is constrained to the `automation_reliability/` output prefix, so it cannot race the 136 implementation worktree which writes to `v2/backend/app/services/paper_execution_ledger/`, `v2/backend/tests/unit/services/paper_execution_ledger/`, and `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`. Codex is forbidden from running the 137 review of 2H.B before 136's `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` marker exists.

## Module location decision

The new package is `v2/backend/app/services/paper_execution_ledger/`. It is a sibling of `v2/backend/app/services/risk_gateway/`, `v2/backend/app/services/orchestrator_decision/`, `v2/backend/app/services/trainer_prediction_output/`, `v2/backend/app/services/trainer_worker_health/`, and `v2/backend/app/services/trainer_parity/`.

There is NO pre-existing `v2/backend/app/services/paper_execution_ledger.py` placeholder file in the committed tree. The 015A scaffold did not create one. 2H.B therefore does NOT include a placeholder-deletion step. The 015A scaffold's placeholder file `v2/backend/app/services/execution_router.py` is unrelated to 2H.B and is NOT touched.

No 2E1, 2E2, 2E3, 2F.A, 2F.B, 2F.C, 2G.A, 2G.B, 2G.C, or 2H.A source or test file is modified by this milestone. The 2H.A planning artifacts at 00–10 are NOT modified. The pre-existing `v2/backend/app/domain/execution/` directory remains byte-for-byte unchanged.

## Service surface

Single public function:

```
def assemble_paper_execution_ledger_entry(
    *,
    decision: RiskDecisionRecord,
    now_ms_clock: Callable[[], int],
) -> PaperExecutionLedgerEntry:
    ...
```

Validation order (deterministic, verified by tests):

1. `decision` is a `RiskDecisionRecord`. Otherwise raise `PaperExecutionLedgerServiceError("must_be_risk_decision_record", field="decision")`.
2. `now_ms_clock` is callable. Otherwise raise `PaperExecutionLedgerServiceError("must_be_callable", field="now_ms_clock")`.
3. Call `now_ms_clock()` exactly once. Bind to `now_ms`.
4. `type(now_ms) is int` (and not `bool`). Otherwise raise `PaperExecutionLedgerServiceError("must_be_int", field="now_ms_clock")`.
5. `now_ms >= 0`. Otherwise raise `PaperExecutionLedgerServiceError("must_be_nonnegative", field="now_ms_clock")`.
6. `len(decision.risk_decision_id) <= 125`. Otherwise raise `PaperExecutionLedgerServiceError("risk_decision_id_too_long_for_paper_trade_id_derivation", field="decision.risk_decision_id")`.

Mirror derivation table (first match wins; exhaustive over the 2G.A `_ALLOWED_RISK_REASONS` frozenset):

1. `decision.risk_reason_code == "allow_proceed_long"` → `ledger_action = record_allow`, `ledger_reason_code = mirror_allow_proceed_long`.
2. `decision.risk_reason_code == "allow_proceed_short"` → `ledger_action = record_allow`, `ledger_reason_code = mirror_allow_proceed_short`.
3. `decision.risk_reason_code == "deny_orchestrator_held"` → `ledger_action = record_deny`, `ledger_reason_code = mirror_deny_orchestrator_held`.
4. `decision.risk_reason_code == "deny_orchestrator_abstained"` → `ledger_action = record_deny`, `ledger_reason_code = mirror_deny_orchestrator_abstained`.
5. `decision.risk_reason_code == "deny_default"` → `ledger_action = record_deny`, `ledger_reason_code = mirror_deny_default`.
6. Defensive fallback (unreachable under the 2G.A invariant): raise `PaperExecutionLedgerServiceError("unrecognized_risk_reason_code", field="decision.risk_reason_code")`.

`paper_trade_id = "pt_" + decision.risk_decision_id`. The 125-char input cap keeps `paper_trade_id` within the 2H.A 128-char invariant.

Constructor: `PaperExecutionLedgerEntry(...)` with `live_blocked=True` literal at the call site, all 6 lineage and identity fields propagated unchanged from the input `decision`, plus the derived `paper_trade_id`, the looked-up `now_ms` for `ledger_entry_ts_ms`, and the table-derived `ledger_action`/`ledger_reason_code`/`input_risk_action`/`input_risk_reason_code`.

## Dirty-tree dispatch hold

`git status --porcelain` reports two dirty entries:

- ` M claude_worklog/autonomous_control_plane/claude_master_rebuild_planner_prompt.txt` (harness-managed; planner prompt path).
- `?? claude_worklog/agent_supervisor/tasks/parallel_capacity_readonly_review_codex_fail_marker_recovery_ready.json` (Codex-watchdog-emitted parallel readonly review task; codex_watchdog lane).

Both entries are excluded from the dispatch worktree by the supervisor's worktree-isolation contract. The planner does NOT modify either file in this turn. Task 136 carries `requires_clean_worktree: true`; the dispatch worktree must be clean except for the two excluded entries above.

## REQ_0017 scope discipline

2H.B introduces zero behavior beyond the documented derivation table. No FastAPI route, no Redis adapter, no composition root, no execution side mutation, no PnL or position sizing or quantity or price or fees or slippage, no ledger persistence, no paper executor, no shadow executor, no replay runner, no paper trader process. The service-layer logic is one ordered validation block plus one if/elif/elif/elif/elif/else chain plus one `PaperExecutionLedgerEntry(...)` construction. There is no caching, logging, telemetry, or wall-clock helper invocation in any 2H.B source file.

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

## Forbidden in task 136

- Any modification of `v2/backend/app/domain/paper_execution_ledger/` source files (the 2H.A value-object layer is consumed unchanged).
- Any modification of `v2/backend/app/domain/risk_gateway/` source files (the 2G.A value-object layer is consumed unchanged).
- Any modification of any 2H.A test file under `v2/backend/tests/unit/domain/paper_execution_ledger/`.
- Any modification of any 2G or 2F or 2E source or test file.
- Any modification of any planner-emitted 00–10 doc at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/`.
- Any modification of any planner-emitted 11–14 doc at `claude_worklog/phase2_core_rebuild/paper_execution_ledger_impl/` (these are authored by THIS planner turn).
- Any creation of `v2/backend/app/services/paper_execution_ledger.py` as a single file (the package directory is the only allowed shape).
- Any modification of `v2/backend/app/services/__init__.py` or any other sibling services package.
- Any modification of `v2/backend/app/services/paper_loop.py`.
- Any modification of `v2/backend/app/services/execution_router.py`.
- Any modification of any file under `v2/backend/app/composition/`, `v2/backend/app/adapters/`, `v2/backend/app/api/`, `v2/backend/app/cli/`, `v2/backend/app/jobs/`, or `v2/backend/app/main.py`.
- Any harness BEGIN/END framing-marker leakage in any authored body.
- Any standalone `END_FILE` line in any authored file body.
- Any modification of the master planner prompt.
- Any modification of any task definition under `claude_worklog/agent_supervisor/tasks/`.

## Next milestone after 2H.B closes

When `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_IMPL_AND_VALIDATION_PASSED` is materialized in `16_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_GO_NO_GO.md`, the planner emits 137 (Codex review of 2H.B) and dispatches it. Upon `PHASE2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_PASS` at `18_2H_B_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_CODEX_GO_NO_GO.md`, the planner opens Phase 2H.C (paper execution ledger composition root). After 2H.C Codex review produces `PHASE2H_C_PAPER_EXECUTION_LEDGER_COMPOSITION_ROOT_CODEX_PASS`, REQ_0017 milestone 4 `PAPER_EXECUTION_LEDGER_MVP` is satisfied and milestone 5 `REPLAY_BACKTEST_RUNNER_MVP` opens.

PLANNER_TURN_2H_B_OPEN_PAPER_EXECUTION_LEDGER_ASSEMBLER_SERVICE_READY
