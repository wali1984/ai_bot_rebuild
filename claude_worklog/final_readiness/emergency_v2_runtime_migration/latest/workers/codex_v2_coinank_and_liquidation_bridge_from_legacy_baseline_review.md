# Codex Review: V2 CoinAnk + Liquidation Bridge From Legacy Baseline

Reviewed: 2026-05-14  
Task: `codex_review_v2_coinank_and_liquidation_bridge_from_legacy_baseline`  
Live gate: `blocked_human_only`

## Findings

No blocking findings.

## Scope Reviewed

- `v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py`
- `v2/backend/app/services/coinank_bridge/service.py`
- `v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_coinank_and_liquidation_bridge_from_legacy_baseline_LEGACY_BASELINE_ANALYSIS.md`
- `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_coinank_and_liquidation_bridge_from_legacy_baseline_legacy_behavior_mapping.json`
- `claude_worklog/final_readiness/legacy_startup_baseline_v2_migration/latest/copied_baseline_manifest.json`

I did not access the legacy live bot root.

## Legacy Baseline SHA256 Verification

`LEGACY_BASELINE_SHA256` in the V2 CLI matches `copied_baseline_manifest.json`, and the preserved files on disk match the cited hashes:

| Preserved path | SHA256 |
|---|---|
| `v2/legacy_preserved/startup_baseline/ingest/live_coinank.py` | `cd13dab55c0906c379e4116102c05f960908dd28d6b6e883ca76347cd1f144c8` |
| `v2/legacy_preserved/startup_baseline/ingest/live_coinank_global_aggregator.py` | `1f85c4532e4829aa99ddadbd6a5cd2325ef9e5c4012208eb05876c1b0187eeae` |
| `v2/legacy_preserved/startup_baseline/ingest/live_binance_liquidations.py` | `19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b` |
| `v2/legacy_preserved/startup_baseline/ingest/liquidation_bridge.py` | `5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a` |
| `v2/legacy_preserved/startup_baseline/ingest/liquidation_levels_engine.py` | `fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7` |

Verification command result:

- `python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --verify-baseline-shas`
- Result: `ok: true`, `mismatches: []`, `checked: 5`

## Plan-3 Contract Preservation

The patched legacy CoinAnk Plan-3 contracts are preserved in `v2/backend/app/services/coinank_bridge/service.py` and are covered by the integration test file:

- `PLAN3_INTERVAL_LIMITS` preserves the legacy per-interval lookback caps.
- `MAX_SIZE_LIMITS` preserves the legacy per-interval max point caps.
- `REQUIRED_COINANK_TFS` preserves the default `5m,15m,30m,1h,4h,1d` contract and the `COINANK_TFS` override.
- `PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT` remains `30`.
- `plan3_endtime_for_interval`, `plan3_historical_endtime`, and `align_end_time` preserve the documented legacy behavior.

Manual smoke verification asserted these constants and the baseline SHA contract successfully.

## Missing API Blockers

The bridge surfaces missing upstream data through `missing_api_blockers` and does not synthesize liquidation events when sources are unavailable.

Verified behavior:

- CoinAnk liquidation REST failure records `coinank_liquidation_orders_endpoint_unreachable`.
- Empty event source records `v2_liquidation_event_source_empty`.
- Missing Binance force-order WS owner records `binance_force_order_ws_owner_unbound`.
- Empty unified features records `v2_unified_features_empty`.
- With unavailable upstreams, `liquidations_persisted_total` remains `0`.
- `v2:liquidations:events` remains empty.

A manual no-write smoke run returned:

```json
{"events_smoke_total": 2, "manual_smoke": "pass", "missing_blockers": ["binance_force_order_ws_owner_unbound", "coinank_liquidation_orders_endpoint_unreachable", "v2_liquidation_event_source_empty", "v2_unified_features_empty"], "sha_checked": 5}
```

## Redis Namespace Safety

No old Redis namespace writes were found in the V2 CLI or service.

Checked explicitly for Redis mutation calls and exchange mutation calls:

- `.xadd(`
- `.set(`
- `.hset(`
- `.delete(`
- `.xdel(`
- `.xtrim(`
- `redis.Redis(`
- `redis.from_url(`
- `futures[_]create[_]order`
- `futures[_]change[_]leverage`
- `futures[_]change[_]margin[_]type`
- `create[_]order`
- `cancel[_]order`
- `set[_]leverage`
- `set[_]margin[_]mode`

Result: no matches in executable V2 bridge files.

The service data plane writes only keys beginning with:

- `v2:coinank`
- `v2:liquidations`

Legacy Redis names appear only as documented read-only contract references or payload values such as `trainer_contract_key` and `src_key`; they are not used as Redis/data-plane write keys.

## Exchange Mutation Safety

No exchange-mutating API calls were found. The bridge uses public REST GET fetch logic only and has no order, cancel, leverage, or margin mode mutation path.

The live gate remains `blocked_human_only`; the worker does not expose a path that can unlock it.

## Test Coverage Review

The integration test file covers the required contracts:

- CoinAnk liquidation events persist into V2 namespaced stream.
- Binance liquidation stream is consumed when injected or explicitly documented as delegated.
- Global aggregator contract is preserved as V2 mirrors.
- Patched legacy CoinAnk Plan-3 contracts are preserved.
- Missing API blockers are labelled on unavailable endpoints.
- Old Redis write contract is blocked.
- Real exchange mutation methods are blocked.
- Baseline SHA256 constants match the manifest and on-disk preserved files.

Environment note: `pytest` is not installed in `/usr/bin/python3`, so the direct command could not run here:

```text
/usr/bin/python3: No module named pytest
```

I performed manual import/smoke assertions instead, including SHA verification, Plan-3 constants, missing API blockers, no synthesized liquidation events, successful injected-event intake, and V2-only data-plane keys.

## Decision

GO. The baseline port preserves the required patched Plan-3 contracts, SHA citations match the copied baseline manifest and on-disk preserved files, missing API gaps are surfaced instead of fabricated liquidation data, no old Redis namespace is written, and no exchange mutation path is present.
