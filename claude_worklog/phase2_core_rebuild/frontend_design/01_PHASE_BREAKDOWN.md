# Phase 2F — Phase Breakdown

The Phase 2F track decomposes into ordered sub-phases, each gated by
Codex review and local validation, mirroring the 2E1.A → 2E1.B → 2E1.C.α
authoring cadence. No sub-phase enables live behavior; every sub-phase
restricts writes to documented allowed output prefixes.

| Sub-phase | Subject | Layer | Allowed write scope |
| --- | --- | --- | --- |
| 2F.A.0 | Frontend inventory + gap audit | docs | `claude_worklog/phase2_core_rebuild/frontend_design/` |
| 2F.A.1 | Design-token + animation-primitive spec | docs | `claude_worklog/phase2_core_rebuild/frontend_design/` |
| 2F.B.0 | Design-token module implementation + unit tests | code | `v2/frontend/src/design/`, `v2/frontend/tests/unit/design/` |
| 2F.B.1 | Animation-primitive component implementation + unit tests | code | `v2/frontend/src/components/motion/`, `v2/frontend/tests/unit/motion/` |
| 2F.C.0 | Public Landing + Public Status redesign | code | page-scoped subtrees only |
| 2F.C.1 | Mission Control redesign | code | page-scoped subtrees only |
| 2F.C.2 | Live Readiness redesign with always-visible safety chrome | code | page-scoped subtrees only |
| 2F.D.0..n | Operational page redesigns (one sub-phase per page) | code | one page subtree per sub-phase |
| 2F.E.0 | Approval Center + step-up auth UX | code | scoped to approval-center + auth subtrees |
| 2F.F.0 | Mobile/iPhone PWA polish + slide panels | code | scoped to `pwa/` and `mobile/` subtrees |
| 2F.G.0 | End-to-end Playwright smoke + accessibility audit | tests | `v2/frontend/tests/` |

Only Phase 2F.A.0 is dispatched by the planner turn that authors this
breakdown. 2F.A.1 is deferred until 2F.A.0 is Codex-passed and locally
validated. Every later sub-phase is deferred behind its immediate
predecessor's Codex pass marker.

## Hard exclusions carried through every Phase 2F sub-phase

- No live trading enable.
- No Redis client construction in frontend code.
- No exchange API call in frontend code.
- No legacy module import.
- No production secret in any artifact.
- No deployment script invocation.
- No production migration.
- No use of network-fetching code paths against live endpoints; mock
  data fixtures only.

## Sub-phase 2F.A.0 — definition

Pure documentation. Read-only inventory of `v2/frontend/`. Authors a
gap matrix that ties existing pages to the REQ_0008 page list, the
CLAUDE.md V2 GUI page list, the safety-chrome requirement, the
animation-primitive requirements, and the mobile/iPhone readiness
requirement. No file under `v2/frontend/` is modified.

PHASE2F_FRONTEND_DESIGN_PHASE_BREAKDOWN_READY
