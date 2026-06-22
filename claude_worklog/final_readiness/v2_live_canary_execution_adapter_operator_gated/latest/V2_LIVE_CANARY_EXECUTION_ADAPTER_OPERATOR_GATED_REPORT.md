# V2 Live-Canary Operator-Gated Execution Adapter — Implementation Report

**Generated:** 2026-05-19 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_EXECUTION_ADAPTER_OPERATOR_GATED_READY`
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`
**Default `dry_run`:** `true`
**Default `live_enabled`:** `false`
**Default `exchange_adapter`:** `FakeExchangeAdapter` (no network surface)

This packet replaces the prior `NotImplementedError` placeholder
with a real exchange adapter that is *impossible to activate*
unless every one of the 14 operator-final gate conditions is
simultaneously satisfied AND the caller has explicitly constructed
the adapter with a real `BinanceFuturesExchangeAdapter` AND set
`live_enabled=True` / `dry_run=False`.

## The 14 gate conditions

Each is enumerated in `LiveCanaryExecutionAdapter.evaluate_real_order_blockers`:

| Gate | Condition | Blocker label |
| --- | --- | --- |
| 1 | Operator approval file present | `GATE_1_OPERATOR_APPROVAL_FILE_ABSENT` |
| 2 | Codex final live-canary PASS marker present | `GATE_2_CODEX_FINAL_LIVE_CANARY_PASS_MARKER_ABSENT` |
| 3 | Permission probe PASS exists AND fresh | `GATE_3_PERMISSION_PROBE_PASS_NOT_PRESENT` / `GATE_3_PERMISSION_PROBE_STALE_AGE_SECONDS_*` |
| 4 | Canary mode selected (V2-native or legacy-signal) | `GATE_4_CANARY_MODE_NOT_SELECTED_OR_INVALID` |
| 5 | Approved symbol whitelist non-empty | `GATE_5_APPROVED_SYMBOL_WHITELIST_EMPTY` |
| 6 | Candidate symbol in approved whitelist | `GATE_6_SYMBOL_NOT_IN_APPROVED_WHITELIST` |
| 7 | Max notional cap present and positive | `GATE_7_MAX_NOTIONAL_CAP_MISSING_OR_NONPOSITIVE` |
| 8 | Requested notional within cap | `GATE_8_REQUESTED_NOTIONAL_ABOVE_CAP` |
| 9 | Daily trade count below limit | `GATE_9_DAILY_TRADE_COUNT_AT_OR_ABOVE_LIMIT` |
| 10 | Daily realized loss below limit | `GATE_10_DAILY_LOSS_AT_OR_ABOVE_LIMIT` |
| 11 | Kill switch DISARMED | `GATE_11_KILL_SWITCH_ARMED` |
| 12 | `live_enabled=True` AND `dry_run=False` | `GATE_12_LIVE_ENABLED_FALSE` / `GATE_12_DRY_RUN_TRUE_BLOCKS_REAL_ORDER` |
| 13 | Runtime gate matches `live_canary_operator_approved`; runtime symbols match approved | `GATE_13_RUNTIME_LIVE_GATE_NOT_OPERATOR_APPROVED` / `GATE_13_RUNTIME_LIVE_SYMBOLS_NOT_EQUAL_APPROVED_SYMBOLS` |
| 14 | NO leverage / margin / Redis-trim / legacy-shutdown approval flags | `GATE_14_*_APPROVAL_PRESENT_NOT_ALLOWED` |

Even with all 14 gates clear, the adapter still requires the caller
to have constructed it with `exchange_adapter=BinanceFuturesExchangeAdapter(...)`;
otherwise the default `FakeExchangeAdapter` is what's invoked, and
no real network call occurs.

## What the real adapter does and does NOT do

`BinanceFuturesExchangeAdapter`:

- The ONLY public method is `submit_real_order`.
- The ONLY endpoint is `POST /fapi/v1/order` (Binance Futures
  documented New Order endpoint).
- Refuses any intent missing
  `canary_signed_by_executor_gate_cascade=True`.
- Reads and discards the response body so account state, position
  details, or order IDs cannot leak into the payload.
- NEVER cancels orders. NEVER modifies orders. NEVER changes
  leverage. NEVER changes margin mode. NEVER writes legacy Redis.
- Static class-level test asserts no member contains
  "leverage" / "margin" / "cancel" / "modify".

`FakeExchangeAdapter` (the default):

- Records intents in-memory.
- Returns `{"real_order_submitted": False, "exchange_response_status": "FAKE_NO_NETWORK_CALL"}`.
- NEVER opens a network socket.

## Files shipped

- `v2/backend/app/services/live_canary/execution_adapter.py`:
  - `ExchangeAdapter` Protocol, `FakeExchangeAdapter`,
    `BinanceFuturesExchangeAdapter`.
  - Extended `ApprovalEnvelope` with
    `runtime_live_gate_requested` and
    `runtime_live_symbols_requested`.
  - `PermissionProbeFreshness.from_path` reads the probe status
    file and checks `go_no_go=READY` + freshness window.
  - `LiveCanaryExecutionAdapter.evaluate_real_order_blockers`
    enumerates the 14-condition cascade.
  - `LiveCanaryExecutionAdapter.submit_canary_order` returns a
    structured BLOCKED result with a fake adapter when ANY gate
    fails, otherwise signs the intent and dispatches to the
    configured exchange adapter.
  - `_safe_redis_set` enforces the 5-key allowlist
    (`v2:live_canary:intents`, `:ledger`, `:heartbeat`, `:status`,
    `:kill_switch`).
  - `parse_approval_file` parses the new `runtime_live_gate` and
    `runtime_live_symbols` fields (defaults to `blocked_human_only`
    and `()`).
- `v2/backend/app/cli/v2_live_canary_executor.py`:
  - Default exchange adapter: `FakeExchangeAdapter`.
  - Reads permission probe status freshness via
    `PermissionProbeFreshness.from_path`.
  - Reports new operator-gated fields in the status payload:
    `runtime_live_gate_requested`, `runtime_live_symbols_requested`,
    `codex_final_live_canary_pass_marker_present`,
    `permission_probe_fresh`, `permission_probe_age_seconds`,
    `operator_gated_gate_cascade_conditions`.
  - `allowed_redis_writes` extended with `v2:live_canary:kill_switch`.
- `v2/backend/tests/integration/cli/test_v2_live_canary_execution_adapter_operator_gated.py`
  — 48 new tests, one per gate condition plus default-construction
  safety + real-adapter construction guards + Redis-write boundary
  + payload safety + approval file parser + permission probe
  freshness. NEVER constructs `BinanceFuturesExchangeAdapter` with
  real credentials; NEVER reaches a real network call.
- `v2/backend/tests/integration/cli/test_v2_live_canary_executor.py`
  — 13 tests updated to the new `GATE_*` blocker labels; the
  obsolete `NotImplementedError` test replaced with
  `test_submit_canary_order_returns_blocked_with_default_adapter`.
- `tools/v2_live_canary_validation_sweep.py` updated to scan test
  files in a narrower band (exchange-mutation only) because tests
  legitimately contain synthetic adversarial inputs.

## Test results

- `test_v2_live_canary_execution_adapter_operator_gated.py` — **48 passed.**
- `test_v2_live_canary_executor.py` — **13 passed.**
- `test_v2_live_canary_permission_probe.py` — **13 passed.**
- Total: **74 passed.**

## Validation sweep (offline, adversarial)

`tools/v2_live_canary_validation_sweep.py` PASS with 20 files
scanned (6 source + 4 systemd + 7 status + 3 test files):

```
{
  "files_scanned": 20,
  "missing_files": [],
  "secret_hits": 0,
  "approval_true_hits": 0,
  "legacy_redis_hits": 0,
  "exchange_mutation_hits": 0,
  "json_parse_failures": 0,
  "status": "PASS"
}
```

No secret-like value in source/status, no `"approves_X": true`
drift, no legacy Redis namespace, no exchange-mutation verb in
source or test files.

## What this packet did NOT do

- Did NOT place a real order. The default adapter is
  `FakeExchangeAdapter`; the real adapter is in source but
  unreachable from the executor CLI.
- Did NOT cancel or modify any order.
- Did NOT change leverage or margin mode (the real adapter has no
  such method).
- Did NOT enable live trading.
- Did NOT create any operator approval token.
- Did NOT create any Codex final pass marker.
- Did NOT add any symbol to `live_symbols`.
- Did NOT flip `live_gate` away from `blocked_human_only`.
- Did NOT modify the legacy bot tree or stop legacy.
- Did NOT trim Redis or write any legacy Redis key.
- Did NOT write outside the `v2:live_canary:*` 5-key allowlist.
- Did NOT expose any raw API key/secret value in payloads or logs.

## Operator final-approval checklist

To advance from this PASS to a real live canary order, the operator
must complete every step below, and Codex must pass the final
review:

1. Place `.local_secrets/live_canary.env` with:
   - `V2_LIVE_CANARY_MODE` (one of the valid modes)
   - `V2_LIVE_CANARY_SYMBOLS=<approved symbol list>`
   - `V2_LIVE_CANARY_MAX_NOTIONAL_USDT=<small positive number>`
   - `V2_LIVE_CANARY_MAX_DAILY_TRADES=<small integer>`
   - `V2_LIVE_CANARY_MAX_DAILY_LOSS_USDT=<small positive number>`
   - `V2_LIVE_CANARY_DRY_RUN=true` initially
2. Export `BINANCE_API_KEY` and `BINANCE_API_SECRET` in the operator
   shell. NEVER write these into the env file.
3. Run the permission probe one-shot; verify it transitions to
   `V2_LIVE_CANARY_PERMISSION_PROBE_READY` and the status file's
   `generated_utc` is fresh.
4. Place the operator approval file at
   `claude_worklog/approvals/OPERATOR_ACCEPTS_V2_LIVE_CANARY_LIMITATIONS.md`
   with `runtime_live_gate: live_canary_operator_approved` and
   `runtime_live_symbols: <same as live_symbols>`. The four
   `*_approved` fields for leverage / margin / Redis-trim /
   legacy-shutdown MUST remain `NO`.
5. Submit this packet to Codex for the final live-canary review.
   When Codex passes, place the marker at
   `claude_worklog/final_readiness/v2_live_canary_execution_adapter_operator_gated/latest/codex_review/CODEX_FINAL_LIVE_CANARY_PASS.marker`.
6. In a separate, reviewed entrypoint (NOT the executor CLI),
   construct `LiveCanaryExecutionAdapter` with
   `exchange_adapter=BinanceFuturesExchangeAdapter(api_key, api_secret)`,
   `dry_run=False`, `live_enabled=True`. Disarm the kill switch.
7. Call `adapter.submit_canary_order(candidate=..., cycle_id=...)`.
   The 14-gate cascade runs; if any gate fails, the result is
   BLOCKED with the failing gate labels and no real order goes out.
   If all gates pass, the signed POST to `/fapi/v1/order` executes,
   and the result records the actual exchange response status.

The executor CLI is NOT the entrypoint for real orders. It
defaults to the fake adapter and dry-run. A separate operator-only
entrypoint must be authored and reviewed before any real order
flow exists.

## Source pointers

- `v2/backend/app/services/live_canary/execution_adapter.py:215-285`
  — `BinanceFuturesExchangeAdapter` with single signed POST surface.
- `v2/backend/app/services/live_canary/execution_adapter.py:357-431`
  — `evaluate_real_order_blockers` 14-gate cascade.
- `v2/backend/app/services/live_canary/execution_adapter.py:480-540`
  — `submit_canary_order` dispatching to fake (default) or real
  exchange adapter.
- `v2/backend/tests/integration/cli/test_v2_live_canary_execution_adapter_operator_gated.py`
  — 48 fail-closed gate tests.
- `tools/v2_live_canary_validation_sweep.py` — PASS at 20 files, 0
  hits.
