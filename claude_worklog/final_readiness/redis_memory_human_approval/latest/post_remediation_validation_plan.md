# Post-Remediation Validation Plan

After an explicitly approved Phase 3F trim, run only read-only checks:

- `redis-cli INFO memory`
- `redis-cli XLEN liquidations:events`
- `redis-cli MEMORY USAGE liquidations:events SAMPLES 0`
- `redis-cli XINFO GROUPS liquidations:events`
- dashboard payload refresh
- runtime monitor revalidation

No live trading approval is implied by Redis remediation.

POST_REDIS_REMEDIATION_VALIDATION_PLAN_READY
