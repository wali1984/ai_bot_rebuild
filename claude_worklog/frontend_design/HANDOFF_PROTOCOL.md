# Claude Design Handoff Protocol

Status: `CODEX_DESIGN_HANDOFF_REVIEW_PROTOCOL_READY`

Claude Design outputs are design references for the V2 frontend. They are not source-of-truth runtime evidence and must not be copied blindly into production code.

## Folder Convention

Claude Design output location:

`claude_worklog/frontend_design/handoffs/YYYYMMDD_<design_slug>/`

The current historical handoff folder `claude_worklog/frontend_design/handoffs/2026-05-11/` is accepted as a legacy naming variant. New folders should use the compact `YYYYMMDD_<design_slug>` convention.

## Required Handoff Files

Each handoff package should contain:

- `DESIGN_HANDOFF.md`
- `DESIGN_SOURCE_ZIP_OR_FILES/`
- `ROUTE_MAP.json`
- `COMPONENT_MAP.json`
- `DATA_CONTRACT_MAP.json`
- `SAFETY_STATE_MAP.json`
- `MISSING_EVIDENCE_MAP.md`
- `IMPLEMENTATION_NOTES.md`
- `CLAUDE_CODE_TASK.md`
- `CODEX_REVIEW_CHECKLIST.md`

## Mapping Rules

Any prototype file such as `app.jsx`, `data.jsx`, `module-placeholder.jsx`, `mission-control.jsx`, `pages-*.jsx`, `risk-control.jsx`, or `signal-explainability.jsx` must be mapped to real V2 route/component/data contracts before implementation.

Claude Code must inspect the existing V2 frontend before applying a design:

- `v2/frontend/src/router.tsx`
- `v2/frontend/src/pages/registry.ts`
- `v2/frontend/src/pages/**`
- `v2/frontend/src/components/**`
- `v2/frontend/public/**/operator_dashboard_payload.json`

## Data Truth Rules

- `data.jsx` and static demo metrics must not ship as real data.
- Mock design data must be removed, labeled `DESIGN_MOCK_DATA_TO_REMOVE`, or converted to explicit evidence gaps.
- Static proof data must be labeled `STATIC_PROOF_FIXTURE`.
- Read-only market data must be labeled `READONLY_MARKET_FEED`.
- Read-only account data must be labeled `READONLY_ACCOUNT_FEED`.
- Runtime monitor data must be labeled `RUNTIME_MONITOR_PAYLOAD`.
- Missing data must show: `Evidence missing - cannot explain without guessing.`
- `module-placeholder` behavior must not remain placeholder-only.

## Safety Rules

The design package cannot decide live readiness, signal validity, trade safety, or capital approval. V2 artifacts, runtime monitor payloads, read-only market/account payloads, audit ledger, risk decisions, trainer lineage, script registry, and GO/NO-GO markers remain source of truth.

The global `LIVE TRADING: BLOCKED_HUMAN_ONLY` state must remain visible. Claude Design may propose layout and interaction, but Claude Code and Codex must enforce safety state, data truth, and final live-gate boundaries.
