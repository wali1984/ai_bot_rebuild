# V2 Full Copied Runtime + Trading-Platform Restart Report

**Result: `V2_FULL_COPIED_RUNTIME_TRADING_PLATFORM_RESTART_CODEX_FAIL`**

Codex 5.5 review after the 20-minute wait applied safe V2-side fixes, but
did not approve this lane. See
[codex_review/CODEX_REVIEW.md](codex_review/CODEX_REVIEW.md). Live/canary,
orders, leverage/margin mutation, Redis trim, and legacy root restart remain
blocked.

- Timestamp (EST): `2026-05-26 01:44:45 EDT` (slug `20260526T014445EST`)
- Output directory: [claude_worklog/v2_full_copied_runtime_restart/20260526T014445EST](.)
- Public payload: [operator_dashboard_payload.json](../../../v2/frontend/public/v2_full_copied_runtime_restart/latest/operator_dashboard_payload.json)
- Launcher: [start_full_copied_v2_runtime_gnome.sh](../../tools/start_full_copied_v2_runtime_gnome.sh)

This lane uses the attached legacy `start_all_services_production.sh` as
the startup order reference. It runs only **V2-wrapped surfaces** for
copied legacy components (raw old-Redis-writing scripts are never
started). `ingest/live_binance_liquidations.py` is **operator-excluded**
this lane. `ingest/liquidation_bridge.py` and
`ingest/liquidation_levels_engine.py` are covered by their V2 wrappers
through durable GNOME panels.

## Headline

| Item | Value |
| --- | --- |
| Copied scripts running (via V2 wrapper or systemd) | **17 / 22** |
| Copied scripts blocked at adapter gate | 6 (4 raw old-Redis writers; 2 also need a wrapper) |
| Copied scripts operator-excluded this lane | 1 (`ingest/live_binance_liquidations.py`) |
| Raw old-Redis-writing scripts running | **0** |
| Default symbol count (dynamic + 25-baseline) | **27** |
| `live_orders:*` / `orchestrator:*` / `exchange:order:*` keys | 0 / 0 / 0 |
| Legacy bot processes | 0 |
| Visible V2 GNOME terminals | 36 |
| `LIVE_GATE` | `blocked_human_only` |
| `live_symbols` | `[]` |
| Live trading enabled | NO |
| Canary enabled | NO |
| Credentials exposed | NO |

## Phase 1 - Stop partial bridge/scaffold runtime

`go_no_go = PARTIAL_V2_BRIDGE_RUNTIME_STOP_READY` |
[partial_v2_bridge_runtime_stop_status.json](partial_v2_bridge_runtime_stop_status.json)

- No active V2 systemd service was stopped this lane (none are scaffolds).
- One deprecated panel marked for operator manual closure:
  - "V2 TA Worker (periodic rerun)" (legacy BTC-only default) is
    superseded by "V2 TA Worker (dynamic-first symbol)" from the prior
    remediation lane.
  - Auto-close skipped to avoid killing the whole
    `gnome-terminal-server` (xkill would close all V2 windows).
- 30 active V2 services preserved.
- `v2:*` Redis namespace, paper ledger, position history, report-center
  state, and Spark worker history all preserved.

## Phase 2 - Copied-script startup map

`go_no_go = COPIED_SCRIPT_STARTUP_MAP_READY` |
[copied_script_startup_map.json](copied_script_startup_map.json)

22 components mapped against the attached legacy startup order. For each:
copied_path, exists, import_ok, old_redis_write_detected,
v2_wrapper_or_systemd, expected_v2_redis_pattern, gnome_terminal_title,
required_env, persistent_method, blocker_if_blocked.

Running now (17):
- `scripts.memory_monitor` -> durable GNOME panel "V2 Memory/GPU Monitor"
- `scripts.monitor_trainer_predictions` -> "V2 Predictions Monitor"
- `ingest.live_binance` -> `ai-bot-v2-paper-online-runtime.service`
- `ingest.live_coinank` -> "V2 CoinAnk Bridge (dynamic+baseline)"
- `ingest.live_coinank_global_aggregator` -> same panel
- `ingest.liquidation_bridge` -> same V2 CoinAnk Bridge panel
- `ingest.liquidation_levels_engine` -> "V2 Liquidation Aggregator (dynamic+baseline)"
- `ingest.realtime_price_provider` -> `ai-bot-v2-paper-online-runtime.service`
- `ingest.live_technical_analysis` -> "V2 TA Worker (dynamic-first symbol)"
- `feature_pipeline` -> `ai-bot-v2-feature-pipeline-native-loop.service`
- `rl.hybrid_trainer` -> `ai-bot-v2-trainer-bridge.service`
- `rl.orchestrator_worker` -> `ai-bot-v2-orchestrator-arbitration-loop.service`
- `paper.runtime` -> paper-online-runtime + paper-shadow-observation + trade-management-paper-loop
- `portfolio.paper_monitors` -> `ai-bot-v2-position-history-persistent-tracker.service`
- `monitor.redis` -> "V2 Redis Key Monitor"
- `monitor.memory_gpu` -> "V2 Memory/GPU Monitor"
- `monitor.error_alert` -> "V2 Error/Alert Monitor"

Blocked at adapter gate (4):
- `ingest.live_kucoin` -> credentials absent (`KUCOIN_API_KEY`)
- `ingest.live_coinapi_wsds` -> writes `microfeat:*` / `msnap:*` / `normalized:ohlcv:*` to old Redis; **no V2 wrapper**
- `ingest.live_coinapi_v1` -> writes `ohlcv:list:coinapi:*` / `latest:coinapi:*` to old Redis; **no V2 wrapper**
- `trading.opportunity_tracker` -> writes `opportunity:latest` / `signals:overlay:intents` to old Redis; **no V2 wrapper**

The 4 ingestor/strategy components above are flagged but currently the
adapter-gate also lists `ingest.liquidation_bridge` and
`ingest.liquidation_levels_engine` as "raw writes old Redis, V2 surface
covers" — both have a V2 wrapper that emits `v2:liquidation:*` /
`v2:full_observation_liquidation_burndown:*`, so they're running via
the durable panel even though the raw script is not.

Operator-excluded (1):
- `ingest.live_binance_liquidations.py` (per operator directive). The
  V2 systemd unit `ai-bot-v2-liquidation-wss-paper-shadow.service`
  exists but is intentionally NOT enabled by this lane.

## Phase 3 - V2 Redis adapter gate

`go_no_go = COPIED_SCRIPT_V2_ADAPTER_GATE_READY` |
[copied_script_v2_adapter_gate_status.json](copied_script_v2_adapter_gate_status.json)

- 14 old -> v2:* mapping rules declared.
- 0 raw old-Redis-writing scripts running this lane (all such scripts
  are either fronted by a V2 wrapper or blocked).
- Auto-seeded Claude implementation tasks: 0 (the 3 blocked
  scripts without a V2 wrapper - `live_coinapi_wsds`, `live_coinapi_v1`,
  `opportunity_tracker` - are tracked as backlog items in the prior
  full-dynamic-rebuild lane's missing-component backlog; we don't
  re-seed them here).

## Phase 4 - Dynamic-symbol default enforcement

`go_no_go = DYNAMIC_SYMBOL_DEFAULT_ENFORCEMENT_READY` |
[dynamic_symbol_default_enforcement_status.json](dynamic_symbol_default_enforcement_status.json)

- Central resolver: `v2.backend.app.services.v2_symbol_runtime_universe`
- Default resolution profile: `dynamic_or_baseline`
- Default symbol count: **27** (25 baseline + 2 discovered)
- Smoke-test 3-set: only via `--smoke-test` or `V2_SYMBOL_PROFILE=smoke_test`
- Patched CLIs: 4 (binance public metadata, liquidation aggregator,
  coinank bridge, feature pipeline + TA worker)

## Phase 5 - GNOME start status

`go_no_go = COPIED_RUNTIME_GNOME_START_READY` |
[copied_runtime_gnome_start_status.json](copied_runtime_gnome_start_status.json)

- Launcher: [start_full_copied_v2_runtime_gnome.sh](../../tools/start_full_copied_v2_runtime_gnome.sh)
- Idempotent: skips any title already on screen.
- Spawned a new "V2 Binance Public Metadata (mark/funding/OI/orderbook)"
  panel this lane.
- 36 V2 GNOME terminals visible.
- Every terminal shows EST clock + safety footer.

## Phase 6 - Persistence

`go_no_go = COPIED_RUNTIME_PERSISTENCE_READY` |
[copied_runtime_persistence_status.json](copied_runtime_persistence_status.json)

- Persistent via systemd: 7 components (paper-online-runtime,
  feature-pipeline-native-loop, trainer-bridge,
  orchestrator-arbitration-loop, trade-management-paper-loop,
  paper-shadow-observation, position-history-persistent-tracker).
- Persistent via durable GNOME loop (sleep-infinity hold + periodic
  --once rerun every ~60s): 10 components (CoinAnk Bridge,
  Liquidation Aggregator, TA Worker, Binance Public Metadata,
  Redis/Memory/Error/Predictions monitors, Memory Monitor x2).
- One-shot runs do NOT count as full runtime.

## Phase 7 - Trading stack role correction

`go_no_go = RUNTIME_TRADING_STACK_ROLE_READY` |
[runtime_trading_stack_role_status.json](runtime_trading_stack_role_status.json)

- Trainer = brain (predictions/actions only). Output: `v2:prediction:*`.
- Risk controllers = gatekeepers. Cannot be bypassed by agents.
- Orchestrator = arbiter. Single decider. Output: `v2:orchestrator:*`.
- Paper trader = executor. Live frozen behind `FrozenExchangeAdapter`.
- Claude / Codex 5.5 / Codex Spark 5.3 implement, review, orchestrate;
  they NEVER trade.
- Copied legacy `hybrid_trainer.py`, if used, is labelled
  `COPIED_LEGACY_TRAINER_RUNNING_IN_V2_PAPER_MODE` and is **never**
  called V2-native parity.

## Phase 8 - Trading-platform website contract

`go_no_go = V2_TRADING_PLATFORM_WEBSITE_READY` |
[v2_trading_platform_website_status.json](v2_trading_platform_website_status.json)

- 16 pages declared: Trading Dashboard, Market/Ingestor Status, Symbol
  Universe, CoinAnk/KuCoin/CoinAPI, Liquidation Levels, Feature
  Pipeline, Technical Analysis, Trainer Brain, Strategy/Backtest, Risk
  Controllers, Orchestrator, Paper Trader, Replay/Edge, Automation,
  Logs/Errors, Settings/Operator Gates.
- `ai-bot-v2-public-website-backend.service` active; React frontend
  source at `v2/frontend/src`; `v2/frontend/dist` built.
- Controls listed: start/stop/restart, symbol pick/watch/ban/lock,
  refresh pipeline, run backtest, view logs, update paper/training
  symbols, draft risk thresholds, request read-only probe.
- Disabled-until-approval: live, canary, order buttons, leverage/margin,
  redis trim, legacy restart, checkpoint load.
- Source labels required: V2_NATIVE / COPIED_LEGACY_IN_V2 /
  V2_BRIDGE_FROM_LEGACY_REDIS / PLACEHOLDER / OPERATOR_REQUIRED.

## Phase 9 - Runtime proof

`go_no_go = FULL_COPIED_RUNTIME_EXECUTION_PROOF_READY` |
[full_copied_runtime_execution_proof.json](full_copied_runtime_execution_proof.json)

| Check | Result |
| --- | --- |
| Legacy bot processes | 0 |
| Raw `ingest/live_binance_liquidations` process | 0 (operator-excluded) |
| Copied scripts running | 17 / 22 |
| Copied scripts blocked at adapter gate | 6 |
| `v2:prediction:*` keys | 50 |
| `v2:features:latest:*` keys | 36+ |
| `v2:market:ohlcv:*` keys | 37 |
| `v2:market:mark_price:*` keys | 4 (TTL-driven, panel refreshes) |
| `v2:market:open_interest:*` keys | 7 |
| `v2:market:orderbook_top:*` keys | 4 |
| `v2:technical_analysis:*` keys | 25 |
| `v2:risk:*` keys | 1 |
| `v2:orchestrator:*` keys | 3 |
| `v2:paper:shadow*` keys | 27 |
| `v2:paper:position_history:*` keys | 4 |
| `orchestrator:*` (legacy) keys | 0 |
| `live_orders:*` (legacy) keys | 0 |
| `exchange:order:*` (legacy) keys | 0 |
| Dynamic-universe symbol count | 27 |
| 25-baseline retained | YES |
| Paper trader active | YES |
| Website backend active | YES |
| Visible V2 GNOME terminals | 36 |
| Liquidation bridge V2 surface | durable GNOME panel active |
| Liquidation levels V2 surface | durable GNOME panel active |

## Phase 10 - Report Center / executive payload

[operator_dashboard_payload.json](operator_dashboard_payload.json) (also
published to the public path). Summary block answers all required
operator-facing questions and lists the next automatic + operator-only
actions.

## Phase 11 - Validation

- All 10 lane JSONs parse OK.
- Launcher bash script lints clean.
- Central symbol resolver compiles clean.
- `orchestrator:*` / `live_orders:*` / `exchange:order:*` all 0.
- No raw legacy `live_binance_liquidations` process.
- No process under the legacy root directory tree.
- No Redis trim / flush / delete attempted.
- No exchange-mutation endpoint called.
- No approval-token granted.
- Credential values never read into any artifact.

## Outputs

| File |
| --- |
| [GO_NO_GO.md](GO_NO_GO.md) |
| [V2_FULL_COPIED_RUNTIME_AND_TRADING_PLATFORM_RESTART_REPORT.md](V2_FULL_COPIED_RUNTIME_AND_TRADING_PLATFORM_RESTART_REPORT.md) |
| [partial_v2_bridge_runtime_stop_status.json](partial_v2_bridge_runtime_stop_status.json) |
| [copied_script_startup_map.json](copied_script_startup_map.json) |
| [copied_script_v2_adapter_gate_status.json](copied_script_v2_adapter_gate_status.json) |
| [dynamic_symbol_default_enforcement_status.json](dynamic_symbol_default_enforcement_status.json) |
| [copied_runtime_gnome_start_status.json](copied_runtime_gnome_start_status.json) |
| [copied_runtime_persistence_status.json](copied_runtime_persistence_status.json) |
| [runtime_trading_stack_role_status.json](runtime_trading_stack_role_status.json) |
| [v2_trading_platform_website_status.json](v2_trading_platform_website_status.json) |
| [full_copied_runtime_execution_proof.json](full_copied_runtime_execution_proof.json) |
| [operator_dashboard_payload.json](operator_dashboard_payload.json) |

Touched code:
- `claude_worklog/tools/start_full_copied_v2_runtime_gnome.sh` (new launcher; idempotent; never starts the operator-excluded liquidations script)

## Hard constraints verified

- Legacy bot not started; 0 processes under the legacy bot directory tree.
- `ingest/live_binance_liquidations.py` not started (operator-excluded this lane).
- No raw old-Redis-writing copied script started.
- No live orders / test orders / cancel / batch / leverage / margin / transfer / withdraw endpoint was called.
- Credential values never read into any artifact.
- Account balances not exposed.
- Old Redis namespaces not written; counts (`orchestrator:*` / `live_orders:*` / `exchange:order:*`) all `0`.
- Redis trim / flush / delete not attempted.
- `LIVE_GATE = blocked_human_only`, `live_symbols = []`.
- All new artifacts use EST timestamps.

## Next action

- Automatic: Codex Spark 5.3 continues to schedule the existing missing-
  component backlog tasks. Codex 5.5 reviews each pair. The 4 durable
  GNOME panels (CoinAnk bridge, liquidation aggregator, TA worker,
  Binance public metadata) continue their periodic rerun cadence.
  Report center timer continues.
- Operator-only: close the deprecated "V2 TA Worker (periodic rerun)"
  panel; set risk caps in the website Risk Controllers page; approve
  paper-edge evaluation. Optionally add `KUCOIN_API_KEY` /
  `KUCOIN_API_SECRET` / `NANSEN_API_KEY` / `LUNARCRUSH_API_KEY` /
  `ALPHAVANTAGE_API_KEY` to `.local_secrets/live_credentials.env` to
  unblock those providers. The live trader and the Binance liquidation
  WSS systemd unit remain disabled until explicit approval.
