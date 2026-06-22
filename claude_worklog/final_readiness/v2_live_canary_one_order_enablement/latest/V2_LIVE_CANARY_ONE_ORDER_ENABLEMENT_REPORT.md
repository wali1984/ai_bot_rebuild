# V2 Live-Canary One-Order Enablement

**Generated:** 2026-05-20 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_READY_PENDING_CODEX`
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`

## Purpose

This packet ships the one-order enablement CLI required to reach
the operator-approved BTCUSDT canary path. The packet itself
**ships no real order** — the `_READY_PENDING_CODEX` outcome means
the implementation is in place, every prerequisite is verified,
and Codex must issue the one-order PASS marker before the operator
can invoke `--execute-live-once`.

## What was built

### CLI: [v2_live_canary_one_order_enablement.py](v2/backend/app/cli/v2_live_canary_one_order_enablement.py)

Two modes, both gated by an identical 15-condition preflight
cascade:

1. **`--preflight-only`** — reads approval file, env config,
   permission probe status, three Codex PASS markers (one-order /
   private-signed-post bypass / dry-run binding), kill switch,
   live-canary ledger, and writes a preflight status JSON. ZERO
   network calls. ZERO exchange mutations.
2. **`--execute-live-once`** — fail-closed unless every preflight
   gate clears. Builds an `IntentCandidate` for BTCUSDT with the
   operator-approved notional, constructs a
   `LiveCanaryExecutionAdapter` with `dry_run=False`,
   `live_enabled=True`, and `exchange_adapter=BinanceFuturesExchangeAdapter(api_key, api_secret)`
   (real) when run from an operator shell — or
   `FakeExchangeAdapter` when tests pass `transport=`. The
   `submit_canary_order` call is wrapped in `try/finally` so the
   auto-relock fires regardless of outcome.

### Auto re-lock (mandatory after every `--execute-live-once`)

`_auto_relock_status_payload(...)` writes
`v2:live_canary:status` with:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=False` (implicit — there's no live executor service running)
- `dry_run=True` (back to dry-run default)
- `one_order_attempt_consumed=True` when the adapter was actually
  reached (preflight cleared and the submit was attempted)
- `auto_relocked=True`

Plus a ledger entry tagged
`one_order_enablement_invocation=True` so the next preflight's
daily-trade-count gate sees the attempt and refuses any second
invocation today.

### The 15-gate preflight cascade

| # | Blocker | Source |
| --- | --- | --- |
| 1 | `PREFLIGHT_OPERATOR_APPROVAL_FILE_ABSENT` | parse_approval_file |
| 2 | `PREFLIGHT_CANARY_MODE_MISMATCH` | must be LEGACY_SIGNAL_V2_EXECUTION_CANARY |
| 3 | `PREFLIGHT_APPROVAL_ALLOWED_SYMBOLS_MISSING_BTCUSDT` | approval.allowed_symbols |
| 4 | `PREFLIGHT_APPROVAL_MAX_NOTIONAL_MISSING_OR_NONPOSITIVE` / `ABOVE_PACKET_CAP` | ≤ 55 USDT |
| 5 | `PREFLIGHT_APPROVAL_MAX_DAILY_TRADES_INVALID` | ≤ 1 |
| 6 | `PREFLIGHT_APPROVAL_MAX_DAILY_LOSS_INVALID` | ≤ 5 USDT |
| 7 | `PREFLIGHT_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED` | runtime_live_gate target |
| 8 | `PREFLIGHT_RUNTIME_LIVE_SYMBOLS_NOT_EXACTLY_BTCUSDT` | runtime_live_symbols target |
| 9 | `PREFLIGHT_LEVERAGE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED` | refuse mutation |
| 10 | `PREFLIGHT_MARGIN_MODE_CHANGE_APPROVAL_PRESENT_NOT_ALLOWED` | refuse mutation |
| 11 | `PREFLIGHT_REDIS_TRIM_APPROVAL_PRESENT_NOT_ALLOWED` | refuse mutation |
| 12 | `PREFLIGHT_LEGACY_SHUTDOWN_APPROVAL_PRESENT_NOT_ALLOWED` | refuse mutation |
| 13a | `PREFLIGHT_PERMISSION_PROBE_PASS_NOT_PRESENT` | probe READY required |
| 13b | `PREFLIGHT_PERMISSION_PROBE_STALE_AGE_SECONDS_*` | < 600 s |
| 14a | `PREFLIGHT_CODEX_ONE_ORDER_PASS_MARKER_ABSENT_OR_MISMATCH` | exact content check |
| 14b | `PREFLIGHT_CODEX_PRIVATE_SIGNED_POST_BYPASS_PASS_MARKER_ABSENT_OR_MISMATCH` | exact content check |
| 14c | `PREFLIGHT_CODEX_DRY_RUN_BINDING_PASS_MARKER_ABSENT_OR_MISMATCH` | exact content check |
| 15 | `PREFLIGHT_KILL_SWITCH_ARMED` | redis read |
| 16 | `PREFLIGHT_CANDIDATE_SYMBOL_NOT_BTCUSDT` | candidate check |
| 17 | `PREFLIGHT_CANDIDATE_NOTIONAL_ABOVE_CAP` | candidate ≤ 55 |
| 18 | `PREFLIGHT_CANDIDATE_NOTIONAL_BELOW_EXCHANGE_MIN` | candidate ≥ 50 |
| 19 | `PREFLIGHT_DAILY_LIVE_TRADE_COUNT_AT_OR_ABOVE_LIMIT` | ledger scan |
| 20 | `PREFLIGHT_DAILY_LOSS_AT_OR_ABOVE_LIMIT` | ledger scan |

The downstream `LiveCanaryExecutionAdapter` *also* revalidates its
own 14-gate cascade inside `submit_signed_canary_order`. Defense
in depth: even if a hypothetical packet bug skipped a preflight
check, the adapter's transport boundary would still refuse.

### No recurring live service

There is no new systemd timer for `--execute-live-once`. The
existing dry-run timer (`ai-bot-v2-live-canary-dry-run.timer`)
stays active for the dry-run scope; the one-order path is
**operator-invoked only**.

## Runtime preflight against current state

```
go_no_go=V2_LIVE_CANARY_ONE_ORDER_PREFLIGHT_BLOCKED
preflight_ready=False
blockers=['PREFLIGHT_CODEX_ONE_ORDER_PASS_MARKER_ABSENT_OR_MISMATCH']
approval_file_present=True
canary_mode_selected=LEGACY_SIGNAL_V2_EXECUTION_CANARY
runtime_live_gate_requested=live_canary_operator_approved
runtime_live_symbols_requested=['BTCUSDT']
permission_probe_pass_present=True
permission_probe_fresh=True
codex_one_order_pass_present=False
codex_private_signed_post_bypass_pass_present=True
codex_dry_run_binding_pass_present=True
kill_switch_armed=False
daily_live_trade_count=0
daily_loss_usdt=0.0
```

**Exactly one** blocker: the Codex one-order PASS marker is absent.
Every other prerequisite has been satisfied by prior packets:
permission probe READY+fresh, approval file binds, dry-run binding
Codex PASS, private signed-post bypass Codex PASS, kill switch
disarmed, no prior live trade today, no daily loss today.

## Test results

**23 / 23 pass** in
[test_v2_live_canary_one_order_enablement.py](v2/backend/tests/integration/cli/test_v2_live_canary_one_order_enablement.py).
Coverage:

- Preflight READY with full approved config.
- Preflight BLOCKED on missing Codex one-order PASS file.
- Preflight BLOCKED on wrong Codex one-order PASS content.
- Preflight BLOCKED on armed kill switch.
- Preflight BLOCKED on daily-trade-count at limit (ledger scan).
- Preflight BLOCKED on notional > 55.
- Preflight BLOCKED on notional < 50 (exchange min).
- Preflight BLOCKED on symbol != BTCUSDT.
- Preflight BLOCKED on stale permission probe.
- Preflight BLOCKED on runtime_live_symbols != [BTCUSDT].
- Preflight BLOCKED on `leverage_change_approved: YES`.
- Preflight BLOCKED on `margin_mode_change_approved: YES`.
- `--execute-live-once` BLOCKED without Codex one-order PASS file
  → fake transport NEVER invoked.
- `--execute-live-once` BLOCKED with armed kill switch → fake
  transport NEVER invoked.
- `--execute-live-once` BLOCKED with notional > 55 → fake transport
  NEVER invoked.
- `--execute-live-once` BLOCKED with symbol != BTCUSDT → fake
  transport NEVER invoked.
- `--execute-live-once` BLOCKED with stale probe → fake transport
  NEVER invoked.
- `--execute-live-once` happy path with `FakeExchangeAdapter`:
  preflight passes, adapter invoked **exactly once**, auto-relock
  fires, `live_gate_after=blocked_human_only`, `live_symbols_after=[]`,
  `one_order_attempt_consumed=True`, `raw_credential_in_payload=NEVER`.
- **No second attempt today**: the second `--execute-live-once`
  call after a successful (fake) attempt finds the daily-trade-count
  gate already armed; second fake transport `call_count == 0`.
- **No legacy Redis writes**: every observed Redis key starts with
  `v2:live_canary:`.
- **No raw credential serialization**: synthetic credential injected
  into env never appears in the result payload.
- Preflight payload pins all safety invariants when BLOCKED.
- Auto-relock status payload pins live_gate=blocked_human_only,
  live_symbols=[], all `approves_*=false`,
  `raw_credential_in_payload=NEVER`.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` PASS at 22 files. 0
secret hits, 0 approval_true hits, 0 legacy Redis writes, 0
exchange-mutation verbs, 0 JSON parse failures.

## Safety pins (all enforced)

`dry_run=true` (default), `live_enabled=false` (default),
`exchange_adapter_kind=FakeExchangeAdapter` (default + tests),
`real_order_attempted=false`, `real_order_submitted=false`,
`places_real_order=false`, `writes_exchange_orders=false`,
`writes_legacy_redis=false`, `leverage_changed=false`,
`margin_mode_changed=false`, `live_gate=blocked_human_only`,
`live_symbols=[]`, `approves_live=false`, `approves_canary=false`,
`approves_legacy_shutdown=false`, `approves_redis_trim=false`,
`raw_credential_in_payload=NEVER`,
`private_signed_post_bypass_remediated=true`,
`private_signed_post_callable=false`,
`final_order_post_boundary_count=1`,
`final_post_revalidates_all_gates=true`,
`checkpoint_compatibility_claimed=false`,
`policy_architecture_parity_claimed=false`.

## What this packet did NOT do

- Did NOT create the Codex one-order PASS marker.
- Did NOT place any real order.
- Did NOT call `/fapi/v1/order`.
- Did NOT call `/fapi/v1/order/test` (neither operator-approved gate
  is set).
- Did NOT enable any new recurring systemd service.
- Did NOT change leverage or margin mode.
- Did NOT modify the legacy bot tree.
- Did NOT write to legacy Redis keys.
- Did NOT add any frontend control button.
- Did NOT expose raw credentials.
- Did NOT touch the existing dry-run timer or the website backend
  service.

## Operator next steps

1. Submit this packet to Codex for the one-order enablement review.
2. On Codex PASS, place the marker at
   `claude_worklog/final_readiness/v2_live_canary_one_order_enablement/latest/codex_review/CODEX_GO_NO_GO.md`
   containing exactly the single line
   `V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_PASS`.
3. From a shell with `BINANCE_API_KEY` and `BINANCE_API_SECRET`
   exported (the same shell environment Codex verified for the
   permission-probe READY path), invoke:
   ```
   python3 -m v2.backend.app.cli.v2_live_canary_one_order_enablement --execute-live-once
   ```
4. The CLI re-runs the full 15-gate preflight, dispatches to the
   real `BinanceFuturesExchangeAdapter`, the adapter independently
   re-validates its 14-gate cascade inline before any `urlopen`
   call, the order goes through, and the auto-relock fires in
   `try/finally` returning the system to
   `live_gate=blocked_human_only`, `live_symbols=[]`.
5. A second invocation the same UTC day is blocked by the
   daily-trade-count cap reading the live-canary ledger.

## Source pointers

- [v2_live_canary_one_order_enablement.py](v2/backend/app/cli/v2_live_canary_one_order_enablement.py)
  — CLI + preflight + execute_live_once + auto-relock.
- [test_v2_live_canary_one_order_enablement.py](v2/backend/tests/integration/cli/test_v2_live_canary_one_order_enablement.py)
  — 23 tests; all use FakeExchangeAdapter; no real network call.
- Adapter the CLI dispatches into:
  [execution_adapter.py](v2/backend/app/services/live_canary/execution_adapter.py).
  The adapter's transport boundary (`submit_signed_canary_order`)
  independently re-validates the 14-gate cascade inline before its
  single `urllib.request.urlopen` call.
