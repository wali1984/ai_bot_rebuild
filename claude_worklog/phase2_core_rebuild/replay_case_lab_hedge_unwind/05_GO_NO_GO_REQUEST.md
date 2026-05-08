# Phase 2M — GO Request

## What this milestone certifies on PASS

The `PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY` marker certifies the following at HEAD-after-implementation:

- Five outcome-variant fixture builders exist under `v2/backend/tests/unit/replay_case_lab_hedge_unwind/fixtures.py` and produce typed `PaperExecutionLedgerEntry` mirror rows and `ReplayBacktestRun` instances per `02_REPLAY_CASE_OUTCOME_MATRIX.md` and `03_TYPED_INPUT_FIXTURE_SPEC.md`.
- A deterministic monotonic test clock builder `build_test_clock` exists under the same fixture module.
- A pytest module `v2/backend/tests/unit/replay_case_lab_hedge_unwind/test_lab_hedge_unwind_replay_case.py` exists, instantiates a `ReplayBacktestRunner` per the existing composition root, drives the five fixture builders, asserts the per-outcome typed mirror projections and step counts per `04_TEST_PLAN.md`, and passes locally under `python -m pytest`.
- An implementation report `06_IMPLEMENTATION_REPORT.md` exists and documents the per-outcome step counts, the read-only legacy evidence pointers consulted, and the safety posture invariants verified.
- No file under `v2/backend/app/` is modified.
- No file under `claude_worklog/phase2_core_rebuild/` other than the seven Phase 2M packet artifacts (00 / 01 / 02 / 03 / 04 / 05 authored by this planner turn, 06 / 07 authored by the supervisor task) is modified.
- No file under `claude_worklog/autonomous_control_plane/` other than the planner turn note for this turn is modified.
- No file under `claude_worklog/agent_supervisor/tasks/` other than the new task definition `163_phase2m_replay_case_lab_hedge_unwind_squeeze_implementation.json` is modified.
- No file under `/home/wali/Desktop/AI BOT` is modified.
- No Redis read or write occurred.
- No live service restart occurred.
- No exchange order, leverage change, or margin change occurred.
- No deployment or production migration occurred.
- No secret value was read, printed, or committed.
- No live-readiness gate flip occurred. `FINAL_NON_LIVE_REBUILD_READY_FOR_LIVE_GATE_REVIEW` remains a separate downstream artifact requiring explicit human approval.

## What this milestone explicitly does NOT certify

- it does NOT certify that the V2 risk gateway blocks LAB-style hedge unwinds. Hedge / residual-exposure / squeeze-risk modelling is explicitly out of scope at Phase 2M and belongs to a separate, later milestone;
- it does NOT certify that paper-mode evidence-collection is wired. The paper-mode evidence-collection harness is a separate, later lane A milestone;
- it does NOT certify that shadow-mode evidence-collection is wired. The shadow-mode evidence-collection harness is a separate, later lane A milestone;
- it does NOT certify that the 30-day historical PnL audit (REQ_0024) is complete. The historical PnL audit is a separate, later lane A milestone;
- it does NOT enable live trading;
- it does NOT advance the live-readiness gate.

## Marker body expected at PASS

```
PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_READY
```

## Marker body expected at FAIL with concrete documentation blockers

```
PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_IMPLEMENTATION_FAIL
```

On FAIL with concrete documentation blockers and no safety violation, the supervisor either dispatches a REQ_0007 / REQ_0014 autofix scoped to the Phase 2M packet only, or, if the FAIL is a stale-rubric / pre-existing-placeholder false positive analogous to the earlier 2H / 2I / 2J / 2K reconciliation precedent, the supervisor authors a `08_RECONCILIATION_ADDENDUM.md` addendum and rewrites the `07_GO_NO_GO.md` marker body to PASS per the established reconciliation precedent. On any safety violation, surface to human attention; no autofix is permitted.

PHASE2M_REPLAY_CASE_LAB_HEDGE_UNWIND_GO_NO_GO_REQUEST_READY
