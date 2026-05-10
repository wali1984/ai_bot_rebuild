# Redis Retention Policy

- Redis is transport/cache only, not durable audit storage.
- Live signal streams require bounded retention sufficient for consumer recovery.
- Executed/audit streams require V2 audit-ledger or Postgres offload before any trim.
- Trainer prediction streams require recent-window retention plus durable prediction ledger.
- Feature caches require TTL or bounded retention by namespace.
- Monitor telemetry should move to files/Postgres, not unbounded Redis growth.
- Unknown keys are preserved until producer and consumer are classified.

REDIS_RETENTION_POLICY_READY
