# 04 Redis Namespace and Retention Plan

## Namespace policy
- V2 writes only to `v2:*`.
- Legacy Redis keys are read-only to V2.
- No deletion/mutation of legacy namespaces.

## Retention policy
- Hot streams use bounded retention (`MAXLEN`/time-based archival policy).
- Audit ledger is offloaded to database as source of truth.
- Redis is for short-lived operational state, not infinite history.

## Memory guardrails
- Warning band: 85%
- Elevated band: 90%
- Critical band: 95%

## Legacy finding and constraint
- Legacy Redis reached approximately 96.8%.
- Therefore V2 cannot permit unbounded Redis growth.

## V2 key categories (examples)
- `v2:universe:*`
- `v2:selection:*`
- `v2:monitor:*`
- `v2:evidence:*`
- `v2:risk:*`
- `v2:fleet:*`

## Operational rules
- Every V2 stream/hash must define retention class.
- Critical lineage and governance records must be mirrored to DB.
- Memory alerts are mandatory inputs to readiness and safety dashboards.
