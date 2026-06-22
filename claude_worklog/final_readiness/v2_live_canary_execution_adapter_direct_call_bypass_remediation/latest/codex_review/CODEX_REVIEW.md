# Codex Review: V2 Live-Canary Execution Adapter Direct-Call Bypass Remediation

Generated: `2026-05-19T03:47:00Z`

GO/NO-GO: `V2_LIVE_CANARY_EXECUTION_ADAPTER_DIRECT_CALL_BYPASS_REMEDIATION_CODEX_FAIL`

## Decision

Codex fails the direct-call bypass remediation. The prior forged boolean path is closed: `submit_real_order` is gone, and a direct call to `submit_signed_canary_order(gate_decision={"canary_signed_by_executor_gate_cascade": true})` is rejected with zero `urlopen` calls.

However, the real adapter still exposes a directly callable signed POST helper, `BinanceFuturesExchangeAdapter._perform_signed_post(candidate)`. Codex monkeypatched `urllib.request.urlopen` and proved that this method reaches the Binance Futures order endpoint without rechecking the 14 gate cascade.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Fail Blocker

`REAL_EXCHANGE_ADAPTER_PRIVATE_SIGNED_POST_BYPASSES_GATE_REVALIDATION`

Observed proof, with no real network call:

- imported `BinanceFuturesExchangeAdapter` directly;
- monkeypatched `urllib.request.urlopen`;
- constructed an `IntentCandidate`;
- called `adapter._perform_signed_post(candidate)`;
- observed `urlopen` call count: `1`;
- observed result flags:
  - `real_order_attempted=true`
  - `real_order_submitted=true`
  - `places_real_order=true`
  - `writes_exchange_orders=true`

The method is named private, but it remains callable on the imported adapter. Under this review contract, any direct-call path that can reach the real order endpoint without current gate revalidation is a fail.

## Prior Bypass Proof Rerun

Codex reran the exact prior bypass shape:

- monkeypatched `urllib.request.urlopen`;
- imported `BinanceFuturesExchangeAdapter` directly;
- attempted to pass forged `canary_signed_by_executor_gate_cascade=true`.

Result:

- `submit_real_order` no longer exists;
- `submit_signed_canary_order` rejected the dict as `REJECTED_NON_GATE_DECISION_OBJECT`;
- `urlopen` call count stayed `0`;
- `real_order_submitted=false`;
- `places_real_order=false`.

That closes the previous blocker, but not the remaining direct `_perform_signed_post` path.

## Gate Cascade Review

Positive findings in `submit_signed_canary_order`:

- rejects non-`GateDecision` objects;
- rejects forged `GateDecision` tokens;
- re-reads the operator approval file;
- requires Codex final live-canary marker;
- re-reads permission probe status and freshness;
- checks mode, whitelist, symbol membership, notional cap, daily trade cap, daily loss cap, kill switch, `live_enabled=true`, `dry_run=false`, runtime live gate, runtime live symbols, and absence of leverage/margin/Redis-trim/legacy-shutdown approvals.

The issue is not the shared gate evaluator. The issue is that the actual signed POST boundary can still be called without that evaluator.

## Runtime State

Codex verified current runtime remains blocked:

- operator approval file: absent;
- Codex final live-canary marker: absent;
- `.local_secrets/live_canary.env`: absent;
- executor CLI: `FakeExchangeAdapter`;
- `dry_run=true`;
- `live_enabled=false`;
- `permission_probe_go_no_go=V2_LIVE_CANARY_PERMISSION_PROBE_BLOCKED`;
- `live_gate=blocked_human_only`;
- `live_symbols=[]`;
- live-canary timers: inactive/not enabled.

Observed live Redis keys are limited to:

- `v2:live_canary:heartbeat`
- `v2:live_canary:intents`
- `v2:live_canary:ledger`
- `v2:live_canary:status`

The refreshed status payload reports no real order attempted or submitted.

## Safety

Codex verified:

- no real exchange network call occurred during this review;
- no raw secret-value hits outside `.local_secrets`;
- no old Redis write path in the reviewed default executor path;
- no leverage endpoint found;
- no margin endpoint found;
- no cancel/modify endpoint found;
- no live/canary/shutdown/Redis-trim approval was created;
- default CLI remains fake/dry-run/live-disabled.

Safety state remains:

- `live_gate`: `blocked_human_only`
- `live_symbols`: `[]`
- `approves_live`: `false`
- `approves_canary`: `false`
- `approves_legacy_shutdown`: `false`
- `approves_redis_trim`: `false`

## Runtime Governors

Standing governors remain ready:

- `CODEX_8H_WAR_ROOM_REVIEW_GOVERNOR_READY`
- runtime GO/NO-GO: `READY`
- website GO/NO-GO: `PASS`
- overall GO/NO-GO: `READY`
- `CODEX_CONTINUOUS_REMEDIATION_REVIEW_GOVERNOR_READY`

This packet-level fail does not indicate runtime drift; it blocks only the live-canary real adapter remediation.

## Validation

- Focused live-canary tests: `84 passed`.
- `py_compile`: PASS.
- Validation sweep: PASS, 20 files scanned.
- Default executor dry-run one-shot: PASS, operator approval still required.
- Raw secret-value scan: PASS, `0` hits outside `.local_secrets`.
- Old Redis write scan: PASS.
- Leverage/margin/cancel/modify endpoint scan: PASS.
- Prior forged-boolean bypass proof: PASS, `0` `urlopen` calls.
- Direct `_perform_signed_post` bypass proof: FAIL BLOCKER, `1` `urlopen` call under monkeypatch.

The existing tests are insufficient because they do not assert that `_perform_signed_post` itself cannot be invoked directly.

## Required Remediation

Move the 14-gate revalidation into the actual signed POST boundary, or make the network step impossible to call without a freshly revalidated gate decision. Acceptable fixes include:

- change `_perform_signed_post` to require a `GateDecision` and re-run `_evaluate_real_order_blockers` inside that method before constructing a request; or
- remove `_perform_signed_post` from the adapter surface and inline the network call only after revalidation in an unexported function that still validates its input; and
- add a regression test that monkeypatches `urllib.request.urlopen`, calls any remaining signed-post helper directly, and proves `urlopen` stays at `0` unless all 14 gates are revalidated at that boundary.

Do not proceed to final live-canary approval until this is fixed and re-reviewed.

## Final Decision

`V2_LIVE_CANARY_EXECUTION_ADAPTER_DIRECT_CALL_BYPASS_REMEDIATION_CODEX_FAIL`
