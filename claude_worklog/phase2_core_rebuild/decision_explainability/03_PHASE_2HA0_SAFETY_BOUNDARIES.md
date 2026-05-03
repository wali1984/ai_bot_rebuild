# Phase 2H.A.0 — Safety Boundaries

This sub-phase is documentation-only. It does NOT compile code, run
unit tests, install packages, build artifacts, write Redis, place
orders, restart services, deploy, or modify the legacy bot. It does
NOT execute any V2 module; it only enumerates and reads V2 source
files.

## Read scope (allowed)

- `claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/01_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/02_PHASE_2HA0_LINEAGE_INVENTORY_TASK_SPEC.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/04_PHASE_2HA0_GO_NO_GO_REQUEST.md`
- `CLAUDE.md`
- read-only enumeration of every file under
  `v2/backend/app/domain/` listed in spec 02 "Inputs the implementer
  MUST read".

## Read scope (forbidden)

- any file under `/home/wali/Desktop/AI BOT/`
- any `.env` or secrets file
- any Redis key (no Redis client construction)
- any network resource (no HTTP/TCP/UDP/DNS)
- any file under `legacy_reference/` (this sub-phase has no need to
  touch legacy)
- any file under `v2/frontend/` (Phase 2H is backend-domain inventory;
  frontend wiring is Phase 2H.C.0)

## Write scope (allowed)

- `claude_worklog/phase2_core_rebuild/decision_explainability/05_DECISION_LINEAGE_INVENTORY_REPORT.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/06_DECISION_LINEAGE_GAP_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/decision_explainability/07_DECISION_LINEAGE_GO_NO_GO.md`

## Write scope (forbidden — exhaustive)

- ANY file under `v2/` (frontend or backend).
- ANY file under `legacy_reference/`.
- ANY file under `/home/wali/Desktop/AI BOT/`.
- ANY `.env` or secrets file.
- ANY file under `claude_worklog/agent_supervisor/tasks/` (the
  planner authors task definitions; the inventory implementer does
  not).
- ANY file outside the three allowed output paths above.

## Forbidden subprocess set

- `python -m pytest` and any `pytest` invocation against `v2/` (this
  is documentation-only).
- `python -m py_compile` against any `v2/` file.
- `npm`, `npx`, `pnpm`, `yarn`, `vite`, `tsc`, `playwright`,
  `vitest`, `jest`.
- Any subprocess that touches Redis, the legacy bot, or the network.

Allowed subprocess set: `grep`, `rg`, `wc`, `python -c` for arithmetic
or JSON parsing only.

## Live-trading status

LIVE TRADING: BLOCKED. No Phase 2H.A.0 artifact may change this. No
recommendation in any 2H.A.0 artifact may suggest enabling live
trading or relaxing the LIVE TRADING: BLOCKED state.

## Cross-lane non-interference

Phase 2H.A.0 writes only under
`claude_worklog/phase2_core_rebuild/decision_explainability/`. It
shares no marker file with REQ_0006 Phase 2E1.C.α/β or REQ_0008
Phase 2F.A.0/2F.A.1. It MUST NOT read or write the marker files of
those lanes.

PHASE2HA0_DECISION_LINEAGE_SAFETY_BOUNDARIES_READY
