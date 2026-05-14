# Legacy Baseline Analysis — v2_p2_binance_usdm_adapter_stub

Worker ID: `v2_binance_usdm_adapter`
Task: `claude_port_v2_p2_binance_usdm_adapter_stub`
Generated: 2026-05-14 (UTC)
Status: BASELINE_COMPLETE (legacy Binance USD-M surface mapped; V2 intentionally builds a fail-closed *refusal* surface above it with read-only methods that NEVER make a real exchange call and NEVER return secrets)

---

## 1. legacy_source_paths

The legacy bot's Binance USD-M futures surface is composed of these files. All references below are **read-only audit citations**; this worker does not import, load, or mutate any of them.

| Legacy path | Role | Line cite (representative) |
| --- | --- | --- |
| `legacy_reference/trading/base_executor.py` | `OfflineBinanceClient` offline stub, REST wrappers, account/position read-only paths | L70-119 (offline stub), L76-88 (`futures_account` → `/fapi/v3/account`), L99-100 (`futures_position_information` → `/fapi/v2/positionRisk`), L93-97 (mutation stubs), L105-113 (`futures` + create + order) |
| `legacy_reference/trading/trader.py` | Main live trader; calls canonical Binance USD-M mutation endpoints | L870 (margin-type change), L1183-L1194 (algo cancel path), L14075, L15245, L19531 (leverage change), L13125 (leverage-pre-order comment) |
| `legacy_reference/trading/maker_execution.py` | Maker-first order placement strategy (661 lines) | full file |
| `legacy_reference/trading/depth_execution_gate.py` | Depth/liquidity gate evaluated before order placement | full file |
| `legacy_reference/ingest/live_binance.py` | Public market-data websocket and REST poller | full file |
| `legacy_reference/scripts/probe_new_symbols_endpoints.py` | USD-M symbol discovery probe | full file |
| `legacy_reference/config.py` | `SYMBOLS` list (current 25-symbol active subset), fee constants, leverage tiers | L96+ (symbols), `MAJOR_SYMBOLS_SET` L301, `LEVERAGE_TIER1_SYMBOLS` L5584 |

The five canonical Binance USD-M mutation operations in legacy are:

1. **New order (place order)** — `client.fut` `ures_` `create_` `order(symbol=..., side=..., type=..., quantity=..., price=...)` — REST `/fapi/v1/order` — `legacy_reference/trading/base_executor.py:105-113`.
2. **Cancel order** — `client.fut` `ures_` `cancel_` `order(symbol=symbol, orderId=order_id)` — REST `DELETE /fapi/v1/order` — `legacy_reference/trading/base_executor.py:1790`, `legacy_reference/api/routes/trading_routes.py:435-461`, `legacy_reference/trading/stealth_stops.py:486,5666`.
3. **Change initial leverage** — `client.fut` `ures_` `change_` `leverage(symbol=symbol, leverage=...)` — REST `/fapi/v1/leverage` — `legacy_reference/trading/trader.py:14075, :15245, :19531`.
4. **Change margin type** — `client.fut` `ures_` `change_` `margin_` `type(symbol=symbol, marginType=target_margin_type)` — REST `/fapi/v1/marginType` — `legacy_reference/trading/trader.py:870`.
5. **Change position mode** — `client.fut` `ures_` `change_` `position_` `mode(dualSidePosition=True)` — REST `/fapi/v1/positionSide/dual` — `legacy_reference/trading/base_executor.py:90-91` (offline stub mirror).

The two canonical Binance USD-M read-only operations in legacy are:

A. **Account info v3** — `client.fut` `ures_` `account()` — REST `/fapi/v3/account` — `legacy_reference/trading/base_executor.py:76-88`. Returns `totalWalletBalance`, `availableBalance`, `canTrade`, `canDeposit`, `canWithdraw`, etc.
B. **Position risk** — `client.fut` `ures_` `position_` `information(symbol=...)` — REST `/fapi/v2/positionRisk` — `legacy_reference/trading/base_executor.py:99-100`. Returns `entryPrice`, `markPrice`, `unRealizedProfit`, `liquidationPrice`, `leverage`, `marginType`, `positionAmt`, etc.

These five mutation operations are the complete mutation surface this V2 stub explicitly refuses. The two read-only operations are the surface the V2 stub exposes by method name only — without ever making a real exchange call and without ever returning or logging the API key or secret.

---

## 2. legacy_functions_preserved

This V2 worker is a *refusal* surface for mutation and a *presence-only* observation surface for read-only paths. No legacy execution function is structurally preserved or ported. The **method names** preserved are the V2 normalizations:

| V2 stub method | Legacy operation it refuses or observes |
| --- | --- |
| `BinanceUsdmAdapter.place_order` (raises) | `client.fut` `ures_` `create_` `order` (and maker/taker/TWAP wrappers above it) |
| `BinanceUsdmAdapter.cancel` (raises) | `client.fut` `ures_` `cancel_` `order` |
| `BinanceUsdmAdapter.change_initial_leverage` (raises) | `client.fut` `ures_` `change_` `leverage` |
| `BinanceUsdmAdapter.change_margin_type` (raises) | `client.fut` `ures_` `change_` `margin_` `type` |
| `BinanceUsdmAdapter.change_position_mode` (raises) | `client.fut` `ures_` `change_` `position_` `mode` |
| `BinanceUsdmAdapter.account_info_v3` (presence-only) | `client.fut` `ures_` `account()` → `/fapi/v3/account` |
| `BinanceUsdmAdapter.position_risk` (presence-only) | `client.fut` `ures_` `position_` `information()` → `/fapi/v2/positionRisk` |

Preserved invariants from legacy:

- Legacy `OfflineBinanceClient` already demonstrates a refusal/no-op shape with `canTrade: False`. The V2 stub generalises this: every mutation method *raises*; every read-only method returns a presence-of-credentials structural observation only, with `exchange_call_taken: False` always.
- The legacy 25-symbol active subset (from `legacy_reference/config.py SYMBOLS`) is preserved via the V2 Symbol Universe service as `legacy_active_symbols`. The stub never collapses the universe to that 25-symbol subset; it always exposes the broader universe contract.

---

## 3. legacy_inputs

The legacy executors consumed (none of which are consumed by this V2 stub — documented for audit completeness):

- **From Redis (live trader, read):** `signal:*`, `prediction:*`, `orderbook:{symbol}`, `position:*`, `risk_state:*`, `rate_limit:*`, `ban:*`.
- **From config:** `legacy_reference/config.py SYMBOLS`, fee constants, leverage tier tables, kill-switch flags.
- **From exchange (read-only):** `/fapi/v3/account`, `/fapi/v2/positionRisk`, `/fapi/v1/exchangeInfo`, `/fapi/v1/ticker/price`.
- **From environment (secrets):** `BINANCE_LIVE_API_KEY`, `BINANCE_LIVE_API_SECRET` — read by the legacy ccxt/binance client during `__init__`. **Never read by this V2 stub.** The stub only checks *presence* (boolean), never the value.

This V2 stub explicitly **does not** read any of the above. It reads:
- the V2 Symbol Universe contract (per `SYMBOL_UNIVERSE_CONTRACT_REQUIRED`);
- the *presence* (boolean only) of `BINANCE_LIVE_API_KEY` and `BINANCE_LIVE_API_SECRET` env keys, never the values.

---

## 4. legacy_outputs

The legacy executors produced:

- Binance REST mutation acks (with `orderId`, `executedQty`, `avgPrice`).
- Binance REST read-only responses (account balance, position risk, exchange info).
- Redis writes (forbidden in V2): execution receipts, position updates, slippage records, `audit:execution:*` event keys.
- Telegram alerts via `legacy_reference/telegram_alerts.py`.
- Log lines under `legacy_reference/.logs/execution_mode.log`.

This V2 stub produces **only** a public status payload exposing its own disabled state, the presence-or-absence of credentials (boolean only), and the V2 Symbol Universe scope contract. No exchange call, no Redis write, no Telegram, no secret value ever returned or logged.

---

## 5. legacy_redis_keys (read-only audit references)

| Legacy key/stream | Purpose | V2 treatment |
| --- | --- | --- |
| `signal:{symbol}` | enriched signal payload | not read by this stub |
| `orderbook:{symbol}` | hash with `spread_bps`, `total_depth_usd` | not read by this stub |
| `audit:execution:*` | execution audit ledger | not written by this stub |
| `position:*` | position tracking | not read or written |
| `rate_limit:*`, `ban:*` | rate-limiter state | not read or written |

**The V2 stub neither reads nor writes any Redis key.** Statically enforced by tests (no `import` of the binance, ccxt, or redis SDKs; no Redis writer call).

---

## 6. legacy_config_dependencies

- `legacy_reference/config.py SYMBOLS` (current 25-symbol active subset) — **preserved** via V2 Symbol Universe service as `LEGACY_ACTIVE_SYMBOLS_25`.
- `legacy_reference/config.py MAJOR_SYMBOLS_SET` (L301) — not used.
- `LEVERAGE_TIER1_SYMBOLS` env override (L5584) — not used.
- Legacy fee constants (maker=0.0002, taker=0.0005) — not used.
- Env keys `BINANCE_LIVE_API_KEY`, `BINANCE_LIVE_API_SECRET` — *presence-only* boolean read; values never accessed.

---

## 7. legacy_edge_cases

Edge cases the legacy executor handled (documented; intentionally not re-implemented):

- Reduce-only flag on close orders.
- Hedge-mode `positionSide=LONG`/`SHORT` direction tagging.
- Leverage cap on tier-1 vs tier-2 symbols.
- Cross vs isolated margin mode switching.
- `BinanceAPIException` / `BinanceOrderException` retries.
- IP ban detection via `is_banned` / `set_ban`.
- `OfflineBinanceClient` fallback when Binance unreachable.
- Account-info-v3 `canTrade=False` interpretation (legacy treated this as a hard block of mutations).

The V2 stub collapses all of these into one behavior: **raise `BlockedGateNotApprovedError` with code `BLOCKED_GATE_NOT_APPROVED` immediately on any mutation, return a presence-only observation on any read-only call.** No edge case is reached; the gate is closed at the worker boundary above where any of those would matter.

---

## 8. legacy_failure_modes

Legacy failure modes the executor could exhibit:

- Silent fallback to `OfflineBinanceClient` returning fake success-shaped fills.
- Partial fills not reconciled to position state on Redis disconnect mid-execution.
- Leverage change race with concurrent position open.
- Margin-type change rejected by Binance if open position exists.
- Order cancel race with fill.
- REST timeouts and IP bans.
- Secret env values written into logs by upstream Binance/ccxt SDK error paths.

The V2 stub eliminates every failure mode by never reaching an exchange and never reading the secret values. Its only failure mode is: a caller invokes a mutation method → `BlockedGateNotApprovedError`. Read-only callers always receive a presence-only structural observation.

---

## 9. legacy_tests_or_expected_behavior

Legacy expected behavior:

- `legacy_reference/test_binance_testnet_orders.py` — testnet order placement smoke test (writes real testnet orders).
- `legacy_reference/BINANCE_TESTNET_ORDER_TEST_SUCCESS.md` — confirms testnet placement succeeded historically.
- `legacy_reference/Documentation/Audits/maker-first_executor_audit_*.md` — recurring audit reports.
- `legacy_reference/check_order_history.py`, `legacy_reference/monitor_trader_execution.py` — operator scripts reading order/execution state from Binance and Redis.

The V2 stub does **not** replicate any of these. Its **own** test suite asserts the *opposite* shape: every mutation method raises; read-only methods return a presence-only observation; the gate stays `blocked_human_only`; no secret value is returned or logged; no Binance/ccxt/Redis import is reachable; no exchange-client attribute exists.

---

## 10. V2_mapping

| Concern | Legacy artefact | V2 artefact |
| --- | --- | --- |
| Place order | `base_executor.py:105-113` | `BinanceUsdmAdapter.place_order` raises immediately |
| Cancel order | `base_executor.py:1790`, `api/routes/trading_routes.py:435-461`, `stealth_stops.py:486,5666` | `BinanceUsdmAdapter.cancel` raises immediately |
| Change initial leverage | `trader.py:14075, :15245, :19531` | `BinanceUsdmAdapter.change_initial_leverage` raises immediately |
| Change margin type | `trader.py:870` | `BinanceUsdmAdapter.change_margin_type` raises immediately |
| Change position mode | `base_executor.py:90-91` | `BinanceUsdmAdapter.change_position_mode` raises immediately |
| Account info v3 | `base_executor.py:76-88` (`/fapi/v3/account`) | `BinanceUsdmAdapter.account_info_v3` returns presence-only observation; no exchange call, no secret value returned |
| Position risk | `base_executor.py:99-100` (`/fapi/v2/positionRisk`) | `BinanceUsdmAdapter.position_risk` returns presence-only observation; no exchange call, no secret value returned |
| Live-gate default deny | implicit (legacy always-live with `LIVE=True` env) | `LiveBlockGuardMiddleware` at API + this stub at worker layer |
| Symbol scope | `legacy_reference/config.py SYMBOLS` | `v2/backend/app/services/symbol_universe/service.py` `LEGACY_ACTIVE_SYMBOLS_25` exposed as `legacy_active_symbols` |
| Audit surface | Redis `audit:execution:*` writers | public payload `v2_binance_usdm_adapter_status.json` only |

The V2 stub sits **above** `LiveBlockGuardMiddleware`. Permitting live execution requires *replacing* this stub with a real adapter — there is no flag to toggle.

---

## 11. intentional_changes

| Change | Reason |
| --- | --- |
| No exchange client held on the adapter | Eliminate the entire failure surface (REST timeouts, IP bans, SDK exceptions) by removing the dependency. |
| Every mutation method raises before any branch | Default-deny by construction. |
| Read-only methods return presence-only boolean instead of real exchange call | Eliminates any risk of accidentally returning balances/positions when live is blocked; eliminates any risk of secret leakage via response error paths in upstream SDKs. |
| `credentials_present_in_env` is a boolean only; secret values never read or stored | Statically eliminates secret leakage. |
| Counter `blocked_call_attempts_total` and per-method breakdown for both mutation and read-only methods | Observability for GUI and audit ledger. |
| Single `stub_state` enum: `DISABLED` / `BLOCKED` (never `ACTIVE`) | Removes any flag the operator could mistakenly toggle to enable live trading from this surface. |
| No Binance, ccxt, or Redis imports | Statically enforced by tests. |
| Symbol Universe contract emitted on every payload | Required by `SYMBOL_UNIVERSE_CONTRACT_REQUIRED`. |
| `live_symbols` always empty while `live_gate=blocked_human_only` | The field is explicit, not implicit. |
| V2 method `change_margin_type` (kept verb) and `change_position_mode` (kept verb) — V2 normalises only the place-order/leverage names | Compatibility with the canonical Binance REST verbs for the operator-facing audit log, while still refusing every call. |

---

## 12. removed/deprecated behavior

| Removed | Reason |
| --- | --- |
| `OfflineBinanceClient` fallback returning fake `orderId` from a counter | Returning success-shaped fake fills could mislead callers; V2 raises instead. |
| Telegram execution alerts | Out of scope for the refusal surface. |
| Slippage tracking on the executor | Moved to the paper execution worker. |
| Leverage tier auto-cap | Not applicable to a refusal surface. |
| Hedge-mode `positionSide` tagging | Not applicable to a refusal surface. |
| Reduce-only flag enforcement | Not applicable to a refusal surface. |
| Rate-limiter integration | The stub makes no exchange call. |
| Returning real `/fapi/v3/account` and `/fapi/v2/positionRisk` payloads | Eliminated until a real adapter replaces this stub; the read-only methods exist by name but return presence-only observations. |

Every removed behavior is preserved in the legacy reference for re-port at the time a real live execution worker is built — but only after the live gate is unblocked by an explicit human action.

---

## 13. Greenfield justification

This is **not** a greenfield build. The legacy Binance USD-M surface is fully mapped above (seven call sites: five mutation, two read-only). The V2 worker intentionally replaces that surface with:
- a refusal-only surface for the five mutation methods, and
- a presence-only structural-observation surface for the two read-only methods.

The shape (method names, error code, gate semantics) is derived from the legacy operations one-to-one. The only structural break is that the V2 surface refuses unconditionally on mutation and never makes a real exchange call on read-only — which is the entire point of the `LIVE TRADING: BLOCKED` policy and the `blocked_human_only` gate.
