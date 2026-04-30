# 10 Enterprise Website Product Requirements

## Requirement ID
V2-WEB-ENTERPRISE-001

## Product intent
V2 is a full enterprise-grade personal trading platform website, not only an observability/risk tool.

## Core requirement
- Website is the primary operator control center for all platform functions.
- UX must be professional, animated, polished, and uncluttered.
- No demo/sample/mock pages are allowed in production scope.
- Every page must be bound to actual runtime data and real system controls (or explicitly read-only, if safety-gated).

## Mandatory principles
1. Single control plane
- One website for runtime operations, audit, diagnostics, and governance.

2. Real-data enforcement
- Page readiness requires live data bindings to real APIs/streams/stores.
- Static placeholder cards are prohibited outside explicit development mode.

3. Role separation
- Operator area: day-to-day safe controls and runtime supervision.
- Admin-only area: dangerous/system-wide controls, policy and credential boundaries.

4. Safety-first control model
- High-impact actions require explicit gate checks, approvals, and audit log entry.
- Live trading controls blocked by default until readiness gates pass.

5. Auditability
- Every control interaction and config mutation must generate immutable audit events.

## Operator vs admin boundaries
### Operator-visible and operator-allowed
- Monitoring, diagnostics, read-only explainability, paper/replay operations, bounded runtime controls, safe start/stop for non-live utility components where policy allows.

### Admin-only
- Exchange credential lifecycle, RBAC policy changes, live-trading enablement gates, leverage/margin policy changes, fleet topology changes, deployment/hosting controls, dangerous config mutations.

## Non-functional requirements
- Responsive web UI with production-grade visual consistency.
- Deterministic data refresh with visible freshness/source metadata.
- Fault-tolerant page behavior under partial backend degradation.
- End-to-end traceability from UI event to backend audit record.

## Pre-architecture acceptance for this requirement
- Website scope explicitly includes all core platform domains (market universe, ingestors, feature flow, trainer/orchestrator/risk/trader fleet, storage health, audit, config, replay/paper, readiness, hosting).
- Role boundary matrix defined and enforceable via RBAC.
- No non-bound mock page remains in release scope.
