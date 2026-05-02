# Redis Key and Stream Expectations

| category | expectation |
|---|---|
| feature_pipeline | reads market-data streams; writes feature/state keys; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT |
| infra | Redis service itself; V2 must not restart or mutate legacy Redis |
| ingestor | reads config/env; writes market-data keys/streams; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT |
| market_data_bridge | reads raw market-data streams; writes derived liquidation/price streams; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT |
| monitor | read-only liveness/log/Redis checks where applicable |
| orchestrator | reads predictions/proposals/signals; writes decisions/intents; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT |
| trader | reads decisions/intents and exchange state; writes execution/order state in legacy runtime; V2 must paper/shadow first |
| trainer | reads feature/state keys; writes predictions/proposals/signals; exact keys UNKNOWN_REQUIRES_READ_ONLY_AUDIT |

V2 policy:
- legacy Redis is read-only.
- V2 writes only to `v2:*` namespace.
- durable lineage belongs in DB/audit ledger, not unbounded Redis streams.

REDIS_EXPECTATIONS_READY
