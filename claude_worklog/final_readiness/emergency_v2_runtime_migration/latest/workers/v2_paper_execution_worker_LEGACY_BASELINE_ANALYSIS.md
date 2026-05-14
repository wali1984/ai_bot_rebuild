# v2_paper_execution_worker — Legacy Baseline Analysis

## Purpose

This file is the legacy-first baseline mandated by the
**LEGACY-FIRST MANDATE** for every V2 emergency-runtime-migration
worker. It documents *what the legacy bot already does today* for paper
trade execution recording so the V2 port can be reviewed as a
behaviour-preserving lift, not a greenfield reinvention. Each claim is
backed by a `legacy_reference` path + line range that can be re-verified
with `grep` / `wc -l` / direct read.

The V2 worker (`v2/backend/app/cli/v2_paper_execution_worker.py`) is a
thin CLI wrapper around the already-shipped library logic at
`v2/backend/app/services/paper_execution_ledger/service.py` +
`v2/backend/app/composition/paper_execution_ledger/runtime.py`. The
wrapper does not re-implement decision logic; it consumes
`RiskDecisionRecord` events and stamps `PaperExecutionLedgerEntry`
rows. Simulated-fill anchors (notional, fee rates, slippage bps) are
derived from legacy fee constants documented below.

## Legacy source paths

| Path | Role |
|---|---|
| `legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py` | Pre-refactor paper trader — order simulation, position tracking, P&L. |
| `legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py` | Earlier snapshot of the same paper trader. |
| `legacy_reference/PAPER_TRADER_COMPLETE.md` | Narrative describing legacy paper-trader responsibilities. |
| `legacy_reference/trading/base_executor.py` | Shared executor base — `paper_mode=True` branch lives here. |
| `legacy_reference/trading/trader.py` | Live trader; carries the canonical maker/taker fee rates re-used as anchors. |
| `legacy_reference/config.py` | `BASE_NOTIONAL` (legacy 500.0); `get_live_config()`. |

## legacy_functions_preserved

| Legacy function / responsibility | Legacy file | Preserved in V2 as |
|---|---|---|
| Record an "allow" decision as a simulated paper fill | `paper_trader.py` (PaperTrader: order-simulation loop, `_simulate_order_fill`, `_track_paper_position`) | `assemble_paper_execution_ledger_entry(...) → ledger_action=record_allow` + `simulated_fill.fill_recorded=true` |
| Record a "deny" decision as no-fill ledger row | `paper_trader.py` (PaperTrader: skip-on-no-signal branch) | `assemble_paper_execution_ledger_entry(...) → ledger_action=record_deny` + `simulated_fill.fill_recorded=false` |
| Default fee rates (`maker=0.0002`, `taker=0.0005`) | `legacy_reference/trading/trader.py:2269-2275` | `FEE_RATE_MAKER_DEFAULT=0.0002`, `FEE_RATE_TAKER_DEFAULT=0.0005` (worker constants) |
| Base notional sizing knob | `legacy_reference/config.py:1894` (`BASE_NOTIONAL = 500.0`) | `BASE_NOTIONAL_USDT_DEFAULT=100.0` (intentional V2 reduction; see *Intentional changes* below) |
| Paper-only invariant (no exchange call) | `paper_trader.py` (`paper_mode=True` branch in `BaseExecutor`) and `base_executor.py` | `EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_PAPER_PATH"` + tests that assert no exchange-mutation method name appears in worker source |

## legacy_inputs

The legacy `PaperTrader` consumed:

1. **Trainer decisions** via Redis pub/sub (`legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py:18 imports redis`) — namespaced under `wma:signal:*`, `wma:risk_state`, `wma:kill_switch:*`.
2. **Account balance** (initial 1000.0 in legacy default).
3. **Market price feed** (python-binance Client for read-only market data).

In V2 the equivalent input contract is a **`RiskDecisionRecord`** (already produced upstream by `v2_risk_gateway_runtime_worker`). The V2 worker takes:

1. `--decision-file PATH` to a JSON file containing a `RiskDecisionRecord` (either a direct dict, a list under `risk_decisions`, or the bridge format from `v2_risk_gateway_runtime_worker_status.json`).
2. Fallback: `v2/frontend/public/operator_runtime/v2_risk_gateway_runtime_worker/latest/v2_risk_gateway_runtime_worker_status.json` (the upstream worker's public status payload).

No legacy Redis is read; no Binance client is instantiated.

## legacy_outputs

The legacy `PaperTrader` wrote:

1. Simulated orders into `self.paper_orders` and positions into `self.paper_positions` (in-memory).
2. Telegram alerts via `telegram_alerts.TelegramNotifier`.
3. Logs to `legacy_reference/paper_trader.log`.
4. Periodic state into `wma:paper:*` Redis keys (audit-only references — *not* re-used by V2).

V2 outputs:

1. `PaperExecutionLedgerEntry` dataclass instance (in-memory only — not persisted by this worker; the live ledger DB write is a separate downstream port).
2. Public payload JSON files at:
   - `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
   - `v2/runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`
   - `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_paper_execution_worker_status.json`
3. CLI exit code `0` on a fully-processed record, `2` on `MISSING_RUNTIME_EVIDENCE` / fail-closed.

## legacy_redis_keys (audit-only references; never writers)

The legacy paper-trader observed and wrote the following Redis namespaces. The V2 worker references them in audit-only lists so the migration coverage is provable, but does **not** read or write them:

- `wma:paper:positions`
- `wma:paper:orders`
- `wma:paper:balance`
- `wma:paper:trade_log`
- `wma:signal:*` (consumed)
- `wma:risk_state`
- `wma:kill_switch`, `wma:kill_switch:{account}`, `wma:kill_switch:{symbol}`

The V2 worker source contains **no** `import redis` / `from redis` / `.set(` / `.hset(` / `.xadd(` / `.publish(` statements. The above keys appear only as constant string literals in audit-only configuration if at all.

## legacy_config_dependencies

| Legacy config key | Legacy file:line | V2 worker treatment |
|---|---|---|
| `BASE_NOTIONAL` | `legacy_reference/config.py:1894` | V2 default `100.0`; intentional reduction (paper sandbox conservatism). |
| `BINANCE_API_MAX_CALLS_PER_MINUTE` | `paper_trader.py:37` | Not used (V2 paper path does not call the exchange). |
| `get_live_config()` | `paper_trader.py:33`, `config.py:4115` | Not used (V2 worker does not call exchange API). |
| Maker/taker commission rates | `trader.py:2269-2275`, `trader.py:15305-15307` | Lifted as `FEE_RATE_MAKER_DEFAULT=0.0002`, `FEE_RATE_TAKER_DEFAULT=0.0005`. |
| Slippage tracking | `legacy_reference/trading/execution_engine.py:30-100` (SlippageTracker) | V2 paper recorder uses a fixed `DEFAULT_SLIPPAGE_BPS=5.0` placeholder; per-symbol modelling is deferred to a later port. |

## legacy_edge_cases

| Edge case | Legacy handling | V2 mapping |
|---|---|---|
| No signal received from trainer | `PaperTrader` loop sleeps and continues. | V2 fails closed with `MISSING_RUNTIME_EVIDENCE`, returns CLI rc 2. |
| Trainer signal is hold/abstain | Legacy paper-trader skips the order. | V2 stamps `record_deny` with `mirror_deny_*` reason; no fill. |
| Trainer signal allow but kill-switch active | Legacy `BaseExecutor` blocks the order via Redis kill-switch read. | V2 paper worker assumes the upstream `v2_risk_gateway_runtime_worker` has already produced a `deny` action; V2 paper worker never re-implements the kill-switch read. |
| Risk decision payload missing required field | Legacy would throw and Telegram-alert. | V2 fails closed with `runtime_evidence_status="INVALID_RUNTIME_EVIDENCE"`. |
| Unknown `risk_reason_code` | Legacy would log and skip. | V2 raises `PaperExecutionLedgerServiceError("unrecognized_risk_reason_code")` — caught by the worker and re-classified as `INVALID_RUNTIME_EVIDENCE`. |
| `risk_decision_id` > 125 chars (would push `paper_trade_id` past 128-char limit) | Legacy did not validate. | V2 service raises; V2 worker fail-closes. |
| Live trading attempted | Legacy `BaseExecutor` had a `paper_mode=True` switch; if mis-configured it could route to live API. | V2 worker has no live codepath; `LIVE_GATE_STATUS = "blocked_human_only"` is a single constant declared once and not reassigned. Tests assert no live-opening or approval-token string in source. |

## legacy_failure_modes

The legacy paper-trader had these failure modes that the V2 port explicitly avoids:

1. **Redis dependency** — legacy paper-trader required a running Redis instance and would crash on its absence.  V2 worker has zero Redis dependency.
2. **Binance client dependency** — even paper mode imported `binance.client.Client` for market data; missing library raised `ImportError`. V2 worker has zero Binance dependency.
3. **In-process state** — positions and balance lived in memory and were lost on restart. V2 worker is stateless; each invocation processes one decision and writes a deterministic public payload.
4. **No fail-closed invariant** — legacy paper-trader could continue running with no upstream signals (sleeping). V2 worker classifies that as `MISSING_RUNTIME_EVIDENCE` and exits 2.

## legacy_tests_or_expected_behavior

There were no Python unit tests covering the legacy paper-trader's allow-vs-deny ledger mapping. Documented behaviour from `legacy_reference/PAPER_TRADER_COMPLETE.md` is the closest narrative spec. The V2 port adds 28 integration tests covering the explicit allow/deny matrix, fail-closed cases, source-string contracts, the Symbol Universe contract, paper PnL/equity fields, a fake exchange spy, and the blocked live-gate invariant.

## V2_mapping

| Legacy concern | V2 location |
|---|---|
| `paper_trader.py:PaperTrader.run_loop` | `v2/backend/app/cli/v2_paper_execution_worker.py:run_once` + `main` |
| `paper_trader.py:_simulate_order_fill` (notional, fee, slippage) | `v2/backend/app/cli/v2_paper_execution_worker.py:_build_simulated_fill` |
| `paper_trader.py:position bookkeeping` | Deferred to V2 paper-online runtime port (out of scope). |
| `paper_trader.py:telegram_alerts.TelegramNotifier` | Deferred to V2 alerting service (out of scope). |
| `paper_trader.py:redis.Redis(...)` | **Removed.** V2 worker reads only V2-namespaced JSON payloads. |
| `paper_trader.py:binance.client.Client` | **Removed.** V2 worker has no exchange dependency. |
| Maker / taker fee constants in `trader.py` | `FEE_RATE_MAKER_DEFAULT=0.0002`, `FEE_RATE_TAKER_DEFAULT=0.0005` in the worker module. |

## intentional_changes

| Change | Reason |
|---|---|
| `base_notional_usdt` default 100.0 vs legacy 500.0 | The V2 paper recorder is for sandbox replay reconciliation, not size-matching the legacy live runtime. A 5× smaller notional makes per-symbol fee/slippage easier to reason about under the paper-vs-shadow sanity checks. Re-configurable in a later port. |
| Removed in-process position state | V2 separates *ledger stamping* (this worker) from *position accounting* (downstream port). Single-responsibility, easier to test. |
| Removed Redis reads/writes | V2 evidence integrity rule (CLAUDE.md): no legacy-Redis writes from V2 workers. |
| Removed Telegram alerts | Alerting is consolidated into V2 alerting service to avoid duplicate notifications. |
| Single fixed `DEFAULT_SLIPPAGE_BPS = 5.0` | Per-symbol slippage modelling is a separate concern (legacy `SlippageTracker`). For the ledger-stamping path, a conservative bps placeholder is sufficient. |

## removed_or_deprecated_behavior

| Removed behavior | Reason |
|---|---|
| Direct Binance `Client(...)` instantiation for market data | V2 paper recorder needs no market data; price reference is supplied upstream (or omitted). |
| Direct Redis read/write of `wma:paper:*` keys | V2 evidence integrity rule. |
| Telegram alerts on fill | Consolidated alerting; the public payload is the single source of truth. |
| In-process balance bookkeeping | Moved to a downstream port; this worker is *stamp-only*. |
| `OfflineBinanceClient` fallback class | Not needed — V2 paper path never touches the exchange. |
| `CircuitBreaker` shared with the live executor | Out of scope; the V2 gate is the upstream risk gateway. |
| Mutating state on live-enable / approval-token flow | Explicitly disallowed; tests assert these substrings do not appear in the worker source. |

## live-trading invariants (mandatory)

- `LIVE_GATE_STATUS = "blocked_human_only"` is the only assignment of this constant in the worker.
- `gate_always_blocked_invariant = True` is emitted on every public payload.
- `exchange_call_invariant = "NO_REAL_EXCHANGE_CALL_FROM_PAPER_PATH"` is emitted on every public payload.
- The worker source contains no `create[_]order` / `cancel[_]order` / `futures[_]create[_]order` / `futures[_]change[_]leverage` / `futures[_]change[_]margin[_]type` / `place[_]order` substring.
- The worker source contains no `import binance` / `from binance` / `import ccxt` / `from ccxt` / `import redis` / `from redis` import.
- The worker source contains no `.set(` / `.hset(` / `.xadd(` / `.publish(` writer call.
- The worker source contains no live-gate-opening, enable-live, or approval-token substring.

## verification_commands

```text
# Legacy fee anchors
sed -n '2265,2280p' legacy_reference/trading/trader.py
sed -n '1890,1900p' legacy_reference/config.py
# Legacy paper trader bytes
wc -l legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py
# V2 worker bytes
wc -l v2/backend/app/cli/v2_paper_execution_worker.py
# V2 worker source-string contract
grep -nE 'create[_]order|cancel[_]order|futures[_]create[_]order|futures[_]change[_]leverage|futures[_]change[_]margin[_]type|place[_]order' v2/backend/app/cli/v2_paper_execution_worker.py || echo "OK no exchange-mutation methods"
grep -nE '^(import|from) (binance|ccxt|redis)' v2/backend/app/cli/v2_paper_execution_worker.py || echo "OK no forbidden imports"
grep -nE 'unblock|enable[_]live|approval[_]token' v2/backend/app/cli/v2_paper_execution_worker.py || echo "OK gate cannot be opened"
# V2 tests
.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_paper_execution_worker.py -v
