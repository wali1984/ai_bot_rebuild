# CoinAnk Runtime Contract Check

All Redis evidence was collected with read-only commands only: `PING`, `TYPE`, `GET`, `HGETALL`, `XLEN`, `XREVRANGE`, and `SCAN`.

| Item | Value |
|---|---|
| redis ping | `PONG` |
| classifications | `COINANK_PATCH_RUNTIME_CURRENT, COINANK_MANIFEST_MISSING, COINANK_GLOBAL_11_KEY_CONTRACT_CURRENT, COINANK_FORBIDDEN_MARKET_SOURCE_OBSERVED, COINANK_CONTRACT_BLOCKED` |
| missing evidence count | `4` |
| liquidations:events status | `STALE` |
| global 11 current | `CURRENT` |

## Key Status

| Item | Value |
|---|---|
| heartbeat:IngestCoinAnk | `CURRENT` |
| heartbeat:CoinAnkIngest | `CURRENT` |
| coinank:runtime:last_cycle_id | `MISSING_EVIDENCE` |
| coinank:runtime | `MISSING_EVIDENCE` |
| coinank:feature_manifest | `MISSING_EVIDENCE` |
| coinank:endpoints | `MISSING_EVIDENCE` |
| coinank:endpoint_manifest | `MISSING_EVIDENCE` |
| coinank:cycle_log | `MISSING_EVIDENCE` |
| coinank:monitor:last_report | `MISSING_EVIDENCE` |
| coinank:radar:symbol_scores | `MISSING_EVIDENCE` |
| raw:coinank:liquidation_orders:global | `CURRENT` |
| unified_features:BTCUSDT:5m | `CURRENT` |
| unified_features:ETHUSDT:15m | `CURRENT` |

## Endpoint Key Scan Counts

| Item | Value |
|---|---|
| indicator_smc | `0` |
| agg_cvd | `46` |
| weighted_funding | `0` |
| liquidation_rank | `0` |
| global_coinank | `20` |

## Missing Evidence

- indicator_smc: no matching endpoint feature keys observed
- weighted_funding: no matching endpoint feature keys observed
- liquidation_rank: no matching endpoint feature keys observed
- endpoint manifest keys coinank:endpoint_manifest / coinank:endpoints not observed
