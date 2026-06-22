# Codex Review: V2 Live-Canary Operator-Gated Execution Adapter

Generated: `2026-05-19T03:13:57Z`

GO/NO-GO: `V2_LIVE_CANARY_EXECUTION_ADAPTER_CODEX_FAIL`

## Decision

Codex fails the operator-gated execution adapter. The default executor CLI remains fake/dry-run and the 14-gate cascade is well covered, but the real `BinanceFuturesExchangeAdapter` can be imported and called directly with a forgeable boolean field:

`canary_signed_by_executor_gate_cascade=True`

That direct call path does not re-check the operator approval file, Codex final pass marker, permission-probe freshness, symbol whitelist, notional cap, daily trade cap, daily loss cap, kill switch, runtime live gate, or runtime live symbols. Under the review contract, any live order path that can bypass those gates is a fail.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Fail Blocker

`REAL_EXCHANGE_ADAPTER_DIRECT_CALL_BYPASSES_OPERATOR_GATE_CASCADE`

Codex proved the direct-call path without touching the network by monkeypatching `urllib.request.urlopen`. With dummy credentials and a payload containing the boolean gate flag, the real adapter attempted a signed POST to:

`https://fapi.binance.com/fapi/v1/order`

Observed from the monkeypatched call:

- fake network calls: `1`
- method: `POST`
- result `real_order_submitted=true`
- result `places_real_order=true`

No real network call was made during this proof. The finding is code-level reachability: the real adapter trusts a caller-provided boolean instead of an unforgeable gate proof.

## Positive Findings

Codex verified the default runtime path is still blocked:

- executor CLI constructs `FakeExchangeAdapter`
- executor CLI runs `dry_run=true`
- executor CLI sets `live_enabled=false`
- operator approval file is absent
- Codex final live-canary marker is absent
- `.local_secrets/live_canary.env` is absent
- permission probe status is not READY
- live-canary timers/services are inactive and not enabled

Live Redis state after a dry-run executor refresh is V2-only:

- `v2:live_canary:intents`
- `v2:live_canary:ledger`
- `v2:live_canary:heartbeat`
- `v2:live_canary:status`

The live Redis payloads show:

- `exchange_adapter_kind=FakeExchangeAdapter`
- `live_enabled=false`
- `real_order_submitted=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `live_symbols=[]`

## Gate Cascade Review

The `LiveCanaryExecutionAdapter.evaluate_real_order_blockers` method enumerates the required gates:

- operator approval file;
- Codex final pass marker;
- permission probe READY and fresh;
- canary mode selected;
- symbol whitelist non-empty;
- candidate symbol inside whitelist;
- max notional cap present and positive;
- requested notional at or below cap;
- daily trade count below limit;
- daily loss below limit;
- kill switch disarmed;
- `live_enabled=true` and `dry_run=false`;
- runtime live gate equals `live_canary_operator_approved`;
- runtime live symbols equal approved symbols;
- leverage, margin, Redis-trim, and legacy-shutdown approvals absent.

The problem is not the cascade itself. The problem is that the real exchange adapter does not enforce the cascade and can be called directly.

## Safety

Codex verified:

- no raw secret-value hits in reviewed artifacts;
- no old Redis write path in the default executor path;
- no leverage or margin endpoint in the real adapter class;
- no cancel/modify endpoint in the real adapter class;
- no legacy-shutdown approval in reviewed payloads;
- no production-equivalence claim in reviewed payloads;
- `live_gate=blocked_human_only` in current runtime payloads;
- `live_symbols=[]` in current runtime payloads.

These positive checks do not override the direct-call fail blocker.

## Runtime Governors

Standing governors remain ready:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- core migration GO/NO-GO: `READY`
- overall GO/NO-GO: `READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`

## Validation

- Focused live-canary tests: `74 passed`.
- `py_compile`: PASS.
- Validation sweep: PASS, 20 files scanned.
- Live dry-run executor one-shot: PASS.
- Redis write boundary check: PASS for current runtime keys.
- Raw secret-value scan: PASS.
- Old Redis write scan: PASS.
- Leverage/margin/cancel/modify endpoint scan: PASS.
- Direct-call bypass proof: FAIL BLOCKER.

The current tests are insufficient because they do not assert that `BinanceFuturesExchangeAdapter.submit_real_order` cannot be called directly with a forged `canary_signed_by_executor_gate_cascade=True` field.

## Required Remediation

Make the real exchange adapter incapable of bypassing the gate cascade. Acceptable fixes include:

- remove the direct network adapter from this packet until the final reviewed entrypoint exists; or
- make `BinanceFuturesExchangeAdapter` private to a final reviewed entrypoint and not importable as a general service surface; or
- replace the forgeable boolean with an unforgeable gate-proof object created only after the 14-gate cascade and validated inside the real adapter; and
- add tests proving direct calls to the real adapter cannot submit an order without the same operator approval, final Codex marker, fresh permission probe, whitelist, limits, kill switch, runtime live gate, and runtime live symbols.

Until this is fixed, no final live-canary approval should be issued.

## Final Decision

`V2_LIVE_CANARY_EXECUTION_ADAPTER_CODEX_FAIL`
