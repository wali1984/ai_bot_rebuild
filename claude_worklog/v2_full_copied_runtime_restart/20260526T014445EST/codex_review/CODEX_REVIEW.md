# Codex 5.5 Review - V2 Full Copied Runtime And Trading Platform Restart

Generated: 2026-05-26T02:23:26-0400 EDT

## Verdict

`V2_FULL_COPIED_RUNTIME_TRADING_PLATFORM_RESTART_CODEX_FAIL`

Codex applied safe V2-side fixes, but the packet cannot pass. The active core
runtime defaults were remediated during review, yet V2 source still contains
BTC-only and BTC/ETH/SOL defaults outside explicit smoke-test mode, and the
restart packet still overstates readiness/role truth.

## Safe Fixes Applied

- Replaced active default symbol handling with the shared dynamic universe /
  25-symbol baseline resolver in:
  - `v2_native_ingestors_live_loop.py`
  - `v2_feature_pipeline_native_loop.py`
  - `v2_rl_core_inference_loop.py`
  - `v2_liquidation_wss_loop.py`
  - `v2_position_history_persistent_tracker.py`
  - `paper_online_runtime.py`
  - `v2_feature_snapshot_builder.py`
- Tightened `v2_symbol_runtime_universe.resolve_symbols()` so explicit
  BTC/ETH/SOL is rejected unless `--smoke-test` or
  `V2_SYMBOL_PROFILE=smoke_test` is present.
- Removed the active user-systemd position-history `--symbols BTCUSDT,ETHUSDT,SOLUSDT`
  override and reloaded user systemd.
- Restarted only affected V2 paper/shadow services. Legacy root was not
  restarted.
- Terminated the deprecated BTC-only `V2 TA Worker` GNOME panel after confirming
  the newer dynamic TA panel exists.
- Added an in-progress dynamic payload for the native ingestor so the Report
  Center does not show a stale 3-symbol state during the slower 27-symbol fetch.
- Added missing safety fields to the feature snapshot builder payload:
  `live_symbols=[]`, `approves_live=false`, `approves_canary=false`,
  `places_real_order=false`, `writes_exchange_orders=false`.
- Registered `v2_full_copied_runtime_restart` in Report Center.
- Added focused regression coverage:
  `v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py`.

## Pass/Fail Matrix

| Check | Result | Evidence |
| --- | --- | --- |
| Partial bridge/scaffold runtime stopped or superseded | PASS after Codex fix | Deprecated BTC-only TA panel process was terminated; only the dynamic TA panel remains. |
| Copied safe scripts started from AI BOT REBUILD | PARTIAL | Multiple copied surfaces are active, but startup map still has inconsistencies and wrappers counted as copied-script starts. |
| Binance liquidation script not started | PASS | No `live_binance_liquidations.py` process observed. |
| `liquidation_bridge` / `liquidation_levels` started or blocked | PARTIAL | Raw old-Redis versions remain blocked; V2 surfaces are active through wrappers. |
| No old Redis writes occur | PARTIAL | No order/live/exchange/leverage/margin keys observed; preserved legacy data namespaces still exist and a writer-level proof is not complete. |
| Dynamic symbol universe default | PASS for remediated active lanes | Active core payloads were changed to dynamic/25 baseline and explicit 3-symbol calls now fail closed without smoke-test opt-in. |
| 25-symbol baseline retained | PASS | Resolver default includes the 25-symbol baseline. |
| No BTC-only or BTC/ETH/SOL default remains | FAIL | Remaining source defaults exist in non-remediated V2 modules. |
| Website is trading platform, not coding/report page | PARTIAL | Packet is declarative; rendered proof of runtime/control-state coverage is still missing. |
| Trainer/risk/orchestrator/trader roles correct | FAIL | Trainer bridge/parity mode is still described too strongly as V2-native in packet status. |
| Agents are not trading agents | PASS | Claude/Codex/Spark remain implementation/review/scheduler roles only. |
| No live/canary/shutdown approvals | PASS | No approval field or runtime key found enabling live/canary/shutdown. |
| `LIVE_GATE=blocked_human_only` | PASS | Runtime payloads and process env remain blocked. |
| `live_symbols=[]` | PASS after Codex fix | Active payloads expose an empty live symbol list. |

## Remaining Blockers

1. Hard-coded non-smoke defaults remain in V2 source, including:
   - `v2_alt_data_symbol_universe_scoring.py`
   - `v2_full_observation_builder_status.py`
   - `v2_nansen_altdata_ingestor.py`
   - `v2_alt_data_symbol_candidate_publisher.py`
   - `v2_feature_pipeline_native.py`
   - `v2_market_ingestor.py`
   - `v2_alternative_data_status.py`
   - `v2_website_redis_bridge_status.py`
   - `v2_native_edge_proof_evaluator.py`
   - `v2_post_hoc_replay_outcome_miner.py`
   - `v2_position_price_tracking_recorder.py`
   - `v2_lunarcrush_altdata_ingestor.py`
   - `readonly_market_exchange_data_plane.py`
   - `native_runtime_migration/*` constants labelled as active symbols.
2. The copied-runtime startup map still mixes raw copied scripts, V2 wrappers,
   and blocked old-Redis components, so "copied safe scripts running" is not
   fully proven.
3. The trainer role must stay labelled as copied/parity/baseline bridge until
   a native trainer checkpoint and native training path are proven. It cannot
   be called V2-native readiness.
4. Website status still needs rendered/control-center evidence showing real
   runtime state, missing components, disabled live/order controls, and safety
   fields. The current packet alone is report/declaration heavy.
5. Remaining old Redis namespaces contain preserved legacy data. That is not
   deletion-worthy, but current-writer proof must stay separate from key-count
   proof.

## Verification

- `python3 -m py_compile` passed for touched V2 modules and the report registry.
- `pytest v2/backend/tests/unit/cli/test_v2_dynamic_runtime_symbol_defaults.py -q`
  passed: 4 tests.
- Redis order/live/exchange mutation patterns observed at zero:
  `orchestrator:*`, `live_orders:*`, `exchange:order:*`, `order:*`,
  `*leverage*`, `*margin*`.

