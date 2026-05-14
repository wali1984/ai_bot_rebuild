# v2_coinank_and_liquidation_bridge — Legacy-Baseline Port Report

**Task:** `claude_port_v2_coinank_and_liquidation_bridge_from_legacy_baseline`
**Lane:** runtime_migration
**Worker ID:** `v2_coinank_and_liquidation_bridge`
**Live gate:** `blocked_human_only` (immutable from this worker)
**Status:** EMITTED, pending Codex review.

## What was emitted

| Output file | Role |
|---|---|
| `v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py` | CLI entrypoint (`python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --loop --interval 5`). Public REST GETs only; writes V2 status payload + V2 data-plane file; updates the operator coinank_market_intelligence_status.json payload. |
| `v2/backend/app/services/coinank_bridge/service.py` | Pure service layer with `CoinankBridgeService`, Plan-3 contracts, 11-key contract, liquidation-event canonical schema, levels-engine algorithm. No legacy Redis writes. |
| `v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py` | All 7 required tests + 4 helper-shape tests (SHA-match, required public payload fields, levels-engine staleness contract, build_status helper). |
| `v2/frontend/public/operator_runtime/coinank_market_intelligence/latest/coinank_market_intelligence_status.json` | Seeded public payload for the operator dashboard with all required public fields. |
| `..._LEGACY_BASELINE_ANALYSIS.md` | Legacy-anchored analysis with SHA citations (all 5 files). |
| `..._legacy_behavior_mapping.json` | Machine-readable legacy → V2 mapping. |
| `..._status.json` | Worker status (this file's machine-readable peer). |
| `..._report.md` | This file. |

## Legacy baselines anchored

The worker is anchored to five preserved baselines under
`v2/legacy_preserved/startup_baseline/ingest/`. SHAs are taken verbatim
from `copied_baseline_manifest.json` and embedded as
`LEGACY_BASELINE_SHA256` inside the CLI module:

- `ingest/live_coinank.py` — `cd13dab55c0906c379e4116102c05f960908dd28d6b6e883ca76347cd1f144c8`
- `ingest/live_coinank_global_aggregator.py` — `1f85c4532e4829aa99ddadbd6a5cd2325ef9e5c4012208eb05876c1b0187eeae`
- `ingest/live_binance_liquidations.py` — `19711590a3d194fd05ae3be85ef7bd6dec397f6394d02f7e91008c44c310131b`
- `ingest/liquidation_bridge.py` — `5d70e395938228b61162b531310cd751403ddfeebb8920429e73cdcdbe35d48a`
- `ingest/liquidation_levels_engine.py` — `fed3c90b5193c27d24dc183089730bda49ff69a1758b597e23a154397f839df7`

The test
`test_ingestor_sha256_matches_copied_baseline_manifest_contract`
reads the manifest at test-time and asserts each constant matches; it
also recomputes the SHA against the on-disk preserved file if present.

## Plan-3 contracts (preserved verbatim)

The patched Plan-3 contracts from `live_coinank.py` (L576-580, L583-598,
L606-610, L915-927, L970-993) are preserved verbatim:

- `PLAN3_INTERVAL_LIMITS` — per-interval max lookback days.
- `MAX_SIZE_LIMITS` — per-interval max points to avoid error code 7.
- `REQUIRED_COINANK_TFS` — defaults to `("5m","15m","30m","1h","4h","1d")`,
  with the `COINANK_TFS` env override preserved.
- `PLAN3_HISTORICAL_ENDTIME_DAYS_DEFAULT = 30` for `liquidation_orders`.
- `plan3_endtime_for_interval(interval)` aligns to interval boundary and
  caps to `now - max_days*86400_000 + 60min`.

## Global 11-key contract (preserved verbatim, V2-mirrored)

The 11 trainer-contract names from
`rl/hybrid_trainer.py::_load_global_features` (documented in the legacy
`live_coinank_global_aggregator.py` docstring L7-19) are preserved as
`GLOBAL_11_KEY_CONTRACT`. V2 writes them as **V2-namespaced mirror keys**
(`v2:coinank:global:{name}:latest`); the legacy
`features:global_coinank:{name}:latest` keys are NEVER written. The
trainer-contract name is carried inside the payload (`trainer_contract_key`)
so a downstream V2 trainer can map by name without re-translation.

## Liquidation pipeline (preserved verbatim)

The legacy canonical event schema from
`liquidation_bridge.publish` (file L56-126) and the deque-based decay
weighting from `liquidation_levels_engine.LevelEngine._compute_mapping`
(file L341-460) are preserved verbatim. The legacy WS consumer
`live_binance_liquidations.consume_force_orders` is **explicitly delegated**
to a separate V2 WS worker; the bridge CLI itself does **not** open WS
sessions, which keeps tests pure-Python and the bridge independent of any
asyncio reactor.

## missing_api_blockers policy (NEVER synthesize)

When upstream data is unavailable, the worker labels a missing-API blocker
in three categories:

- `coinank_liquidation_orders_endpoint_unreachable` — CoinAnk public REST
  liquidation_orders failed (non-2xx or unparseable).
- `binance_force_order_ws_owner_unbound` — no binance force_order events
  injected; WS owner is separate.
- `v2_liquidation_event_source_empty` — no event source produced any
  events this cycle.

The worker NEVER fabricates events to fill these gaps. Test
`test_missing_api_blockers_labelled_when_endpoint_unavailable` enforces
this contract.

## V2 namespace (only place V2 writes)

| V2 key                                                     | role                                                                              |
|------------------------------------------------------------|-----------------------------------------------------------------------------------|
| `v2:coinank:global:{name}:latest`                          | global 11-key aggregator output (V2 mirror)                                       |
| `v2:coinank:endpoint:{endpoint}:latest`                    | latest Plan-3 endpoint snapshot                                                   |
| `v2:coinank:endpoint_manifest`                             | active endpoint manifest                                                          |
| `v2:coinank:cycle_runtime`                                 | last completed cycle metadata                                                     |
| `v2:liquidations:events`                                   | canonical liquidation event list                                                  |
| `v2:liquidations:stats:{1m,5m,15m,30m,1h}`                 | windowed aggregations                                                             |
| `v2:liquidations:levels:{symbol}:{tf}`                     | computed long/short level mapping                                                 |
| `v2:liquidations:dedup_index`                              | dedup record (in-memory; TTL'd)                                                   |
| `v2:liquidations:missing_api_blockers`                     | list of `missing_api_blocker` records (NEVER replaced by synthesis)               |

## Tests (required + extras)

Required:

1. `test_coinank_liquidation_events_persisted_into_v2_namespaced_stream`
2. `test_binance_liquidation_stream_consumed_or_explicitly_documented_as_optional`
3. `test_global_aggregator_logic_preserved_or_replaced_with_documented_reason`
4. `test_patched_legacy_coinank_plan3_contracts_preserved`
5. `test_missing_api_blockers_labelled_when_endpoint_unavailable`
6. `test_no_old_redis_write_contract`
7. `test_no_real_exchange_mutating_method_invoked_contract`

Extras:

- `test_required_public_payload_fields_present`
- `test_ingestor_sha256_matches_copied_baseline_manifest_contract`
- `test_levels_engine_preserves_staleness_and_bucket_width_contract`
- `test_build_status_includes_all_required_public_payload_fields`

## Required public payload fields (all surfaced)

`worker_id`, `last_run_ts`, `liquidations_persisted_total`,
`funding_freshness`, `oi_freshness`, `long_short_freshness`,
`missing_api_blockers`, `legacy_baseline_source_paths`,
`legacy_baseline_source_sha256_list`, `live_gate`, `current_gate_state`,
`freshness_seconds`.

## Runnable invocation

```
python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --loop --interval 5
```

For ad-hoc verification:

```
python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --once
python3 -m v2.backend.app.cli.v2_coinank_and_liquidation_bridge --verify-baseline-shas
pytest v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py -q
```

## Next steps

1. Supervisor materializes the BEGIN_FILE blocks emitted by this task.
2. Run `pytest v2/backend/tests/integration/cli/test_v2_coinank_and_liquidation_bridge.py`.
3. Trigger `codex_review_v2_coinank_and_liquidation_bridge_from_legacy_baseline`.
