# V2 Redis Pressure Prevention Architecture

- Use Redis only for transport/cache.
- Use V2 audit ledger/Postgres/Timescale for durable history.
- Enforce maxlen/TTL at producer boundaries.
- Isolate V2 namespaces from legacy namespaces.
- Add dashboard alert bands: warn at 75%, block at 90%, critical at 95%.
- Reject unbounded streams during code review.
- Move monitor packets to local files or DB, not Redis.
- Require retention policy metadata for every stream producer.

V2_REDIS_PREVENTION_ARCHITECTURE_READY
