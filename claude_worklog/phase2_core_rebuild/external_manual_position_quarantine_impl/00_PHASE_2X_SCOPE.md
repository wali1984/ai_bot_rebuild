# Phase 2X Scope

Phase 2X adds a non-live typed external/manual position quarantine domain. It introduces value objects, a pure assembler service, a composition root, and unit tests for downstream risk-gateway hardening.

In scope:
- `ManualPositionFlag` with `manual_position_quarantined` and `manual_position_not_present`.
- `ExternalPositionQuarantineRecord` mirroring existing risk lineage IDs and carrying the five Phase 2V trainer-parity fields.
- Pure service assembly from an existing `RiskDecisionRecord`.
- Composition-root runtime with callable clock validation and no build-time clock invocation.

Out of scope: execution, paper/shadow/live traders, Redis, FastAPI surfaces, exchange calls, deployment, migrations, new lineage IDs, and live-gate changes.

PHASE_2X_SCOPE_READY
