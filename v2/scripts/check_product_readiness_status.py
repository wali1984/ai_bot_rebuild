#!/usr/bin/env python3
"""Validate the machine-readable product readiness snapshot.

This guard is intentionally narrow. It prevents accidental promotion of the
current monitored blockers in docs/product-readiness-status.json. It does not
prove launch readiness, route readiness, realtime data readiness, or live
trading readiness.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_LAUNCH_BLOCKED = {
    "full_product_launch",
    "paper_read_only_launch",
    "real_live_trading",
    "production_ready_claim",
}

EXPECTED_GUARDRAILS = {
    "do_not_mark_trade_pass",
    "do_not_mark_market_symbol_pass",
    "do_not_mark_phase13_pass",
    "do_not_mark_phase14_pass_without_current_rerun",
    "do_not_mark_phase15_pass",
    "do_not_mark_paper_launch_pass",
    "do_not_mark_full_product_launch_pass",
    "do_not_mark_admin_security_pass",
    "do_not_mark_any_monitored_route_pass_without_current_evidence",
    "do_not_mark_real_live_trading_pass",
    "treat_prior_pass_evidence_as_historical_after_changes",
}

EXPECTED_PENDING_OR_MISSING_EVIDENCE = {
    'account_scope_partial_match_fail_closed_after_latest_changes': 'PENDING',
    'account_scope_proof_metadata_after_latest_changes': 'PENDING',
    'account_scope_strict_data_match_after_latest_changes': 'PENDING',
    'admin_audit_readiness_status_after_latest_changes': 'PENDING',
    'admin_audit_retention_policy_after_latest_changes': 'PENDING',
    'admin_exchange_account_readonly_normalization_after_latest_changes': 'PENDING',
    'admin_paper_account_preservation_after_latest_changes': 'PENDING',
    'admin_sqlalchemy_audit_store_after_latest_changes': 'PENDING',
    'alembic_auth_migration_approval_smoke_runner_after_latest_changes': 'PENDING',
    'alembic_auth_revocation_admin_audit_migration_approval_after_latest_changes': 'PENDING',
    'alerts_contract_after_latest_changes': 'PENDING',
    'alerts_crud_delivery_audit_repositories': 'MISSING',
    'all_public_trader_account_scope_call_sites_reviewed_after_latest_changes': 'PENDING',
    'auth_admin_activation_audit_after_latest_changes': 'PENDING',
    'auth_admin_step_up_after_latest_changes': 'PENDING',
    'auth_admin_user_mutation_audit_after_latest_changes': 'PENDING',
    'auth_password_change_session_revocation_after_latest_changes': 'PENDING',
    'auth_production_cookie_samesite_fail_closed_after_latest_changes': 'PENDING',
    'auth_production_issuer_audience_fail_closed_after_latest_changes': 'PENDING',
    'auth_production_password_policy_after_latest_changes': 'PENDING',
    'auth_production_revocation_store_fail_closed_after_latest_changes': 'PENDING',
    'auth_production_secret_fail_closed_after_latest_changes': 'PENDING',
    'auth_production_secret_strength_after_latest_changes': 'PENDING',
    'auth_production_session_minutes_fail_closed_after_latest_changes': 'PENDING',
    'auth_refresh_token_rotation_after_latest_changes': 'PENDING',
    'auth_revocation_store_error_fail_closed_after_latest_changes': 'PENDING',
    'auth_secret_rotation_after_latest_changes': 'PENDING',
    'auth_secure_cookie_after_latest_changes': 'PENDING',
    'auth_session_hardening_artifact_metadata_after_latest_changes': 'PENDING',
    'auth_session_hardening_smoke_runner_after_latest_changes': 'PENDING',
    'auth_session_issuer_audience_after_latest_changes': 'PENDING',
    'auth_session_revocation_after_latest_changes': 'PENDING',
    'auth_session_security_status_after_latest_changes': 'PENDING',
    'auth_session_ttl_after_latest_changes': 'PENDING',
    'auth_session_version_invalidation_after_latest_changes': 'PENDING',
    'auth_sqlalchemy_revocation_store_after_latest_changes': 'PENDING',
    'backend_credential_binding_after_latest_changes': 'PENDING',
    'backend_native_public_stream_after_latest_changes': 'PENDING',
    'backend_only_binance_credential_vault': 'PARTIAL',
    'backend_only_credential_status_after_latest_changes': 'PENDING',
    'backend_pytest_after_latest_changes': 'PENDING',
    'broader_trader_account_metric_scope_cleanup_after_latest_changes': 'PENDING',
    'browser_side_native_public_stream_after_latest_changes': 'PENDING',
    'build_after_latest_changes': 'PENDING',
    'credential_permission_probe_artifact_after_latest_changes': 'PENDING',
    'credential_readonly_scope_enforcement_after_latest_changes': 'PENDING',
    'credential_reference_hidden_after_latest_changes': 'PENDING',
    'credential_secret_redaction_smoke_artifact_after_latest_changes': 'PENDING',
    'credential_vault_readiness_status_after_latest_changes': 'PENDING',
    'current_validation_evidence_smoke_runner_after_latest_changes': 'PENDING',
    'dashboard_trader_scoped_account_after_latest_changes': 'PENDING',
    'derivatives_realtime_source_smoke_runner_after_latest_changes': 'PENDING',
    'durable_credential_vault_artifact_metadata_after_latest_changes': 'PENDING',
    'durable_credential_vault_smoke_runner_after_latest_changes': 'PENDING',
    'durable_paper_audit_policy': 'PARTIAL',
    'durable_paper_audit_policy_artifact_after_latest_changes': 'PENDING',
    'durable_paper_audit_policy_smoke_runner_after_latest_changes': 'PENDING',
    'focused_playwright_after_latest_changes': 'PENDING',
    'frontend_credential_status_display_after_latest_changes': 'PENDING',
    'frontend_primary_exchange_account_scope_selection_after_latest_changes': 'PENDING',
    'frontend_realtime_stream_merge_after_latest_changes': 'PENDING',
    'frontend_trader_scoped_paper_account_after_latest_changes': 'PENDING',
    'frontend_typed_activity_row_scope_filter_after_latest_changes': 'PENDING',
    'frontend_typed_portfolio_signal_scope_filter_after_latest_changes': 'PENDING',
    'full_chromium_after_latest_changes': 'PENDING',
    'full_phase13_visual_review': 'MISSING',
    'landing_public_account_metrics_removed_after_latest_changes': 'PENDING',
    'lint_after_latest_changes': 'PENDING',
    'local_paper_audit_chain_verification_after_latest_changes': 'PENDING',
    'local_paper_audit_chain_window_completeness_after_latest_changes': 'PENDING',
    'local_paper_audit_ledger_after_latest_changes': 'PENDING',
    'local_paper_fill_writer_after_latest_changes': 'PENDING',
    'market_derivatives_contract_after_latest_changes': 'PENDING',
    'market_stream_alert_active_only_delivery_after_latest_changes': 'PENDING',
    'market_stream_alert_history_after_latest_changes': 'PENDING',
    'market_stream_alert_webhook_notifier_after_latest_changes': 'PENDING',
    'market_stream_status_alert_after_latest_changes': 'PENDING',
    'market_stream_telemetry_after_latest_changes': 'PENDING',
    'market_stream_telemetry_persistence_after_latest_changes': 'PENDING',
    'paper_audit_retention_policy_after_latest_changes': 'PENDING',
    'paper_execution_policy_status_after_latest_changes': 'PENDING',
    'paper_order_audit_events_after_latest_changes': 'PENDING',
    'paper_order_repository_submit_cancel_after_latest_changes': 'PENDING',
    'paper_trading_trader_scoped_account_after_latest_changes': 'PENDING',
    'phase13_visual_review_smoke_runner_after_latest_changes': 'PENDING',
    'phase_blocker_map_repository_credential_boundary_after_latest_changes': 'PENDING',
    'positions_trader_scoped_account_after_latest_changes': 'PENDING',
    'prochart_backend_snapshot_live_candle_filter_after_latest_changes': 'PENDING',
    'prochart_derivative_overlay_null_clear_after_latest_changes': 'PENDING',
    'prochart_overlay_timestamp_normalization_after_latest_changes': 'PENDING',
    'prochart_realtime_contract_spec_after_latest_changes': 'PENDING',
    'prochart_realtime_merge_after_latest_changes': 'PENDING',
    'prochart_stream_symbol_timeframe_filter_after_latest_changes': 'PENDING',
    'prochart_timestamp_normalization_after_latest_changes': 'PENDING',
    'prochart_typed_candle_envelope_filter_after_latest_changes': 'PENDING',
    'production_alert_delivery_audit_artifact_metadata_after_latest_changes': 'PENDING',
    'production_alert_delivery_audit_smoke_runner_after_latest_changes': 'PENDING',
    'production_https_smoke': 'MISSING',
    'production_https_smoke_artifact_metadata_after_latest_changes': 'PENDING',
    'production_https_smoke_runner_after_latest_changes': 'PENDING',
    'production_paper_action_validation_artifact_metadata_after_latest_changes': 'PENDING',
    'production_paper_action_validation_smoke_runner_after_latest_changes': 'PENDING',
    'production_paper_actions_fail_closed_after_latest_changes': 'PENDING',
    'production_paper_fill_writer_artifact_metadata_after_latest_changes': 'PENDING',
    'production_paper_submit_cancel_validation': 'MISSING',
    'production_stream_alerting_artifact_after_latest_changes': 'PENDING',
    'production_stream_alerting_smoke_runner_after_latest_changes': 'PENDING',
    'production_stream_validation_alerting': 'PARTIAL',
    'production_stream_validation_artifact_metadata_after_latest_changes': 'PENDING',
    'production_trader_repositories_and_writers': 'MISSING',
    'production_trader_repository_smoke_artifact_metadata_after_latest_changes': 'PENDING',
    'production_trader_repository_smoke_runner_after_latest_changes': 'PENDING',
    'public_status_market_stream_alert_after_latest_changes': 'PENDING',
    'public_status_market_stream_health_after_latest_changes': 'PENDING',
    'public_trader_source_copy_cleanup_after_latest_changes': 'PENDING',
    'markets_symbols_readonly_contract_after_latest_changes': 'PENDING',
    'readiness_blocker_closure_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_blocker_owner_label_guard_after_latest_changes': 'PENDING',
    'readiness_change_control_status_lock_guard_after_latest_changes': 'PENDING',
    'readiness_completion_checklist_phase_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_completion_checklist_validation_queue_drift_guard_after_latest_changes': 'PENDING',
    'readiness_current_blocker_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_current_blockers_exact_key_guard_after_latest_changes': 'PENDING',
    'readiness_current_status_index_exact_guard_coverage_after_latest_changes': 'PENDING',
    'readiness_docs_acceptance_matrix_route_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_consistency_guard_after_latest_changes': 'PENDING',
    'readiness_docs_current_blocker_key_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_exchange_scope_phrase_guard_after_latest_changes': 'PENDING',
    'readiness_docs_guard_account_scope_prochart_phrases_after_latest_changes': 'PENDING',
    'readiness_docs_guard_repository_credential_phrases_after_latest_changes': 'PENDING',
    'readiness_docs_launch_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_phase_blocker_current_key_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_phase_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_route_table_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_source_of_truth_drift_guard_after_latest_changes': 'PENDING',
    'readiness_docs_to_check_source_of_truth_coupling_after_latest_changes': 'PENDING',
    'readiness_docs_validation_queue_drift_guard_after_latest_changes': 'PENDING',
    'readiness_evidence_exact_key_guard_after_latest_changes': 'PENDING',
    'readiness_evidence_status_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_guardrail_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_history_event_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_history_event_monitor_log_drift_guard_after_latest_changes': 'PENDING',
    'readiness_history_evidence_key_snapshot_guard_after_latest_changes': 'PENDING',
    'readiness_history_supersession_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_launch_phase_guardrail_exact_key_guard_after_latest_changes': 'PENDING',
    'readiness_launch_readiness_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_monitor_route_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_pending_evidence_ledger_after_latest_changes': 'PENDING',
    'readiness_pending_evidence_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_pending_evidence_validation_coverage_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_phase_launch_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_phase_progress_status_drift_guard_after_latest_changes': 'PENDING',
    'readiness_route_blocker_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_route_blockers_exact_key_guard_after_latest_changes': 'PENDING',
    'readiness_route_blockers_global_blocker_coupling_after_latest_changes': 'PENDING',
    'readiness_route_closure_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_route_status_exact_key_guard_after_latest_changes': 'PENDING',
    'readiness_route_status_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_runbook_exact_guard_coverage_after_latest_changes': 'PENDING',
    'readiness_schema_guard_evidence_keys_aligned_after_latest_changes': 'PENDING',
    'readiness_source_artifact_existence_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_source_of_truth_artifact_existence_guard_after_latest_changes': 'PENDING',
    'readiness_source_of_truth_core_artifacts_after_latest_changes': 'PENDING',
    'readiness_source_of_truth_docs_guard_checked_artifacts_after_latest_changes': 'PENDING',
    'readiness_source_of_truth_exact_key_guard_after_latest_changes': 'PENDING',
    'readiness_source_of_truth_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_status_snapshot_manifest_ledger_drift_guard_after_latest_changes': 'PENDING',
    'readiness_validation_queue_exact_command_guard_after_latest_changes': 'PENDING',
    'readiness_validation_queue_ledger_drift_guard_after_latest_changes': 'PENDING',
    'real_live_trading_approval': 'MISSING',
    'repository_row_level_scope_filtering_after_latest_changes': 'PENDING',
    'screenshot_overflow_after_latest_changes': 'PENDING',
    'secret_redaction_smoke_runner_after_latest_changes': 'PENDING',
    'signed_read_validation_artifact_after_latest_changes': 'PENDING',
    'sqlalchemy_alert_repository_after_latest_changes': 'PENDING',
    'sqlalchemy_trader_account_repository_after_latest_changes': 'PENDING',
    'status_schema_blocker_requirements_after_latest_changes': 'PENDING',
    'status_schema_evidence_queue_requirements_after_latest_changes': 'PENDING',
    'status_schema_launch_phase_guardrail_requirements_after_latest_changes': 'PENDING',
    'status_schema_source_of_truth_requirements_after_latest_changes': 'PENDING',
    'symbol_data_legacy_terminal_fallback_removed_after_latest_changes': 'PENDING',
    'trade_open_order_explicit_local_repository_guard_after_latest_changes': 'PENDING',
    'trade_open_order_paper_fill_ui_after_latest_changes': 'PENDING',
    'trade_typed_activity_tabs_after_latest_changes': 'PENDING',
    'trader_account_binding_copy_after_latest_changes': 'PENDING',
    'trader_account_repository_strict_matching_after_latest_changes': 'PENDING',
    'trader_account_repository_unique_paper_scope_after_latest_changes': 'PENDING',
    'trader_account_scope_smoke_artifact_after_latest_changes': 'PENDING',
    'trader_account_scope_smoke_runner_after_latest_changes': 'PENDING',
    'trader_exchange_account_scope_normalization_after_latest_changes': 'PENDING',
    'trader_repository_readiness_status_after_latest_changes': 'PENDING',
    'trader_scoped_signed_readonly_account_after_latest_changes': 'PENDING',
    'trader_user_scope_enforcement_after_latest_changes': 'PENDING',
    'typecheck_after_latest_changes': 'PENDING',
}

EXPECTED_CURRENT_BLOCKERS = {
    'alembic_auth_revocation_admin_audit_migration_approval_missing',
    'alert_crud_delivery_audit_repositories_missing',
    'backend_only_binance_credential_vault_missing',
    'current_validation_rerun_pending',
    'derivatives_realtime_sources_missing',
    'durable_paper_audit_policy_missing',
    'full_phase13_visual_review_missing',
    'production_auth_session_hardening_missing',
    'production_https_smoke_missing',
    'production_paper_fill_writer_missing',
    'production_paper_submit_cancel_validation_missing',
    'production_stream_validation_alerting_missing',
    'production_trader_account_repositories_and_writers_missing',
}

EXPECTED_ROUTE_BLOCKERS = {
    "/": {
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "/login": {
        "production_auth_session_hardening_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "/account-settings": {
        "production_auth_session_hardening_missing",
        "production_trader_account_repositories_and_writers_missing",
        "backend_only_binance_credential_vault_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "/status": {
        "production_stream_validation_alerting_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "/dashboard": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/markets": {
        "production_stream_validation_alerting_missing",
        "derivatives_realtime_sources_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/markets/symbols": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/trade": {
        "production_stream_validation_alerting_missing",
        "production_trader_account_repositories_and_writers_missing",
        "backend_only_binance_credential_vault_missing",
        "production_paper_submit_cancel_validation_missing",
        "durable_paper_audit_policy_missing",
        "current_validation_rerun_pending",
    },
    "/trade/paper": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/market/:symbol": {
        "production_stream_validation_alerting_missing",
        "derivatives_realtime_sources_missing",
        "current_validation_rerun_pending",
    },
    "/chart/:symbol": {
        "production_https_smoke_missing",
        "production_stream_validation_alerting_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/derivatives": {
        "production_stream_validation_alerting_missing",
        "derivatives_realtime_sources_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/signals": {
        "production_stream_validation_alerting_missing",
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/ai-predictions": {
        "production_stream_validation_alerting_missing",
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/ai-predictions/model-state": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/alerts": {
        "alert_crud_delivery_audit_repositories_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/backtests": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/backtests/replay": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/research": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/research/technical-analysis": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/portfolio": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/portfolio/executions": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "/portfolio/history": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
}

ADMIN_ROUTE_BLOCKERS = {
    "production_auth_session_hardening_missing",
    "alembic_auth_revocation_admin_audit_migration_approval_missing",
    "full_phase13_visual_review_missing",
    "production_https_smoke_missing",
    "current_validation_rerun_pending",
}

for _admin_route in (
    "/admin",
    "/admin/system",
    "/admin/ingestors",
    "/admin/trainer",
    "/admin/orchestrator",
    "/admin/risk",
    "/admin/traders",
    "/admin/execution",
    "/admin/exchanges",
    "/admin/config",
    "/admin/readiness",
    "/admin/users",
    "/admin/logs",
    "/admin/reports",
    "/system/*",
    "/admin/audit",
    "/admin/evidence",
    "/admin/scripts",
    "/admin/build-validation",
    "/admin/coverage",
    "/admin/migrations",
    "/admin/codex",
    "/admin/ai-tools",
):
    EXPECTED_ROUTE_BLOCKERS[_admin_route] = ADMIN_ROUTE_BLOCKERS

EXPECTED_QUEUE_COMMANDS = {
    '../.venv/bin/python -m pytest backend/tests/integration/api/test_auth_rbac_and_status.py backend/tests/integration/api/v2/test_market_contract_routes.py',
    '../.venv/bin/python -m pytest backend/tests/unit/api/test_readonly_market_stream_parser.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_alembic_auth_migration_approval_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_auth_session_hardening_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_current_validation_evidence_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_derivatives_realtime_source_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_durable_credential_vault_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_durable_paper_audit_policy_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_phase13_visual_review_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/services/website/test_website_contracts.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_alert_delivery_audit_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_https_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_paper_action_validation_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_stream_alerting_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_production_trader_repository_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_run_trader_account_scope_smoke.py',
    '../.venv/bin/python -m pytest backend/tests/unit/scripts/test_check_readiness_docs_consistency.py',
    'npm run build',
    'npm run lint --if-present',
    'npm run typecheck',
    'npx playwright test --project=chromium',
    'npx playwright test tests/e2e/api_v2_contract_states.spec.ts --project=chromium',
    'npx playwright test tests/e2e/market_detail_redesign.spec.ts --project=chromium',
    'npx playwright test tests/e2e/pro_chart_realtime_contract.spec.ts --project=chromium',
    'npx playwright test tests/e2e/redesign_screenshot_overflow.spec.ts --project=chromium',
    'npx playwright test tests/e2e/symbols_route_readonly_contract.spec.ts --project=chromium',
    'npx playwright test tests/e2e/trade_terminal_redesign.spec.ts --project=chromium',
    'npx playwright test tests/e2e/trader_nav_cleanliness.spec.ts --project=chromium',
    'python scripts/check_product_readiness_schema_requirements.py',
    'python scripts/check_product_readiness_status.py',
    'python scripts/check_readiness_docs_consistency.py',
}

EXPECTED_SOURCE_OF_TRUTH = {
    "docs_index": "docs/product-readiness-docs-index.md",
    "current_status": "docs/product-readiness-current-status.md",
    "completion_checklist": "docs/product-readiness-completion-checklist.md",
    "readiness_monitor": "docs/product-readiness-monitor.md",
    "monitor_log": "docs/product-readiness-monitor-log.md",
    "phase_blocker_map": "docs/product-readiness-phase-blocker-map.md",
    "blocker_owner_map": "docs/product-readiness-blocker-owner-map.md",
    "blocker_closure_ledger": "docs/product-readiness-blocker-closure-ledger.md",
    "change_control": "docs/product-readiness-change-control.md",
    "monitor_runbook": "docs/product-readiness-monitor-runbook.md",
    "phase_progress": "docs/frontend-redesign-phase-progress.md",
    "master_todo": "docs/frontend-redesign-master-todo.md",
    "acceptance_matrix": "docs/redesign-acceptance-matrix.md",
    "launch_readiness": "docs/launch-readiness.md",
    "api_gap_register": "docs/api-gap-register.md",
    "auth_rbac_audit": "docs/auth-rbac-audit.md",
    "data_source_inventory": "docs/data-source-inventory.md",
    "visible_string_ledger": "docs/visible-string-ledger.md",
    "trade_redesign_audit": "docs/trade-redesign-audit.md",
    "phase_13a_visual_review": "docs/phase-13a-visual-review.md",
    "ui_defect_log_after": "docs/ui-defect-log-after.md",
    "current_blocker_ledger": "docs/product-readiness-current-blocker-ledger.md",
    "validation_queue_ledger": "docs/product-readiness-validation-queue-ledger.md",
    "source_artifact_existence_ledger": "docs/product-readiness-source-artifact-existence-ledger.md",
    "source_of_truth_ledger": "docs/product-readiness-source-of-truth-ledger.md",
    "status_schema": "docs/product-readiness-status.schema.json",
    "status_snapshot": "docs/product-readiness-status.json",
    "status_snapshot_manifest_ledger": "docs/product-readiness-status-snapshot-manifest-ledger.md",
    "status_history": "docs/product-readiness-status-history.jsonl",
    "history_event_ledger": "docs/product-readiness-history-event-ledger.md",
    "evidence_status_ledger": "docs/product-readiness-evidence-status-ledger.md",
    "pending_evidence_ledger": "docs/product-readiness-pending-evidence-ledger.md",
    "pending_evidence_validation_coverage_ledger": "docs/product-readiness-pending-evidence-validation-coverage-ledger.md",
    "guardrail_ledger": "docs/product-readiness-guardrail-ledger.md",
    "route_status_ledger": "docs/product-readiness-route-status-ledger.md",
    "route_closure_ledger": "docs/product-readiness-route-closure-ledger.md",
    "route_blocker_ledger": "docs/product-readiness-route-blocker-ledger.md",
    "phase_launch_ledger": "docs/product-readiness-phase-launch-ledger.md",
    "status_guard": "scripts/check_product_readiness_status.py",
    "docs_status_guard": "scripts/check_readiness_docs_consistency.py",
    "schema_requirements_guard": "scripts/check_product_readiness_schema_requirements.py",
}


def _load_status(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"readiness status file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"readiness status file is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("readiness status root must be a JSON object")
    return payload


def _expect(errors: list[str], condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def validate(payload: dict[str, Any], repo_root: Path) -> list[str]:
    errors: list[str] = []

    source_of_truth = payload.get("source_of_truth")
    _expect(errors, isinstance(source_of_truth, dict), "source_of_truth must be an object")
    if isinstance(source_of_truth, dict):
        unexpected_source_keys = set(map(str, source_of_truth)).difference(EXPECTED_SOURCE_OF_TRUTH)
        missing_source_keys = set(EXPECTED_SOURCE_OF_TRUTH).difference(map(str, source_of_truth))
        _expect(errors, not unexpected_source_keys, f"source_of_truth has unexpected keys: {sorted(unexpected_source_keys)}")
        _expect(errors, not missing_source_keys, f"source_of_truth missing keys: {sorted(missing_source_keys)}")
        for key, expected in EXPECTED_SOURCE_OF_TRUTH.items():
            _expect(
                errors,
                source_of_truth.get(key) == expected,
                f"source_of_truth.{key} must be {expected}",
            )
        for key, artifact_path in sorted(source_of_truth.items()):
            if isinstance(artifact_path, str):
                _expect(
                    errors,
                    (repo_root / artifact_path).exists(),
                    f"source_of_truth artifact path does not exist for {key}: {artifact_path}",
                )

    launch_status = payload.get("launch_status")
    _expect(errors, isinstance(launch_status, dict), "launch_status must be an object")
    if isinstance(launch_status, dict):
        unexpected_launch_keys = set(map(str, launch_status)).difference(EXPECTED_LAUNCH_BLOCKED)
        missing_launch_keys = EXPECTED_LAUNCH_BLOCKED.difference(map(str, launch_status))
        _expect(errors, not unexpected_launch_keys, f"launch_status has unexpected keys: {sorted(unexpected_launch_keys)}")
        _expect(errors, not missing_launch_keys, f"launch_status missing keys: {sorted(missing_launch_keys)}")
        for key in EXPECTED_LAUNCH_BLOCKED:
            _expect(errors, launch_status.get(key) == "BLOCKED", f"launch_status.{key} must remain BLOCKED")

    route_status = payload.get("route_status")
    _expect(errors, isinstance(route_status, dict), "route_status must be an object")
    if isinstance(route_status, dict):
        unexpected_routes = set(map(str, route_status)).difference(EXPECTED_ROUTE_BLOCKERS)
        missing_routes = set(EXPECTED_ROUTE_BLOCKERS).difference(map(str, route_status))
        _expect(errors, not unexpected_routes, f"route_status has unexpected monitored routes: {sorted(unexpected_routes)}")
        _expect(errors, not missing_routes, f"route_status missing monitored routes: {sorted(missing_routes)}")
        for route, route_payload in sorted(route_status.items()):
            _expect(errors, isinstance(route_payload, dict), f"route_status.{route} must be an object")
            if isinstance(route_payload, dict):
                status = route_payload.get("status")
                _expect(
                    errors,
                    status in {"IN_PROGRESS", "BLOCKED"},
                    f"{route} must remain IN_PROGRESS or BLOCKED unless current evidence closes its blockers",
                )
                blockers = route_payload.get("blockers")
                _expect(
                    errors,
                    isinstance(blockers, list) and len(blockers) > 0,
                    f"{route} must list active blockers while monitored",
                )
        for route in EXPECTED_ROUTE_BLOCKERS:
            route_payload = route_status.get(route)
            _expect(errors, isinstance(route_payload, dict), f"route_status.{route} must be an object")
            if isinstance(route_payload, dict):
                _expect(errors, route_payload.get("status") == "IN_PROGRESS", f"{route} must remain IN_PROGRESS")
                blockers = route_payload.get("blockers")
                _expect(errors, isinstance(blockers, list) and len(blockers) > 0, f"{route} must list active blockers")
                if isinstance(blockers, list):
                    blocker_items = set(map(str, blockers))
                    missing = EXPECTED_ROUTE_BLOCKERS[route].difference(blocker_items)
                    unexpected = blocker_items.difference(EXPECTED_ROUTE_BLOCKERS[route])
                    _expect(errors, not missing, f"{route} missing expected blockers: {', '.join(sorted(missing))}")
                    _expect(errors, not unexpected, f"{route} has unexpected blockers: {', '.join(sorted(unexpected))}")
                    _expect(errors, len(blocker_items) == len(blockers), f"{route} blockers must not contain duplicate keys")

    phase_status = payload.get("phase_status")
    _expect(errors, isinstance(phase_status, dict), "phase_status must be an object")
    if isinstance(phase_status, dict):
        expected_phase_keys = {str(phase) for phase in range(16)}
        unexpected_phase_keys = set(map(str, phase_status)).difference(expected_phase_keys)
        missing_phase_keys = expected_phase_keys.difference(map(str, phase_status))
        _expect(errors, not unexpected_phase_keys, f"phase_status has unexpected keys: {sorted(unexpected_phase_keys)}")
        _expect(errors, not missing_phase_keys, f"phase_status missing keys: {sorted(missing_phase_keys)}")
        for phase in map(str, range(15)):
            _expect(errors, phase_status.get(phase) == "IN_PROGRESS", f"phase {phase} must remain IN_PROGRESS")
        _expect(errors, phase_status.get("15") == "BLOCKED", "phase 15 must remain BLOCKED")

    blockers = payload.get("current_blockers")
    _expect(errors, isinstance(blockers, list) and len(blockers) > 0, "current_blockers must be a non-empty array")
    if isinstance(blockers, list):
        blocker_items = set(map(str, blockers))
        unexpected = blocker_items.difference(EXPECTED_CURRENT_BLOCKERS)
        missing = EXPECTED_CURRENT_BLOCKERS.difference(blocker_items)
        _expect(errors, not unexpected, f"current_blockers has unexpected blockers: {', '.join(sorted(unexpected))}")
        _expect(errors, not missing, f"current_blockers missing expected blockers: {', '.join(sorted(missing))}")
        _expect(errors, len(blocker_items) == len(blockers), "current_blockers must not contain duplicate blocker keys")

        if isinstance(route_status, dict):
            for route, route_payload in sorted(route_status.items()):
                route_blockers = route_payload.get("blockers") if isinstance(route_payload, dict) else None
                if isinstance(route_blockers, list):
                    unrepresented = set(map(str, route_blockers)).difference(blocker_items)
                    _expect(
                        errors,
                        not unrepresented,
                        f"route_status blockers not represented in current_blockers for {route}: {sorted(unrepresented)}",
                    )

    validation_queue = payload.get("pending_validation_queue")
    _expect(
        errors,
        isinstance(validation_queue, list) and len(validation_queue) > 0,
        "pending_validation_queue must be a non-empty array",
    )
    if isinstance(validation_queue, list):
        queue_items = set(map(str, validation_queue))
        unexpected_queue_items = queue_items.difference(EXPECTED_QUEUE_COMMANDS)
        missing_queue_items = EXPECTED_QUEUE_COMMANDS.difference(queue_items)
        _expect(errors, not unexpected_queue_items, f"pending_validation_queue has unexpected commands: {sorted(unexpected_queue_items)}")
        _expect(errors, not missing_queue_items, f"pending_validation_queue missing commands: {sorted(missing_queue_items)}")
        _expect(errors, len(queue_items) == len(validation_queue), "pending_validation_queue must not contain duplicate commands")

    evidence = payload.get("last_current_evidence")
    _expect(errors, isinstance(evidence, dict), "last_current_evidence must be an object")
    if isinstance(evidence, dict):
        unexpected_evidence_keys = set(map(str, evidence)).difference(EXPECTED_PENDING_OR_MISSING_EVIDENCE)
        missing_evidence_keys = set(EXPECTED_PENDING_OR_MISSING_EVIDENCE).difference(map(str, evidence))
        _expect(errors, not unexpected_evidence_keys, f"last_current_evidence has unexpected keys: {sorted(unexpected_evidence_keys)}")
        _expect(errors, not missing_evidence_keys, f"last_current_evidence missing keys: {sorted(missing_evidence_keys)}")
        for key, expected in EXPECTED_PENDING_OR_MISSING_EVIDENCE.items():
            _expect(errors, evidence.get(key) == expected, f"last_current_evidence.{key} must remain {expected}")

        history_path = repo_root / EXPECTED_SOURCE_OF_TRUTH["status_history"]
        try:
            history_lines = history_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            errors.append(f"status history file cannot be read: {history_path}: {exc}")
            history_lines = []
        for line_number, raw_line in enumerate(history_lines, start=1):
            line = raw_line.strip()
            if not line:
                continue
            try:
                history_entry = json.loads(line)
            except json.JSONDecodeError as exc:
                errors.append(f"status history JSON invalid on line {line_number}: {exc}")
                continue
            details = history_entry.get("details") if isinstance(history_entry, dict) else None
            if not isinstance(details, dict):
                continue
            evidence_key = details.get("evidence_key")
            if isinstance(evidence_key, str):
                _expect(
                    errors,
                    evidence_key in evidence,
                    f"status history evidence_key is not tracked in last_current_evidence: {evidence_key}",
                )

    guardrails = payload.get("guardrails")
    _expect(errors, isinstance(guardrails, dict), "guardrails must be an object")
    if isinstance(guardrails, dict):
        unexpected_guardrail_keys = set(map(str, guardrails)).difference(EXPECTED_GUARDRAILS)
        missing_guardrail_keys = EXPECTED_GUARDRAILS.difference(map(str, guardrails))
        _expect(errors, not unexpected_guardrail_keys, f"guardrails has unexpected keys: {sorted(unexpected_guardrail_keys)}")
        _expect(errors, not missing_guardrail_keys, f"guardrails missing keys: {sorted(missing_guardrail_keys)}")
        for key in EXPECTED_GUARDRAILS:
            _expect(errors, guardrails.get(key) is True, f"guardrails.{key} must remain true")

    return errors


def main(argv: list[str]) -> int:
    repo_root = Path(__file__).resolve().parents[1]
    status_path = Path(argv[1]) if len(argv) > 1 else repo_root / "docs" / "product-readiness-status.json"
    payload = _load_status(status_path)
    errors = validate(payload, repo_root)
    if errors:
        print("Product readiness status guard: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Product readiness status guard: PASS")
    print("This confirms only monitored no-PASS guardrails, not product readiness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
