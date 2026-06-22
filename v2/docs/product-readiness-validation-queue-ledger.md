# Product Readiness Validation Queue Ledger

Generated: 2026-06-14

Purpose: human-readable mirror of every `pending_validation_queue` command in `docs/product-readiness-status.json`. This file does not run validation and does not mark any route, phase, launch gate, admin security gate, `/trade`, `/market/:symbol`, paper/read-only release, or real live trading state complete.

Validation was not run after the latest guard/doc changes; conservative statuses remain authoritative.

Pending evidence key: `readiness_validation_queue_ledger_drift_guard_after_latest_changes`.

## Pending validation queue mirror

| Pending validation command | Status |
|---|---|
| `python scripts/check_product_readiness_status.py` | `PENDING` |
| `python scripts/check_readiness_docs_consistency.py` | `PENDING` |
| `python scripts/check_product_readiness_schema_requirements.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/integration/api/test_auth_rbac_and_status.py backend/tests/integration/api/v2/test_market_contract_routes.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_alembic_auth_migration_approval_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/api/test_readonly_market_stream_parser.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_derivatives_realtime_source_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_stream_alerting_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_alert_delivery_audit_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_https_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_durable_credential_vault_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_auth_session_hardening_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_trader_account_scope_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_trader_repository_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_check_readiness_docs_consistency.py` | `PENDING` |
| `npm run typecheck` | `PENDING` |
| `npm run build` | `PENDING` |
| `npm run lint --if-present` | `PENDING` |
| `npx playwright test tests/e2e/trade_terminal_redesign.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/market_detail_redesign.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/api_v2_contract_states.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/trader_nav_cleanliness.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/public_status_redesign.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/pro_chart_realtime_contract.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium` | `PENDING` |
| `npx playwright test tests/e2e/symbols_route_readonly_contract.spec.ts --project=chromium` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_phase13_visual_review_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_current_validation_evidence_smoke.py` | `PENDING` |
| `npx playwright test --project=chromium` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_durable_paper_audit_policy_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_paper_action_validation_smoke.py` | `PENDING` |
| `../.venv/bin/python -m pytest backend/tests/unit/services/website/test_website_contracts.py` | `PENDING` |

## Status rule

All rows must remain mirrored from `docs/product-readiness-status.json`. A queued command remains pending until it is explicitly run and its result is recorded as current evidence.
