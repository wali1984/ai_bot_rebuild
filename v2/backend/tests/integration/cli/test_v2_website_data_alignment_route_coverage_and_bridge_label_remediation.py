"""Tests for the V2 website alignment route-coverage + bridge-label
remediation packet."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.report_center.report_registry import LANES
from v2.backend.app.services.website_alignment.route_coverage_and_bridge_label_remediation import (
    LABEL_LEGACY_REFERENCE_ONLY,
    LABEL_PLACEHOLDER_NOT_READY,
    LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
    LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    build_corrected_redis_bridge_contracts,
    build_full_route_coverage_inventory,
    build_report_center_lane_spec,
    default_paths,
    run_remediation_packet,
    scan_registered_routes,
)


REPO_ROOT = Path(__file__).resolve().parents[5]


def test_scanner_finds_all_registered_frontend_routes():
    routes = scan_registered_routes(REPO_ROOT)
    # The current frontend exposes 44 unique routes per Codex finding.
    assert len(routes) >= 40, f"only {len(routes)} routes scanned"


def test_full_inventory_covers_every_registered_route():
    inv = build_full_route_coverage_inventory(REPO_ROOT)
    assert inv["registered_route_count"] >= 40
    assert inv["every_registered_route_has_inventory_entry"] is True
    # Every entry must carry one of the four canonical labels.
    allowed = {
        LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
        LABEL_LEGACY_REFERENCE_ONLY,
        LABEL_PLACEHOLDER_NOT_READY,
    }
    for p in inv["pages"]:
        assert p["source_label"] in allowed, p


def test_corrected_redis_bridge_contracts_relabel_legacy_streams():
    contracts = build_corrected_redis_bridge_contracts()
    by_key = {row["legacy_key"]: row for row in contracts["rows"]}
    # signals:trading and price:* must NOT be V2_NATIVE.
    assert by_key["signals:trading"]["label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    assert by_key["price:*"]["label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    # The V2-native equivalents must be present as separate rows.
    assert by_key["v2:orchestrator:decisions"]["label"] == LABEL_V2_NATIVE_PUBLIC_PAYLOAD
    assert by_key["v2:market:prices:{symbol}"]["label"] == LABEL_V2_NATIVE_PUBLIC_PAYLOAD
    assert contracts["no_v2_native_label_for_legacy_keys"] is True


def test_no_legacy_key_is_labelled_v2_native_public_payload():
    contracts = build_corrected_redis_bridge_contracts()
    for row in contracts["rows"]:
        if row["legacy_key"].startswith("v2:"):
            continue
        assert row["label"] != LABEL_V2_NATIVE_PUBLIC_PAYLOAD, row


def test_report_center_lane_spec_describes_required_lane():
    spec = build_report_center_lane_spec()
    assert spec["lane_id"] == "v2_website_data_alignment_and_control_plane"
    assert spec["owner"] == "CLAUDE"
    assert spec["blocks_production_equivalence"] is True
    assert spec["registry_already_inserted"] is True


def test_report_center_registry_now_contains_website_alignment_lane():
    lane_ids = {l.lane_id for l in LANES}
    assert "v2_website_data_alignment_and_control_plane" in lane_ids
    assert "v2_full_paper_only_startup_manifest_runtime" in lane_ids


def test_run_remediation_packet_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_remediation_packet(paths)
    assert result.go_no_go.endswith("READY")
    for required in [
        "GO_NO_GO.md",
        ("V2_WEBSITE_DATA_ALIGNMENT_ROUTE_COVERAGE_AND_BRIDGE_LABEL_"
         "REMEDIATION_REPORT.md"),
        "full_route_coverage_inventory.json",
        "corrected_redis_bridge_contracts.json",
        "report_center_lane_spec.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()


def test_emitted_artifacts_have_no_truthy_approval_or_v2_native_label_for_legacy(
    tmp_path: Path,
):
    paths = default_paths(tmp_path)
    run_remediation_packet(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"no_v2_native_label_for_bridge_data": false',
        '"frontend_does_not_read_redis_directly": false',
        '"no_v2_native_label_for_legacy_keys": false',
        '"every_registered_route_has_inventory_entry": false',
        # Specifically guard against the previous packet's mislabel.
        '"legacy_key": "signals:trading", "label": "V2_NATIVE_PUBLIC_PAYLOAD"',
        '"legacy_key": "price:*", "label": "V2_NATIVE_PUBLIC_PAYLOAD"',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
