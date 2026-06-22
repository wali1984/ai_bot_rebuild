# Codex Review: V2 Website Data Alignment + Control Plane

GO/NO-GO: `V2_WEBSITE_DATA_ALIGNMENT_CONTROL_PLANE_CODEX_PASS`

This re-review covers website data alignment after primary artifact integration
remediation. It does not approve live trading, canary, legacy shutdown, Redis
trim, order controls, adopt controls, or exchange mutation.

## Verified

- Primary website alignment artifacts now use the remediated 44-route
  inventory: `page_count=44`, `registered_route_count=44`,
  `documented_page_count=44`, `unknown_route_count=0`, and 44 unique routes.
- The stale 22-page / 21-route state is gone from the primary payload.
- `signals:trading` is `V2_BRIDGE_FROM_LEGACY_REDIS`, not
  `V2_NATIVE_PUBLIC_PAYLOAD`.
- `price:*` is `V2_BRIDGE_FROM_LEGACY_REDIS`, not
  `V2_NATIVE_PUBLIC_PAYLOAD`.
- V2-native equivalents are represented separately:
  `v2:orchestrator:decisions` and `v2:market:prices:{symbol}` remain
  `V2_NATIVE_PUBLIC_PAYLOAD`.
- Missing/stale data remains visible through explicit
  `PLACEHOLDER_NOT_READY` and bridge labels; bridge data is not relabelled as
  native.
- Frontend source scan found no direct Redis client usage.
- Deployed dashboard verification was attempted and returned HTTP 200 for `/`,
  `/landing`, `/markets`, `/admin/mission-control`, and
  `/admin/report-center`.
- Report center exposes `v2_website_data_alignment_and_control_plane` as fresh
  and points to `/v2_website_data_alignment_and_control_plane/latest/operator_dashboard_payload.json`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Future controls remain disabled; no live/order/shutdown/adopt controls are
  enabled.
- Scoped scans found no raw key material, old Redis write path, exchange
  mutation path, truthy approval, or non-empty `live_symbols`.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/website_alignment/primary_artifact_integration_remediation.py \
  v2/backend/app/cli/v2_website_data_alignment_primary_artifact_integration_remediation.py \
  v2/backend/app/services/report_center/report_registry.py \
  v2/backend/app/cli/v2_report_center_indexer.py

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_website_data_alignment_primary_artifact_integration_remediation.py \
  v2/backend/tests/integration/cli/test_v2_website_data_alignment_and_control_plane.py \
  v2/backend/tests/integration/cli/test_v2_website_data_alignment_route_coverage_and_bridge_label_remediation.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Focused combined startup/website/report-center run:

```text
56 passed in 5.28s
```

JSON validation passed for website alignment, primary integration remediation,
startup runtime, and report-center artifacts.
