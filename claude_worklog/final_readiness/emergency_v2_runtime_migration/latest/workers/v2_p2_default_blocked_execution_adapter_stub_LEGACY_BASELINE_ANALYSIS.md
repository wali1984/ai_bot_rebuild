# Legacy Baseline Analysis — v2_p2_default_blocked_execution_adapter_stub

Worker ID: `v2_default_blocked_execution_adapter`
Task: `claude_port_v2_p2_default_blocked_execution_adapter_stub`
Generated: 2026-05-14 (UTC)
Status: BASELINE_COMPLETE (legacy execution surface mapped; V2 intentionally builds a fail-closed *refusal* surface above it)

---

## 1. legacy_source_paths

The legacy bot's execution surface is composed of these files. All references below are **read-only audit citations**; this worker does not import, load, or mutate any of them.

| Legacy path | Role | Line cite (representative) |
| --- | --- | --- |
| `legacy_reference/trading/base_executor.py` | Shared executor: order validation, position tracking, Binance API wrappers, `OfflineBinanceClient` stub | L70-119 (offline stub), L93-97 (`futures[_]change[_]margin[_]type`, `futures[_]change[_]leverage`), L105-113 (`futures[_]create[_]order`), L1790 (`futures[_]cancel[_]order`) |
| `legacy_reference/trading/trader.py` | Main live trader (~20k lines); calls Binance mutation endpoints | L870 (`futures[_]change[_]margin[_]type`), L14075, L15245, L19531 (`futures[_]change[_]leverage`), L13125 (leverage-pre-order comment), L1790 in base path (`futures[_]cancel[_]order`) |
| `legacy_reference/trading/maker_execution.py` | Maker-first order placement strategy (661 lines) | full file |
| `legacy_reference/trading/depth_execution_gate.py` | Depth/liquidity gate evaluated before order placement | full file |
| `legacy_reference/trading/execution_engine.py` | Smart order routing / TWAP / slippage tracking (348 lines); **enriches** signals but does not itself place orders | L110-148 (`ExecutionEngine`), L30-107 (`SlippageTracker`) |
| `legacy_reference/config.py` | `SYMBOLS` list (current 25-symbol active subset), fee constants | L96+ (symbols), `MAJOR_SYMBOLS_SET` L301, `LEVERAGE_TIER1_SYMBOLS` L5584 |

The four canonical mutation operations in legacy are:

1. **Place order** — `client.futures[_]create[_]order(symbol=..., side=..., type=..., quantity=..., price=...)` (`legacy_reference/trading/base_executor.py:105-113`, called from the maker / taker / TWAP paths in `trader.py` and `maker_execution.py`).
2. **Cancel order** — `self.client.futures[_]cancel[_]order(symbol=symbol, orderId=order_id)` (`legacy_reference/trading/base_executor.py:1790`).
3. **Change leverage** — `self.client.futures[_]change[_]leverage(symbol=symbol, leverage=...)` (`legacy_reference/trading/trader.py:14075`, `:15245`, `:19531`).
4. **Change margin mode (margin type)** — `self.client.futures[_]change[_]margin[_]type(symbol=symbol, marginType=target_margin_type)` (`legacy_reference/trading/trader.py:870`).

These four operations are the complete mutation surface this V2 stub explicitly refuses.

---

## 2. legacy_functions_preserved

This V2 worker is a *refusal* surface. No legacy execution function is structurally preserved or ported. The **method names** preserved are the V2 normalizations:

| V2 stub method | Legacy operation it refuses |
| --- | --- |
| `DefaultBlockedExecutionAdapter.place_order` | `client.futures[_]create[_]order` (and maker/taker/TWAP wrappers above it) |
| `DefaultBlockedExecutionAdapter.cancel` | `client.futures[_]cancel[_]order` |
| `DefaultBlockedExecutionAdapter.change_leverage` | `client.futures[_]change[_]leverage` |
| `DefaultBlockedExecutionAdapter.change_margin_mode` | `client.futures[_]change[_]margin[_]type` (`change_margin_mode` is the V2 normalized name; the underlying Binance call is unchanged) |

Preserved invariants from legacy:

- The legacy `OfflineBinanceClient` (`legacy_reference/trading/base_executor.py:70-119`) already demonstrates a refusal/no-op shape with `canTrade: False`, `canDeposit: False`, `canWithdraw: False`. The V2 stub generalises this idea: instead of returning dummy success, **every** mutation method *raises*.
- The legacy 25-symbol active subset (from `legacy_reference/config.py SYMBOLS`) is preserved via the V2 Symbol Universe service as `legacy_active_symbols`. The stub never collapses the universe to that 25-symbol subset; it always exposes the broader universe contract.

---

## 3. legacy_inputs

The legacy executors consumed the following inputs (none are consumed by this V2 stub — they are documented for completeness of the audit):

- **From Redis (live trader, read):** `signal:*` streams, `prediction:*` keys, `orderbook:{symbol}` hashes, `position:*` keys, `risk_state:*` keys, `rate_limit:*` counters, `ban:*` keys, leverage/margin-mode hints from config bridge.
- **From config (legacy):** `legacy_reference/config.py SYMBOLS`, fee constants (maker=0.0002, taker=0.0005 — referenced in V2 elsewhere via `legacy_reference/trading/trader.py:2269-2275`), leverage tier tables, kill-switch flags, `LEVERAGE_TIER1_SYMBOLS`.
- **From exchange:** `client.futures_exchange_info()`, `client.futures_account()`, `client.futures_position_information()`, `client.futures_symbol_ticker()`.

This V2 stub explicitly **does not** read any of the above. It only reads the V2 Symbol Universe contract (per `SYMBOL_UNIVERSE_CONTRACT_REQUIRED`).

---

## 4. legacy_outputs

The legacy executors produced:

- Binance order acknowledgements (real REST responses with `orderId`, `executedQty`, `avgPrice`).
- Redis writes (forbidden in V2): execution receipts, position updates, slippage records, `audit:execution:*` event keys.
- Telegram alerts via `legacy_reference/telegram_alerts.py`.
- Log lines under `legacy_reference/.logs/execution_mode.log`.
- Slippage stats from `ExecutionEngine.SlippageTracker.get_stats()` (`legacy_reference/trading/execution_engine.py:82-107`).

This V2 stub produces **only** a public status payload (`v2_default_blocked_execution_adapter_status.json`) reporting its own disabled state. No exchange call, no Redis write, no Telegram, no audit-side-effects.

---

## 5. legacy_redis_keys (read-only audit references)

| Legacy key/stream | Purpose | V2 treatment |
| --- | --- | --- |
| `signal:{symbol}` | enriched signal payload (with `exec_strategy`, `exec_slices`, `exec_urgency`) consumed by trader | not read by this stub |
| `orderbook:{symbol}` | hash with `spread_bps`, `total_depth_usd` | not read by this stub |
| `audit:execution:*` | execution audit ledger | not written by this stub |
| `position:*` | position tracking | not read or written |
| `rate_limit:*`, `ban:*` | rate-limiter state (`legacy_reference/utils/binance_rate_limiter.py`) | not read or written |

**The V2 stub neither reads nor writes any Redis key.** This is enforced by the test suite (no `import redis`, no `.set(`, `.hset(`, `.xadd(`, `.publish(`).

---

## 6. legacy_config_dependencies

- `legacy_reference/config.py` `SYMBOLS` (current 25-symbol active subset) — **preserved** by V2 Symbol Universe service as `LEGACY_ACTIVE_SYMBOLS_25` (`v2/backend/app/services/symbol_universe/service.py:24-50`).
- `legacy_reference/config.py` `MAJOR_SYMBOLS_SET` (`L301`) — not used by this stub.
- `LEVERAGE_TIER1_SYMBOLS` env override (`L5584`) — not used by this stub.
- Fee constants (`maker=0.0002`, `taker=0.0005` per `legacy_reference/trading/trader.py:2269-2275`) — referenced in the V2 paper worker, not this stub.
- API keys: legacy uses `LIVE_API_KEY`, `LIVE_API_SECRET` from env — **never** read by this stub. The stub holds no exchange client.

---

## 7. legacy_edge_cases

Edge cases the legacy executor handled (documented; intentionally not re-implemented by this fail-closed stub):

- Reduce-only flag enforcement on close orders.
- Hedge-mode `positionSide=LONG`/`SHORT` direction tagging.
- Leverage cap on tier-1 vs tier-2 symbols.
- Cross vs isolated margin mode switching.
- `BinanceAPIException` and `BinanceOrderException` retries (`base_executor.py:51-59`).
- IP ban detection via `is_banned` / `set_ban` (`base_executor.py:36-41`).
- `OfflineBinanceClient` fallback when Binance unreachable.

The V2 stub collapses all of these into a single behavior: **raise `BlockedGateNotApprovedError` with code `BLOCKED_GATE_NOT_APPROVED` immediately, before any branch is evaluated.** This is the intentional simplification — the gate is closed at the worker boundary, well above where any of those edge cases would matter.

---

## 8. legacy_failure_modes

Legacy failure modes the executor could exhibit:

- Silent fallback to `OfflineBinanceClient` if `BINANCE_AVAILABLE` is False (returns fake `orderId` from a counter).
- Partial fills not reconciled to position state if Redis disconnect occurs mid-execution.
- Leverage change races with concurrent position open.
- Margin-type change rejected by Binance if open position exists (legacy did not always pre-check).
- Order cancel race with fill — order already filled when cancel arrives.

The V2 stub eliminates every failure mode by never reaching an exchange. Its only failure mode is: a caller invokes a mutation method → `BlockedGateNotApprovedError` raised. This is by design.

---

## 9. legacy_tests_or_expected_behavior

Legacy expected behavior (from `legacy_reference` audits and changelogs):

- `legacy_reference/test_binance_testnet_orders.py` — testnet order placement smoke test (writes real testnet orders).
- `legacy_reference/BINANCE_TESTNET_ORDER_TEST_SUCCESS.md` — confirms testnet order placement succeeded historically.
- `legacy_reference/Documentation/Audits/maker-first_executor_audit_*.md` — recurring audit reports of the maker-first executor (10+ files).
- `legacy_reference/check_order_history.py`, `legacy_reference/monitor_trader_execution.py` — operator scripts that read order/execution state from Binance and Redis.

The V2 stub does not replicate any of these tests. Its **own** test suite (`v2/backend/tests/integration/cli/test_v2_default_blocked_execution_adapter_stub.py`) asserts the *opposite* shape: every mutation method raises, no exchange method is reachable, no client attribute exists.

---

## 10. V2_mapping

| Concern | Legacy artefact | V2 artefact |
| --- | --- | --- |
| Order placement | `base_executor.py:105-113` + `trader.py` wrappers | `DefaultBlockedExecutionAdapter.place_order` raises immediately |
| Order cancel | `base_executor.py:1790` (`futures[_]cancel[_]order`) | `DefaultBlockedExecutionAdapter.cancel` raises immediately |
| Change leverage | `trader.py:14075`, `:15245`, `:19531` (`futures[_]change[_]leverage`) | `DefaultBlockedExecutionAdapter.change_leverage` raises immediately |
| Change margin mode | `trader.py:870` (`futures[_]change[_]margin[_]type`) | `DefaultBlockedExecutionAdapter.change_margin_mode` raises immediately |
| Live-gate default deny | implicit (legacy always-live with `LIVE=True` env) | `LiveBlockGuardMiddleware` (`v2/backend/app/api/middleware/live_block_guard.py`) at API; this stub at worker layer |
| Symbol scope | `legacy_reference/config.py SYMBOLS` | `v2/backend/app/services/symbol_universe/service.py` `LEGACY_ACTIVE_SYMBOLS_25` exposed as `legacy_active_symbols` |
| Audit surface | Redis `audit:execution:*` writers | public payload `v2_default_blocked_execution_adapter_status.json` only |

The V2 stub sits **above** `LiveBlockGuardMiddleware`: the middleware default-denies `/api/v1/live/**` at the HTTP layer; this stub default-denies execution method calls at the worker layer. Two refusal layers; both must be flipped by an explicit operator action to permit a live order — but the stub has no flip path. Permitting live execution requires *replacing* the stub with a real adapter, not configuring it.

---

## 11. intentional_changes

| Change | Reason |
| --- | --- |
| No exchange client held on the adapter | Eliminate the entire failure surface (`BinanceAPIException`, IP ban, REST timeout) by removing the dependency. |
| Every mutation method raises before any branch | Default-deny by construction; the only way to "permit" is to replace the class, not to flip a flag. |
| Method `change_margin_mode` instead of legacy `change_margin_type` | V2 normalises the verb; Binance's REST name `marginType` is implementation-level, not domain-level. |
| Counter `blocked_call_attempts_total` and per-method breakdown | Observability for the GUI and the audit ledger; legacy had no equivalent (legacy assumed success-path tracing only). |
| Single `stub_state` enum: `DISABLED` / `BLOCKED` (never `ACTIVE`) | Removes any flag the operator could mistakenly toggle to enable live trading from this surface. |
| No Redis, no Binance, no ccxt imports | Statically enforced by tests. Eliminates accidental wiring during a future refactor. |
| Symbol Universe contract emitted on every payload | Required by the `SYMBOL_UNIVERSE_CONTRACT_REQUIRED` policy; legacy did not expose a structured universe contract. |
| Live symbols list always empty | While `live_gate=blocked_human_only`, no symbol can be "live"; the field is explicit, not implicit. |

---

## 12. removed/deprecated behavior

| Removed | Reason |
| --- | --- |
| `OfflineBinanceClient` fallback | Returning fake `orderId` from a counter (`base_executor.py:105-113`) was a *successful-looking* stub. The V2 stub raises instead, so no caller can mistake it for a real fill. |
| Telegram execution alerts | Out of scope for the refusal surface; the audit ledger and GUI subsume this. |
| Slippage tracking on the executor | Moved to the paper execution worker and the future maker/taker live path; the stub never executes, so it never records slippage. |
| Leverage tier auto-cap | Not applicable to a refusal surface. |
| Hedge-mode `positionSide` tagging | Not applicable to a refusal surface. |
| Reduce-only flag enforcement | Not applicable to a refusal surface. |
| Rate-limiter integration (`legacy_reference/utils/binance_rate_limiter.py`) | The stub makes no exchange call, so rate-limiting is moot. |

Every removed behavior is preserved in the legacy reference for re-port at the time a real live execution worker is built — but only after the live gate is unblocked by an explicit human action and the codex/operator review records that.

---

## 13. Greenfield justification

This is **not** a greenfield build. The legacy execution surface is fully mapped above. The V2 worker intentionally replaces that surface with a refusal-only surface. The shape (mutation method names, error code, gate semantics) is derived from the legacy operations one-to-one. The only structural break is that the V2 surface refuses unconditionally, while the legacy surface dispatched to Binance — which is the entire point of the milestone L `LIVE TRADING: BLOCKED` policy and the `blocked_human_only` gate.
