# V2 Live-Canary Execution Adapter — Direct-Call Bypass Remediation

**Generated:** 2026-05-19 (UTC)
**GO_NO_GO:** `V2_LIVE_CANARY_EXECUTION_ADAPTER_DIRECT_CALL_BYPASS_REMEDIATION_READY`
**Codex prior fail:** `REAL_EXCHANGE_ADAPTER_DIRECT_CALL_BYPASSES_OPERATOR_GATE_CASCADE`
**Default `live_gate`:** `blocked_human_only`
**Default `live_symbols`:** `[]`
**Default `dry_run`:** `true`
**Default `live_enabled`:** `false`
**Default `exchange_adapter_kind`:** `FakeExchangeAdapter`

## What changed

The forgeable boolean trust boundary
(`canary_signed_by_executor_gate_cascade`) has been removed from
intent payloads entirely. The real exchange adapter now
independently re-evaluates all 14 gates from current disk/Redis
state at the moment of submission. A direct call to
`BinanceFuturesExchangeAdapter.submit_signed_canary_order` cannot
reach `urllib.request.urlopen` unless the operator approval file,
Codex final pass marker, fresh permission probe, kill switch,
runtime live gate, runtime live symbols, notional cap, daily
counters, and the four leverage / margin / Redis-trim /
legacy-shutdown approval restrictions all clear when the transport
re-reads them at submission time.

### Architectural changes

1. **Removed** the field
   `canary_signed_by_executor_gate_cascade` from
   `LiveCanaryExecutionAdapter.build_intent_record`. No caller-
   supplied boolean of any shape can authorize a real order.
2. **Added** a module-private constant `_MODULE_GATE_TOKEN`
   (per-process random token) and a `GateDecision` dataclass that
   carries the parameters needed for re-validation.
3. **Extracted** the 14-gate cascade into a module-level
   `_evaluate_real_order_blockers` function. Both the executor
   (during intent building) and the real transport (during
   submission revalidation) call this same function, so the two
   evaluations cannot drift.
4. **Replaced** `BinanceFuturesExchangeAdapter.submit_real_order`
   with `submit_signed_canary_order(*, gate_decision)` that:
   - rejects non-`GateDecision` arguments (defense-in-depth);
   - rejects `GateDecision` with a forged `_token`
     (defense-in-depth);
   - re-reads `parse_approval_file(gate_decision.approval_file_path)`
     from disk;
   - re-reads
     `PermissionProbeFreshness.from_path(gate_decision.permission_probe_status_path)`
     from disk;
   - calls `_evaluate_real_order_blockers(...)` with the freshly-read
     state;
   - returns `REJECTED_GATE_REVALIDATION_FAILED` with the full
     blocker list when any gate fails — and no network call occurs;
   - only after every gate clears does
     `_perform_signed_post(candidate)` run the signed POST to
     `/fapi/v1/order`.
5. **Replaced** `FakeExchangeAdapter.submit_real_order` with
   `submit_signed_canary_order(*, gate_decision)` for interface
   parity. The fake transport NEVER calls the network.
6. **Updated** `LiveCanaryExecutionAdapter.submit_canary_order` to
   build a `GateDecision` via the module-private factory and
   dispatch to the configured transport. On any executor-level
   blocker, a fresh `FakeExchangeAdapter` is invoked instead of
   the configured (possibly real) transport.
7. **Added** the status fields `direct_call_bypass_remediated:
   true`, `caller_supplied_gate_boolean_accepted: false`, and
   `final_submit_rechecks_all_gates: true` to the intent record,
   the executor CLI status payload, and the operator dashboard
   payload.

### Why this is secure

The `_MODULE_GATE_TOKEN` defense alone is insufficient — a caller
could import the constant from the module and forge a matching
token. The real security guarantee is the
**re-validation step**:

- The transport reads the operator approval file FRESHLY at submission.
- The transport reads the Codex final pass marker FRESHLY at submission.
- The transport reads the permission probe status file FRESHLY at submission.
- The transport reads the kill switch via the passed Redis client FRESHLY at submission.
- The transport reads runtime live gate / symbols FRESHLY from the approval file at submission.
- The transport then calls the shared `_evaluate_real_order_blockers` function.
- If any gate fails, NO urlopen call happens.

A direct-call attacker cannot fake the absence of an approval file,
the absence of a Codex marker, the staleness of the permission
probe, an armed kill switch, a wrong runtime live gate, etc. The
network call is GATED BY THE FILESYSTEM AND REDIS STATE, not by a
caller-supplied flag.

## Codex-regression test suite

The Codex-required test name
`test_real_exchange_adapter_direct_call_cannot_bypass_gate_cascade`
is implemented and passes. It monkeypatches
`urllib.request.urlopen` to fail loudly if reached, then attempts
several direct-call attacks against
`BinanceFuturesExchangeAdapter.submit_signed_canary_order`:

- non-`GateDecision` argument (dict with forged
  `canary_signed_by_executor_gate_cascade=True`);
- correctly-typed `GateDecision` with forged `_token`;

Both attacks are rejected without any urlopen call.

In addition, **eight scenario tests** prove that even with the
correct token, a direct call to the transport cannot reach the
network when any single state check fails:

| Test name | Failing gate | urlopen calls |
| --- | --- | --- |
| `test_direct_call_no_approval_file_causes_zero_urlopen` | GATE_1 | 0 |
| `test_direct_call_no_codex_final_marker_causes_zero_urlopen` | GATE_2 | 0 |
| `test_direct_call_stale_permission_probe_causes_zero_urlopen` | GATE_3 | 0 |
| `test_direct_call_kill_switch_armed_causes_zero_urlopen` | GATE_11 | 0 |
| `test_direct_call_runtime_live_gate_blocked_causes_zero_urlopen` | GATE_13 | 0 |
| `test_direct_call_runtime_live_symbols_empty_causes_zero_urlopen` | GATE_13 | 0 |
| `test_direct_call_over_max_notional_causes_zero_urlopen` | GATE_8 | 0 |

And two positive-path tests:

- `test_positive_path_all_gates_pass_uses_fake_transport_only` —
  when every gate clears AND a fake transport is configured, the
  fake transport is called once and urlopen is never reached.
- `test_positive_path_real_transport_revalidates_and_reaches_urlopen`
  — when every state-check clears at submission, the real
  transport DOES reach urlopen (proving re-validation is what
  gates the call; we still don't hit the actual network because
  the test monkeypatches urlopen to raise).

## Test results

- `test_v2_live_canary_execution_adapter_operator_gated.py` — **58 passed**
  (48 prior gate tests + 10 new direct-call bypass regression tests).
- `test_v2_live_canary_executor.py` — **13 passed**.
- `test_v2_live_canary_permission_probe.py` — **13 passed**.
- Total: **84 passed.**

## Validation sweep

`tools/v2_live_canary_validation_sweep.py` PASS at 20 files
scanned:

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

## What this packet did NOT do

- Did NOT place a real order (no test ever reached real Binance;
  the only positive-path test that touches the urlopen surface
  monkeypatches it to raise).
- Did NOT call the real exchange network in any test.
- Did NOT cancel or modify any order.
- Did NOT change leverage or margin mode (no such method exists on
  the real adapter class).
- Did NOT enable live trading.
- Did NOT create any operator approval file.
- Did NOT create any Codex final pass marker.
- Did NOT add any symbol to `live_symbols`.
- Did NOT flip `live_gate` away from `blocked_human_only`.
- Did NOT modify the legacy bot tree or stop legacy.
- Did NOT trim Redis or write any legacy Redis key.
- Did NOT enable any live-canary systemd timer / service.
- Did NOT expose any raw API key/secret value in payloads or logs.
- Did NOT drift into website, paper analytics, observation
  builder, alt-data, shutdown, or policy-architecture work.

## Status payload safety pins (every payload, every cycle)

- `direct_call_bypass_remediated: true`
- `caller_supplied_gate_boolean_accepted: false`
- `final_submit_rechecks_all_gates: true`
- `real_order_attempted: false`
- `real_order_submitted: false`
- `places_real_order: false`
- `writes_exchange_orders: false`
- `writes_legacy_redis: false`
- `leverage_changed: false`
- `margin_mode_changed: false`
- `exchange_adapter_kind: FakeExchangeAdapter` (default)
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

- `v2/backend/app/services/live_canary/execution_adapter.py:103-105`
  — `_MODULE_GATE_TOKEN` per-process random constant.
- `v2/backend/app/services/live_canary/execution_adapter.py:215-241`
  — `GateDecision` dataclass and `_create_gate_decision` factory.
- `v2/backend/app/services/live_canary/execution_adapter.py:255-330`
  — `_evaluate_real_order_blockers` shared 14-gate function.
- `v2/backend/app/services/live_canary/execution_adapter.py:392-465`
  — `BinanceFuturesExchangeAdapter.submit_signed_canary_order` with
  three-stage rejection (type check, token check, state
  re-validation).
- `v2/backend/app/services/live_canary/execution_adapter.py:467-540`
  — `_perform_signed_post` private network step (unreachable
  except through the re-validated path above).
- `v2/backend/tests/integration/cli/test_v2_live_canary_execution_adapter_operator_gated.py`
  — 58 tests; Codex-regression name
  `test_real_exchange_adapter_direct_call_cannot_bypass_gate_cascade`
  plus eight scenario tests with urlopen spy.

## Non-approvals (unchanged)

This remediation does NOT approve live trading, canary trading,
exchange mutation, leverage/margin change, Redis trim, legacy
shutdown, checkpoint compatibility, policy architecture parity, or
production equivalence. The 14-gate cascade is now resistant to
direct-call bypass; final live-canary approval still requires the
operator's explicit approval file, fresh permission probe,
operator-set runtime live gate, and a Codex final pass marker.
