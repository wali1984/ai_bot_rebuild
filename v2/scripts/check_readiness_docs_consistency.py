#!/usr/bin/env python3
"""Validate human-readable readiness docs against no-PASS guardrails.

This guard is intentionally conservative. It checks that the main readiness
docs do not accidentally promote blocked/in-progress gates after implementation
work. It does not prove product readiness, launch readiness, realtime data
coverage, visual QA, or live trading safety.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any


DOCS_TO_CHECK = [
    "docs/product-readiness-current-status.md",
    "docs/product-readiness-monitor.md",
    "docs/product-readiness-monitor-log.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-phase-blocker-map.md",
    "docs/product-readiness-blocker-owner-map.md",
    "docs/product-readiness-blocker-closure-ledger.md",
    "docs/product-readiness-change-control.md",
    "docs/product-readiness-monitor-runbook.md",
    "docs/product-readiness-docs-index.md",
    "docs/frontend-redesign-phase-progress.md",
    "docs/frontend-redesign-master-todo.md",
    "docs/redesign-acceptance-matrix.md",
    "docs/launch-readiness.md",
    "docs/api-gap-register.md",
    "docs/auth-rbac-audit.md",
    "docs/data-source-inventory.md",
    "docs/visible-string-ledger.md",
    "docs/trade-redesign-audit.md",
    "docs/product-readiness-evidence-status-ledger.md",
    "docs/product-readiness-pending-evidence-ledger.md",
    "docs/product-readiness-pending-evidence-validation-coverage-ledger.md",
    "docs/product-readiness-guardrail-ledger.md",
    "docs/product-readiness-route-status-ledger.md",
    "docs/product-readiness-current-blocker-ledger.md",
    "docs/product-readiness-validation-queue-ledger.md",
    "docs/product-readiness-source-of-truth-ledger.md",
    "docs/product-readiness-history-event-ledger.md",
    "docs/product-readiness-history-supersession-ledger.md",
    "docs/product-readiness-status-snapshot-manifest-ledger.md",
    "docs/product-readiness-source-artifact-existence-ledger.md",
    "docs/product-readiness-route-closure-ledger.md",
    "docs/product-readiness-route-blocker-ledger.md",
    "docs/product-readiness-phase-launch-ledger.md",
]

STATUS_TABLE_DOCS = {
    "docs/product-readiness-current-status.md",
    "docs/product-readiness-monitor.md",
    "docs/product-readiness-monitor-log.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-phase-blocker-map.md",
    "docs/product-readiness-monitor-runbook.md",
    "docs/product-readiness-docs-index.md",
    "docs/frontend-redesign-phase-progress.md",
    "docs/frontend-redesign-master-todo.md",
    "docs/redesign-acceptance-matrix.md",
    "docs/launch-readiness.md",
}

ROUTE_STATUS_TABLE_DOCS = {
    "docs/product-readiness-current-status.md",
    "docs/product-readiness-monitor.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-docs-index.md",
    "docs/redesign-acceptance-matrix.md",
}

PHASE_STATUS_TABLE_DOCS = {
    "docs/product-readiness-completion-checklist.md",
    "docs/frontend-redesign-master-todo.md",
    "docs/frontend-redesign-phase-progress.md",
}

LAUNCH_STATUS_TABLE_DOCS = {
    "docs/product-readiness-current-status.md",
    "docs/launch-readiness.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-docs-index.md",
}

BLOCKER_KEY_TABLE_DOCS = {
    "docs/product-readiness-docs-index.md",
    "docs/product-readiness-monitor-runbook.md",
    "docs/product-readiness-change-control.md",
    "docs/product-readiness-current-status.md",
    "docs/product-readiness-monitor.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-blocker-owner-map.md",
    "docs/product-readiness-phase-blocker-map.md",
}

VALIDATION_QUEUE_DOCS = {
    "docs/product-readiness-validation-queue-ledger.md",
    "docs/product-readiness-monitor.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-monitor-runbook.md",
}

SOURCE_OF_TRUTH_DOCS = {
    "docs/product-readiness-docs-index.md",
}

VALIDATION_QUEUE_LEDGER_DOCS = {
    "docs/product-readiness-validation-queue-ledger.md",
}

BLOCKER_CLOSURE_LEDGER_DOCS = {
    "docs/product-readiness-blocker-closure-ledger.md",
}

CURRENT_BLOCKER_LEDGER_DOCS = {
    "docs/product-readiness-current-blocker-ledger.md",
}

STATUS_SNAPSHOT_MANIFEST_LEDGER_DOCS = {
    "docs/product-readiness-status-snapshot-manifest-ledger.md",
}

SOURCE_ARTIFACT_EXISTENCE_LEDGER_DOCS = {
    "docs/product-readiness-source-artifact-existence-ledger.md",
}

SOURCE_OF_TRUTH_LEDGER_DOCS = {
    "docs/product-readiness-source-of-truth-ledger.md",
}

EVIDENCE_STATUS_LEDGER_DOCS = {
    "docs/product-readiness-evidence-status-ledger.md",
}

PENDING_EVIDENCE_LEDGER_DOCS = {
    "docs/product-readiness-pending-evidence-ledger.md",
}

PENDING_EVIDENCE_VALIDATION_COVERAGE_LEDGER_DOCS = {
    "docs/product-readiness-pending-evidence-validation-coverage-ledger.md",
}

GUARDRAIL_LEDGER_DOCS = {
    "docs/product-readiness-guardrail-ledger.md",
}

ROUTE_STATUS_LEDGER_DOCS = {
    "docs/product-readiness-route-status-ledger.md",
}

ROUTE_CLOSURE_LEDGER_DOCS = {
    "docs/product-readiness-route-closure-ledger.md",
}

ROUTE_BLOCKER_LEDGER_DOCS = {
    "docs/product-readiness-route-blocker-ledger.md",
}

PHASE_LAUNCH_LEDGER_DOCS = {
    "docs/product-readiness-phase-launch-ledger.md",
}

HISTORY_EVENT_LEDGER_DOCS = {
    "docs/product-readiness-history-event-ledger.md",
}

HISTORY_SUPERSESSION_LEDGER_DOCS = {
    "docs/product-readiness-history-supersession-ledger.md",
}

HISTORY_EVENT_LOG_DOCS = {
    "docs/product-readiness-monitor-log.md",
}

LAUNCH_STATUS_LABELS = {
    "full_product_launch": "Full product launch",
    "paper_read_only_launch": "Paper/read-only launch",
    "real_live_trading": "Real live trading",
    "production_ready_claim": "Production-ready claim",
}

REQUIRED_DOC_PHRASES = {
    "docs/product-readiness-current-status.md": [
        "explicit local repository readiness metadata",
        "read-only multi-trader account-scope smoke runner",
        "multi-trader account-scope smoke artifact metadata",
        "SQLAlchemy trader account repository adapter",
        "credential vault readiness metadata",
        "credential permission-probe artifact metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "admin audit readiness metadata",
        "admin audit retention policy metadata",
        "Alembic version-script approval gate",
        "account-scope proof metadata/strict data match/partial-scope fail-closed",
        "focused ProChart spec/stream symbol-timeframe filter",
        "backend snapshot live-candle filter",
        "any monitored route, admin security, launch",
        "`/` | IN PROGRESS",
        "`/login` | IN PROGRESS",
        "`/account-settings` | IN PROGRESS",
        "`/status` | IN PROGRESS",
        "`/dashboard` | IN PROGRESS",
        "`/markets` | IN PROGRESS",
        "`/markets/symbols` | IN PROGRESS",
        "`/alerts` | IN PROGRESS",
        "`/trade/paper` | IN PROGRESS",
        "`/derivatives` | IN PROGRESS",
        "`/signals` | IN PROGRESS",
        "`/ai-predictions` | IN PROGRESS",
        "`/ai-predictions/model-state` | IN PROGRESS",
        "`/backtests` | IN PROGRESS",
        "`/backtests/replay` | IN PROGRESS",
        "`/research` | IN PROGRESS",
        "`/research/technical-analysis` | IN PROGRESS",
        "`/portfolio` | IN PROGRESS",
        "`/portfolio/executions` | IN PROGRESS",
        "`/portfolio/history` | IN PROGRESS",
        "`/admin` | IN PROGRESS",
        "`/admin/system` | IN PROGRESS",
        "`/admin/users` | IN PROGRESS",
        "`/system/*` | IN PROGRESS",
        "`/admin/audit` | IN PROGRESS",
        "`/admin/scripts` | IN PROGRESS",
        "`/admin/migrations` | IN PROGRESS",
        "Do not mark Phase 14",
        "exact readiness guard key-set coverage",
        "Current status, status snapshot, and status history are source-of-truth artifacts",
        "Docs-consistency checked readiness docs are source-of-truth artifacts",
        "Every docs-consistency checked document must be declared in source_of_truth",
        "schema source-of-truth/evidence-queue/launch-phase-guardrail/exact route-status/current-blocker/route-blocker/validation-queue/source-of-truth/evidence",
    ],
    "docs/product-readiness-monitor.md": [
        "production stream alerting",
        "production repositories",
        "credential vault",
        "credential vault readiness metadata",
        "credential permission-probe artifact metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "admin-only audit-store readiness metadata",
        "retention-policy metadata",
        "Alembic version-script approval gate",
        "local vault-file credential binding",
        "explicit local repository readiness metadata",
        "SQLAlchemy trader account repository adapter",
        "protected admin activation/reset workflow with production step-up gate and local audit event",
        "signed read-only account adapter",
        "safe credential-status copy",
        "stream telemetry persistence",
        "local stream alert history",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "scripts/run_production_alert_delivery_audit_smoke.py",
        "production alert delivery/audit smoke runner",
        "ALPHAFORGE_PRODUCTION_ALERT_DELIVERY_AUDIT_ARTIFACT",
        "production alert delivery/audit artifact metadata",
        "ALPHAFORGE_ALERT_STORE_BACKEND=sqlalchemy",
        "SQLAlchemy alert repository",
        "multi-trader account-scope smoke runner",
        "multi-trader account-scope smoke artifact metadata",
        "outbound alert webhook notifier/active-only alert delivery",
        "read-only `/api/v2/alerts` unavailable contract",
        "alert CRUD/delivery/audit repositories",
        "exchange-account metadata normalization",
        "local paper-account uniqueness",
        "production-secret strength/rotation, issuer/audience, session TTL, password policy, cookie SameSite, and revocation-store required/error fail-closed/session security status/refresh token rotation/password-change session revocation/session-version invalidation",
        "frontend scoped paper-account display",
        "trader account binding copy",
        "account-scope proof metadata/strict data match/partial-scope fail-closed",
        "trade typed activity tabs",
        "ProChart realtime",
        "overlay timestamp normalization",
        "focused ProChart spec/stream symbol-timeframe filter",
        "production paper submit/cancel validation",
        "production paper actions fail closed",
        "durable paper audit policy artifact metadata",
        "durable paper audit policy smoke runner",
        "scripts/run_production_paper_action_validation_smoke.py",
        "production paper action validation smoke runner",
        "ALPHAFORGE_PRODUCTION_PAPER_ACTION_VALIDATION_ARTIFACT",
        "production paper action validation artifact metadata",
        "scripts/run_durable_paper_audit_policy_smoke.py",
        "hash-chained local paper audit events",
        "append-only local ledger/chain verification/window completeness",
        "protected admin activation/reset workflow with production step-up gate and local audit event",
        "durable paper audit policy",
        "pending rerun",
    ],
    "docs/product-readiness-completion-checklist.md": [
        "NOT COMPLETE",
        "Real live trading remains blocked",
        "credential configured/pending status",
        "credential vault readiness metadata",
        "credential permission-probe artifact metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "admin audit readiness metadata",
        "admin audit retention policy metadata",
        "Alembic version-script authoring is still approval-gated",
        "local repository readiness metadata",
        "multi-trader account-scope smoke runner",
        "multi-trader account-scope smoke artifact metadata",
        "SQLAlchemy trader account repository adapter",
        "signed read-only account adapters",
        "telemetry persistence coverage",
        "local stream alert history",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "outbound alert webhook notifier/active-only alert delivery",
        "exchange-account read-only normalization",
        "local paper-account uniqueness",
        "production-secret strength/rotation, issuer/audience, session TTL, password policy, cookie SameSite, and revocation-store required/error fail-closed/session security status/refresh token rotation/password-change session revocation/session-version invalidation",
        "frontend scoped paper-account display",
        "trader account binding copy",
        "trader account-scope proof metadata/strict data match/partial-scope fail-closed",
        "trade typed activity tabs",
        "ProChart realtime timestamp normalization",
        "overlay timestamp normalization",
        "focused ProChart spec/stream symbol-timeframe filter",
        "production paper actions fail closed",
        "hash-chained local paper audit events",
        "append-only local ledger/chain verification/window completeness",
        "durable paper audit policy",
        "paper audit retention policy metadata",
        "durable paper audit policy artifact metadata",
        "current validation",
        "exact route-status/current-blocker/route-blocker/validation-queue/source-of-truth/evidence",
    ],
    "docs/product-readiness-monitor-runbook.md": [
        "Do not mark `/trade` PASS",
        "Do not mark `/market/:symbol` PASS",
        "Run only when explicitly approved for validation",
        "Hash-chained local paper audit events and append-only local ledger/chain verification/window completeness are partial evidence only",
        "Env/local vault-file binding is partial evidence only",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "scripts/run_secret_redaction_smoke.py",
        "durable paper audit policy",
        "backend/tests/unit/api/test_readonly_market_stream_parser.py",
        "local stream alert history",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "scripts/run_production_stream_alerting_smoke.py",
        "backend/tests/unit/scripts/test_run_production_stream_alerting_smoke.py",
        "backend/tests/unit/scripts/test_run_trader_account_scope_smoke.py",
        "scripts/run_trader_account_scope_smoke.py",
        "ALPHAFORGE_PRODUCTION_TRADER_REPOSITORY_SMOKE_ARTIFACT",
        "scripts/run_production_trader_repository_smoke.py",
        "ALPHAFORGE_TRADER_ACCOUNT_SCOPE_SMOKE_ARTIFACT",
        "outbound alert webhook notifier/active-only alert delivery",
        "Local repository integrity",
        "Readiness guard exactness",
        "exact source-of-truth, route-status, route-blocker, current-blocker, evidence, validation-queue, launch/phase/guardrail key sets",
    ],
    "docs/product-readiness-evidence-status-ledger.md": [
        "Product Readiness Evidence Status Ledger",
        "last_current_evidence",
        "Evidence status mirror",
        "Validation was not run",
        "readiness_evidence_status_ledger_drift_guard_after_latest_changes",
        "full_phase13_visual_review",
        "real_live_trading_approval",
    ],
    "docs/product-readiness-pending-evidence-ledger.md": [
        "Product Readiness Pending Evidence Ledger",
        "last_current_evidence",
        "Validation was not run",
        "No route, phase, launch gate",
        "readiness_pending_evidence_ledger_after_latest_changes",
        "readiness_pending_evidence_ledger_drift_guard_after_latest_changes",
    ],
    "docs/product-readiness-pending-evidence-validation-coverage-ledger.md": [
        "Product Readiness Pending Evidence Validation Coverage Ledger",
        "pending_validation_queue",
        "Evidence coverage group",
        "not proof of execution",
        "readiness_pending_evidence_validation_coverage_ledger_drift_guard_after_latest_changes",
        "python scripts/check_product_readiness_status.py",
        "npx playwright test --project=chromium",
        "Real live trading remains blocked",
    ],
    "docs/product-readiness-guardrail-ledger.md": [
        "Product Readiness Guardrail Ledger",
        "guardrails",
        "Validation was not run",
        "No route, phase, launch gate",
        "readiness_guardrail_ledger_drift_guard_after_latest_changes",
        "do_not_mark_trade_pass",
        "do_not_mark_real_live_trading_pass",
    ],
    "docs/product-readiness-route-status-ledger.md": [
        "Product Readiness Route Status Ledger",
        "route_status",
        "Validation was not run",
        "Route status mirror",
        "readiness_route_status_ledger_drift_guard_after_latest_changes",
        "`/trade` | `IN_PROGRESS`",
        "`/market/:symbol` | `IN_PROGRESS`",
    ],
    "docs/product-readiness-validation-queue-ledger.md": [
        "Product Readiness Validation Queue Ledger",
        "pending_validation_queue",
        "Validation was not run",
        "Pending validation queue mirror",
        "readiness_validation_queue_ledger_drift_guard_after_latest_changes",
        "python scripts/check_product_readiness_status.py",
        "npx playwright test --project=chromium",
    ],
    "docs/product-readiness-blocker-closure-ledger.md": [
        "Product Readiness Blocker Closure Ledger",
        "Blocker closure mirror",
        "Required closure evidence",
        "Validation was not run",
        "readiness_blocker_closure_ledger_drift_guard_after_latest_changes",
        "production_paper_fill_writer_missing",
        "Current validation rerun pending",
    ],
    "docs/product-readiness-current-blocker-ledger.md": [
        "Product Readiness Current Blocker Ledger",
        "current_blockers",
        "Validation was not run",
        "Current blocker mirror",
        "readiness_current_blocker_ledger_drift_guard_after_latest_changes",
        "current_validation_rerun_pending",
        "production_https_smoke_missing",
    ],
    "docs/product-readiness-history-event-ledger.md": [
        "Product Readiness History Event Ledger",
        "Status history event mirror",
        "Validation was not run",
        "readiness_history_event_ledger_drift_guard_after_latest_changes",
        "NO_EVIDENCE_KEY",
        "history_event_ledger_drift_guard_added",
    ],
    "docs/product-readiness-history-supersession-ledger.md": [
        "Product Readiness History Supersession Ledger",
        "Superseded history rows",
        "Validation was not run",
        "readiness_history_supersession_ledger_drift_guard_after_latest_changes",
        "trader_user_scope_enforcement",
        "exchange_account_scope_requires_paper_account_hardened",
    ],
    "docs/product-readiness-status-snapshot-manifest-ledger.md": [
        "Product Readiness Status Snapshot Manifest Ledger",
        "Status snapshot manifest mirror",
        "Validation was not run",
        "readiness_status_snapshot_manifest_ledger_drift_guard_after_latest_changes",
        "source_of_truth",
        "last_current_evidence",
    ],
    "docs/product-readiness-source-artifact-existence-ledger.md": [
        "Product Readiness Source Artifact Existence Ledger",
        "source_of_truth",
        "Artifact status",
        "Validation was not run",
        "readiness_source_artifact_existence_ledger_drift_guard_after_latest_changes",
        "source_artifact_existence_ledger",
        "EXISTS",
    ],
    "docs/product-readiness-source-of-truth-ledger.md": [
        "Product Readiness Source Of Truth Ledger",
        "source_of_truth",
        "Validation was not run",
        "Source-of-truth mirror",
        "readiness_source_of_truth_ledger_drift_guard_after_latest_changes",
        "status_snapshot",
        "source_of_truth_ledger",
    ],
    "docs/product-readiness-route-closure-ledger.md": [
        "Product Readiness Route Closure Ledger",
        "Route closure mirror",
        "Required route closure evidence",
        "Validation was not run",
        "readiness_route_closure_ledger_drift_guard_after_latest_changes",
        "`/trade`",
        "production_paper_submit_cancel_validation_missing",
    ],
    "docs/product-readiness-route-blocker-ledger.md": [
        "Product Readiness Route Blocker Ledger",
        "route_status",
        "Validation was not run",
        "Route blocker mirror",
        "readiness_route_blocker_ledger_drift_guard_after_latest_changes",
        "production_trader_account_repositories_and_writers_missing",
        "current_validation_rerun_pending",
    ],
    "docs/product-readiness-phase-launch-ledger.md": [
        "Product Readiness Phase And Launch Ledger",
        "phase_status",
        "launch_status",
        "Validation was not run",
        "readiness_phase_launch_ledger_drift_guard_after_latest_changes",
        "Phase 15",
        "real_live_trading",
    ],
    "docs/product-readiness-docs-index.md": [
        "durable paper audit policy blocker",
        "alert CRUD/delivery/audit blocker",
        "read-only alerts unavailable contract",
        "paper audit retention policy evidence",
        "SQLAlchemy trader account repository evidence",
        "multi-trader account-scope smoke runner evidence",
        "multi-trader account-scope smoke artifact metadata",
        "credential permission-probe artifact evidence",
        "signed-read validation artifact evidence",
        "secret-redaction smoke artifact evidence",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "production paper actions fail closed evidence",
        "durable paper audit policy artifact metadata",
        "local repository readiness metadata boundary",
        "credential vault readiness metadata boundary",
        "admin audit readiness metadata",
        "retention-policy guard evidence",
        "repository/credential docs guard evidence",
        "source-of-truth",
        "Do not mark any monitored route as `PASS`",
        "Do not mark full product launch or admin security as `PASS`",
        "Every `DOCS_TO_CHECK` entry must be present in `source_of_truth`",
        "docs-consistency guard checked docs",
        "docs/frontend-redesign-master-todo.md",
        "docs/api-gap-register.md",
        "docs/auth-rbac-audit.md",
        "docs/data-source-inventory.md",
        "docs/visible-string-ledger.md",
        "docs/trade-redesign-audit.md",
        "Exact source-of-truth coverage",
        "docs/product-readiness-current-status.md",
        "docs/product-readiness-status.json",
        "docs/product-readiness-status-history.jsonl",
        "docs/product-readiness-pending-evidence-ledger.md",
        "docs/product-readiness-pending-evidence-validation-coverage-ledger.md",
        "Exact guard coverage",
        "exact source-of-truth, route-status, route-blocker, current-blocker, evidence, validation-queue, launch/phase/guardrail key sets",
        "`/` | IN PROGRESS",
        "`/login` | IN PROGRESS",
        "`/account-settings` | IN PROGRESS",
        "`/status` | IN PROGRESS",
        "`/dashboard` | IN PROGRESS",
        "`/markets` | IN PROGRESS",
        "`/markets/symbols` | IN PROGRESS",
        "`/alerts` | IN PROGRESS",
        "`/trade/paper` | IN PROGRESS",
        "`/derivatives` | IN PROGRESS",
        "`/signals` | IN PROGRESS",
        "`/ai-predictions` | IN PROGRESS",
        "`/ai-predictions/model-state` | IN PROGRESS",
        "`/backtests` | IN PROGRESS",
        "`/backtests/replay` | IN PROGRESS",
        "`/research` | IN PROGRESS",
        "`/research/technical-analysis` | IN PROGRESS",
        "`/portfolio` | IN PROGRESS",
        "`/portfolio/executions` | IN PROGRESS",
        "`/portfolio/history` | IN PROGRESS",
        "`/admin` | IN PROGRESS",
        "`/admin/system` | IN PROGRESS",
        "`/admin/users` | IN PROGRESS",
        "`/system/*` | IN PROGRESS",
        "`/admin/audit` | IN PROGRESS",
        "`/admin/scripts` | IN PROGRESS",
        "`/admin/migrations` | IN PROGRESS",
    ],
    "docs/product-readiness-change-control.md": [
        "durable paper audit policy",
        "credential vault readiness metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "admin audit readiness metadata",
        "admin audit readiness metadata with retention-policy metadata",
        "Alembic version-script approval gate",
        "local repository readiness metadata",
        "no live exchange mutation path exists",
    ],
    "docs/product-readiness-phase-blocker-map.md": [
        "durable paper audit policy",
        "credential vault readiness metadata",
        "admin audit readiness metadata",
        "Alembic version-script approval gate",
        "local repository readiness metadata",
        "repository/credential docs guard evidence key",
        "`/trade` | IN PROGRESS",
        "Real live trading | BLOCKED",
    ],
    "docs/product-readiness-blocker-owner-map.md": [
        "Durable paper audit policy missing",
        "durable paper audit policy artifact metadata",
        "Hash-chained local paper audit events and append-only local ledger/chain verification/window completeness are partial evidence only",
        "Env/local vault-file binding, credential vault readiness metadata, credential permission-probe artifact metadata, signed-read validation artifact metadata, secret-redaction smoke artifact metadata, and safe secret-redaction smoke runner are partial evidence only",
        "Production stream validation/alerting missing",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "Local stream alert history is partial evidence only",
        "Outbound alert webhook notifier/active-only alert delivery is partial evidence only",
        "Alert CRUD/delivery/audit repositories missing",
        "read-only `/api/v2/alerts` unavailable contract is partial evidence only",
        "Local repository integrity, readiness metadata, and paper-account uniqueness are partial evidence only",
        "multi-trader account-scope smoke runner",
        "multi-trader account-scope smoke artifact metadata",
        "SQLAlchemy trader account repository adapter seam",
        "Real live trading approval missing",
    ],
    "docs/frontend-redesign-master-todo.md": [
        "trader account-scope proof metadata/strict data match/partial-scope fail-closed",
        "trader account binding copy",
        "overlay timestamp normalization",
        "focused ProChart spec/stream symbol-timeframe filter",
        "IN PROGRESS",
        "BLOCKED",
    ],
    "docs/redesign-acceptance-matrix.md": [
        "IN PROGRESS",
        "BLOCKED",
        "historical",
        "trader account-scope proof metadata/strict data match/partial-scope fail-closed",
        "focused ProChart spec/stream symbol-timeframe filter",
    ],
    "docs/launch-readiness.md": [
        "BLOCKED",
        "real live trading",
        "Market stream",
        "trader account-scope proof metadata/strict data match/partial-scope fail-closed",
        "local stream alert history",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "outbound alert webhook notifier/active-only alert delivery",
        "local paper-account uniqueness",
        "local repository readiness metadata",
        "multi-trader account-scope smoke runner",
        "multi-trader account-scope smoke artifact metadata",
        "credential vault readiness metadata",
        "credential permission-probe artifact metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "admin audit readiness metadata",
        "Alembic version-script approval gate",
        "production-secret strength/rotation, issuer/audience, session TTL, password policy, cookie SameSite, and revocation-store required/error fail-closed/session security status/refresh token rotation/password-change session revocation/session-version invalidation",
        "trader account binding copy",
        "SQLAlchemy trader account repository adapter",
        "focused ProChart spec/stream symbol-timeframe filter",
        "protected admin activation/reset",
        "durable paper audit policy",
        "hash-chained local paper audit events",
        "append-only local ledger/chain verification/window completeness",
        "local vault-file credential binding",
    ],
    "docs/api-gap-register.md": [
        "`GET /api/admin/credential-status`",
        "admin audit-store readiness",
        "Alembic version-script authoring is still approval-gated",
        "`/api/admin/trader-accounts`",
        "`GET /api/v2/market/{symbol}/stream-status`",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "credential vault readiness metadata",
        "credential permission-probe artifact metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "partial local repository readiness metadata",
        "SQLAlchemy trader account repository adapter",
        "production credential vault",
        "local vault-file",
        "signed read-only adapter",
        "exchange-account metadata",
        "durable paper audit policy",
        "durable paper audit policy artifact metadata",
        "append-only local ledger/chain verification/window completeness",
    ],
    "docs/auth-rbac-audit.md": [
        "`GET /api/admin/credential-status`",
        "credential-status",
        "credential vault readiness metadata",
        "credential permission-probe artifact metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "admin audit-store readiness",
        "Alembic version-script authoring is still approval-gated",
        "local vault-file",
        "`POST /api/admin/users/{id}/activation`",
        "signed read-only account adapter",
        "owning user `trader_id`",
    ],
    "docs/data-source-inventory.md": [
        "`/api/admin/credential-status`",
        "admin audit readiness",
        "`/api/v2/market/{symbol}/stream-status`",
        "production stream alerting artifact metadata",
        "production stream alerting smoke runner",
        "credential vault readiness metadata",
        "signed-read validation artifact metadata",
        "secret-redaction smoke artifact metadata",
        "safe secret-redaction smoke runner",
        "auth/session hardening artifact metadata",
        "local repository readiness metadata",
        "account-scope smoke runner",
        "account-scope smoke artifact metadata",
        "SQLAlchemy trader account repository adapter",
        "credential vault",
        "local vault-file",
        "activate/reset users through an admin-protected route",
        "signed account adapter",
        "normalized to the owning user `trader_id` and `paper_account_id`",
    ],
    "docs/visible-string-ledger.md": [
        "Credential source unavailable",
        "CHECKED PENDING RERUN",
    ],
    "docs/trade-redesign-audit.md": [
        "credential-status",
        "local vault-file",
        "explicit partial local paper execution policy",
        "production paper actions fail closed",
        "paper audit retention policy metadata",
        "durable paper audit policy artifact metadata",
        "append-only local ledger/chain verification/window completeness",
        "HISTORICAL PASS",
        "pending rerun",
        "durable paper audit policy",
    ],
}

EXPECTED_STATUS = {
    "/trade": "IN_PROGRESS",
    "/market/:symbol": "IN_PROGRESS",
    "/chart/:symbol": "IN_PROGRESS",
    "phase13": "IN_PROGRESS",
    "phase14": "IN_PROGRESS",
    "phase15": "BLOCKED",
    "full_product_launch": "BLOCKED",
    "paper_read_only_launch": "BLOCKED",
    "real_live_trading": "BLOCKED",
}

PROMOTED_VALUES = {"PASS", "PASSED", "COMPLETE", "COMPLETED", "READY", "LIVE_READY", "APPROVED"}

PROMOTION_PATTERNS = [
    re.compile(r"\bfull product launch\s*(?:is|:|-)\s*(?:pass|ready|complete|approved)\b", re.I),
    re.compile(r"\bpaper/read-only launch\s*(?:is|:|-)\s*(?:pass|ready|complete|approved)\b", re.I),
    re.compile(r"\breal live trading\s*(?:is|:|-)\s*(?:enabled|ready|pass|complete|approved)\b", re.I),
    re.compile(r"\bphase 15\s*(?:is|:|-)\s*(?:pass|ready|complete|approved)\b", re.I),
    re.compile(r"\b/trade\s*(?:is|:|-)\s*(?:pass|ready|complete|approved)\b", re.I),
    re.compile(r"\b/market/:symbol\s*(?:is|:|-)\s*(?:pass|ready|complete|approved)\b", re.I),
    re.compile(r"\b/chart/:symbol\s*(?:is|:|-)\s*(?:pass|ready|complete|approved)\b", re.I),
]

CURRENT_SCOPE_DOCS = {
    "docs/product-readiness-current-status.md",
    "docs/product-readiness-monitor.md",
    "docs/product-readiness-completion-checklist.md",
    "docs/product-readiness-monitor-runbook.md",
    "docs/frontend-redesign-phase-progress.md",
    "docs/frontend-redesign-master-todo.md",
    "docs/launch-readiness.md",
    "docs/api-gap-register.md",
    "docs/auth-rbac-audit.md",
    "docs/data-source-inventory.md",
    "docs/trade-redesign-audit.md",
}

STALE_EXCHANGE_SCOPE_PHRASES = [
    "exchange-account metadata requires trader scope",
    "exchange-account metadata requires a trader scope",
    "exchange-account metadata normalized to the owning user trader scope",
    "exchange-account metadata is normalized to the owning user `trader_id`,",
    "exchange-account metadata matches the owning trader,",
]


def _load_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise SystemExit(f"status JSON not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise SystemExit(f"status JSON invalid: {exc}") from exc
    if not isinstance(payload, dict):
        raise SystemExit("status JSON root must be an object")
    return payload


def _read_doc(repo_root: Path, relative_path: str, errors: list[str]) -> str:
    path = repo_root / relative_path
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        errors.append(f"missing readiness doc: {relative_path}")
    return ""


def _normalise(value: str) -> str:
    value = value.strip().strip("`").strip()
    value = re.sub(r"\s+", " ", value)
    return value


def _status_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", value.upper()).strip("_")


def _pipe_cells(line: str) -> list[str]:
    stripped = line.strip()
    if not stripped.startswith("|") or not stripped.endswith("|"):
        return []
    if re.fullmatch(r"\|[\s:\-|\`]+\|?", stripped):
        return []
    cells = [_normalise(cell) for cell in stripped.strip("|").split("|")]
    return cells if any(cells) else []


def _looks_like_route_key(cell: str) -> str | None:
    lowered = cell.lower().strip("`")
    if lowered in {"/trade", "trade"}:
        return "/trade"
    if lowered in {"/market/:symbol", "/market/:symbol?", "market detail", "market symbol"}:
        return "/market/:symbol"
    return None


def _looks_like_launch_key(cell: str) -> str | None:
    lowered = cell.lower().strip("`")
    if lowered in {"phase 13", "phase13"}:
        return "phase13"
    if lowered in {"phase 14", "phase14"}:
        return "phase14"
    if lowered in {"phase 15", "phase15"}:
        return "phase15"
    if lowered == "full product launch":
        return "full_product_launch"
    if lowered in {"paper/read-only launch", "paper read-only launch", "paper launch"}:
        return "paper_read_only_launch"
    if lowered == "real live trading":
        return "real_live_trading"
    return None


def _check_json_status(payload: dict[str, Any], errors: list[str]) -> None:
    launch = payload.get("launch_status")
    if not isinstance(launch, dict):
        errors.append("launch_status missing or invalid in product-readiness-status.json")
    else:
        for key in LAUNCH_STATUS_LABELS:
            if launch.get(key) != "BLOCKED":
                errors.append(f"launch_status.{key} must remain BLOCKED")

    routes = payload.get("route_status")
    if not isinstance(routes, dict):
        errors.append("route_status missing or invalid in product-readiness-status.json")
    else:
        for route in ("/trade", "/market/:symbol"):
            route_payload = routes.get(route)
            status = route_payload.get("status") if isinstance(route_payload, dict) else None
            if status != "IN_PROGRESS":
                errors.append(f"route_status.{route}.status must remain IN_PROGRESS")

    phases = payload.get("phase_status")
    if not isinstance(phases, dict):
        errors.append("phase_status missing or invalid in product-readiness-status.json")
    else:
        if phases.get("13") != "IN_PROGRESS":
            errors.append("phase_status.13 must remain IN_PROGRESS")
        if phases.get("14") != "IN_PROGRESS":
            errors.append("phase_status.14 must remain IN_PROGRESS")
        if phases.get("15") != "BLOCKED":
            errors.append("phase_status.15 must remain BLOCKED")


def _check_doc_text(relative_path: str, text: str, errors: list[str]) -> None:
    for pattern in PROMOTION_PATTERNS:
        match = pattern.search(text)
        if match:
            errors.append(f"{relative_path} has unsafe promotion wording: {match.group(0)!r}")

    lowered_text = text.lower()
    for phrase in REQUIRED_DOC_PHRASES.get(relative_path, []):
        if phrase.lower() not in lowered_text:
            errors.append(f"{relative_path} missing required readiness phrase: {phrase!r}")

    if relative_path in CURRENT_SCOPE_DOCS:
        for phrase in STALE_EXCHANGE_SCOPE_PHRASES:
            if phrase.lower() in lowered_text:
                errors.append(
                    f"{relative_path} has stale exchange-account scope wording; "
                    "use trader_id plus paper_account_id scope: "
                    f"{phrase!r}"
                )

    if relative_path not in STATUS_TABLE_DOCS:
        return

    for line_number, line in enumerate(text.splitlines(), start=1):
        cells = _pipe_cells(line)
        if len(cells) < 2:
            continue

        key = _looks_like_route_key(cells[0]) or _looks_like_launch_key(cells[0])
        if key is None:
            continue

        status_tokens = {_status_token(cell) for cell in cells[1:]}
        promoted = sorted(PROMOTED_VALUES.intersection(status_tokens))
        expected = EXPECTED_STATUS[key]
        has_expected = any(token == expected or token.startswith(f"{expected}_") for token in status_tokens)

        if promoted:
            errors.append(f"{relative_path}:{line_number} promotes {key} with {', '.join(promoted)}")
        if not has_expected:
            errors.append(f"{relative_path}:{line_number} expected {key} to include {expected}")


def _route_aliases(route: str) -> set[str]:
    aliases = {route}
    if route == "/":
        aliases.add("/landing")
    if route == "/market/:symbol":
        aliases.add("/market/:symbol?")
    return aliases


def _check_monitored_route_table(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in ROUTE_STATUS_TABLE_DOCS:
        return

    route_status = payload.get("route_status")
    if not isinstance(route_status, dict):
        errors.append("route_status missing or invalid in product-readiness-status.json")
        return

    seen: set[str] = set()
    route_aliases = {
        route: {alias.lower() for alias in _route_aliases(route)}
        for route in map(str, route_status)
    }

    for line_number, line in enumerate(text.splitlines(), start=1):
        cells = _pipe_cells(line)
        if len(cells) < 2:
            continue
        first_cell = cells[0].strip().strip("`").lower()
        matched_route = next(
            (route for route, aliases in route_aliases.items() if first_cell in aliases),
            None,
        )
        if matched_route is None:
            continue

        route_payload = route_status.get(matched_route)
        if not isinstance(route_payload, dict):
            errors.append(f"route_status.{matched_route} must be an object")
            continue

        expected = route_payload.get("status")
        if expected not in {"IN_PROGRESS", "BLOCKED"}:
            errors.append(f"route_status.{matched_route}.status must remain IN_PROGRESS or BLOCKED")
            continue

        cells_to_check = [cells[-1]] if relative_path == "docs/redesign-acceptance-matrix.md" else cells[1:]
        status_tokens = {_status_token(cell) for cell in cells_to_check}
        promoted = sorted(PROMOTED_VALUES.intersection(status_tokens))
        has_expected = any(
            token == expected or token.startswith(f"{expected}_")
            for token in status_tokens
        )
        seen.add(matched_route)

        if promoted:
            errors.append(f"{relative_path}:{line_number} promotes route {matched_route} with {', '.join(promoted)}")
        if not has_expected:
            errors.append(f"{relative_path}:{line_number} expected route {matched_route} to include {expected}")

    missing = sorted(set(map(str, route_status)).difference(seen))
    if missing:
        errors.append(f"{relative_path} missing monitored route rows: {', '.join(missing)}")


def _check_phase_status_table(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in PHASE_STATUS_TABLE_DOCS:
        return

    phase_status = payload.get("phase_status")
    if not isinstance(phase_status, dict):
        errors.append("phase_status missing or invalid in product-readiness-status.json")
        return

    seen: set[str] = set()
    for line_number, line in enumerate(text.splitlines(), start=1):
        cells = _pipe_cells(line)
        if len(cells) < 2:
            continue
        phase = cells[0].strip()
        if phase not in phase_status:
            continue
        expected = str(phase_status[phase])
        status_tokens = {_status_token(cell) for cell in cells[1:]}
        promoted = sorted(PROMOTED_VALUES.intersection(status_tokens))
        has_expected = any(token == expected or token.startswith(f"{expected}_") for token in status_tokens)
        seen.add(phase)
        if promoted:
            errors.append(f"{relative_path}:{line_number} promotes phase {phase} with {', '.join(promoted)}")
        if not has_expected:
            errors.append(f"{relative_path}:{line_number} expected phase {phase} to include {expected}")

    missing = sorted(set(map(str, phase_status)).difference(seen), key=lambda value: int(value))
    if missing:
        errors.append(f"{relative_path} missing monitored phase rows: {', '.join(missing)}")


def _check_launch_status_table(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in LAUNCH_STATUS_TABLE_DOCS:
        return

    launch_status = payload.get("launch_status")
    if not isinstance(launch_status, dict):
        errors.append("launch_status missing or invalid in product-readiness-status.json")
        return

    lowered_text = text.lower()
    for key, label in LAUNCH_STATUS_LABELS.items():
        status = launch_status.get(key)
        if status != "BLOCKED":
            errors.append(f"launch_status.{key} must remain BLOCKED")
            continue
        expected_phrase = f"| {label} | {status}"
        if expected_phrase.lower() not in lowered_text:
            errors.append(f"{relative_path} missing monitored launch status row: {label} | {status}")


def _check_current_blocker_key_table(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in BLOCKER_KEY_TABLE_DOCS:
        return

    current_blockers = payload.get("current_blockers")
    if not isinstance(current_blockers, list):
        errors.append("current_blockers missing or invalid in product-readiness-status.json")
        return

    lowered_text = text.lower()
    for blocker in sorted(map(str, current_blockers)):
        expected_fragment = f"| `{blocker}` |"
        if expected_fragment.lower() not in lowered_text:
            errors.append(f"{relative_path} missing current blocker key row: {blocker}")




def _check_blocker_owner_labels(
    relative_path: str,
    text: str,
    errors: list[str],
) -> None:
    if relative_path != "docs/product-readiness-blocker-owner-map.md":
        return

    for line_number, line in enumerate(text.splitlines(), start=1):
        cells = _pipe_cells(line)
        if len(cells) < 3:
            continue
        blocker_key = cells[0].strip("`")
        owner_label = cells[1]
        if not blocker_key.endswith("_missing"):
            continue
        expected_owner_row = f"| {owner_label} |"
        if expected_owner_row not in text:
            errors.append(
                f"{relative_path}:{line_number} blocker key {blocker_key} references missing owner row: {owner_label}"
            )



def _check_change_control_status_locks(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path != "docs/product-readiness-change-control.md":
        return

    route_status = payload.get("route_status")
    if isinstance(route_status, dict):
        for route, route_payload in sorted(route_status.items()):
            status = route_payload.get("status") if isinstance(route_payload, dict) else None
            expected_row = f"| `{route}` | {status} | `route_status` |"
            if expected_row not in text:
                errors.append(f"{relative_path} missing change-control route lock row: {route}={status}")

    phase_status = payload.get("phase_status")
    if isinstance(phase_status, dict):
        for phase, status in sorted(phase_status.items(), key=lambda item: int(item[0])):
            expected_row = f"| Phase {phase} | {status} | `phase_status` |"
            if expected_row not in text:
                errors.append(f"{relative_path} missing change-control phase lock row: {phase}={status}")

    launch_status = payload.get("launch_status")
    if isinstance(launch_status, dict):
        for key, label in LAUNCH_STATUS_LABELS.items():
            status = launch_status.get(key)
            expected_row = f"| {label} | {status} | `launch_status` |"
            if expected_row not in text:
                errors.append(f"{relative_path} missing change-control launch lock row: {label}={status}")

def _check_validation_queue(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in VALIDATION_QUEUE_DOCS:
        return

    queue = payload.get("pending_validation_queue")
    if not isinstance(queue, list):
        errors.append("pending_validation_queue missing or invalid in product-readiness-status.json")
        return

    for command in map(str, queue):
        if command not in text:
            errors.append(f"{relative_path} missing pending validation command: {command}")


def _check_validation_queue_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in VALIDATION_QUEUE_LEDGER_DOCS:
        return

    queue = payload.get("pending_validation_queue")
    if not isinstance(queue, list):
        errors.append(f"{relative_path}: product-readiness-status.json pending_validation_queue is not an array")
        return

    for command in map(str, queue):
        row = f"| `{command}` | `PENDING` |"
        if row not in text:
            errors.append(f"{relative_path}: missing validation queue ledger row {row}")


def _check_blocker_closure_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in BLOCKER_CLOSURE_LEDGER_DOCS:
        return

    expected_labels = {
        "production_trader_account_repositories_and_writers_missing": "Production trader/account repositories and writers missing",
        "backend_only_binance_credential_vault_missing": "Binance credential vault missing",
        "production_stream_validation_alerting_missing": "Production stream validation/alerting missing",
        "derivatives_realtime_sources_missing": "Derivatives realtime sources missing",
        "alert_crud_delivery_audit_repositories_missing": "Alert CRUD/delivery/audit repositories missing",
        "production_paper_fill_writer_missing": "Production paper fill writer missing",
        "production_paper_submit_cancel_validation_missing": "Production paper submit/cancel validation missing",
        "durable_paper_audit_policy_missing": "Durable paper audit policy missing",
        "production_auth_session_hardening_missing": "Production auth/session hardening missing",
        "alembic_auth_revocation_admin_audit_migration_approval_missing": "Alembic auth/revocation/admin-audit migration approval missing",
        "full_phase13_visual_review_missing": "Full Phase 13 visual QA missing",
        "production_https_smoke_missing": "Production HTTPS smoke missing",
        "current_validation_rerun_pending": "Current validation rerun pending",
    }

    blockers = payload.get("current_blockers")
    if not isinstance(blockers, list):
        errors.append(f"{relative_path}: product-readiness-status.json current_blockers is not an array")
        return

    for blocker in blockers:
        label = expected_labels.get(str(blocker))
        if label is None:
            errors.append(f"{relative_path}: missing expected label mapping for blocker {blocker}")
            continue
        row_prefix = f"| `{blocker}` | {label} |"
        if row_prefix not in text:
            errors.append(f"{relative_path}: missing blocker closure ledger row prefix {row_prefix}")


def _check_current_blocker_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in CURRENT_BLOCKER_LEDGER_DOCS:
        return

    blockers = payload.get("current_blockers")
    if not isinstance(blockers, list):
        errors.append(f"{relative_path}: product-readiness-status.json current_blockers is not an array")
        return

    for blocker in blockers:
        row = f"| `{blocker}` | `ACTIVE` |"
        if row not in text:
            errors.append(f"{relative_path}: missing current blocker ledger row {row}")


def _shape_summary(value: Any) -> str:
    if isinstance(value, dict):
        return f"object:{len(value)}"
    if isinstance(value, list):
        return f"array:{len(value)}"
    return type(value).__name__


def _check_status_snapshot_manifest_ledger(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in STATUS_SNAPSHOT_MANIFEST_LEDGER_DOCS:
        return

    for key in sorted(payload):
        row = f"| `{key}` | `{_shape_summary(payload[key])}` |"
        if row not in text:
            errors.append(f"{relative_path}: missing status snapshot manifest ledger row {row}")


def _check_source_artifact_existence_ledger(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    repo_root: Path,
    errors: list[str],
) -> None:
    if relative_path not in SOURCE_ARTIFACT_EXISTENCE_LEDGER_DOCS:
        return

    source_of_truth = payload.get("source_of_truth")
    if not isinstance(source_of_truth, dict):
        errors.append(f"{relative_path}: product-readiness-status.json source_of_truth is not an object")
        return

    for key, artifact in sorted(source_of_truth.items()):
        artifact_status = "EXISTS" if (repo_root / str(artifact)).exists() else "MISSING"
        row = f"| `{key}` | `{artifact}` | `{artifact_status}` |"
        if row not in text:
            errors.append(f"{relative_path}: missing source artifact existence ledger row {row}")


def _check_source_of_truth_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in SOURCE_OF_TRUTH_LEDGER_DOCS:
        return

    source_of_truth = payload.get("source_of_truth")
    if not isinstance(source_of_truth, dict):
        errors.append(f"{relative_path}: product-readiness-status.json source_of_truth is not an object")
        return

    for key, artifact in sorted(source_of_truth.items()):
        row = f"| `{key}` | `{artifact}` |"
        if row not in text:
            errors.append(f"{relative_path}: missing source-of-truth ledger row {row}")


def _check_source_of_truth_index(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in SOURCE_OF_TRUTH_DOCS:
        return

    source_of_truth = payload.get("source_of_truth")
    if not isinstance(source_of_truth, dict):
        errors.append("source_of_truth missing or invalid in product-readiness-status.json")
        return

    for key, artifact in sorted(source_of_truth.items()):
        artifact_text = str(artifact)
        if artifact_text not in text:
            errors.append(f"{relative_path} missing source-of-truth artifact {key}: {artifact_text}")


def _check_evidence_status_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in EVIDENCE_STATUS_LEDGER_DOCS:
        return

    evidence = payload.get("last_current_evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{relative_path}: product-readiness-status.json last_current_evidence is not an object")
        return

    for key, value in sorted(evidence.items()):
        row = f"| `{key}` | `{value}` |"
        if row not in text:
            errors.append(f"{relative_path}: missing evidence status ledger row {row}")


def _check_pending_evidence_ledger(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in PENDING_EVIDENCE_LEDGER_DOCS:
        return

    evidence = payload.get("last_current_evidence")
    if not isinstance(evidence, dict):
        errors.append("last_current_evidence missing or invalid in product-readiness-status.json")
        return

    for key, value in sorted(evidence.items()):
        expected_row = f"| `{key}` | `{value}` |"
        if expected_row not in text:
            errors.append(f"{relative_path} missing evidence ledger row: {key}={value}")



def _check_pending_evidence_validation_coverage_ledger(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in PENDING_EVIDENCE_VALIDATION_COVERAGE_LEDGER_DOCS:
        return

    queue = payload.get("pending_validation_queue")
    if not isinstance(queue, list):
        errors.append("pending_validation_queue missing or invalid in product-readiness-status.json")
        return

    for command in map(str, queue):
        row_prefix = f"| `{command}` |"
        if row_prefix not in text:
            errors.append(f"{relative_path} missing pending validation coverage row: {command}")

    required_coverage_phrases = [
        "Machine-readable readiness status",
        "Human-readable readiness docs drift",
        "JSON schema exactness",
        "Backend auth/RBAC/status contracts",
        "Read-only market stream parser behavior",
        "Production stream alerting smoke runner",
        "Production HTTPS smoke runner artifact validation",
        "Multi-trader account-scope smoke runner",
"Production trader repository smoke runner",
        "Frontend TypeScript contract integrity",
        "Frontend production build integrity",
        "Frontend lint/static quality coverage",
        "/trade terminal contract",
        "/market/:symbol market-detail layout",
        "Frontend-visible /api/v2 contract states",
        "Public/trader navigation cleanliness",
        "ProChart realtime merge",
        "Screenshot matrix capture",
        "Full Chromium regression suite",
        "production_https_smoke",
        "full_phase13_visual_review",
        "real_live_trading_approval",
    ]
    lowered_text = text.lower()
    for phrase in required_coverage_phrases:
        if phrase.lower() not in lowered_text:
            errors.append(f"{relative_path} missing pending validation coverage phrase: {phrase}")


def _check_route_status_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in ROUTE_STATUS_LEDGER_DOCS:
        return

    route_status = payload.get("route_status")
    if not isinstance(route_status, dict):
        errors.append(f"{relative_path}: product-readiness-status.json route_status is not an object")
        return

    for route, route_payload in sorted(route_status.items()):
        if not isinstance(route_payload, dict):
            errors.append(f"{relative_path}: route_status.{route} is not an object")
            continue
        row = f"| `{route}` | `{route_payload.get('status', 'UNKNOWN')}` |"
        if row not in text:
            errors.append(f"{relative_path}: missing route status ledger row {row}")


def _check_phase_launch_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in PHASE_LAUNCH_LEDGER_DOCS:
        return

    phase_status = payload.get("phase_status")
    if not isinstance(phase_status, dict):
        errors.append(f"{relative_path}: product-readiness-status.json phase_status is not an object")
    else:
        for phase, expected in sorted(phase_status.items(), key=lambda item: int(item[0])):
            row = f"| `Phase {phase}` | `{expected}` |"
            if row not in text:
                errors.append(f"{relative_path}: missing phase launch ledger row {row}")

    launch_status = payload.get("launch_status")
    if not isinstance(launch_status, dict):
        errors.append(f"{relative_path}: product-readiness-status.json launch_status is not an object")
    else:
        for key, expected in sorted(launch_status.items()):
            row = f"| `{key}` | `{expected}` |"
            if row not in text:
                errors.append(f"{relative_path}: missing phase launch ledger row {row}")


def _check_route_closure_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in ROUTE_CLOSURE_LEDGER_DOCS:
        return

    route_status = payload.get("route_status")
    if not isinstance(route_status, dict):
        errors.append(f"{relative_path}: product-readiness-status.json route_status is not an object")
        return

    for route, route_payload in sorted(route_status.items()):
        if not isinstance(route_payload, dict):
            errors.append(f"{relative_path}: route_status.{route} is not an object")
            continue
        route_state = str(route_payload.get("status", "UNKNOWN"))
        blockers = route_payload.get("blockers")
        if not isinstance(blockers, list) or not blockers:
            row_prefix = f"| `{route}` | `{route_state}` | `NO_BLOCKER_LISTED` |"
            if row_prefix not in text:
                errors.append(f"{relative_path}: missing route closure ledger row prefix {row_prefix}")
            continue
        for blocker in blockers:
            row_prefix = f"| `{route}` | `{route_state}` | `{blocker}` |"
            if row_prefix not in text:
                errors.append(f"{relative_path}: missing route closure ledger row prefix {row_prefix}")


def _check_route_blocker_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in ROUTE_BLOCKER_LEDGER_DOCS:
        return

    route_status = payload.get("route_status")
    if not isinstance(route_status, dict):
        errors.append(f"{relative_path}: product-readiness-status.json route_status is not an object")
        return

    for route, route_payload in sorted(route_status.items()):
        if not isinstance(route_payload, dict):
            errors.append(f"{relative_path}: route_status.{route} is not an object")
            continue
        route_state = str(route_payload.get("status", "UNKNOWN"))
        blockers = route_payload.get("blockers")
        if not isinstance(blockers, list) or not blockers:
            row = f"| `{route}` | `{route_state}` | `NO_BLOCKER_LISTED` |"
            if row not in text:
                errors.append(f"{relative_path}: missing route blocker ledger row {row}")
            continue
        for blocker in blockers:
            row = f"| `{route}` | `{route_state}` | `{blocker}` |"
            if row not in text:
                errors.append(f"{relative_path}: missing route blocker ledger row {row}")


def _check_guardrail_ledger(relative_path: str, text: str, payload: dict[str, Any], errors: list[str]) -> None:
    if relative_path not in GUARDRAIL_LEDGER_DOCS:
        return

    guardrails = payload.get("guardrails")
    if not isinstance(guardrails, dict):
        errors.append(f"{relative_path}: product-readiness-status.json guardrails is not an object")
        return

    for key, expected in sorted(guardrails.items()):
        value = "true" if expected is True else "false" if expected is False else str(expected)
        row = f"| `{key}` | `{value}` |"
        if row not in text:
            errors.append(f"{relative_path}: missing guardrail ledger row {row}")


def _check_history_supersession_ledger(
    relative_path: str,
    text: str,
    payload: dict[str, Any],
    errors: list[str],
) -> None:
    if relative_path not in HISTORY_SUPERSESSION_LEDGER_DOCS:
        return

    evidence = payload.get("last_current_evidence")
    if not isinstance(evidence, dict):
        errors.append(f"{relative_path}: product-readiness-status.json last_current_evidence is not an object")
        return

    current_status = str(evidence.get("trader_exchange_account_scope_normalization_after_latest_changes"))
    row = (
        "| `trader_user_scope_enforcement` | "
        "`exchange_account_scope_requires_paper_account_hardened` | "
        "`trader_exchange_account_scope_normalization_after_latest_changes` | "
        f"`{current_status}` |"
    )
    if row not in text:
        errors.append(f"{relative_path}: missing history supersession row prefix {row}")

    if "trader_id` and `paper_account_id" not in text:
        errors.append(f"{relative_path}: supersession ledger must name current trader_id plus paper_account_id scope")


def _check_history_event_ledger(
    relative_path: str,
    text: str,
    repo_root: Path,
    errors: list[str],
) -> None:
    if relative_path not in HISTORY_EVENT_LEDGER_DOCS:
        return

    history_path = repo_root / "docs" / "product-readiness-status-history.jsonl"
    try:
        history_lines = history_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"missing readiness status history: {history_path}: {exc}")
        return

    for line_number, raw_line in enumerate(history_lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            item = json.loads(line)
        except json.JSONDecodeError as exc:
            errors.append(f"invalid status history JSON on line {line_number}: {exc}")
            continue
        details = item.get("details") if isinstance(item.get("details"), dict) else {}
        ev_key = details.get("evidence_key") if isinstance(details.get("evidence_key"), str) else "NO_EVIDENCE_KEY"
        ev_status = details.get("evidence_status") if isinstance(details.get("evidence_status"), str) else "NO_EVIDENCE_STATUS"
        generated = (
            item.get("generated_at")
            or item.get("timestamp")
            or item.get("generated")
            or item.get("date")
            or "UNKNOWN"
        )
        row = (
            f"| `{line_number}` | `{generated}` | "
            f"`{item.get('event', 'UNKNOWN')}` | `{item.get('status', 'UNKNOWN')}` | "
            f"`{ev_key}` | `{ev_status}` |"
        )
        if row not in text:
            errors.append(f"{relative_path}: missing history event ledger row {row}")


def _check_history_event_monitor_log(
    relative_path: str,
    text: str,
    repo_root: Path,
    errors: list[str],
) -> None:
    if relative_path not in HISTORY_EVENT_LOG_DOCS:
        return

    history_path = repo_root / "docs" / "product-readiness-status-history.jsonl"
    try:
        history_lines = history_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        errors.append(f"missing readiness status history: {history_path}: {exc}")
        return

    for line_number, raw_line in enumerate(history_lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            event = json.loads(line).get("event")
        except json.JSONDecodeError as exc:
            errors.append(f"invalid status history JSON on line {line_number}: {exc}")
            continue
        if not isinstance(event, str) or not event:
            errors.append(f"status history line {line_number} missing event string")
            continue
        if event not in text:
            errors.append(f"{relative_path} missing status-history event slug: {event}")

def _check_docs_to_check_source_of_truth(payload: dict[str, Any], errors: list[str]) -> None:
    source_of_truth = payload.get("source_of_truth")
    if not isinstance(source_of_truth, dict):
        errors.append("source_of_truth missing or invalid in product-readiness-status.json")
        return

    source_paths = set(map(str, source_of_truth.values()))
    missing = sorted(set(DOCS_TO_CHECK).difference(source_paths))
    if missing:
        errors.append(
            "DOCS_TO_CHECK entries missing from source_of_truth: " + ", ".join(missing)
        )


def validate(repo_root: Path) -> list[str]:
    errors: list[str] = []
    payload = _load_json(repo_root / "docs" / "product-readiness-status.json")
    _check_json_status(payload, errors)
    _check_docs_to_check_source_of_truth(payload, errors)

    for relative_path in DOCS_TO_CHECK:
        text = _read_doc(repo_root, relative_path, errors)
        if text:
            _check_doc_text(relative_path, text, errors)
            _check_monitored_route_table(relative_path, text, payload, errors)
            _check_phase_status_table(relative_path, text, payload, errors)
            _check_launch_status_table(relative_path, text, payload, errors)
            _check_current_blocker_key_table(relative_path, text, payload, errors)
            _check_blocker_owner_labels(relative_path, text, errors)
            _check_change_control_status_locks(relative_path, text, payload, errors)
            _check_validation_queue(relative_path, text, payload, errors)
            _check_validation_queue_ledger(relative_path, text, payload, errors)
            _check_source_of_truth_index(relative_path, text, payload, errors)
            _check_blocker_closure_ledger(relative_path, text, payload, errors)
            _check_current_blocker_ledger(relative_path, text, payload, errors)
            _check_status_snapshot_manifest_ledger(relative_path, text, payload, errors)
            _check_source_artifact_existence_ledger(relative_path, text, payload, repo_root, errors)
            _check_source_of_truth_ledger(relative_path, text, payload, errors)
            _check_evidence_status_ledger(relative_path, text, payload, errors)
            _check_pending_evidence_ledger(relative_path, text, payload, errors)
            _check_pending_evidence_validation_coverage_ledger(relative_path, text, payload, errors)
            _check_guardrail_ledger(relative_path, text, payload, errors)
            _check_route_closure_ledger(relative_path, text, payload, errors)
            _check_route_blocker_ledger(relative_path, text, payload, errors)
            _check_phase_launch_ledger(relative_path, text, payload, errors)
            _check_route_status_ledger(relative_path, text, payload, errors)
            _check_history_supersession_ledger(relative_path, text, payload, errors)
            _check_history_event_ledger(relative_path, text, repo_root, errors)
            _check_history_event_monitor_log(relative_path, text, repo_root, errors)

    return errors


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    errors = validate(repo_root)
    if errors:
        print("Readiness docs consistency guard: FAIL", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Readiness docs consistency guard: PASS")
    print("This confirms only human-readable no-PASS consistency, not readiness.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
