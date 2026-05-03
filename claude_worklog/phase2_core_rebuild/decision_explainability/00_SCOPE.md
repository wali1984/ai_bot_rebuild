# Phase 2H — Full Decision Explainability and Under-the-Hood UI — Scope

This phase covers REQ_0009
(`claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`).

It runs in parallel with REQ_0006 Phase 2E1.C.α/β (trainer liveness +
growth-window domain layers) and REQ_0008 Phase 2F.A.x (frontend design
system). The three lanes touch disjoint write paths:

- REQ_0006 Phase 2E1.C.α/β writes only under
  `v2/backend/app/domain/trainer_liveness/`,
  `v2/backend/tests/unit/domain/trainer_liveness/`,
  `v2/backend/app/domain/trainer_liveness_growth/`,
  `v2/backend/tests/unit/domain/trainer_liveness_growth/`, and the
  worklog reports under
  `claude_worklog/phase2_core_rebuild/trainer_gpu_parity_impl/`.
- REQ_0008 Phase 2F writes only under `v2/frontend/` and
  `claude_worklog/phase2_core_rebuild/frontend_design/`.
- REQ_0009 Phase 2H writes only under
  `claude_worklog/phase2_core_rebuild/decision_explainability/` for the
  documentation sub-phases (2H.A.x) and, in later code sub-phases,
  under `v2/backend/app/domain/decision_explanation/` and
  `v2/backend/tests/unit/domain/decision_explanation/`.

There is no shared module under modification, no shared marker file,
and no shared supervisor task ID. Either lane may complete first
without affecting the others.

## Active requirement source

`claude_worklog/requirements_inbox/REQ_0009_FULL_DECISION_EXPLAINABILITY_AND_UNDER_THE_HOOD_UI.md`.

## Phase 2H objective

Establish a full lineage-and-explanation contract that ties every
visible system decision back to its raw inputs and intermediate
artifacts, and surface that contract in the V2 backend domain layer
and (later) the frontend explainability pages required by REQ_0009 and
by the CLAUDE.md "Signal Explainability Rule".

The lineage chain to be made explicit and audit-renderable is:

```
raw source data
  → feature snapshot
  → feature changes
  → trainer prediction
  → confidence change
  → signal
  → orchestrator decision
  → risk gateway decision
  → execution intent
  → paper/shadow/live-blocked trader action
  → result/PnL attribution
```

Every node in the chain MUST be addressable by a stable id
(`feature_snapshot_id`, `prediction_id`, `signal_id`, `decision_id`,
`risk_decision_id`, `execution_intent_id`) and MUST carry the inputs,
the rule or model that produced the output, the freshness/quality
flags, and the human-readable reason text.

## In scope (Phase 2H — overall)

- Lineage inventory mapping REQ_0009 chain stages to existing V2
  domain modules under `v2/backend/app/domain/` (predictions,
  decisions, signals, risk, traders, lineage, governance, execution,
  monitor, symbols, features, trainer_parity, trainer_liveness,
  universe), with a per-stage gap matrix.
- Stable-id contract specification: which modules MUST mint, which
  MUST forward, which MUST persist.
- Confidence-delta explanation contract (previous, new, delta, top
  positive/negative feature contributors, source freshness, regime
  context, model/checkpoint version, data-quality impact).
- Symbol-state-change explanation contract.
- Risk-gateway decision explanation contract (signal reason, sizing
  reason, stale-signal check, duplicate check, exposure check,
  drawdown check, live-gate status, execution mode, final reason).
- Trade open/close/hedge/block decision explanation contract.
- Audit timeline contract (write-once chain of explanation records).
- Backend domain code for explanation packaging and rendering, with
  unit tests, in later sub-phases.
- Frontend explainability page wiring is OUT OF SCOPE for Phase 2H and
  will be handled in REQ_0008 Phase 2F.D.x sub-phases that consume the
  Phase 2H backend contract.

## Out of scope (Phase 2H)

- Trainer parity service implementation (REQ_0006 / Phase 2E).
- Frontend design tokens, animation primitives, or page redesigns
  (REQ_0008 / Phase 2F).
- Redis read/write paths.
- Live exchange API integration.
- Production deployment artifacts.
- Production secrets handling beyond manifest references.
- Modifications to `/home/wali/Desktop/AI BOT/`.
- Any change to `legacy_reference/`.
- Any subprocess invocation from explanation code.
- Any direct import of legacy modules.

## Hard exclusions for every Phase 2H sub-phase

- No live trading enable.
- No Redis client construction in explanation code.
- No exchange API call in explanation code.
- No legacy module import.
- No production secret in any artifact.
- No deployment script invocation.
- No production migration.
- No use of network-fetching code paths against live endpoints; mock
  data fixtures only.

## Layer-isolation rule

The Phase 2H code sub-phases MUST live in a dedicated package
`v2/backend/app/domain/decision_explanation/` and MUST NOT import
from `v2/backend/app/domain/trainer_liveness/` (REQ_0006 α package) or
`v2/backend/app/domain/trainer_liveness_growth/` (REQ_0006 β package
when authored) or from any frontend module. Reuse of cross-domain
types is allowed only via shared `v2/backend/app/domain/lineage/`
identifier helpers, which are already established (`chain.py`,
`ids.py`, `validators.py`).

PHASE2H_DECISION_EXPLAINABILITY_SCOPE_READY
