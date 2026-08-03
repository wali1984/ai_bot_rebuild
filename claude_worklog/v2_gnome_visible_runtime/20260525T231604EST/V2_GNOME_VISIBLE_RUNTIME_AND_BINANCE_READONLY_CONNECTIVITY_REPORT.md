# V2 Visible GNOME Runtime + Binance Read-Only Connectivity Report

**Result: `V2_GNOME_VISIBLE_RUNTIME_AND_BINANCE_READONLY_CONNECTIVITY_READY`**

- Timestamp (EST): `2026-05-25 23:16:04 EST` (slug `20260525T231604EST`)
- Output directory: [claude_worklog/v2_gnome_visible_runtime/20260525T231604EST](.)
- Public payload: [operator_dashboard_payload.json](../../../v2/frontend/public/v2_gnome_visible_runtime_and_binance_readonly/latest/operator_dashboard_payload.json)
- Launcher: [start_v2_rebuild_gnome_terminals.sh](../../tools/start_v2_rebuild_gnome_terminals.sh)
- Visible-panel module: [v2_visible_terminal_panel.py](../../tools/v2_visible_terminal_panel.py)
- Legacy-style monitor module: [v2_legacy_style_monitors.py](../../tools/v2_legacy_style_monitors.py)
- Safe credential loader: [v2/backend/app/services/safe_env_loader.py](../../../v2/backend/app/services/safe_env_loader.py)
- Read-only Binance probe: [v2/backend/app/services/binance_readonly_probe.py](../../../v2/backend/app/services/binance_readonly_probe.py)
- Exchange freeze wrapper: [v2/backend/app/services/exchange_mutation_freeze.py](../../../v2/backend/app/services/exchange_mutation_freeze.py)

## Headline

| Item | Value |
| --- | --- |
| V2 GNOME output visible | **YES** |
| Binance read-only connectivity | **READY** |
| Live orders frozen | **YES** |
| Real order attempted | **NO** |
| Real order submitted | **NO** |
| Credentials exposed in any artifact | **NO** |
| Balances exposed | **NO** |
| Total GNOME terminals open | **32** (22 service panels + 10 legacy-style monitors) |
| Active V2 systemd services | **29** |
| Legacy bot processes | **0** |
| Mutation-token hits in panel logs | **0** |
| Approval-token hits in panel logs | **0** |
| Old-Redis writes (`orchestrator:*`, `live_orders:*`, `exchange:order:*`) | **0** |
| LIVE_GATE | `blocked_human_only` |
| live_symbols | `[]` |
| All timestamps in new artifacts | **EST** (America/New_York) |

## Phase 1 - EST time standardization

`go_no_go = V2_EST_TIME_STANDARDIZATION_READY`. See
[est_time_standardization_status.json](est_time_standardization_status.json).

All new artifacts in this lane use EST. Filename slug is `YYYYMMDDTHHMMSSEST`.
Report headers and terminal panel clocks show `YYYY-MM-DD HH:MM:SS EDT/EST`.
Historical UTC artifacts are NOT rewritten.

## Phase 2 - live_credentials.env loader proof

`go_no_go = V2_LIVE_CREDENTIALS_ENV_LOADER_READY`. See
[live_credentials_env_loader_status.json](live_credentials_env_loader_status.json).

- Loader module: `v2/backend/app/services/safe_env_loader.py`
- Credentials path: `.local_secrets/live_credentials.env` (15 keys parsed)
- Canonical Binance keys present by name: `BINANCE_API_KEY -> KEY_PRESENT_BY_NAME`, `BINANCE_API_SECRET -> KEY_PRESENT_BY_NAME`
- Legacy adapter alias status (informational): `BINANCE_LIVE_API_KEY` / `BINANCE_LIVE_API_SECRET` -> KEY_ABSENT_BY_NAME
- `values_exposed_in_this_report = false`
- `values_exposed_in_worklog = false`
- `values_exposed_in_public_payload = false`
- The loader returns name -> sentinel only and never logs/writes values.
- `bind_to_environ(apply=True, keys=...)` is the only call that copies values
  into the process env, and only the names the caller explicitly requests.

## Phase 3 - Binance read-only connectivity

`go_no_go = V2_BINANCE_READONLY_CONNECTIVITY_READY`. See
[binance_readonly_connectivity_status.json](binance_readonly_connectivity_status.json).

- Public probes (no auth): `/fapi/v1/time` HTTP 200, `/fapi/v1/exchangeInfo` HTTP 200 (741 symbols, 623 TRADING).
- Signed probes (HMAC-SHA256 from credentials env): `/fapi/v1/apiTradingStatus` HTTP 200, `/fapi/v3/account` HTTP 200 (fee_tier returned; 11 assets, 0 positions; **balances redacted**).
- Forbidden endpoints (never called): order / test-order / cancel / batch / leverage / margin / transfer / withdraw.
- `credentials_values_exposed = false`, `balances_exposed = false`.
- `LIVE_GATE = blocked_human_only`, `live_symbols = []`.
- Note: `canTrade` / `canWithdraw` returned `None` on this Binance USD-M account; HTTP 200 confirms read-only connectivity. The probe does not unlock the gate.

## Phase 4 - Exchange adapter mutation freeze

`go_no_go = V2_EXCHANGE_ADAPTER_MUTATION_FREEZE_READY`. See
[exchange_adapter_mutation_freeze_status.json](exchange_adapter_mutation_freeze_status.json).

- Wrapper class: `FrozenExchangeAdapter` in `v2/backend/app/services/exchange_mutation_freeze.py`.
- Refused on every documented mutation method (adapter-native plus defense-in-depth additions for `modify`, `test`, `batch`, `set_leverage`, `set_margin_mode`, `set_position_side`, `transfer`, `withdraw`).
- Catch-all `__getattr__` refuses attacker-style names (any attribute whose name contains `_order`, `leverage`, `margin`, `position_side`, `transfer`, or `withdraw`).
- Read-only methods (`account_info_v3`, `position_risk`) forward to the upstream adapter, which still never makes a real exchange call.
- Error code: `EXCHANGE_MUTATION_FROZEN`.

## Phase 5 + 6 - GNOME terminal output

`go_no_go = V2_GNOME_TERMINAL_VISIBLE_OUTPUT_READY`. See
[gnome_terminal_visible_output_status.json](gnome_terminal_visible_output_status.json).

32 terminals are open, all heartbeating at a 10 s interval.

### 22 service panels (clear-screen + reprint every 10 s)

Each panel shows: title, EST clock, iteration counter, systemd unit
state (active/sub-state, MainPID, MemoryCurrent, ExecMainStartTimestamp),
journal tail (5 lines), log-file tail (where applicable), Redis key
counts for the relevant patterns with 3-sample keys each, public-payload
freshness (newest .json age in seconds with color cutoffs), and a
mandatory safety footer:

```
safety:  LIVE_GATE=blocked_human_only  live_symbols=[]  real_order_attempted=false  V2_PAPER_ONLY=true
```

Categories: `redis_status_monitor`, `market_runtime`, `feature_pipeline`,
`technical_analysis`, `symbol_universe`, `trainer_prediction_publisher`,
`risk_decision_loop`, `orchestrator_arbitration`, `paper_trade_management`,
`paper_ledger_paper_runtime`, `position_history_tracker`,
`liquidation_wss_paper_shadow`, `replay_outcome_miner`,
`production_equivalence_comparator`, `report_center_indexer`,
`executive_command_center`, `no_manual_next_action_policy`,
`spark_worker_pool`, `claude_workers`, `codex_workers`,
`event_watchers`, `runtime_cutover_watchdog`.

### 10 legacy-style monitor panels

| Monitor | Title | Shows |
| --- | --- | --- |
| service | V2 Service Monitor | active vs failed count; focus subset 13 services |
| resources | V2 Memory/GPU Monitor | RAM/swap, load, GPU util/mem/temp/power, disk |
| redis | V2 Redis Key Monitor | dbsize, used_memory, key counts for 13 patterns (v2:* green, legacy red) |
| market | V2 Market Data Monitor | `v2:market:ohlcv:*` counts + TTL/size, paper_online payload age |
| predictions | V2 Predictions Monitor | `v2:prediction:*` counts + sample key/value preview, trainer-bridge journal |
| decision | V2 Risk/Orchestrator Monitor | `v2:risk:*`, `v2:orchestrator:*` counts + orchestrator journal + operator_runtime payload age |
| paper | V2 Paper Trading Monitor | shadow/ledger/position_history/trade_management counts + journals |
| exchange | V2 Exchange Read-Only Monitor | server_time, exchange_info every 10 s; signed probes every 6 iters; freeze wrapper status |
| automation | V2 Automation/Spark Monitor | Claude/Codex worker counts, parallel-scheduler, agent-supervisor, worker_pool_status.json contents |
| errors | V2 Error/Alert Monitor | failed v2 services; journal errors `priority=err` last 5 min; `v2/runtime/*.log` tails |

Idempotency: re-running the launcher when a terminal of a given title is
already on screen skips it. The launcher aborts if any process under the
legacy bot path is detected.

## Phase 7 - Visible runtime verification

`go_no_go = V2_VISIBLE_RUNTIME_VERIFICATION_READY`. See
[v2_visible_runtime_verification_status.json](v2_visible_runtime_verification_status.json).

| Check | Result |
| --- | --- |
| Expected terminal titles | 32 |
| Visible terminal titles | 32 |
| Visible-missing | 0 |
| Visible-extra | 0 |
| Blank/silent categories | 0 |
| Missing EST stamp in log | 0 |
| Missing safety footer in log | 0 |
| Active V2 systemd services | 29 |
| Legacy bot processes | 0 |
| `v2:*` Redis keys | 263 |
| `orchestrator:*` keys | 0 |
| `live_orders:*` keys | 0 |
| `exchange:order:*` keys | 0 |
| Exchange-mutation token hits in panel logs | 0 |
| Approval-token hits in panel logs | 0 |

The scanner explicitly excludes permission-flag reads (e.g.
`can_withdraw=None`, `balances_redacted=True`, `freeze wrapper` line,
`forbidden_method_names`) so that the read-only exchange monitor does
not falsely register as a mutation attempt.

## Phase 8 - Report Center / operator dashboard

Public copy at
[v2/frontend/public/v2_gnome_visible_runtime_and_binance_readonly/latest/operator_dashboard_payload.json](../../../v2/frontend/public/v2_gnome_visible_runtime_and_binance_readonly/latest/operator_dashboard_payload.json).

Summary block contains the seven YES/NO answers required by the task,
plus per-phase `go_no_go` sub-objects.

## Phase 9 - Outputs

Artifacts in this directory:

- [GO_NO_GO.md](GO_NO_GO.md)
- [V2_GNOME_VISIBLE_RUNTIME_AND_BINANCE_READONLY_CONNECTIVITY_REPORT.md](V2_GNOME_VISIBLE_RUNTIME_AND_BINANCE_READONLY_CONNECTIVITY_REPORT.md)
- [est_time_standardization_status.json](est_time_standardization_status.json)
- [live_credentials_env_loader_status.json](live_credentials_env_loader_status.json)
- [binance_readonly_connectivity_status.json](binance_readonly_connectivity_status.json)
- [exchange_adapter_mutation_freeze_status.json](exchange_adapter_mutation_freeze_status.json)
- [gnome_terminal_visible_output_status.json](gnome_terminal_visible_output_status.json)
- [v2_visible_runtime_verification_status.json](v2_visible_runtime_verification_status.json)
- [v2_gnome_terminal_startup_manifest.json](v2_gnome_terminal_startup_manifest.json)
- [operator_dashboard_payload.json](operator_dashboard_payload.json)

Touched code:
- `v2/backend/app/services/safe_env_loader.py`
- `v2/backend/app/services/binance_readonly_probe.py`
- `v2/backend/app/services/exchange_mutation_freeze.py`
- `claude_worklog/tools/v2_visible_terminal_panel.py`
- `claude_worklog/tools/v2_legacy_style_monitors.py`
- `claude_worklog/tools/start_v2_rebuild_gnome_terminals.sh`

Per-terminal log directory:
`claude_worklog/agent_supervisor/logs/v2_gnome_visible_runtime/20260525T231604EST/`

## Hard constraints verified

- Real orders: not attempted, not submitted.
- Order / test-order / cancel / batch / leverage / margin / transfer / withdraw endpoints: not called.
- Credential values: not printed in any artifact; only `KEY_PRESENT_BY_NAME` / `KEY_ABSENT_BY_NAME` sentinels.
- Account balances: not exposed.
- Old Redis namespaces: not written; counts (`orchestrator:*`, `live_orders:*`, `exchange:order:*`) all `0`.
- Redis trim/flush: not attempted.
- Legacy not restarted (0 processes under the legacy bot path).
- `LIVE_GATE = blocked_human_only`, `live_symbols = []`.
- Every new artifact uses EST timestamps.

## Next action

- Automatic: GNOME panels refresh every 10 s; signed exchange probes rerun every ~60 s; no automatic fix queued.
- Operator-only: operator may close any of the 32 GNOME terminals at will; no live-trading approval is being requested; all live gates remain `blocked_human_only`.
