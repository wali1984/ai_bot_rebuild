# Codex Review: V2 Website Data Alignment Route Coverage and Bridge Label Remediation

GO/NO-GO: `V2_WEBSITE_DATA_ALIGNMENT_CONTROL_PLANE_CODEX_FAIL`

This review covers the route-coverage and bridge-label remediation packet. It
does not approve live trading, canary, legacy shutdown, Redis trim, direct
website controls, or exchange mutation.

## Blocking Finding

1. **The remediation artifacts are correct, but the current website
   alignment/control-plane artifacts still expose stale data.**

   The remediation sidecar packet has the expected 44-route inventory and
   corrected bridge labels. However, the primary website alignment payloads
   under `v2_website_data_alignment_and_control_plane/latest` still report the
   old 22-entry inventory, and `redis_bridge_contracts.json` still labels
   `signals:trading` and `price:*` as `V2_NATIVE_PUBLIC_PAYLOAD`.

   Current primary payload evidence:

   ```text
   v2_website_data_alignment_and_control_plane/latest/website_data_inventory.json
   page_count=22
   unique_routes=21
   label_counts={PLACEHOLDER_NOT_READY=1, V2_BRIDGE_FROM_LEGACY_REDIS=2, V2_NATIVE_PUBLIC_PAYLOAD=19}

   v2_website_data_alignment_and_control_plane/latest/redis_bridge_contracts.json
   legacy_key=signals:trading label=V2_NATIVE_PUBLIC_PAYLOAD
   legacy_key=price:* label=V2_NATIVE_PUBLIC_PAYLOAD
   ```

   Report center now includes the website alignment lane, but it points at the
   primary stale payload:

   ```text
   report_id=v2_website_data_alignment_and_control_plane
   public_payload_path=/v2_website_data_alignment_and_control_plane/latest/operator_dashboard_payload.json
   go_no_go=V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY
   stale=true
   ```

   This means the remediation is not yet the current website control-plane
   state exposed by the lane. The review cannot pass while the main artifacts
   still contain the exact stale conditions from the prior Codex failure.

## Verified Remediation Work

- The remediation sidecar inventory covers all 44 registered frontend routes:

  ```text
  registered_route_count=44
  documented_page_count=44
  unknown_route_count=0
  label_counts={PLACEHOLDER_NOT_READY=2, V2_BRIDGE_FROM_LEGACY_REDIS=4, V2_NATIVE_PUBLIC_PAYLOAD=38}
  ```

- The remediation sidecar corrected bridge contracts relabel:

  ```text
  prediction:* -> V2_BRIDGE_FROM_LEGACY_REDIS
  coinank:* -> V2_BRIDGE_FROM_LEGACY_REDIS
  signals:trading -> V2_BRIDGE_FROM_LEGACY_REDIS
  price:* -> V2_BRIDGE_FROM_LEGACY_REDIS
  v2:orchestrator:decisions -> V2_NATIVE_PUBLIC_PAYLOAD
  v2:market:prices:{symbol} -> V2_NATIVE_PUBLIC_PAYLOAD
  ```

- Report-center registry includes both
  `v2_website_data_alignment_and_control_plane` and
  `v2_full_paper_only_startup_manifest_runtime`.
- Frontend source scan found no direct Redis client/import/direct connection
  pattern.
- Deployed dashboard verification was attempted and independently corroborated
  read-only:

  ```text
  https://dashboard.wajidali.us/ 200 text/html; charset=utf-8 537
  https://dashboard.wajidali.us/landing 200 text/html; charset=utf-8 537
  https://dashboard.wajidali.us/markets 200 text/html; charset=utf-8 537
  https://dashboard.wajidali.us/admin/mission-control 200 text/html; charset=utf-8 537
  https://dashboard.wajidali.us/admin/report-center 200 text/html; charset=utf-8 537
  ```

## Safety Scan

Scoped scans across website alignment services, CLIs, worklog artifacts, and
public mirrors found:

```text
old_redis_write_path=0
raw_secret_hits=0
direct_frontend_redis_client=0
```

Exchange/live/shutdown token hits were disabled future-control identifiers and
safety text; no executable exchange mutation path was found in the reviewed
website alignment scope.

Current safety state:

```text
live_gate=blocked_human_only
live_symbols=[]
approves_live=false
approves_canary=false
approves_legacy_shutdown=false
approves_redis_trim=false
```

## Verification

```text
python -m py_compile \
  v2/backend/app/services/website_alignment/website_data_alignment.py \
  v2/backend/app/services/website_alignment/route_coverage_and_bridge_label_remediation.py \
  v2/backend/app/services/report_center/report_registry.py
```

Result: pass.

```text
PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_website_data_alignment_route_coverage_and_bridge_label_remediation.py \
  v2/backend/tests/integration/cli/test_v2_website_data_alignment_and_control_plane.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Result: included in combined run, passing.

Combined focused run:

```text
42 passed in 4.33s
```

The tests validate the sidecar remediation packet, but they do not require the
primary website alignment artifacts and report-center lane payload to consume
the remediated inventory/contracts.

## Required Remediation Before Pass

1. Update/regenerate the primary
   `v2_website_data_alignment_and_control_plane/latest` worklog and public
   artifacts so they contain the 44-route inventory and corrected bridge
   contracts, or point the report-center lane at a payload that contains those
   remediated fields.
2. Ensure `operator_dashboard_payload.json` for the website alignment lane
   surfaces route count 44 and corrected bridge-label status.
3. Add a regression test that fails when the primary website alignment
   artifacts still contain the stale 22-page inventory or label
   `signals:trading` / `price:*` as V2-native.
4. Re-run the report center indexer and verify the lane is non-stale and
   exposes the remediated state.

## Safety Scoreboard

- did_not_modify_legacy = true
- did_not_stop_v2_runtime = true
- did_not_write_old_redis = true
- did_not_call_exchange_mutation = true
- did_not_enable_live = true
- did_not_create_approvals = true
- live_gate = blocked_human_only
- live_symbols = []
- approves_live = false
- approves_canary = false
- approves_legacy_shutdown = false
- approves_redis_trim = false
