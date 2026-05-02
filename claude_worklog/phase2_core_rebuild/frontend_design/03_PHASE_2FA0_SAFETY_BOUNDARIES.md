# Phase 2F.A.0 — Safety Boundaries

This sub-phase is documentation-only. It does NOT compile code, run
tests, install packages, build artifacts, write Redis, place orders,
restart services, deploy, or modify the legacy bot.

## Read scope (allowed)

- `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/01_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/02_PHASE_2FA0_FRONTEND_INVENTORY_TASK_SPEC.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/04_PHASE_2FA0_GO_NO_GO_REQUEST.md`
- `CLAUDE.md`
- read-only enumeration of `v2/frontend/` (every file under it MAY be
  read; none MAY be modified)

## Read scope (forbidden)

- any file under `/home/wali/Desktop/AI BOT/`
- any `.env` or secrets file
- any Redis key
- any network resource
- any file under `legacy_reference/` (this sub-phase has no need to
  touch legacy)

## Write scope (allowed)

- `claude_worklog/phase2_core_rebuild/frontend_design/05_FRONTEND_INVENTORY_REPORT.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/06_FRONTEND_INVENTORY_GAP_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/07_FRONTEND_INVENTORY_GO_NO_GO.md`

## Write scope (forbidden — exhaustive)

- ANY file under `v2/` (frontend or backend).
- ANY file under `legacy_reference/`.
- ANY file under `/home/wali/Desktop/AI BOT/`.
- ANY `.env` or secrets file.
- ANY file outside the three allowed output paths above.

## Forbidden actions

- Run `npm install`, `npm run`, `npx`, `pnpm`, `yarn` — anything that
  resolves a dependency graph or downloads packages.
- Run `vite`, `tsc`, `playwright`, `eslint`, `prettier`, `vitest`,
  `jest`, `karma`.
- Run any subprocess that opens a network socket.
- Run any subprocess against the legacy trainer venv.
- Connect to Redis.
- Connect to the network.
- Place exchange orders.
- Cancel exchange orders.
- Change leverage or margin.
- Restart any running service.
- Enable live trading.
- Deploy.
- Run production migrations.
- Expose or commit secrets.

## Allowed subprocesses

- `grep` / `rg` (read-only)
- `wc` (read-only count of lines / bytes)
- `python -c "import json,sys; ..."` for JSON parsing of `package.json`
  (no `subprocess` import inside the python -c expression).

The implementer MAY also list directories with `ls` semantics through
the planner-supplied tools (the `Glob` tool, the `Bash ls` invocation
via the harness). No file is created, modified, or deleted under
`v2/frontend/` by any of these.

## Authoring tool discipline

- Implementer MAY use BEGIN_FILE / END_FILE blocks for the three
  authored Markdown files. The harness END_FILE-marker materialization
  defect documented in `claude_worklog/autonomous_control_plane/
  PLANNER_PHASE2E1B_END_FILE_MARKER_DISCOVERY.md` is harmless for
  Markdown.
- Implementer MAY use the `Write` tool instead.
- Implementer MUST NOT author any Python or TypeScript file in this
  sub-phase.

## Stop conditions

The implementer halts and writes
`PHASE2FA0_FRONTEND_INVENTORY_BLOCKED` to
`07_FRONTEND_INVENTORY_GO_NO_GO.md` under any of:

- a forbidden token surface in the inventory grep;
- a write attempt outside the allowed prefix;
- any directive that would require Redis, subprocess (beyond the
  allowlist above), network, GPU, legacy import, deployment, or live
  behavior;
- a request to compile / type-check / install / build any frontend
  artifact (those are 2F.B.0 + concerns, not 2F.A.0).

PHASE2FA0_FRONTEND_INVENTORY_SAFETY_BOUNDARIES_READY
