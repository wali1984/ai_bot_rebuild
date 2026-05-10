# V2 Redis Liquidation History Prevention Requirements

- Liquidation history must not accumulate unbounded in Redis.
- Durable liquidation history must move to V2 audit ledger, Postgres/Timescale, parquet, or compressed local archive.
- Redis should retain only bounded recent transport/cache windows.
- High-volume streams need explicit retention policy and dashboard memory bands.
- Producers must publish stream growth metrics.
- Monitor telemetry should write to files or V2 DB, not unbounded Redis streams.

V2_REDIS_LIQUIDATION_HISTORY_PREVENTION_REQUIREMENTS_READY
