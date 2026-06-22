# Codex Review: V2 Full Paper-Only Startup Manifest Runtime

GO/NO-GO: `V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_RUNTIME_CODEX_PASS`

This re-review covers the paper-only startup manifest runtime after role
coverage remediation. It does not approve edge, canary, live trading, legacy
shutdown, Redis trim, symbol adoption, daemon installation, or raw legacy script
execution.

## Fix Applied During Review

- Corrected `build_refreshed_v2_paper_startup_manifest_status()` so the primary
  startup runtime payload represents the canonical 38-role legacy manifest
  exactly once instead of merging the previous V2-only role list with canonical
  rows and reporting 58 roles.
- Tightened the remediation regression test so the primary runtime role count
  must equal the canonical manifest role count.
- Regenerated the startup role-coverage remediation packet, refreshed the
  primary startup runtime worklog/public payloads, and re-indexed report center.

## Verified

- Canonical legacy manifest count is represented:
  `canonical_manifest_role_count=38`, `role_count=38`,
  `missing_role_count=0`.
- Previously missing roles are present, including `vpn_monitor`,
  `system_telegram_monitor`, memory monitors,
  `ingest_live_coinank_global_aggregator`, `ingest_liquidation_bridge`,
  `ingest_liquidation_levels_engine`, `ingest_live_coinapi_v1`,
  `process_listing_and_resource_report`, and
  `telegram_completion_notification`.
- Every role uses one valid classification:
  `V2_SERVICE_ACTIVE`, `V2_SERVICE_STARTABLE`, `V2_BRIDGE_READ_ONLY`,
  `V2_PLACEHOLDER_BLOCKED`, `OPERATOR_DECISION_REQUIRED`, or
  `NOT_REQUIRED_FOR_PAPER_SHADOW`.
- Bridge-only roles remain bridge-labelled, not V2-native:
  `ingest_live_coinank`, `ingest_live_coinank_global_aggregator`, and
  `rl_hybrid_trainer` are `V2_BRIDGE_READ_ONLY`.
- Raw legacy scripts are not run as V2-native, no live trader/order adapter is
  started, and the API key audit exposes names/status only with no value fields.
- Dynamic 25-symbol coverage remains visible: universe size 25, current active
  symbols BTCUSDT/ETHUSDT/SOLUSDT only.
- Report center exposes `v2_full_paper_only_startup_manifest_runtime` as fresh
  and points to `/v2_full_paper_only_startup_manifest_runtime/latest/operator_dashboard_payload.json`.

## Safety

- `live_gate=blocked_human_only`
- `live_symbols=[]`
- `approves_live=false`
- `approves_canary=false`
- `approves_legacy_shutdown=false`
- `approves_redis_trim=false`
- Scoped scans found no old Redis write path, exchange mutation path, raw
  secret, truthy approval, or non-empty `live_symbols`.

## Verification

```text
python -m py_compile \
  v2/backend/app/services/native_runtime_migration/startup_role_coverage_remediation.py \
  v2/backend/app/cli/v2_full_paper_only_startup_manifest_role_coverage_remediation.py \
  v2/backend/app/services/report_center/report_registry.py \
  v2/backend/app/cli/v2_report_center_indexer.py

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_full_paper_only_startup_manifest_role_coverage_remediation

PYTHONPATH=$PWD .venv/bin/python \
  -m v2.backend.app.cli.v2_report_center_indexer --once --json

PYTHONPATH=$PWD .venv/bin/pytest \
  v2/backend/tests/integration/cli/test_v2_full_paper_only_startup_manifest_role_coverage_remediation.py \
  v2/backend/tests/integration/cli/test_v2_full_paper_only_startup_manifest_runtime.py \
  v2/backend/tests/unit/services/report_center/test_report_center.py -q
```

Focused combined startup/website/report-center run:

```text
56 passed in 5.28s
```

JSON validation passed for startup runtime, role-coverage remediation,
website alignment, and report-center artifacts.
