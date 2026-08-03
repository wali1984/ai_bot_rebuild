"""Tests for the V2 startup-manifest role coverage remediation."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.native_runtime_migration.startup_role_coverage_remediation import (
    build_refreshed_v2_paper_startup_manifest_status,
    build_startup_manifest_role_coverage_status,
    default_paths,
    run_remediation_packet,
)
from v2.backend.app.services.native_runtime_migration.v2_paper_startup_manifest import (
    VALID_STATUSES,
)


REPO_ROOT = Path(__file__).resolve().parents[5]


def test_canonical_role_coverage_includes_all_38_canonical_roles():
    coverage = build_startup_manifest_role_coverage_status(REPO_ROOT)
    assert coverage["canonical_manifest_role_count"] == 38
    assert coverage["v2_runtime_role_count"] == 38
    assert coverage["missing_role_count"] == 0
    assert coverage["every_canonical_role_represented"] is True


def test_every_role_carries_required_fields_and_valid_status():
    coverage = build_startup_manifest_role_coverage_status(REPO_ROOT)
    required_fields = (
        "legacy_service_id",
        "legacy_command",
        "startup_phase",
        "criticality",
        "live_risk",
        "v2_equivalent",
        "v2_status",
        "bridge_label_required",
        "old_redis_write_allowed",
        "exchange_mutation_allowed",
        "blocks_paper",
        "blocks_production_equivalence",
        "blocks_shutdown",
        "blocks_live",
        "next_action",
    )
    for row in coverage["rows"]:
        for f in required_fields:
            assert f in row, (row["legacy_service_id"], f)
        assert row["v2_status"] in VALID_STATUSES
        assert row["old_redis_write_allowed"] is False
        assert row["exchange_mutation_allowed"] is False
    assert coverage["every_role_has_valid_status"] is True


def test_previously_missing_roles_are_now_represented():
    coverage = build_startup_manifest_role_coverage_status(REPO_ROOT)
    by_id = {r["legacy_service_id"]: r for r in coverage["rows"]}
    for needed in (
        "vpn_monitor",
        "system_telegram_monitor",
        "monitor_system_memory",
        "scripts_memory_monitor",
        "ingest_live_coinank_global_aggregator",
        "ingest_liquidation_bridge",
        "ingest_liquidation_levels_engine",
        "ingest_live_coinapi_v1",
        "process_listing_and_resource_report",
        "telegram_completion_notification",
    ):
        assert needed in by_id, needed


def test_bridge_roles_not_labelled_v2_native_service_active():
    coverage = build_startup_manifest_role_coverage_status(REPO_ROOT)
    by_id = {r["legacy_service_id"]: r for r in coverage["rows"]}
    # Trainer + per-symbol CoinAnk stay bridge; CoinAnk global now has an
    # active V2 read-only service.
    assert by_id["rl_hybrid_trainer"]["v2_status"] == "V2_BRIDGE_READ_ONLY"
    assert by_id["ingest_live_coinank"]["v2_status"] == "V2_BRIDGE_READ_ONLY"
    assert by_id["ingest_live_coinank_global_aggregator"]["v2_status"] == (
        "V2_SERVICE_ACTIVE"
    )


def test_refreshed_runtime_status_role_count_matches_canonical():
    coverage = build_startup_manifest_role_coverage_status(REPO_ROOT)
    refreshed = build_refreshed_v2_paper_startup_manifest_status(REPO_ROOT, coverage)
    assert refreshed["role_count"] == coverage["canonical_manifest_role_count"]
    assert len(refreshed["roles"]) == coverage["canonical_manifest_role_count"]
    assert refreshed["every_canonical_role_represented"] is True
    assert refreshed["missing_role_count"] == 0
    for row in refreshed["roles"]:
        assert row["legacy_service_id"]
        assert row["status"] in VALID_STATUSES
        assert row["old_redis_write_allowed"] is False
        assert row["exchange_mutation_allowed"] is False


def test_run_remediation_packet_emits_all_required_artifacts(tmp_path: Path):
    # Need the canonical manifest under tmp_path; copy from real repo.
    src = (
        REPO_ROOT
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_startup_manifest.json"
    )
    dst = (
        tmp_path
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_startup_manifest.json"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")

    paths = default_paths(tmp_path)
    result = run_remediation_packet(paths)
    assert result.go_no_go == (
        "V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_REMEDIATION_READY"
    )
    for required in [
        "GO_NO_GO.md",
        ("V2_FULL_PAPER_ONLY_STARTUP_MANIFEST_ROLE_COVERAGE_"
         "REMEDIATION_REPORT.md"),
        "startup_manifest_role_coverage_status.json",
        "refreshed_v2_paper_startup_manifest_status.json",
        "refreshed_paper_runtime_process_status.json",
        "operator_dashboard_payload.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    # Primary packet refreshed too.
    assert (
        paths.primary_packet_dir / "v2_paper_startup_manifest_status.json"
    ).exists()
    assert (
        paths.primary_public_dir / "v2_paper_startup_manifest_status.json"
    ).exists()


def test_emitted_artifacts_have_no_truthy_approval_tokens(tmp_path: Path):
    src = (
        REPO_ROOT
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_startup_manifest.json"
    )
    dst = (
        tmp_path
        / "claude_worklog/final_readiness/"
        "v2_legacy_startup_manifest_parity_and_bridge_exit/latest/"
        "legacy_startup_manifest.json"
    )
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(src.read_text(encoding="utf-8"), encoding="utf-8")
    paths = default_paths(tmp_path)
    run_remediation_packet(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"old_redis_write_allowed": true',
        '"exchange_mutation_allowed": true',
        '"every_canonical_role_represented": false',
        '"every_role_has_valid_status": false',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.primary_packet_dir.rglob("*")) + list(paths.primary_public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
