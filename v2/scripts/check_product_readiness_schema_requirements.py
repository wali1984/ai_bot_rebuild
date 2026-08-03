#!/usr/bin/env python3
"""Check readiness status schema no-PASS blocker requirements.

This guard verifies that the JSON schema itself preserves the current monitored
route/global blocker keys. It does not validate runtime behavior, launch
readiness, route readiness, realtime data, or live trading safety.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


EXPECTED_GLOBAL_BLOCKERS = {
    "production_trader_account_repositories_and_writers_missing",
    "backend_only_binance_credential_vault_missing",
    "production_stream_validation_alerting_missing",
    "derivatives_realtime_sources_missing",
    "alert_crud_delivery_audit_repositories_missing",
    "production_paper_fill_writer_missing",
    "production_paper_submit_cancel_validation_missing",
    "durable_paper_audit_policy_missing",
    "production_auth_session_hardening_missing",
    "alembic_auth_revocation_admin_audit_migration_approval_missing",
    "full_phase13_visual_review_missing",
    "production_https_smoke_missing",
    "current_validation_rerun_pending",
}

EXPECTED_ROUTE_BLOCKERS = {
    "landingRoute": {
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "loginRoute": {
        "production_auth_session_hardening_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "accountSettingsRoute": {
        "production_auth_session_hardening_missing",
        "production_trader_account_repositories_and_writers_missing",
        "backend_only_binance_credential_vault_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "statusRoute": {
        "production_stream_validation_alerting_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "dashboardRoute": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "marketsRoute": {
        "production_stream_validation_alerting_missing",
        "derivatives_realtime_sources_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "redirectRoute": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "tradeRoute": {
        "production_stream_validation_alerting_missing",
        "production_trader_account_repositories_and_writers_missing",
        "backend_only_binance_credential_vault_missing",
        "production_paper_submit_cancel_validation_missing",
        "durable_paper_audit_policy_missing",
        "current_validation_rerun_pending",
    },
    "derivativesRoute": {
        "production_stream_validation_alerting_missing",
        "derivatives_realtime_sources_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "signalEvidenceRoute": {
        "production_stream_validation_alerting_missing",
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "traderReadOnlyRoute": {
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "marketSymbolRoute": {
        "production_stream_validation_alerting_missing",
        "derivatives_realtime_sources_missing",
        "current_validation_rerun_pending",
    },
    "proChartRoute": {
        "production_stream_validation_alerting_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "alertsRoute": {
        "alert_crud_delivery_audit_repositories_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "portfolioRoute": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "portfolioExecutionsRoute": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "portfolioHistoryRoute": {
        "production_trader_account_repositories_and_writers_missing",
        "full_phase13_visual_review_missing",
        "current_validation_rerun_pending",
    },
    "adminRoute": {
        "production_auth_session_hardening_missing",
        "alembic_auth_revocation_admin_audit_migration_approval_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
    "superadminRoute": {
        "production_auth_session_hardening_missing",
        "alembic_auth_revocation_admin_audit_migration_approval_missing",
        "full_phase13_visual_review_missing",
        "production_https_smoke_missing",
        "current_validation_rerun_pending",
    },
}

EXPECTED_LAUNCH_STATUS = {
    "full_product_launch": "BLOCKED",
    "paper_read_only_launch": "BLOCKED",
    "real_live_trading": "BLOCKED",
    "production_ready_claim": "BLOCKED",
}

EXPECTED_PHASE_STATUS = {str(phase): "IN_PROGRESS" for phase in range(15)}
EXPECTED_PHASE_STATUS["15"] = "BLOCKED"

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

EXPECTED_EVIDENCE_STATUS = {
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


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"schema file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"schema file is invalid JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("schema root must be a JSON object")
    return payload


def _contains_consts(schema_fragment: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(schema_fragment, dict):
        const = schema_fragment.get("const")
        if isinstance(const, str):
            found.add(const)
        for value in schema_fragment.values():
            found.update(_contains_consts(value))
    elif isinstance(schema_fragment, list):
        for item in schema_fragment:
            found.update(_contains_consts(item))
    return found


def _find_blocker_schemas(schema_fragment: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []
    if isinstance(schema_fragment, dict):
        for key, value in schema_fragment.items():
            if key == "blockers" and isinstance(value, dict):
                found.append(value)
            found.extend(_find_blocker_schemas(value))
    elif isinstance(schema_fragment, list):
        for item in schema_fragment:
            found.extend(_find_blocker_schemas(item))
    return found


def validate(schema: dict[str, Any]) -> list[str]:
    errors: list[str] = []

    source_schema = schema.get("properties", {}).get("source_of_truth", {})
    source_required = set(source_schema.get("required", [])) if isinstance(source_schema, dict) else set()
    source_properties = source_schema.get("properties", {}) if isinstance(source_schema, dict) else {}
    expected_source_keys = set(EXPECTED_SOURCE_OF_TRUTH)
    if isinstance(source_schema, dict) and source_schema.get("additionalProperties") is not False:
        errors.append("source_of_truth schema must reject additionalProperties while source-of-truth artifacts are explicit")
    if not isinstance(source_properties, dict):
        errors.append("source_of_truth schema properties must be an object")
        source_properties = {}
    if set(source_properties) != expected_source_keys:
        errors.append(f"source_of_truth schema properties must exactly match source keys; missing={sorted(expected_source_keys - set(source_properties))} unexpected={sorted(set(source_properties) - expected_source_keys)}")
    if source_required != expected_source_keys:
        errors.append(f"source_of_truth schema required keys must exactly match source keys; missing={sorted(expected_source_keys - source_required)} unexpected={sorted(source_required - expected_source_keys)}")
    for key, expected_path in EXPECTED_SOURCE_OF_TRUTH.items():
        property_schema = source_properties.get(key)
        if not isinstance(property_schema, dict) or property_schema.get("const") != expected_path:
            errors.append(f"source_of_truth.{key} schema must const {expected_path}")

    launch_schema = schema.get("properties", {}).get("launch_status", {})
    launch_properties = launch_schema.get("properties", {}) if isinstance(launch_schema, dict) else {}
    launch_required = set(launch_schema.get("required", [])) if isinstance(launch_schema, dict) else set()
    expected_launch_keys = set(EXPECTED_LAUNCH_STATUS)
    if isinstance(launch_schema, dict) and launch_schema.get("additionalProperties") is not False:
        errors.append("launch_status schema must reject additionalProperties")
    if not isinstance(launch_properties, dict):
        errors.append("launch_status schema properties must be an object")
        launch_properties = {}
    if set(launch_properties) != expected_launch_keys:
        errors.append(f"launch_status schema properties must exactly match launch keys; missing={sorted(expected_launch_keys - set(launch_properties))} unexpected={sorted(set(launch_properties) - expected_launch_keys)}")
    if launch_required != expected_launch_keys:
        errors.append(f"launch_status schema required keys must exactly match launch keys; missing={sorted(expected_launch_keys - launch_required)} unexpected={sorted(launch_required - expected_launch_keys)}")
    for key, expected_status in EXPECTED_LAUNCH_STATUS.items():
        property_schema = launch_properties.get(key)
        if not isinstance(property_schema, dict) or property_schema.get("const") != expected_status:
            errors.append(f"launch_status.{key} schema must const {expected_status}")

    phase_schema = schema.get("properties", {}).get("phase_status", {})
    phase_properties = phase_schema.get("properties", {}) if isinstance(phase_schema, dict) else {}
    phase_required = set(phase_schema.get("required", [])) if isinstance(phase_schema, dict) else set()
    expected_phase_keys = set(EXPECTED_PHASE_STATUS)
    if isinstance(phase_schema, dict) and phase_schema.get("additionalProperties") is not False:
        errors.append("phase_status schema must reject additionalProperties")
    if not isinstance(phase_properties, dict):
        errors.append("phase_status schema properties must be an object")
        phase_properties = {}
    if set(phase_properties) != expected_phase_keys:
        errors.append(f"phase_status schema properties must exactly match phase keys; missing={sorted(expected_phase_keys - set(phase_properties))} unexpected={sorted(set(phase_properties) - expected_phase_keys)}")
    if phase_required != expected_phase_keys:
        errors.append(f"phase_status schema required keys must exactly match phase keys; missing={sorted(expected_phase_keys - phase_required)} unexpected={sorted(phase_required - expected_phase_keys)}")
    for phase, expected_status in EXPECTED_PHASE_STATUS.items():
        property_schema = phase_properties.get(phase)
        if not isinstance(property_schema, dict) or property_schema.get("const") != expected_status:
            errors.append(f"phase_status.{phase} schema must const {expected_status}")

    guardrail_schema = schema.get("properties", {}).get("guardrails", {})
    guardrail_required = set(guardrail_schema.get("required", [])) if isinstance(guardrail_schema, dict) else set()
    guardrail_properties = guardrail_schema.get("properties", {}) if isinstance(guardrail_schema, dict) else {}
    expected_guardrail_keys = set(EXPECTED_GUARDRAILS)
    if isinstance(guardrail_schema, dict) and guardrail_schema.get("additionalProperties") is not False:
        errors.append("guardrails schema must reject additionalProperties")
    if not isinstance(guardrail_properties, dict):
        errors.append("guardrails schema properties must be an object")
        guardrail_properties = {}
    if set(guardrail_properties) != expected_guardrail_keys:
        errors.append(f"guardrails schema properties must exactly match guardrail keys; missing={sorted(expected_guardrail_keys - set(guardrail_properties))} unexpected={sorted(set(guardrail_properties) - expected_guardrail_keys)}")
    if guardrail_required != expected_guardrail_keys:
        errors.append(f"guardrails schema required keys must exactly match guardrail keys; missing={sorted(expected_guardrail_keys - guardrail_required)} unexpected={sorted(guardrail_required - expected_guardrail_keys)}")
    for key in EXPECTED_GUARDRAILS:
        property_schema = guardrail_properties.get(key)
        if not isinstance(property_schema, dict) or property_schema.get("const") is not True:
            errors.append(f"guardrails.{key} schema must const true")

    route_status_schema = schema.get("properties", {}).get("route_status", {})
    route_status = route_status_schema.get("properties", {}) if isinstance(route_status_schema, dict) else {}
    if not isinstance(route_status, dict):
        errors.append("route_status schema properties must be an object")
        route_status = {}
    if isinstance(route_status_schema, dict) and route_status_schema.get("additionalProperties") is not False:
        errors.append("route_status schema must reject additionalProperties while monitored route set is explicit")
    expected_route_keys = {
        "/",
        "/login",
        "/account-settings",
        "/status",
        "/dashboard",
        "/markets",
        "/markets/symbols",
        "/trade",
        "/trade/paper",
        "/market/:symbol",
        "/chart/:symbol",
        "/derivatives",
        "/signals",
        "/ai-predictions",
        "/ai-predictions/model-state",
        "/alerts",
        "/backtests",
        "/backtests/replay",
        "/research",
        "/research/technical-analysis",
        "/portfolio",
        "/portfolio/executions",
        "/portfolio/history",
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
    }
    required_routes = set(route_status_schema.get("required", [])) if isinstance(route_status_schema, dict) else set()
    actual_route_keys = set(route_status)
    if actual_route_keys != expected_route_keys:
        errors.append(f"route_status schema properties must exactly match monitored route set; missing={sorted(expected_route_keys - actual_route_keys)} unexpected={sorted(actual_route_keys - expected_route_keys)}")
    if required_routes != expected_route_keys:
        errors.append(f"route_status schema required routes must exactly match monitored route set; missing={sorted(expected_route_keys - required_routes)} unexpected={sorted(required_routes - expected_route_keys)}")
    route_def = schema.get("$defs", {}).get("route", {})
    route_status_enum = (
        route_def.get("properties", {}).get("status", {}).get("enum", [])
        if isinstance(route_def, dict)
        else []
    )
    if set(route_status_enum) != {"IN_PROGRESS", "BLOCKED"}:
        errors.append("route status enum must be exactly IN_PROGRESS and BLOCKED while no monitored route is complete")
    if route_status.get("/", {}).get("$ref") != "#/$defs/landingRoute":
        errors.append("route_status./ must reference #/$defs/landingRoute")
    if route_status.get("/login", {}).get("$ref") != "#/$defs/loginRoute":
        errors.append("route_status./login must reference #/$defs/loginRoute")
    if route_status.get("/account-settings", {}).get("$ref") != "#/$defs/accountSettingsRoute":
        errors.append("route_status./account-settings must reference #/$defs/accountSettingsRoute")
    if route_status.get("/status", {}).get("$ref") != "#/$defs/statusRoute":
        errors.append("route_status./status must reference #/$defs/statusRoute")
    if route_status.get("/dashboard", {}).get("$ref") != "#/$defs/dashboardRoute":
        errors.append("route_status./dashboard must reference #/$defs/dashboardRoute")
    if route_status.get("/markets", {}).get("$ref") != "#/$defs/marketsRoute":
        errors.append("route_status./markets must reference #/$defs/marketsRoute")
    if route_status.get("/markets/symbols", {}).get("$ref") != "#/$defs/redirectRoute":
        errors.append("route_status./markets/symbols must reference #/$defs/redirectRoute")
    if route_status.get("/trade", {}).get("$ref") != "#/$defs/tradeRoute":
        errors.append("route_status./trade must reference #/$defs/tradeRoute")
    if route_status.get("/trade/paper", {}).get("$ref") != "#/$defs/redirectRoute":
        errors.append("route_status./trade/paper must reference #/$defs/redirectRoute")
    if route_status.get("/market/:symbol", {}).get("$ref") != "#/$defs/marketSymbolRoute":
        errors.append("route_status./market/:symbol must reference #/$defs/marketSymbolRoute")
    if route_status.get("/chart/:symbol", {}).get("$ref") != "#/$defs/proChartRoute":
        errors.append("route_status./chart/:symbol must reference #/$defs/proChartRoute")
    if route_status.get("/derivatives", {}).get("$ref") != "#/$defs/derivativesRoute":
        errors.append("route_status./derivatives must reference #/$defs/derivativesRoute")
    if route_status.get("/signals", {}).get("$ref") != "#/$defs/signalEvidenceRoute":
        errors.append("route_status./signals must reference #/$defs/signalEvidenceRoute")
    if route_status.get("/ai-predictions", {}).get("$ref") != "#/$defs/signalEvidenceRoute":
        errors.append("route_status./ai-predictions must reference #/$defs/signalEvidenceRoute")
    if route_status.get("/ai-predictions/model-state", {}).get("$ref") != "#/$defs/redirectRoute":
        errors.append("route_status./ai-predictions/model-state must reference #/$defs/redirectRoute")
    if route_status.get("/alerts", {}).get("$ref") != "#/$defs/alertsRoute":
        errors.append("route_status./alerts must reference #/$defs/alertsRoute")
    if route_status.get("/backtests", {}).get("$ref") != "#/$defs/traderReadOnlyRoute":
        errors.append("route_status./backtests must reference #/$defs/traderReadOnlyRoute")
    if route_status.get("/backtests/replay", {}).get("$ref") != "#/$defs/redirectRoute":
        errors.append("route_status./backtests/replay must reference #/$defs/redirectRoute")
    if route_status.get("/research", {}).get("$ref") != "#/$defs/traderReadOnlyRoute":
        errors.append("route_status./research must reference #/$defs/traderReadOnlyRoute")
    if route_status.get("/research/technical-analysis", {}).get("$ref") != "#/$defs/redirectRoute":
        errors.append("route_status./research/technical-analysis must reference #/$defs/redirectRoute")
    if route_status.get("/portfolio", {}).get("$ref") != "#/$defs/portfolioRoute":
        errors.append("route_status./portfolio must reference #/$defs/portfolioRoute")
    if route_status.get("/portfolio/executions", {}).get("$ref") != "#/$defs/portfolioExecutionsRoute":
        errors.append("route_status./portfolio/executions must reference #/$defs/portfolioExecutionsRoute")
    if route_status.get("/portfolio/history", {}).get("$ref") != "#/$defs/portfolioHistoryRoute":
        errors.append("route_status./portfolio/history must reference #/$defs/portfolioHistoryRoute")
    for admin_route in (
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
    ):
        if route_status.get(admin_route, {}).get("$ref") != "#/$defs/adminRoute":
            errors.append(f"route_status.{admin_route} must reference #/$defs/adminRoute")
    for superadmin_route in (
        "/admin/audit",
        "/admin/evidence",
        "/admin/scripts",
        "/admin/build-validation",
        "/admin/coverage",
        "/admin/migrations",
        "/admin/codex",
        "/admin/ai-tools",
    ):
        if route_status.get(superadmin_route, {}).get("$ref") != "#/$defs/superadminRoute":
            errors.append(f"route_status.{superadmin_route} must reference #/$defs/superadminRoute")

    current_blocker_schema = schema.get("properties", {}).get("current_blockers", {})
    global_consts = _contains_consts(current_blocker_schema)
    missing_global = EXPECTED_GLOBAL_BLOCKERS.difference(global_consts)
    unexpected_global = global_consts.difference(EXPECTED_GLOBAL_BLOCKERS)
    if missing_global:
        errors.append(f"current_blockers schema missing: {', '.join(sorted(missing_global))}")
    if unexpected_global:
        errors.append(f"current_blockers schema has unexpected blockers: {', '.join(sorted(unexpected_global))}")
    if isinstance(current_blocker_schema, dict):
        expected_count = len(EXPECTED_GLOBAL_BLOCKERS)
        if current_blocker_schema.get("minItems") != expected_count:
            errors.append(f"current_blockers schema minItems must be {expected_count}")
        if current_blocker_schema.get("maxItems") != expected_count:
            errors.append(f"current_blockers schema maxItems must be {expected_count}")
        if current_blocker_schema.get("uniqueItems") is not True:
            errors.append("current_blockers schema must require uniqueItems")
        item_enum = current_blocker_schema.get("items", {}).get("enum") if isinstance(current_blocker_schema.get("items"), dict) else None
        if set(item_enum or []) != EXPECTED_GLOBAL_BLOCKERS:
            errors.append("current_blockers items enum must exactly match expected blockers")

    evidence_schema = schema.get("properties", {}).get("last_current_evidence", {})
    evidence_required = set(evidence_schema.get("required", [])) if isinstance(evidence_schema, dict) else set()
    evidence_properties = evidence_schema.get("properties", {}) if isinstance(evidence_schema, dict) else {}
    expected_evidence_keys = set(EXPECTED_EVIDENCE_STATUS)
    if isinstance(evidence_schema, dict) and evidence_schema.get("additionalProperties") is not False:
        errors.append("last_current_evidence schema must reject additionalProperties while evidence queue is explicit")
    if not isinstance(evidence_properties, dict):
        errors.append("last_current_evidence schema properties must be an object")
        evidence_properties = {}
    if set(evidence_properties) != expected_evidence_keys:
        errors.append(f"last_current_evidence schema properties must exactly match evidence keys; missing={sorted(expected_evidence_keys - set(evidence_properties))} unexpected={sorted(set(evidence_properties) - expected_evidence_keys)}")
    if evidence_required != expected_evidence_keys:
        errors.append(f"last_current_evidence schema required keys must exactly match evidence keys; missing={sorted(expected_evidence_keys - evidence_required)} unexpected={sorted(evidence_required - expected_evidence_keys)}")
    for evidence_key, expected_status in EXPECTED_EVIDENCE_STATUS.items():
        property_schema = evidence_properties.get(evidence_key)
        if not isinstance(property_schema, dict) or property_schema.get("const") != expected_status:
            errors.append(f"last_current_evidence.{evidence_key} schema must const {expected_status}")

    queue_schema = schema.get("properties", {}).get("pending_validation_queue", {})
    queue_consts = _contains_consts(queue_schema)
    missing_queue = EXPECTED_QUEUE_COMMANDS.difference(queue_consts)
    unexpected_queue = queue_consts.difference(EXPECTED_QUEUE_COMMANDS)
    if missing_queue:
        errors.append(f"pending_validation_queue schema missing: {', '.join(sorted(missing_queue))}")
    if unexpected_queue:
        errors.append(f"pending_validation_queue schema has unexpected commands: {', '.join(sorted(unexpected_queue))}")
    if isinstance(queue_schema, dict):
        expected_count = len(EXPECTED_QUEUE_COMMANDS)
        if queue_schema.get("minItems") != expected_count:
            errors.append(f"pending_validation_queue schema minItems must be {expected_count}")
        if queue_schema.get("maxItems") != expected_count:
            errors.append(f"pending_validation_queue schema maxItems must be {expected_count}")
        if queue_schema.get("uniqueItems") is not True:
            errors.append("pending_validation_queue schema must require uniqueItems")
        item_enum = queue_schema.get("items", {}).get("enum") if isinstance(queue_schema.get("items"), dict) else None
        if set(item_enum or []) != EXPECTED_QUEUE_COMMANDS:
            errors.append("pending_validation_queue items enum must exactly match expected commands")

    defs = schema.get("$defs", {})
    if not isinstance(defs, dict):
        errors.append("schema $defs must be an object")
        return errors

    for def_name, expected_blockers in EXPECTED_ROUTE_BLOCKERS.items():
        route_def = defs.get(def_name)
        if not isinstance(route_def, dict):
            errors.append(f"schema missing $defs.{def_name}")
            continue
        route_consts = _contains_consts(route_def)
        missing = expected_blockers.difference(route_consts)
        unexpected = route_consts.intersection(EXPECTED_GLOBAL_BLOCKERS).difference(expected_blockers)
        if missing:
            errors.append(f"$defs.{def_name} missing blockers: {', '.join(sorted(missing))}")
        if unexpected:
            errors.append(f"$defs.{def_name} has unexpected blockers: {', '.join(sorted(unexpected))}")
        blocker_schemas = _find_blocker_schemas(route_def)
        exact_schema_found = False
        for blocker_schema in blocker_schemas:
            if blocker_schema.get("minItems") != len(expected_blockers):
                continue
            if blocker_schema.get("maxItems") != len(expected_blockers):
                continue
            if blocker_schema.get("uniqueItems") is not True:
                continue
            item_enum = blocker_schema.get("items", {}).get("enum") if isinstance(blocker_schema.get("items"), dict) else None
            if set(item_enum or []) == expected_blockers:
                exact_schema_found = True
        if not exact_schema_found:
            errors.append(f"$defs.{def_name}.blockers must require exact blocker keys")

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    schema = _load_json(repo_root / "docs" / "product-readiness-status.schema.json")
    errors = validate(schema)
    if errors:
        print("Product readiness schema requirements guard: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Product readiness schema requirements guard: PASS")
    print("This confirms only schema blocker requirements, not product readiness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
