# NERVYX OpenAPI Compatibility Report

- Generated at: `2026-06-23T19:45:21.028364Z`
- Status: `PARTIAL_SHIMMED_BASE_UNPROVEN`
- Current branch: `codex/pipeline-trust-refresh`
- Current HEAD: `5b0a4997dae6ab50b1f3aba3327ad9959e126247`
- Merge base with `codex/nervyx-one-rebrand`: `680ddfb12d2810d950f7a465a39a4fb8a77ec205`
- Current capture: `PASS` with `114` paths and `118` operations.
- Baseline raw capture: `FAIL`
- Baseline shimmed capture: `PASS` with `65` paths and `65` operations.
- Baseline shims: `app.api.auth_rbac, app.api.v2.alerts_contracts, app.api.v2.hourly_monitor, app.api.v2.live_gate_status, app.api.v2.monitoring_contracts, app.api.v2.status_contracts, app.auth.security, app.auth.users, app.domain.contracts, app.services.credential_status, app.services.live_readiness, app.services.market_stream_alert_history, app.services.market_stream_alert_notifier, app.services.paper_audit_ledger, app.services.paper_trade_management.entry_gate, app.services.pipeline_control.service, app.services.trader_account_repository, app.domain.governance.audit_chain.local_paper_audit_policy_metadata, app.api.v1.chart, app.api.v1.live_gate`

## Diff Summary

- Removed operations from captured baseline: `0`
- Added operations versus captured baseline: `53`
- Removed component schemas: `0`
- Removed component fields: `0`
- Component type changes: `0`
- Operation security changes: `0`
- Static fallback removed route keys: `0`

## Compatibility Verdict

UNPROVEN. The current OpenAPI capture is valid, and the archived merge-base can be captured only after adding temp-directory shims for route modules that the merge-base imports but does not contain. The shimmed comparison is useful diagnostic evidence, but it cannot prove complete endpoint, field, type, or permission compatibility because missing baseline routers had to be replaced with empty APIRouter stubs.


## Artifacts

- `docs/nervyx-openapi-before.json`
- `docs/nervyx-openapi-after.json`
- `artifacts/nervyx-openapi-before-static-routes.json`
- `artifacts/nervyx-openapi-after-static-routes.json`
- `artifacts/nervyx-openapi-compatibility-summary.json`
