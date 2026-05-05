# Phase 2G — Legacy Monitor and Audit Evidence Review

REQ_0019 requires the planner to read read-only legacy monitor and audit evidence before authoring a V2 module so the new system reflects actual legacy runtime behavior, failures, and gaps. This document captures the read for Phase 2G (risk gateway default-deny MVP).

## Read scope (read-only)

The following legacy runtime audit files were read:

- `claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_runtime_audit/12_LEGACY_AUDIT_GO_NO_GO.md`

`09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` is a read-only stub ("Read-only posture captured. No service restart executed.") with no concrete legacy-behavior payload. No legacy code was read or mutated. No Redis state was read or mutated.

`legacy_reference/` was scanned by directory listing only. Names indicate the legacy bot ran a hybrid signal-to-execution path with rule-based and trainer-based signal layers feeding `trader.py` directly. No risk-gateway-style intermediate decision lineage was observed in the legacy directory listing. No file body was read for this milestone, and no file body would change the value-object surface defined in 2G.A.

The pre-existing scaffold artifacts at `v2/backend/app/services/risk_gateway.py` (one-line placeholder docstring) and `v2/backend/app/domain/risk/` (`kill_switch.py`, `live_readiness_state.py`, `phases.py`, `policy_bundle.py`) were inspected by directory listing only. Their bodies are NOT a binding contract on the 2G.A surface and are NOT modified by Phase 2G.

## Behavior assumptions carried forward into V2

The legacy stubs contain no concrete risk-gateway behavior. Phase 2G therefore designs the risk gateway domain strictly from:

1. The authoritative `OrchestratorDecisionRecord` contract emitted by Phase 2F.A and consumed by Phase 2F.B and 2F.C composition root, which carries the four orchestrator-decision actions (`open_long`, `open_short`, `hold`, `abstain`) and the eleven orchestrator-decision reason codes (`proceed_long`, `proceed_short`, `hold_flat_direction`, `abstain_low_confidence`, `abstain_freshness_stale`, `abstain_freshness_missing`, `abstain_worker_degraded`, `abstain_worker_critical`, `abstain_worker_unknown`).
2. REQ_0009 explainability lineage IDs: `risk_decision_id`, `decision_id`, `prediction_id`, `feature_snapshot_id`.
3. REQ_0017 default-deny safety posture: live actions remain blocked, the risk gateway is the place where every non-tradable orchestrator action becomes a typed `deny`, and even tradable orchestrator actions never produce a live exchange action because the live gate remains blocked at the value-object layer (`live_blocked` invariant).
4. REQ_0020 hard live gate: every authored 2G.A source file enforces `live_blocked is True` so any caller constructing a record with `live_blocked == False` fails closed at construction time.

## Failure modes implied by REQ_0017 default-deny posture

The risk gateway domain admits a `deny` action explicitly so that the system never silently coerces a non-tradable orchestrator decision into an execution intent. The reason taxonomy reserves a distinct code for each deny cause:

- `deny_orchestrator_abstained` — input orchestrator action is `abstain` for any abstain reason.
- `deny_orchestrator_held` — input orchestrator action is `hold` with reason `hold_flat_direction`.
- `deny_default` — reserved default-deny taxonomy member for a tradable orchestrator action that fails a future 2G.B-introduced gate (the 2G.A value-object enforces that this code is paired with `open_long` or `open_short` input action).

A single explicit reason code per allow path is also required so the explainability layer (REQ_0009) can render an unambiguous chain:

- `allow_proceed_long` — paired with input action `open_long` and input reason `proceed_long`.
- `allow_proceed_short` — paired with input action `open_short` and input reason `proceed_short`.

## Hard safety rules carried forward

- No `/home/wali/Desktop/AI BOT` mutation by Phase 2G at any sub-phase.
- No Redis access at any layer in any 2G authored source file.
- No live service restart, no exchange action, no leverage/margin change, no live trade enablement, no deployment, no migration, no secret exposure or commit.
- The 2G.A domain MUST validate `live_blocked is True` so any consumer that constructs a record with `live_blocked == False` fails closed at construction time.
- The 2G.A domain MUST NOT import `v2.backend.app.domain.orchestrator_decision` at the value-object layer; the orchestrator action and reason are propagated as plain strings and validated by membership in frozensets. The orchestrator domain is consumed at the 2G.B service layer.

## Constraint: no SMC / liquidity feature use

REQ_0013 SMC / liquidity features are deferred to a later phase, are shadow-only on entry, and are NOT consumed by 2G.A.

## Constraint: no scope drift into prior phases

2G.A MUST NOT modify any 2E1, 2E2, 2E3, 2F.A, 2F.B, or 2F.C source, test, marker, or report file. The 2F.A `OrchestratorDecisionRecord` value-object surface remains frozen.

PHASE2G_LEGACY_EVIDENCE_REVIEW_READY
