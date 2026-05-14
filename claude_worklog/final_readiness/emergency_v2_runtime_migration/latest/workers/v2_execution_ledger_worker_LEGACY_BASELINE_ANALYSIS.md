# v2_execution_ledger_worker — Legacy Baseline Analysis

## Purpose

This file is the legacy-first baseline mandated by the **LEGACY-FIRST
MANDATE** for every V2 emergency-runtime-migration worker. It documents
*what the legacy bot already does today* for paper-trade event recording
and ledger persistence, so the V2 port can be reviewed as a
behaviour-preserving lift, not a greenfield reinvention. Each claim is
backed by a `legacy_reference` path + line range that can be re-verified
with `grep` / `wc -l` / direct read.

The V2 worker
(`v2/backend/app/cli/v2_execution_ledger_worker.py`) is a thin
downstream CLI subscriber to the V2 paper execution worker's public
status payload. It appends accepted paper events to a durable
**append-only** JSONL ledger and exposes a tail of the last N events in
its public_runtime payload. It does not re-implement decision logic,
does not call any exchange, does not read or write legacy Redis, and
does not open the live gate.

## Legacy source paths

| Path | Role |
|---|---|
| `legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py` | Pre-refactor paper trader — `self.paper_orders` dict, `self.paper_positions`, simulated fills, in-process state. |
| `legacy_reference/.backups/fix_signals_20251012_191010/paper_trader.py` | Earlier snapshot of the same paper trader. |
| `legacy_reference/PAPER_TRADER_COMPLETE.md` | Narrative spec for the legacy paper trader and its order/trade bookkeeping. |
| `legacy_reference/trading/base_executor.py` | Legacy shared executor; `paper_mode=True` branch holds the order-storage hook. |
| `legacy_reference/trading/trader.py` | Live trader; the canonical maker/taker fee anchors live here (re-used by upstream paper worker, surfaced as event fields here). |
| `legacy_reference/config.py` | `BASE_NOTIONAL` and related sizing config; not a writer of any persistent ledger. |
| `legacy_reference/monitor_trader_execution.py` | Legacy execution monitor — observed Redis trade_log keys to derive operator views; the closest legacy analog to "expose a tail of recent events". |

There was **no** legacy module that wrote a durable, append-only JSONL
ledger of paper events. The legacy paper-trader kept orders and
positions in-process (lost on restart) and pushed event-shaped state
into Redis (`wma:paper:*`) which the V2 evidence-integrity rule
prohibits us from writing. This worker therefore implements the durable
append-only ledger that legacy lacked while preserving every observable
event field that legacy made available.

## legacy_functions_preserved

| Legacy function / responsibility | Legacy file | Preserved in V2 as |
|---|---|---|
| Order storage on simulated fill | `paper_trader.py:691` (`self.paper_orders[order_id] = order_result`) | `_append_event(...)` appends an event row containing the same fields (`symbol`, `side`, `notional_usdt`, `fee_usdt`, `paper_trade_id`, `paper_trade_ts_ms`) to the JSONL ledger. |
| Order-id sequencing | `paper_trader.py` (`self.next_order_id += 1`) | Deterministic event ids derived from `paper_trade_id` (which is `"pt_" + risk_decision_id`). Append-only semantics replace mutable counters. |
| Trade log surfacing for operator | `monitor_trader_execution.py` (reads Redis `wma:paper:trade_log`) | `tail` field in public_runtime status reflects the last N events from the JSONL ledger. |
| Denial / skip event surfacing | `paper_trader.py` (skip-on-no-signal branch) | Deny events (`ledger_action="record_deny"`, `fill_recorded=false`) are appended to the same ledger so denials are auditable, not silent. |
| Paper-only invariant (no exchange call) | `paper_trader.py` (`paper_mode=True` branch in `BaseExecutor`) and `base_executor.py` | `EXCHANGE_CALL_INVARIANT = "NO_REAL_EXCHANGE_CALL_FROM_LEDGER_WORKER"` + tests that assert no exchange-mutation method name appears in worker source. |

## legacy_inputs

The legacy `PaperTrader` consumed:

1. Trainer decisions via Redis pub/sub (`wma:signal:*`).
2. Account balance (in-process initial = 1000.0).
3. Market price feed (python-binance `Client` for read-only market data).

In V2 the equivalent input for *the ledger worker* is the **public
status payload of `v2_paper_execution_worker`**, which already encodes
the consumed risk decision, the assembled ledger entry, and the
simulated-fill block. The V2 ledger worker takes:

1. `--source-file PATH` to a JSON file shaped like the paper execution
   worker public status payload.
2. Fallback:
   `v2/frontend/public/operator_runtime/v2_paper_execution_worker/latest/v2_paper_execution_worker_status.json`.

No legacy Redis is read; no Binance client is instantiated; no
subscription is opened against the legacy live bot.

## legacy_outputs

The legacy `PaperTrader` wrote:

1. Simulated orders into `self.paper_orders` and positions into
   `self.paper_positions` (in-memory).
2. Redis keys `wma:paper:orders`, `wma:paper:positions`,
   `wma:paper:balance`, `wma:paper:trade_log` (audit-only references —
   never re-used by V2).
3. Telegram alerts via `telegram_alerts.TelegramNotifier`.
4. Logs to `legacy_reference/paper_trader.log`.

V2 outputs:

1. Append-only JSONL ledger at
   `v2/runtime/v2_execution_ledger_worker/latest/paper_events.jsonl`.
2. Public status payload at:
   - `v2/frontend/public/operator_runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json`
   - `v2/runtime/v2_execution_ledger_worker/latest/v2_execution_ledger_worker_status.json`
   - `claude_worklog/final_readiness/emergency_v2_runtime_migration/latest/workers/v2_execution_ledger_worker_status.json`
3. CLI exit code `0` on a fully-processed record (including duplicate
   no-op runs), `2` on `MISSING_RUNTIME_EVIDENCE` / `INVALID_ACTION` /
   `INVALID_PAYLOAD` / `UNWRITABLE_LEDGER_DIR`.

## legacy_redis_keys (audit-only references; never writers)

The legacy paper-trader observed and wrote the following Redis
namespaces. The V2 worker references them in audit-only documentation
so migration coverage is provable, but does **not** read or write them:

- `wma:paper:orders`
- `wma:paper:positions`
- `wma:paper:balance`
- `wma:paper:trade_log`
- `wma:signal:*` (legacy consumer)
- `wma:risk_state`

The V2 worker source contains **no** `import redis` / `from redis` /
`.set(` / `.hset(` / `.xadd(` / `.publish(` statements.

## legacy_config_dependencies

| Legacy config key | Legacy file:line | V2 worker treatment |
|---|---|---|
| `BASE_NOTIONAL` | `legacy_reference/config.py:1894` | Not used in this worker (notional is surfaced from the upstream paper worker's `simulated_fill.notional_usdt`). |
| Maker/taker commission rates | `legacy_reference/trading/trader.py:2269-2275` | Not redefined here; fee fields are copied from the upstream paper worker's `simulated_fill` block. |
| Trade-log Redis namespace | `monitor_trader_execution.py` | Not read; the V2 ledger is the source of truth instead. |

## legacy_edge_cases

| Edge case | Legacy handling | V2 mapping |
|---|---|---|
| No upstream signal | `PaperTrader` loop sleeps and continues. | V2 fails closed with `MISSING_RUNTIME_EVIDENCE`, returns CLI rc 2. |
| Upstream paper worker reports fail-closed | Legacy did not have this notion. | V2 propagates as `MISSING_RUNTIME_EVIDENCE`; nothing is appended. |
| Action outside {allow, deny} | Legacy paper-trader would log and skip. | V2 fails closed with `runtime_evidence_status="INVALID_ACTION"`; nothing is appended; rc 2. |
| Repeated event id (replay) | Legacy used a per-process counter so duplicates were impossible in-process but were trivially possible across restarts. | V2 dedupes by `event_id == paper_trade_id`; second run is a no-op (`duplicate_skipped=true`), no truncation, no rewrite. |
| Unwritable ledger directory | Legacy crashed if Redis was down. | V2 fails closed with `runtime_evidence_status="UNWRITABLE_LEDGER_DIR"`; no exception; status payload still emitted. |
| Process restart | Legacy lost `self.paper_orders` and `self.paper_positions`. | V2 ledger is a durable file; restart preserves all prior events. |
| Live trading attempted | Legacy `BaseExecutor.paper_mode` switch could be misconfigured. | V2 worker has no live codepath; `LIVE_GATE_STATUS` is a single constant; tests assert no live-opening or approval-token substring. |

## legacy_failure_modes

The legacy paper-trader had these failure modes that the V2 ledger
worker explicitly avoids:

1. **Redis dependency** — legacy paper-trader required a running Redis
   instance and crashed on its absence. V2 worker has zero Redis
   dependency.
2. **Binance client dependency** — even paper mode imported
   `binance.client.Client`. V2 worker has zero Binance dependency.
3. **In-process state lost on restart** — `self.paper_orders` evaporated
   on restart. V2 ledger is a durable JSONL file.
4. **No deduplication** — across restarts, repeats were possible. V2
   ledger dedupes by `event_id`.
5. **No append-only invariant** — legacy state mutated in place. V2
   ledger is strictly append-only; no `'w'` open in source; tests
   assert pre-existing lines are byte-preserved across runs.

## legacy_tests_or_expected_behavior

There were no Python unit tests covering the legacy paper-trader's
order-log persistence. Documented behaviour from
`legacy_reference/PAPER_TRADER_COMPLETE.md` is the closest narrative
spec. The V2 port adds an integration test module
(`v2/backend/tests/integration/cli/test_v2_execution_ledger_worker.py`)
covering:

- append-only invariant (idempotent on repeat)
- tail payload reflects last N
- fail-closed on unwritable ledger dir
- no-truncation (pre-existing lines byte-preserved)
- action-set rejection (action ∉ {allow, deny})
- missing upstream evidence → rc 2
- gate-always-blocked invariant
- Symbol Universe contract emitted
- required public payload fields all present (in status and on disk)
- no real exchange-mutation method names in source
- no Binance/ccxt/Redis imports / Redis writers in source
- no codepath opens the live gate
- no exchange-client attribute reachable on the worker module
- deny entries are appended too (audit visibility)
- event_id == paper_trade_id

## V2_mapping

| Legacy concern | V2 location |
|---|---|
| `paper_trader.py:self.paper_orders[order_id] = order_result` | `v2/backend/app/cli/v2_execution_ledger_worker.py::_append_event` |
| `paper_trader.py:next_order_id` counter | Event id derived from upstream `paper_trade_id` (= `"pt_" + risk_decision_id`). |
| `monitor_trader_execution.py` operator tail view | `tail` field in `v2_execution_ledger_worker_status.json`. |
| Redis `wma:paper:trade_log` | **Removed.** Replaced by JSONL ledger file. |
| Telegram fill alerts | **Removed.** Consolidated V2 alerting service (out of scope). |
| In-process position state | **Removed.** This worker is stamp-and-persist only; position accounting is a separate downstream port. |

## intentional_changes

| Change | Reason |
|---|---|
| Durable append-only JSONL ledger (replaces legacy in-process dict + Redis) | Survives restart; satisfies V2 evidence integrity rule; auditable on disk. |
| Dedup by `event_id == paper_trade_id` | Idempotent re-runs and replay; no need for a mutable counter. |
| Tail of last N events surfaced via public_runtime payload | Operator view replaces the legacy Redis trade-log read in `monitor_trader_execution.py`. |
| Strict action-set rejection (`allow` / `deny` only) | Defence in depth: the upstream paper worker should only emit these, but the ledger worker is the second wall. |
| Fail-closed on unwritable ledger dir | Legacy crashed; V2 emits a deterministic fail-closed status instead. |

## removed_or_deprecated_behavior

| Removed behavior | Reason |
|---|---|
| `redis.Redis(...)` reads/writes of `wma:paper:*` keys | V2 evidence integrity rule. |
| `binance.client.Client(...)` instantiation | This worker has no need for market data; upstream paper worker already records fill data. |
| Telegram fill alerts | Consolidated alerting; the public payload is the single source of truth. |
| In-process balance / position bookkeeping | Out of scope for the ledger worker. |
| live-enable / approval-token flow | Explicitly disallowed; tests assert these substrings do not appear in source. |

## live-trading invariants (mandatory)

- `LIVE_GATE_STATUS = "blocked_human_only"` is the only assignment of
  this constant in the worker.
- `gate_always_blocked_invariant = True` is emitted on every public
  payload.
- `exchange_call_invariant = "NO_REAL_EXCHANGE_CALL_FROM_LEDGER_WORKER"`
  is emitted on every public payload and on every appended event.
- The worker source contains no `create[_]order` / `cancel[_]order` /
  `futures[_]create[_]order` / `futures[_]change[_]leverage` /
  `futures[_]change[_]margin[_]type` / `place[_]order` substring.
- The worker source contains no `import binance` / `from binance` /
  `import ccxt` / `from ccxt` / `import redis` / `from redis` import.
- The worker source contains no `.set(` / `.hset(` / `.xadd(` /
  `.publish(` writer call.
- The worker source contains no live-gate-opening, enable-live, or
  approval-token substring.

## verification_commands

```text
# Legacy paper trader (in-process order storage)
sed -n '685,700p' legacy_reference/.backups/fix_signals_20251012_191330/paper_trader.py
# Legacy execution monitor (operator tail view)
wc -l legacy_reference/monitor_trader_execution.py
# V2 worker bytes
wc -l v2/backend/app/cli/v2_execution_ledger_worker.py
# V2 worker source-string contract
grep -nE 'create[_]order|cancel[_]order|futures[_]create[_]order|futures[_]change[_]leverage|futures[_]change[_]margin[_]type|place[_]order' v2/backend/app/cli/v2_execution_ledger_worker.py || echo "OK no exchange-mutation methods"
grep -nE '^(import|from) (binance|ccxt|redis)' v2/backend/app/cli/v2_execution_ledger_worker.py || echo "OK no forbidden imports"
grep -nE 'unblock|enable[_]live|approval[_]token' v2/backend/app/cli/v2_execution_ledger_worker.py || echo "OK gate cannot be opened"
# V2 tests
.venv/bin/pytest v2/backend/tests/integration/cli/test_v2_execution_ledger_worker.py -v
