# Phase 2F.A.0 — Frontend Inventory + Gap Audit Task Spec

This is the authoring spec for the local-Claude inventory task that
will produce a gap matrix between the existing `v2/frontend/` tree and
the REQ_0008 + CLAUDE.md V2 GUI page list. Phase 2F.A.0 is documentation
only. The implementer must NOT modify any file under `v2/frontend/`.

## Predecessor gates

- REQ_0008 in requirements inbox.
- `claude_worklog/phase2_core_rebuild/frontend_design/00_SCOPE.md` ends
  with `PHASE2F_FRONTEND_DESIGN_SCOPE_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/01_PHASE_BREAKDOWN.md`
  ends with `PHASE2F_FRONTEND_DESIGN_PHASE_BREAKDOWN_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/03_PHASE_2FA0_SAFETY_BOUNDARIES.md`
  ends with `PHASE2FA0_FRONTEND_INVENTORY_SAFETY_BOUNDARIES_READY`.
- `claude_worklog/phase2_core_rebuild/frontend_design/04_PHASE_2FA0_GO_NO_GO_REQUEST.md`
  ends with `PHASE2FA0_GO_NO_GO_REQUEST_RECORDED`.

## Inputs the implementer must read

- `claude_worklog/requirements_inbox/REQ_0008_ENTERPRISE_WEBSITE_DESIGN_ANIMATION_SYSTEM.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/00_SCOPE.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/01_PHASE_BREAKDOWN.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/03_PHASE_2FA0_SAFETY_BOUNDARIES.md`
- `CLAUDE.md` (project instructions, "Required V2 GUI Pages" + "Monitor
  Center Requirements" + "Signal Explainability Rule" + "Mobile/iPhone
  Future Rule" sections).
- `v2/frontend/package.json`
- `v2/frontend/tsconfig.json`
- `v2/frontend/vite.config.ts`
- `v2/frontend/playwright.config.ts`
- `v2/frontend/src/main.tsx`
- `v2/frontend/src/router.tsx`
- `v2/frontend/src/styles.css`
- every file under `v2/frontend/src/pages/` (read-only)
- every file under `v2/frontend/src/components/` (read-only)
- every file under `v2/frontend/src/hooks/` (read-only)
- every file under `v2/frontend/src/api/` (read-only)
- every file under `v2/frontend/src/auth/` (read-only)
- every file under `v2/frontend/src/lineage/` (read-only)
- every file under `v2/frontend/src/pwa/` and `v2/frontend/src/mobile/`
  (read-only)
- every file under `v2/frontend/src/constants/` (read-only)
- every file under `v2/frontend/src/types/` (read-only)
- every file under `v2/frontend/tests/` (read-only)

## Outputs the implementer must author (exact set, no extras)

- `claude_worklog/phase2_core_rebuild/frontend_design/05_FRONTEND_INVENTORY_REPORT.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/06_FRONTEND_INVENTORY_GAP_MATRIX.md`
- `claude_worklog/phase2_core_rebuild/frontend_design/07_FRONTEND_INVENTORY_GO_NO_GO.md`

The implementer authors these via `Write` (or BEGIN_FILE/END_FILE blocks
since the harness Markdown materialization is safe). The implementer
MUST NOT author any Python/TypeScript file under `v2/`.

## 05_FRONTEND_INVENTORY_REPORT.md required structure

1. Heading "Phase 2F.A.0 — Frontend Inventory Report".
2. Section "Toolchain" recording exact versions from `package.json`
   (`react`, `react-dom`, `react-router-dom`, `vite`, `typescript`,
   `@playwright/test`, `@vitejs/plugin-react`).
3. Section "Top-level surface" listing each immediate child of
   `v2/frontend/src/` with its file/dir count and one-line purpose
   inferred from the code.
4. Section "Pages" — one row per page directory under
   `v2/frontend/src/pages/`. Columns: page slug, presence of `index.tsx`,
   presence of `route.ts`, presence of `meta.ts`, presence of `rbac.ts`,
   estimated SLOC of `index.tsx`, observed responsibilities (one short
   sentence read from the code, not invented).
5. Section "Shared components" — one row per file under
   `v2/frontend/src/components/`. Columns: path, component name,
   exported public surface, observed responsibilities, animation usage
   (yes/no/pure-static).
6. Section "Hooks" — one row per file under `v2/frontend/src/hooks/`.
7. Section "API surface" — list of helpers under
   `v2/frontend/src/api/` and what backend route shape they expect
   (read from code, do not invent).
8. Section "Auth, lineage, PWA, mobile, constants, types" — short
   descriptions of each, with file lists.
9. Section "Tests" — list of files under `v2/frontend/tests/` and the
   feature each test exercises.
10. Section "Forbidden-token grep result" — record the hit count for
    each of the following tokens across the entire `v2/frontend/`
    subtree: `redis`, `aioredis`, `subprocess`, `os.system`,
    `legacy_reference`, `/home/wali/Desktop/AI BOT`, `BINANCE_API_KEY`,
    `BINANCE_API_SECRET`, `live_trading_enabled = true`. Every count
    must be zero. Any non-zero count is a hard fail and triggers
    `PHASE2FA0_FRONTEND_INVENTORY_BLOCKED`.
11. Section "Live-trading-blocked banner discoverability" — does an
    always-visible safety banner exist? If yes, where? If no, record
    as a P0 gap.
12. Final marker line: `PHASE2FA0_FRONTEND_INVENTORY_REPORT_READY` or
    `PHASE2FA0_FRONTEND_INVENTORY_BLOCKED`.

## 06_FRONTEND_INVENTORY_GAP_MATRIX.md required structure

1. Heading "Phase 2F.A.0 — Gap Matrix".
2. Table A "Required pages" — one row per page in REQ_0008 + CLAUDE.md
   "Required V2 GUI Pages". Columns: required page name, present
   directory under `v2/frontend/src/pages/` (or "MISSING"), gap
   severity (P0/P1/P2), one-line gap description.
3. Table B "Required animation primitives" — one row per primitive in
   REQ_0008 "Animation requirements" (page transitions, status pulse
   indicators, data-flow graph animations, risk-gate block animations,
   streaming activity timeline, symbol heatmap hover/focus states,
   mobile-friendly slide panels). Columns: primitive, present? (yes/
   partial/missing), implementing component path or `MISSING`, gap
   severity, one-line gap description.
4. Table C "Required safety chrome" — one row each for: always-visible
   `LIVE TRADING: BLOCKED` banner, approval-required indicator,
   kill-switch state indicator, agent activity stream, audit ledger
   visibility. Columns: chrome element, present?, location, gap
   severity, one-line gap description.
5. Table D "Required public/admin separation" — one row each for:
   public landing route, public status route, login / step-up auth
   route, admin route gating. Columns: capability, present?, location,
   gap severity, one-line gap description.
6. Table E "Required mobile/iPhone readiness" — one row each for:
   responsive layout, PWA manifest, slide panels, mobile-safe auth,
   push-notification scaffold, mobile approvals. Columns: capability,
   present?, location, gap severity, one-line gap description.
7. Table F "Required lineage visualization" — one row for each lineage
   stage (data, features, trainer, signal, risk, trader) and its
   connecting edges. Columns: stage, present? in lineage component,
   connection visualization present?, gap severity, one-line gap
   description.
8. Section "P0 gap summary" — bulleted list of every P0 row across
   tables A–F, sorted by required page / capability name.
9. Section "Recommended next sub-phase ordering" — recommendation
   referring back to the `01_PHASE_BREAKDOWN.md` order, with any
   adjustments justified by the gap evidence. The implementer does
   NOT change the breakdown file; this section is a recommendation
   only.
10. Final marker line: `PHASE2FA0_FRONTEND_INVENTORY_GAP_MATRIX_READY`
    or `PHASE2FA0_FRONTEND_INVENTORY_BLOCKED`.

## 07_FRONTEND_INVENTORY_GO_NO_GO.md required structure

Exactly one line: `PHASE2FA0_FRONTEND_INVENTORY_PASSED` or
`PHASE2FA0_FRONTEND_INVENTORY_BLOCKED`. No other content.

## Hard exclusions for Phase 2F.A.0

- No write under `v2/frontend/` (or any `v2/` subtree).
- No write outside `claude_worklog/phase2_core_rebuild/frontend_design/`.
- No `npm install`, `npm run`, `npx`, `vite`, `tsc`, `playwright` invocation.
- No subprocess other than `grep` / `rg`, `wc`, `python -c`-for-counting.
- No Redis client construction.
- No exchange API call.
- No legacy module import.
- No legacy file read (under `/home/wali/Desktop/AI BOT/`).
- No production secret read.
- No `.env` read.
- No deployment script invocation.

## Stop conditions

The implementer halts and emits
`PHASE2FA0_FRONTEND_INVENTORY_BLOCKED` to the GO_NO_GO marker file
under any of:

- a forbidden token leak detected during the inventory grep;
- a write attempt outside the allowed prefix;
- a request to mutate `v2/frontend/`;
- any directive that would require Redis, subprocess, network, GPU,
  legacy import, deployment, or live behavior.

PHASE2FA0_FRONTEND_INVENTORY_TASK_SPEC_READY
