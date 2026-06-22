# V2 Live-Canary One-Order Codex Marker Enforcement Remediation

Generated: `2026-05-20T21:36:12Z`

GO/NO-GO: `V2_LIVE_CANARY_ONE_ORDER_CODEX_MARKER_ENFORCEMENT_REMEDIATION_READY`

## Scope

Patch-only remediation of the Codex fail blocker
`PREREQUISITE_CODEX_PASS_MARKERS_NOT_ENFORCED_FOR_ONE_ORDER_PREFLIGHT`
on the V2 live-canary one-order enablement CLI.

This packet:

- does NOT enable live trading
- does NOT place or attempt any exchange order
- does NOT create the one-order Codex PASS marker
- does NOT modify legacy code or runtime
- does NOT change leverage, margin mode, or any exchange setting
- does NOT write to any legacy Redis namespace

`live_gate=blocked_human_only`, `live_symbols=[]`, `live_enabled=false`
remain unchanged.

## Fail Blocker Addressed

From the prior Codex review:

> The one-order CLI labels the private signed-post bypass and dry-run
> approval-binding checks as Codex pass checks, but the code reads the
> implementation `latest/GO_NO_GO.md` files and accepts `*_READY`
> content instead of reading the actual
> `codex_review/CODEX_GO_NO_GO.md` files and requiring `*_CODEX_PASS`.

This packet rebinds both prerequisites to the actual Codex review
files with the exact `*_CODEX_PASS` tokens, and adds defensive
helpers, payload fields, and regression tests so the failure
cannot recur silently.

## Source Patch

File: `v2/backend/app/cli/v2_live_canary_one_order_enablement.py`

Three changes:

1. **Constants rebound.** Both prerequisite marker paths and tokens
   now point at the Codex review files:

   - private signed-post:
     `claude_worklog/final_readiness/v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/codex_review/CODEX_GO_NO_GO.md`
     with required content
     `V2_LIVE_CANARY_EXECUTION_ADAPTER_PRIVATE_SIGNED_POST_BYPASS_REMEDIATION_CODEX_PASS`
   - dry-run approval-binding:
     `claude_worklog/final_readiness/v2_live_canary_dry_run_approval_binding_remediation/latest/codex_review/CODEX_GO_NO_GO.md`
     with required content
     `V2_LIVE_CANARY_DRY_RUN_APPROVAL_BINDING_REMEDIATION_CODEX_PASS`

   The one-order prerequisite path/token was already correct and
   remains:
   `claude_worklog/final_readiness/v2_live_canary_one_order_enablement/latest/codex_review/CODEX_GO_NO_GO.md`
   →
   `V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_PASS`

2. **Exact-match helper added.** `read_exact_codex_pass_marker(path, expected_token)`
   returns `{path, expected, actual, passed}` with `passed=True` only
   when the file's stripped content equals `expected_token` exactly.
   No substring, prefix, or alternate-token acceptance. The prior
   `_check_marker_exact` first-non-empty-line fallback has been
   removed; the legacy alias now delegates to
   `read_exact_codex_pass_marker`.

3. **Audit fields added** to the preflight payload (and therefore to
   the status and dashboard JSON):

   - `implementation_ready_markers_accepted_for_codex_prerequisites`
     (always `false`)
   - per prerequisite (one-order, private signed-post, dry-run binding):
     `prerequisite_*_codex_marker_path`,
     `prerequisite_*_codex_marker_expected`,
     `prerequisite_*_codex_marker_actual`,
     `prerequisite_*_codex_marker_passed`

## Test Patch

File: `v2/backend/tests/integration/cli/test_v2_live_canary_one_order_enablement.py`

Added regression tests that fail under the prior (broken) behavior
and pass under the patched behavior:

- `test_private_signed_post_implementation_ready_marker_does_not_satisfy_codex_prerequisite`
- `test_dry_run_binding_implementation_ready_marker_does_not_satisfy_codex_prerequisite`
- `test_private_signed_post_codex_pass_marker_required_exactly`
- `test_dry_run_binding_codex_pass_marker_required_exactly`
- `test_preflight_blocks_when_prerequisite_files_contain_ready_strings_only`
- `test_preflight_passes_prerequisites_when_exact_codex_pass_files_exist`
- `test_one_order_execution_still_blocks_without_one_order_codex_pass_marker`
- `test_module_default_marker_paths_point_at_codex_review_files`

The last test pins the module-level defaults to the
`codex_review/CODEX_GO_NO_GO.md` paths and the `*_CODEX_PASS` token
strings so a future regression would be caught at collection.

## Source-Level Grep Proof

Searches run against `v2/backend/app/` after the patch:

- `v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/GO_NO_GO.md`: 0 hits
- `v2_live_canary_dry_run_approval_binding_remediation/latest/GO_NO_GO.md`: 0 hits

Active preflight logic now references only the `codex_review/CODEX_GO_NO_GO.md`
files for both prerequisites. The implementation `latest/GO_NO_GO.md`
paths do not appear in any prerequisite check; they exist only in human
report text, never in active preflight logic.

Confirming hits for the new bindings inside the CLI:

```
v2/backend/app/cli/v2_live_canary_one_order_enablement.py:97:    "claude_worklog/final_readiness/v2_live_canary_one_order_enablement/latest/codex_review/CODEX_GO_NO_GO.md"
v2/backend/app/cli/v2_live_canary_one_order_enablement.py:102:   "claude_worklog/final_readiness/v2_live_canary_execution_adapter_private_signed_post_bypass_remediation/latest/codex_review/CODEX_GO_NO_GO.md"
v2/backend/app/cli/v2_live_canary_one_order_enablement.py:109:   "claude_worklog/final_readiness/v2_live_canary_dry_run_approval_binding_remediation/latest/codex_review/CODEX_GO_NO_GO.md"
```

## Validation

| Check                                       | Result |
| ------------------------------------------- | ------ |
| Focused one-order tests                     | PASS (31 tests) |
| Focused live-canary tests (4 modules)       | PASS (131 tests) |
| `py_compile` of patched CLI                 | PASS   |
| JSON validation of refreshed packet files   | PASS   |
| Raw credential scan (no values in payloads) | PASS   |
| Old Redis write scan (`order_intent:`/`order_execution:`/`trader:positions`/`trainer_state:`) | PASS (0 hits in CLI) |
| Exchange mutation scan (`futures_cancel`)   | PASS (0 hits in CLI) |
| Approval drift scan                         | PASS (`.local_secrets/live_canary.env` and operator approval still match `BTCUSDT / 55 / 1 trade / 5 loss`) |

## Refreshed One-Order Preflight Status

The refreshed
`claude_worklog/final_readiness/v2_live_canary_one_order_enablement/latest/one_order_enablement_status.json`
now records, from the patched preflight, both prerequisite probes:

- `prerequisite_private_signed_post_codex_marker_passed = true`
- `prerequisite_dry_run_binding_codex_marker_passed = true`
- `prerequisite_one_order_codex_marker_passed = false`
  (actual token is currently `V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_FAIL`)
- `implementation_ready_markers_accepted_for_codex_prerequisites = false`

The one-order CODEX_PASS marker is still absent, which is correct:
this packet does NOT manufacture that marker. The one-order packet
must be re-reviewed by Codex; only Codex may emit the
`V2_LIVE_CANARY_ONE_ORDER_ENABLEMENT_CODEX_PASS` content.

## Safety Posture

All safety state is unchanged from the prior packet:

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `live_enabled=false`
- `real_order_attempted=false`
- `real_order_submitted=false`
- `places_real_order=false`
- `writes_exchange_orders=false`
- `writes_legacy_redis=false`
- `leverage_changed=false`
- `margin_mode_changed=false`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- `raw_credential_in_payload=NEVER`

## Final Decision

`V2_LIVE_CANARY_ONE_ORDER_CODEX_MARKER_ENFORCEMENT_REMEDIATION_READY`

This remediation is ready for Codex review. Live execution remains
blocked until Codex emits both this packet's PASS marker AND the
one-order PASS marker on a re-reviewed one-order packet.
