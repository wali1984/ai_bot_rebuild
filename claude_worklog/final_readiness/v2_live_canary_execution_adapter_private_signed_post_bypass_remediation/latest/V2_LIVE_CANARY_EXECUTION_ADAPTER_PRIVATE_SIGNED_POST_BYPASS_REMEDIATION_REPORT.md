# V2 Live-Canary Execution Adapter — Private Signed-Post Bypass Remediation

**Generated:** 2026-05-19 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_READY`
**Codex prior fail:** `REAL_EXCHANGE_ADAPTER_PRIVATE_SIGNED_POST_BYPASSES_GATE_REVALIDATION`
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`
**Default `dry_run`:** `true`
**Default `live_enabled`:** `false`
**Default `exchange_adapter_kind`:** `FakeExchangeAdapter`

## What changed

The prior remediation routed `submit_signed_canary_order` through a
private helper `_perform_signed_post(candidate)` that called
`urllib.request.urlopen` without re-evaluating the 14-gate cascade.
A direct caller who imported the adapter could reach the network
via `transport._perform_signed_post(candidate)`. This packet
eliminates that bypass.

### Architectural changes

1. **Deleted** `_perform_signed_post` entirely from
   `BinanceFuturesExchangeAdapter`. The method no longer exists as
   a class attribute, instance method, static method, or module
   helper.
2. **Inlined** the signed-body construction and the
   `urllib.request.urlopen` call into the body of
   `BinanceFuturesExchangeAdapter.submit_signed_canary_order`
   itself. The gate revalidation, the body composition, and the
   network call now live in the same lexical function scope; they
   cannot be invoked in isolation.
3. **Module-level guarantee:** there is exactly ONE `urllib.request.urlopen(`
   call site in the entire `execution_adapter.py` module, and it
   is inside `submit_signed_canary_order` (verified by the static
   source scan test `test_only_one_urlopen_call_site_in_execution_adapter`).
4. **Forbidden bypass names absent.** A test asserts that NONE of
   the following appear as class attributes on
   `BinanceFuturesExchangeAdapter`:
   - `_perform_signed_post`
   - `_signed_post`
   - `_post_order`
   - `_submit_order_raw`
   - `_send_order`
   - `submit_raw`
5. **Single public method.** The only public callable on the real
   adapter class is `submit_signed_canary_order`.
6. **Endpoint surface scan.** The execution-adapter module
   references only `/fapi/v1/order`. No cancel, modify, leverage,
   margin, allOpenOrders, positionMargin, positionRisk, or
   listenKey endpoint appears.

### Why this is secure

Under the new shape, a direct caller who imports
`BinanceFuturesExchangeAdapter` and invokes its only public method
necessarily triggers the gate revalidation block inside that same
function before the inline urlopen call. There is no way to skip
the revalidation by routing through a private helper because no
such helper exists. The validation sweep, the static source scan
test, and the per-attribute assertions all confirm that:

- exactly 1 urlopen call site in the module;
- that call site is inside `submit_signed_canary_order`;
- the gate revalidation step is the first thing that runs in
  `submit_signed_canary_order` after the type/token rejection;
- no other callable can reach `urlopen` for the order endpoint.

## Codex regression test suite

All test names from the Codex remediation requirement are present
and pass:

| Test | Asserts | urlopen calls |
| --- | --- | --- |
| `test_private_signed_post_method_removed_or_unreachable` | None of the forbidden bypass names exist as attributes | n/a |
| `test_real_adapter_has_no_callable_signed_post_bypass` | Only `submit_signed_canary_order` is a public callable | n/a |
| `test_only_one_urlopen_call_site_in_execution_adapter` | Exactly one urlopen call site, inside the gated function | n/a |
| `test_direct_import_cannot_call_order_endpoint_without_gate_revalidation` | Direct call with missing state → blocked, no urlopen | 0 |
| `test_direct_import_with_forged_gate_decision_makes_zero_urlopen_calls` | Forged token rejected before revalidation | 0 |
| `test_direct_import_with_blocked_live_gate_makes_zero_urlopen_calls` | GATE_13 blocks at revalidation | 0 |
| `test_direct_import_with_empty_live_symbols_makes_zero_urlopen_calls` | GATE_13 (symbols) blocks at revalidation | 0 |
| `test_direct_import_with_kill_switch_armed_makes_zero_urlopen_calls` | GATE_11 blocks at revalidation | 0 |
| `test_direct_import_without_codex_final_marker_makes_zero_urlopen_calls` | GATE_2 blocks at revalidation | 0 |
| `test_direct_import_without_operator_approval_makes_zero_urlopen_calls` | GATE_1 blocks at revalidation | 0 |
| `test_positive_path_revalidates_then_calls_urlopen_exactly_once` | All gates clear → urlopen reached exactly once (spy raises) | 1 |
| `test_positive_path_one_failing_gate_makes_zero_urlopen_calls` | One failing gate (notional cap) → no urlopen | 0 |
| `test_execution_adapter_source_has_no_cancel_modify_leverage_margin_endpoints` | Static source scan confirms only `/fapi/v1/order` | n/a |

## Test results

- `test_v2_live_canary_execution_adapter_operator_gated.py` — **71 passed**
  (58 prior tests + 13 new private-signed-post bypass regression tests).
- `test_v2_live_canary_executor.py` — **13 passed**.
- `test_v2_live_canary_permission_probe.py` — **13 passed**.
- Total: **97 passed.**

No real network call occurred during any test. The urlopen spy
fixture replaces `urllib.request.urlopen` with a function that
records every call and raises if reached. The single positive-path
test that does reach the spy proves re-validation passed; the spy
itself never hits Binance.

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` PASS at 20 files:

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

The exchange-mutation scan was tightened to use a word-boundary
regex so that documented forbidden-name strings like
`_submit_order_raw` (a name we explicitly assert is ABSENT) no
longer false-positive against `submit_order`. The new pattern
matches a verb only when followed by a non-identifier character or
end-of-string.

## What this packet did NOT do

- Did NOT place a real order.
- Did NOT call the real exchange network in any test.
- Did NOT cancel or modify any order.
- Did NOT change leverage or margin mode.
- Did NOT enable live trading.
- Did NOT create any operator approval file.
- Did NOT create any Codex final pass marker.
- Did NOT add any symbol to `live_symbols`.
- Did NOT flip `live_gate` away from `blocked_human_only`.
- Did NOT modify the legacy bot tree or stop legacy.
- Did NOT trim Redis or write any legacy Redis key.
- Did NOT enable any live-canary systemd timer / service.
- Did NOT expose any raw API key/secret value in payloads or logs.
- Did NOT drift into website, paper analytics, full observation,
  alt-data, checkpoint, policy architecture, or shutdown work.

## Status payload safety pins (every payload, every cycle)

- `private_signed_post_bypass_remediated: true`
- `private_signed_post_callable: false`
- `final_order_post_boundary_count: 1`
- `final_post_revalidates_all_gates: true`
- `direct_import_urlopen_call_count_with_missing_gates: 0`
- `direct_import_forged_gate_rejected: true`
- `direct_call_bypass_remediated: true`
- `caller_supplied_gate_boolean_accepted: false`
- `final_submit_rechecks_all_gates: true`
- `exchange_adapter_kind: FakeExchangeAdapter` (default)
- `real_order_attempted: false`
- `real_order_submitted: false`
- `places_real_order: false`
- `writes_exchange_orders: false`
- `writes_legacy_redis: false`
- `leverage_changed: false`
- `margin_mode_changed: false`
- `live_gate: blocked_human_only`
- `live_symbols: []`
- `approves_live: false`
- `approves_canary: false`
- `approves_legacy_shutdown: false`
- `approves_redis_trim: false`
- `raw_credential_in_payload: NEVER`
- `checkpoint_compatibility_claimed: false`
- `policy_architecture_parity_claimed: false`

## Source pointers

- `v2/backend/app/services/live_canary/execution_adapter.py:475-620`
  — `BinanceFuturesExchangeAdapter.submit_signed_canary_order` with
  inline gate revalidation immediately followed by inline urlopen
  call. No separate helper method.
- `v2/backend/app/services/live_canary/execution_adapter.py:584`
  — the SINGLE urlopen call site in the module.
- `v2/backend/tests/integration/cli/test_v2_live_canary_execution_adapter_operator_gated.py`
  — 71 tests total, including the 13 Codex-required regression
  tests listed above.
- `tools/v2_live_canary_validation_sweep.py` — tightened
  `scan_exchange_mutation` regex with word boundaries so forbidden-
  name-absence strings no longer false-positive.

## Non-approvals (unchanged)

This remediation does NOT approve live trading, canary trading,
exchange mutation, leverage/margin change, Redis trim, legacy
shutdown, checkpoint compatibility, policy architecture parity, or
production equivalence. The 14-gate cascade is now resistant to
both the original forged-boolean bypass AND the private-signed-post
bypass; final live-canary approval still requires the operator's
explicit approval file, fresh permission probe, operator-set
runtime live gate, and a Codex final pass marker.
