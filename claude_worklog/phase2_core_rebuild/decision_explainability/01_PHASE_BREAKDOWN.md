# Phase 2H — Phase Breakdown

The Phase 2H track decomposes into ordered sub-phases, each gated by
Codex review and local validation, mirroring the 2E1.A → 2E1.B →
2E1.C.α and 2F.A.0 → 2F.A.1 authoring cadence. No sub-phase enables
live behavior; every sub-phase restricts writes to documented allowed
output prefixes. Per the Claude Code Max20 consolidated_default
profile, sub-phases are kept consolidated and split only on validation
or Codex failure.

| Sub-phase | Subject | Layer | Allowed write scope |
| --- | --- | --- | --- |
| 2H.A.0 | Decision-lineage inventory + gap matrix | docs | `claude_worklog/phase2_core_rebuild/decision_explainability/` |
| 2H.A.1 | Stable-id contract + confidence-delta explanation contract spec | docs | `claude_worklog/phase2_core_rebuild/decision_explainability/` |
| 2H.A.2 | Risk/exposure decision-explanation contract spec + symbol-state-change explanation contract spec | docs | `claude_worklog/phase2_core_rebuild/decision_explainability/` |
| 2H.A.3 | Audit-timeline contract spec + paper/shadow/live-blocked explanation contract spec | docs | `claude_worklog/phase2_core_rebuild/decision_explainability/` |
| 2H.B.0 | Decision-explanation domain package skeleton + unit tests | code | `v2/backend/app/domain/decision_explanation/`, `v2/backend/tests/unit/domain/decision_explanation/` |
| 2H.B.1 | Confidence-delta explanation packager + unit tests | code | scoped to the 2H.B.0 subtree |
| 2H.B.2 | Risk-decision explanation packager + unit tests | code | scoped to the 2H.B.0 subtree |
| 2H.B.3 | Symbol-state-change explanation packager + unit tests | code | scoped to the 2H.B.0 subtree |
| 2H.B.4 | Trade open/close/hedge/block explanation packager + unit tests | code | scoped to the 2H.B.0 subtree |
| 2H.B.5 | Audit-timeline explanation aggregator + unit tests | code | scoped to the 2H.B.0 subtree |
| 2H.C.0 | Frontend wiring handoff doc to REQ_0008 Phase 2F.D.x | docs | `claude_worklog/phase2_core_rebuild/decision_explainability/` |

Only Phase 2H.A.0 is dispatched by the planner turn that authors this
breakdown. 2H.A.1, 2H.A.2, and 2H.A.3 are deferred until 2H.A.0 is
Codex-passed and locally validated. Every later sub-phase is deferred
behind its immediate predecessor's Codex pass marker.

## Hard exclusions carried through every Phase 2H sub-phase

- No live trading enable.
- No Redis client construction in explanation code.
- No exchange API call in explanation code.
- No legacy module import.
- No production secret in any artifact.
- No deployment script invocation.
- No production migration.
- No use of network-fetching code paths against live endpoints; mock
  data fixtures only.
- No subprocess invocation other than `pytest`, `python -c`, `python
  -m py_compile`, `grep`, `rg`, `wc`.

## Sub-phase 2H.A.0 — definition

Pure documentation. Read-only inventory of:

- REQ_0009 (full requirements text).
- The CLAUDE.md "Signal Explainability Rule", "Required V2 GUI Pages",
  "Monitor Center Requirements", and "Admin Control Rule" sections.
- The current V2 backend domain modules under
  `v2/backend/app/domain/` that participate in the explanation chain:
  `predictions/`, `decisions/`, `signals/`, `risk/`, `traders/`,
  `lineage/`, `governance/`, `execution/`, `monitor/`, `symbols/`,
  `features/`, `trainer_parity/`, `trainer_liveness/`, `universe/`,
  `connectors/`, `replay/`, `hot_reload/`.

Authors a per-stage chain inventory and a gap matrix that ties REQ_0009
explanation requirements to existing V2 code (or marks as P0/P1/P2
gap). No file under `v2/` is modified. No code is executed beyond
read-only enumeration and the forbidden-token grep.

PHASE2H_DECISION_EXPLAINABILITY_PHASE_BREAKDOWN_READY
