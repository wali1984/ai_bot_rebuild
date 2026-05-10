# Redis Offload To V2 Audit Ledger Plan

1. Export stream IDs and metadata for execution/audit streams without secrets.
2. Materialize durable V2 audit-ledger records in Postgres/Timescale.
3. Verify record counts, min/max stream IDs, and checksums.
4. Require human approval before any Redis trim.
5. After approval, trim only exact reviewed keys/patterns.

REDIS_OFFLOAD_TO_V2_AUDIT_LEDGER_PLAN_READY
