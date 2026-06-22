# Codex 15M Status: Runtime Soak And Production Equivalence

Generated: `2026-06-22T00:25:50Z`

GO/NO-GO: `CODEX_RUNTIME_SOAK_AND_PRODUCTION_EQUIVALENCE_GOVERNOR_BLOCKED`

## Decision

The V2 runtime soak governor is blocked by one or more runtime checks.

This packet does not approve live, canary, exchange mutation, leverage/margin, legacy shutdown, or Redis trim.

## Frontend Truth

- V2 paper/shadow runtime is running and writing v2:* Redis keys.
- Legacy still owns production.
- Do not shut down legacy.
- Live trading is blocked.

## Runtime Counts

- V2 required loops running: `7/10`
- Required V2 namespaces present: `True`
- Payloads fresh: `False`
- Comparison fresh: `True`
- Soak minutes observed: `51743.63`
- Soak 15m ready: `False`
- Soak 1h ready: `False`
- Soak 6h ready: `False`
- Replacement scoreboard shutdown recommendation: `BLOCK_LEGACY_SHUTDOWN_PARITY_INCOMPLETE`

## Fail Blockers

- `V2_REQUIRED_PROCESS_MISSING: production_equivalence_comparator, soak_observer, payload_freshness_refresher`
- `PAYLOAD_STALE_OR_MISSING: soak_observer`
- `REPLACEMENT_SCOREBOARD_V2_RUNTIME_NOT_RUNNING`
- `V2_RUNTIME_SOAK_1H_NOT_READY_AFTER_60M`
- `V2_RUNTIME_SOAK_6H_NOT_READY_AFTER_360M`

## Shutdown Blockers

- `LEGACY_STILL_OWNS_PRODUCTION_RUNTIME`
- `LEGACY_PRODUCTION_REDIS_KEYS_STILL_ACTIVE`

## V2 Redis Counts

| Namespace | Count |
| --- | --- |
| `v2:*` | `1022810` |
| `v2:market:*` | `2688` |
| `v2:features:*` | `28226` |
| `v2:prediction:*` | `755` |
| `v2:trainer:*` | `786` |
| `v2:orchestrator:*` | `3` |
| `v2:paper:*` | `442` |
| `v2:risk:*` | `7` |

## Legacy Redis Counts

| Namespace | Count |
| --- | --- |
| `prediction:*` | `1` |
| `features:*` | `5769` |
| `signals:*` | `3` |
| `market:*` | `58` |
| `trainer:*` | `0` |

## Safety

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`
