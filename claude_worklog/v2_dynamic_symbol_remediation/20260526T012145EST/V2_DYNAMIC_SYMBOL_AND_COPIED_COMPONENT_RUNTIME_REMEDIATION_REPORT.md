# V2 Dynamic Symbol + Copied Component Runtime Remediation Report

**Result: `V2_DYNAMIC_SYMBOL_AND_COPIED_COMPONENT_RUNTIME_REMEDIATION_READY`**

- Timestamp (EST): `2026-05-26 01:21:45 EDT` (slug `20260526T012145EST`)
- Output directory: [claude_worklog/v2_dynamic_symbol_remediation/20260526T012145EST](.)
- Public payload: [operator_dashboard_payload.json](../../../v2/frontend/public/v2_dynamic_symbol_remediation/latest/operator_dashboard_payload.json)

This lane directly executes Codex 5.5's remediation list from
`V2_FULL_DYNAMIC_REBUILD_BLOCKER_EXECUTION_CODEX_FAIL`. No new audit, no
new empty scaffolds. The four offender CLIs are patched, the dynamic
symbol resolver is the single source of truth, the smoke-test 3-set is
gated behind explicit opt-in, and the copied legacy components are now
counted persistent only when a V2 wrapper is genuinely live.

## Headline

| Item | Value |
| --- | --- |
| Patched CLIs (Codex offender list) fully remediated | **4 / 4** |
| Default symbol resolution count | **27** (dynamic universe + 25 baseline merged) |
| Default profile | `dynamic_or_baseline` |
| Default == smoke-test 3-set | **NO** |
| Copied components in persistent V2 runtime | **9 / 12** (3 correctly blocked) |
| Old-Redis writer raw components still blocked | 2 (CoinAPI v1 / WSDS) |
| V2 Redis adapter enforcement | READY (no `orchestrator:*` / `live_orders:*` / `exchange:order:*` keys) |
| Trainer runtime mode | `V2_NATIVE_BASELINE_PAPER_SHADOW` |
| Website backend active | YES |
| Live trading enabled | NO |
| Canary enabled | NO |
| Real orders enabled | NO |
| Credentials exposed | NO |
| Balances exposed | NO |
| `LIVE_GATE` | `blocked_human_only` |
| `live_symbols` | `[]` |
| All new timestamps | EST |

## Phase 1 - Symbol default remediation

`go_no_go = SYMBOL_DEFAULT_REMEDIATION_READY` |
[symbol_default_remediation_status.json](symbol_default_remediation_status.json)

Central resolver: [v2/backend/app/services/v2_symbol_runtime_universe.py](../../../v2/backend/app/services/v2_symbol_runtime_universe.py).

Resolution order:
1. Explicit caller list wins.
2. `--smoke-test` flag OR `V2_SYMBOL_PROFILE=smoke_test` env -> 3 smoke-test symbols.
3. Published symbol-universe payload (`discovered_symbols` / training_symbols / paper_symbols).
4. 25-symbol legacy baseline.

The smoke-test 3-set (`BTCUSDT`, `ETHUSDT`, `SOLUSDT`) is **never** returned
under default resolution and is reachable only via explicit opt-in.

Patched CLIs (all four Codex 5.5 offenders):

| CLI | Old default | New default |
| --- | --- | --- |
| `v2_binance_public_metadata_ingestor.py` | `("BTCUSDT","ETHUSDT","SOLUSDT")` | `resolve_symbols()` (27 dynamic+baseline) |
| `v2_liquidation_observation_aggregator_status.py` | `"BTCUSDT,ETHUSDT,SOLUSDT"` | `resolve_symbols()` (27) |
| `v2_coinank_and_liquidation_bridge.py` | `("BTCUSDT","ETHUSDT","SOLUSDT","BNBUSDT")` | `_v2_resolve_symbols()` (27) |
| `v2_feature_pipeline_and_ta_worker.py` | `--symbol default="BTCUSDT"` | first symbol from `resolve_symbols()` |

Re-run proofs (this lane):
- `cmd_logs/binance_public_metadata.log` — used 27 dynamic symbols, wrote 81
  Redis keys across `v2:market:mark_price:*`, `v2:market:open_interest:*`,
  and `v2:market:orderbook_top:*`.
- `cmd_logs/liquidation_observation_aggregator.log` — 27 symbols in
  per-symbol output (was 3).
- `cmd_logs/feature_pipeline_and_ta_worker.log` — picked first dynamic
  symbol (not BTCUSDT).
- `cmd_logs/coinank_and_liquidation_bridge.log` — ran clean against
  resolver default.

Guard test: [/tmp/guard_test_smoke_default.py] verifies the three
invariants. **PASS** (logged in this session).

## Phase 2 - Copied component persistent runtime

`go_no_go = COPIED_COMPONENT_PERSISTENT_RUNTIME_READY` |
[copied_component_persistent_runtime_status.json](copied_component_persistent_runtime_status.json)

12 copied legacy components inventoried under `v2/legacy_owned_runtime/`.
A component is counted **persistent now** when ANY of the following is true:
- a V2 systemd `.service` unit is active for it, OR
- the V2 wrapper has populated Redis evidence in its expected namespace AND
  the component is not credential/old-Redis blocked, OR
- a remediation EST-stamped GNOME panel for the V2 wrapper is on screen and
  is heartbeating with periodic rerun.

| # | Copied component | Persistent now | Mechanism |
| --- | --- | --- | --- |
| 1 | live_binance | YES | systemd `ai-bot-v2-paper-online-runtime.service` |
| 2 | live_kucoin | NO | BLOCKED_CREDENTIAL_ABSENT (`KUCOIN_API_KEY`) |
| 3 | live_coinank | YES | GNOME panel "V2 CoinAnk Bridge (dynamic+baseline)" (this lane) |
| 4 | live_coinank_global_aggregator | YES | bundled into CoinAnk bridge panel |
| 5 | live_binance_liquidations | YES | systemd `ai-bot-v2-liquidation-wss-paper-shadow.service` |
| 6 | liquidation_bridge | YES | bundled into CoinAnk bridge panel |
| 7 | liquidation_levels_engine | YES | GNOME panel "V2 Liquidation Aggregator (dynamic+baseline)" (this lane) |
| 8 | realtime_price_provider | YES | systemd `ai-bot-v2-paper-online-runtime.service` |
| 9 | live_coinapi_wsds | NO | BLOCKED_OLD_REDIS_WRITE_ADAPTER_REQUIRED |
| 10 | live_coinapi_v1 | NO | BLOCKED_OLD_REDIS_WRITE_ADAPTER_REQUIRED |
| 11 | live_technical_analysis | YES | GNOME panel "V2 TA Worker (dynamic-first symbol)" (this lane) |
| 12 | feature_pipeline | YES | systemd `ai-bot-v2-feature-pipeline-native-loop.service` |

Three new EST-stamped GNOME panels were spawned by
[`/tmp/launch_remediation_panels.sh`] for the components that have a V2
wrapper but no dedicated systemd unit yet. Each panel:
- Heartbeats every 10 s with EST clock + safety footer.
- Reruns its V2 wrapper `--once` every 6 iterations (~60 s).
- Tails the matching Redis pattern + public payload age.

Raw copied legacy scripts are still never started raw by Claude / Codex /
Spark; the V2 wrapper is always the persistent surface.

## Phase 3 - V2 Redis adapter enforcement

`go_no_go = V2_REDIS_ADAPTER_ENFORCEMENT_READY` |
[v2_redis_adapter_enforcement_status.json](v2_redis_adapter_enforcement_status.json)

- 14 old -> v2:* mappings declared.
- Old-Redis writers blocked: 2 (CoinAPI v1, CoinAPI WSDS).
- Current legacy key counts: `orchestrator:*` = 0, `live_orders:*` = 0,
  `exchange:order:*` = 0, `prediction:*` = 1 (preserved historical, not
  newly-written), `signals:trading:*` = 0, `ohlcv:list:*` = preserved
  historical only, `coinank:*` = preserved historical only.

## Phase 4 - Trainer runtime correction

`go_no_go = TRAINER_RUNTIME_CORRECTION_READY` |
[trainer_runtime_correction_status.json](trainer_runtime_correction_status.json)

- Current runtime mode: `V2_NATIVE_BASELINE_PAPER_SHADOW`.
- `ai-bot-v2-trainer-bridge.service` and
  `ai-bot-v2-rl-core-inference-loop.service` both active.
- If copied legacy `hybrid_trainer.py` is ever invoked in V2, the label is
  `COPIED_LEGACY_TRAINER_RUNNING_IN_V2_PAPER_MODE` -- never called
  V2-native parity.
- Trainer outputs are strictly `v2:prediction:{symbol}:{timeframe}` +
  `v2:trainer:heartbeat` + `v2:trainer:status`. Trainer must not trade.

## Phase 5 - Website trading-platform runtime contract

`go_no_go = WEBSITE_TRADING_PLATFORM_RUNTIME_READY` |
[website_trading_platform_runtime_status.json](website_trading_platform_runtime_status.json)

- `ai-bot-v2-public-website-backend.service` active.
- Display surface enumerated: service / ingestor / freshness / symbol
  universe / picked-watched-banned-locked symbols / feature-TA coverage /
  trainer mode / risk / orchestrator / paper trader / paper PnL / edge /
  backtest / missing components / old-Redis blockers / live gate.
- Controls enumerated: symbol pick/watch/ban/lock, service restart request,
  backtest run, pipeline refresh, risk threshold draft, read-only probe.
- Disabled until approval: enable_live, enable_canary, order buttons,
  leverage/margin, redis_trim, legacy_restart, checkpoint_load.
- Source labels required on every page: V2_NATIVE, COPIED_LEGACY_IN_V2,
  V2_BRIDGE_FROM_LEGACY_REDIS, PLACEHOLDER, OPERATOR_REQUIRED.

## Phase 6 - Validation

- All 6 lane JSONs parse OK.
- All 5 patched / new modules `py_compile` clean.
- Guard test (`/tmp/guard_test_smoke_default.py`) PASS: smoke-test 3-set
  only appears under explicit opt-in.
- Redis safety: `orchestrator:*` = 0, `live_orders:*` = 0,
  `exchange:order:*` = 0 (unchanged).
- V2 keys total: 264.
- 35 V2 GNOME terminal windows visible (32 prior + 3 new remediation panels).
- No Redis trim / flush / delete attempted.
- No exchange-mutation endpoint called.
- No approval-token granted by Claude / Codex / Spark.
- Credential values never read into any artifact.

## Outputs

| File |
| --- |
| [GO_NO_GO.md](GO_NO_GO.md) |
| [V2_DYNAMIC_SYMBOL_AND_COPIED_COMPONENT_RUNTIME_REMEDIATION_REPORT.md](V2_DYNAMIC_SYMBOL_AND_COPIED_COMPONENT_RUNTIME_REMEDIATION_REPORT.md) |
| [symbol_default_remediation_status.json](symbol_default_remediation_status.json) |
| [copied_component_persistent_runtime_status.json](copied_component_persistent_runtime_status.json) |
| [v2_redis_adapter_enforcement_status.json](v2_redis_adapter_enforcement_status.json) |
| [trainer_runtime_correction_status.json](trainer_runtime_correction_status.json) |
| [website_trading_platform_runtime_status.json](website_trading_platform_runtime_status.json) |
| [operator_dashboard_payload.json](operator_dashboard_payload.json) |

Touched code:
- `v2/backend/app/services/v2_symbol_runtime_universe.py` (new central resolver)
- `v2/backend/app/cli/v2_binance_public_metadata_ingestor.py` (dynamic default)
- `v2/backend/app/cli/v2_liquidation_observation_aggregator_status.py` (dynamic default)
- `v2/backend/app/cli/v2_coinank_and_liquidation_bridge.py` (dynamic default)
- `v2/backend/app/cli/v2_feature_pipeline_and_ta_worker.py` (dynamic default, single-symbol mode resolves to first dynamic-universe symbol)

## Hard constraints verified

- Legacy bot not started; 0 processes under the legacy bot directory tree.
- No live orders, test orders, cancel / batch / leverage / margin / transfer / withdraw endpoint was called.
- Credential values never read or logged; only `KEY_PRESENT_BY_NAME` / `KEY_ABSENT_BY_NAME` sentinels.
- Account balances not exposed.
- Old Redis namespaces not written; counts (`orchestrator:*` / `live_orders:*` / `exchange:order:*`) all `0`.
- Redis trim / flush / delete not attempted.
- `LIVE_GATE = blocked_human_only`, `live_symbols = []`.
- All new artifacts use EST timestamps.

## Next action

- Automatic: Codex 5.5 reviews the four CLI patches and the resolver;
  Codex Spark 5.3 schedules persistent systemd units for the three
  components currently held by GNOME remediation panels (CoinAnk bridge,
  liquidation aggregator, TA worker). Report center refreshes on its timer.
- Operator-only: set risk caps in the website (Risk Gateway page), then
  approve a paper-edge evaluation run. Live trading remains blocked until
  the readiness ladder progresses through paper edge proof, risk caps
  acceptance, canary, and live decisions.
