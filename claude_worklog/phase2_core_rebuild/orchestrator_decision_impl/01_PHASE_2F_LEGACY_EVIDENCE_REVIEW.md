# Phase 2F — Legacy Monitor and Audit Evidence Review

REQ_0019 requires the planner to read read-only legacy monitor and audit evidence before authoring a V2 module so the new system reflects actual legacy runtime behavior, failures, and gaps. This document captures the read for Phase 2F (orchestrator decision MVP).

## Read scope (read-only)

The following legacy runtime audit files were read:

- `claude_worklog/legacy_runtime_audit/00_AUDIT_SCOPE_AND_SAFETY.md`
- `claude_worklog/legacy_runtime_audit/05_ORCHESTRATOR_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md`
- `claude_worklog/legacy_runtime_audit/11_FAILURE_MODE_AND_GAP_REGISTER.md`
- `claude_worklog/legacy_runtime_audit/12_LEGACY_AUDIT_GO_NO_GO.md`

Both `05_ORCHESTRATOR_RUNTIME_AUDIT.md` and `09_SIGNAL_TO_EXECUTION_RUNTIME_AUDIT.md` are read-only stubs ("Read-only posture captured. No service restart executed.") with no concrete legacy-behavior payload. No legacy code or Redis state was read or mutated.

`legacy_reference/` was scanned by directory listing only. Names indicate the legacy bot ran a hybrid signal pipeline with rule-based and trainer-based signal layers (`hybrid_rule_based_signals.py`, `run_hybrid_trainer_with_signals.py`, `analyze_current_signals.py`, `comprehensive_signal_monitor.py`, `monitor_trainer_signals.py`). No file body was read for this milestone, and no file body would change the value-object surface defined in 2F.A.

## Behavior assumptions carried forward into V2

The legacy stubs contain no concrete decision behavior. Phase 2F therefore designs the orchestrator decision domain strictly from:

1. The authoritative `TrainerPredictionRecord` contract emitted by Phase 2E3.A and consumed by Phase 2E3.B and 2E3.C composition root.
2. REQ_0009 explainability lineage IDs: `decision_id`, `prediction_id`, `feature_snapshot_id`, `signal_id` (signal_id is reserved for an upstream signal layer, not introduced by 2F.A).
3. REQ_0017 default-deny safety posture: live actions remain blocked, decisions are not signals, and the orchestrator decision is a candidate decision that the risk gateway (REQ_0017 milestone 3) further default-denies.
4. The trainer prediction freshness flag taxonomy (`fresh`, `stale`, `missing`) and worker health taxonomy (`HEALTHY`, `DEGRADED`, `CRITICAL`, `UNKNOWN`) already validated in 2E3.A.

## Failure modes implied by REQ_0017 default-deny posture

The orchestrator decision domain admits an `abstain` action explicitly so that the system never silently coerces an unsafe input into a tradable signal. The reason taxonomy reserves a distinct code for each abstain cause:

- `abstain_low_confidence` — calibrated confidence below the threshold the assembler will apply at 2F.B.
- `abstain_freshness_stale` — input prediction freshness flag is `stale`.
- `abstain_freshness_missing` — input prediction freshness flag is `missing`.
- `abstain_worker_degraded` — input worker health is `DEGRADED`.
- `abstain_worker_critical` — input worker health is `CRITICAL`.
- `abstain_worker_unknown` — input worker health is `UNKNOWN`.

A single explicit reason code per abstain cause is required so the explainability layer (REQ_0009) can render an unambiguous chain.

## Hard safety rules carried forward

- No `/home/wali/Desktop/AI BOT` mutation by Phase 2F at any sub-phase.
- No Redis access at any layer in any 2F authored source file.
- No live service restart, no exchange action, no leverage/margin change, no live trade enablement, no deployment, no migration, no secret exposure or commit.
- The 2F.A domain MUST validate `live_blocked is True` so any consumer that constructs a record with `live_blocked == False` fails closed at construction time.

## Constraint: no SMC / liquidity feature use

REQ_0013 SMC / liquidity features are deferred to a later phase, are shadow-only on entry, and are NOT consumed by 2F.A.

PHASE2F_LEGACY_EVIDENCE_REVIEW_READY
