# Codex Review: V2 Live-Canary One-Order Enablement

Generated: `2026-05-20T21:36:12Z`

GO/NO-GO: `V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_FAIL`

## Decision

Codex fails the one-order BTCUSDT live-canary enablement packet. The current runtime state is safe and blocked, the permission probe is READY/fresh, and the dry-run canary path is bounded. However, the one-order preflight does not enforce two prerequisite Codex PASS markers correctly.

The one-order CLI labels the private signed-post bypass and dry-run approval-binding checks as Codex pass checks, but the code reads the implementation `latest/GO_NO_GO.md` files and accepts `*_READY` content instead of reading the actual `codex_review/CODEX_GO_NO_GO.md` files and requiring `*_CODEX_PASS`.

This review does not approve live trading, canary trading, exchange mutation, leverage/margin changes, Redis trim, approval creation, checkpoint compatibility, policy architecture parity, production equivalence, or legacy shutdown.

## Fail Blocker

`PREREQUISITE_CODEX_PASS_MARKERS_NOT_ENFORCED_FOR_ONE_ORDER_PREFLIGHT`

Codex verified the one-order preflight constants currently accept implementation readiness markers for two prerequisite gates:

- private signed-post bypass remediation: accepts `V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_READY`
- dry-run approval-binding remediation: accepts `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_READY`

The required Codex markers exist separately and contain:

- `V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_CODEX_PASS`
- `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_CODEX_PASS`

Codex also proved, without any network call, that a temporary one-order preflight can return ready when the prerequisite marker files contain only the implementation `READY` strings. That means the one-order live path can clear those prerequisite checks without verifying the intended Codex PASS files. Under the review contract, a live order must not be able to happen without the relevant Codex PASS evidence.

The current packet remains blocked only because this one-order review has not emitted a PASS marker. Writing this FAIL preserves that block.

## Positive Findings

Codex verified the operator and runtime setup is otherwise bounded:

- operator approval file exists and matches `BTCUSDT / 55 / 1 trade / 5 loss`
- `.local_secrets/live_canary.env` matches the approval
- permission probe is `V2_LIVE_CANARY_PERMISSION_PROBE_READY` and fresh
- BTCUSDT is tradable in the probe
- BTCUSDT min notional is `50.0`, and approved max notional `55.0` satisfies it
- private signed-post bypass remediation Codex review exists and is PASS
- dry-run approval-binding remediation Codex review exists and is PASS
- current one-order status is blocked before live execution
- current candidate symbol is `BTCUSDT`
- current candidate notional is `55.0`
- max daily live trades is `1`
- max daily loss is `5.0`
- runtime live gate request is scoped to `live_canary_operator_approved`
- runtime live symbols request is scoped to `["BTCUSDT"]`

Current safety state remains:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `real_order_attempted=false`
- `real_order_submitted=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`

## Service And Repeatability

Codex found no recurring live service or timer capable of repeated order submission. The only live-canary systemd unit currently enabled is the dry-run service/timer; no one-order or recurring live execution unit is enabled.

The one-order code has preflight checks for kill switch, daily trade cap, daily loss cap, symbol whitelist, notional cap, and auto-relock status fields. Those checks are useful, but they do not override the prerequisite Codex marker binding failure above.

## Endpoint And Safety Scans

Codex verified during review:

- no `/fapi/v1/order` call occurred
- no `/fapi/v1/order/test` call occurred
- no real exchange network call occurred
- no leverage endpoint is reachable in the reviewed execution adapter
- no margin endpoint is reachable in the reviewed execution adapter
- no cancel/modify endpoint is reachable in the reviewed execution adapter
- Redis evidence is limited to `v2:live_canary:*`
- live-canary ledger scan found zero real-order attempts and zero submitted real orders
- raw credential scan found zero hits outside `.local_secrets`
- no old Redis write path was found
- no legacy shutdown approval was found
- no checkpoint compatibility or policy architecture parity claim was found

## Validation

- Focused live-canary tests: `123 passed`.
- `py_compile`: PASS.
- Live-canary validation sweep: PASS, `22` files scanned.
- JSON validation: PASS.
- Redis write boundary check: PASS.
- Raw credential scan: PASS.
- Old Redis write scan: PASS.
- Exchange mutation scan: PASS.
- Marker-binding proof: FAIL BLOCKER.

## Required Remediation

Patch `v2/backend/app/cli/v2_live_canary_one_order_enablement.py` so the one-order preflight reads the actual prerequisite Codex review markers:

- `claude_worklog/final_readiness/v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/codex_review/CODEX_GO_NO_GO.md`
- expected content: `V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_CODEX_PASS`
- `claude_worklog/final_readiness/v2_live_canary_dry_run_approval_binding_remediation/latest/codex_review/CODEX_GO_NO_GO.md`
- expected content: `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_CODEX_PASS`

Add regression tests proving one-order preflight blocks when only implementation `READY` files exist and no prerequisite `CODEX_PASS` review files exist.

Then rerun this Codex review. Do not create a one-order PASS marker until the marker binding is fixed and re-reviewed.

## Final Decision

`V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_FAIL`
