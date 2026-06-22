"""Tests for the V2 website data alignment + control-plane planner."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.website_alignment.website_data_alignment import (
    LABEL_LEGACY_REFERENCE_ONLY,
    LABEL_PLACEHOLDER_NOT_READY,
    LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
    LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
    LIVE_GATE_BLOCKED,
    build_deployed_dashboard_verification,
    build_future_data_placeholders,
    build_prediction_key_resolution_status,
    build_redis_bridge_contracts,
    build_website_control_plane_future_contract,
    build_website_data_inventory,
    build_website_page_contracts,
    build_website_page_readiness_matrix,
    default_paths,
    run_website_alignment_packet,
)


# ---------------------------------------------------------------------------
# Phase 1 - data inventory
# ---------------------------------------------------------------------------


def test_website_data_inventory_covers_required_operator_pages():
    inv = build_website_data_inventory()
    page_ids = {p["page_id"] for p in inv["pages"]}
    for required in (
        "public_landing",
        "markets",
        "status",
        "ai_brain",
        "trader",
        "history",
        "mission_control",
        "report_center",
        "risk_control",
        "config_admin",
        "paper_trading",
        "exchange_manager",
        "signals",
        "market_intelligence",
        "positions",
        "system_health",
        "top_10_dashboards",
        "alt_data_candidate_publisher",
        "replay_edge_proof",
        "startup_parity_bridge_exit",
        "dynamic_symbol_coverage",
    ):
        assert required in page_ids, required


def test_website_data_inventory_uses_only_valid_source_labels():
    inv = build_website_data_inventory()
    allowed = {
        LABEL_V2_NATIVE_PUBLIC_PAYLOAD,
        LABEL_V2_BRIDGE_FROM_LEGACY_REDIS,
        LABEL_LEGACY_REFERENCE_ONLY,
        LABEL_PLACEHOLDER_NOT_READY,
    }
    for page in inv["pages"]:
        assert page["source_label"] in allowed, page


def test_bridge_pages_are_labeled_bridge_not_native():
    inv = build_website_data_inventory()
    by_id = {p["page_id"]: p for p in inv["pages"]}
    # AI Brain shows prediction from bridge, must be labeled bridge.
    assert by_id["ai_brain"]["source_label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    # Market Intelligence pulls CoinAnk via bridge, must be labeled bridge.
    assert by_id["market_intelligence"]["source_label"] == (
        LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    )


# ---------------------------------------------------------------------------
# Phase 2 - Redis bridge contracts
# ---------------------------------------------------------------------------


def test_redis_bridge_contracts_marks_prediction_and_coinank_as_bridge():
    contracts = build_redis_bridge_contracts()
    by_key = {row["legacy_key"]: row for row in contracts["contracts"]}
    assert by_key["prediction:*"]["label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    assert by_key["coinank:*"]["label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    assert contracts["frontend_does_not_read_redis_directly"] is True


def test_prediction_key_resolution_status_says_not_native_yet():
    status = build_prediction_key_resolution_status()
    assert status["current_source_label"] == LABEL_V2_BRIDGE_FROM_LEGACY_REDIS
    assert status["native_publisher_status"] == "CONTRACT_DEFINED_NOT_IMPLEMENTED"
    assert status["operator_decision_required_before_promotion"] is True


def test_website_page_contracts_blocks_direct_redis_reads():
    contracts = build_website_page_contracts()
    for row in contracts["rows"]:
        assert row["frontend_does_not_read_redis_directly"] is True
    assert contracts["no_v2_native_label_for_bridge_data"] is True


# ---------------------------------------------------------------------------
# Phase 3 - readiness matrix
# ---------------------------------------------------------------------------


def test_page_readiness_matrix_carries_no_enabled_controls(tmp_path: Path):
    matrix = build_website_page_readiness_matrix(tmp_path)
    for row in matrix["rows"]:
        assert row["controls_present"] is False
        assert row["live_controls_present"] is False
        assert row["shutdown_controls_present"] is False
        assert row["adopt_controls_present"] is False
    summary = matrix["summary"]
    assert summary["total_pages"] >= 20


# ---------------------------------------------------------------------------
# Phase 4 - future placeholders
# ---------------------------------------------------------------------------


def test_future_data_placeholders_includes_required_items():
    placeholders = build_future_data_placeholders()
    ids = {p["id"] for p in placeholders["placeholders"]}
    for needed in (
        "native_trainer_predictions",
        "dynamic_25_symbol_ohlcv",
        "dynamic_25_symbol_orderbook",
        "dynamic_ta_features",
        "model_policy_readiness",
        "checkpoint_readiness",
        "edge_proof_thresholds",
        "canary_eligibility",
        "live_readiness_gate",
        "account_exchange_permission_state",
        "paid_external_sources",
        "arkham_future",
    ):
        assert needed in ids, needed
    assert placeholders["none_used_for_live"] is True


# ---------------------------------------------------------------------------
# Phase 5 - deployed dashboard verification (honest stub)
# ---------------------------------------------------------------------------


def test_dashboard_verification_records_failure_honestly_when_probe_fails():
    def failing_probe(url):
        return {
            "url": url,
            "reachable": False,
            "status_code": None,
            "error_class": "URLError",
            "error_message": "simulated_network_failure",
            "stale_or_failure_reason": "DASHBOARD_FETCH_FAILED",
        }

    verification = build_deployed_dashboard_verification(probe_fn=failing_probe)
    assert verification["all_reachable"] is False
    assert verification["any_failed"] is True
    for probe in verification["probes"]:
        assert probe["reachable"] is False
        assert probe["stale_or_failure_reason"] == "DASHBOARD_FETCH_FAILED"
    assert verification["claim_deployed_success_if_fetch_fails"] is False


def test_dashboard_verification_records_success_when_probe_passes():
    def ok_probe(url):
        return {
            "url": url,
            "reachable": True,
            "status_code": 200,
            "cloudflare_proxy": True,
            "content_type": "text/html; charset=utf-8",
            "visible_text_head": "<!doctype html>",
            "fetched_bytes": 16,
        }

    verification = build_deployed_dashboard_verification(probe_fn=ok_probe)
    assert verification["all_reachable"] is True
    assert verification["any_failed"] is False


# ---------------------------------------------------------------------------
# Phase 6 - control-plane future contract
# ---------------------------------------------------------------------------


def test_control_plane_future_contract_keeps_all_controls_disabled():
    contract = build_website_control_plane_future_contract()
    for c in contract["controls"]:
        assert c["current_enabled"] is False
        assert c["operator_required"] is True
        assert c["codex_review_required"] is True
        assert c["not_available_in_phase_1"] is True
        assert c["rendered_now"] is False
    assert contract["any_control_enabled"] is False
    assert contract["any_control_rendered_now"] is False


# ---------------------------------------------------------------------------
# End-to-end
# ---------------------------------------------------------------------------


def _ok_probe(url):
    return {
        "url": url,
        "reachable": True,
        "status_code": 200,
        "cloudflare_proxy": True,
        "content_type": "text/html",
        "visible_text_head": "<!doctype html>",
        "fetched_bytes": 16,
    }


def test_run_website_alignment_packet_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_website_alignment_packet(paths, probe_fn=_ok_probe)
    assert result.go_no_go == "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_READY"
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go
    for required in [
        "V2_WEBSITE_DATA_ALIGNMENT_AND_CONTROL_PLANE_REPORT.md",
        "website_data_inventory.json",
        "redis_bridge_contracts.json",
        "prediction_key_resolution_status.json",
        "website_page_contracts.json",
        "website_page_readiness_matrix.json",
        "future_data_placeholders.json",
        "deployed_dashboard_verification.json",
        "website_control_plane_future_contract.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    for public_required in [
        "operator_dashboard_payload.json",
        "deployed_dashboard_verification.json",
        "website_data_inventory.json",
        "website_page_readiness_matrix.json",
        "website_control_plane_future_contract.json",
    ]:
        assert (paths.public_dir / public_required).exists(), public_required


def test_emitted_artifacts_have_no_truthy_approval_or_enabled_controls(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_website_alignment_packet(paths, probe_fn=_ok_probe)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"did_not_enable_any_control": false',
        '"did_not_render_live_or_order_or_shutdown_or_adopt_button": false',
        '"frontend_does_not_read_redis_directly": false',
        '"no_v2_native_label_for_bridge_data": false',
        '"any_control_enabled": true',
        '"current_enabled": true',
        '"rendered_now": true',
        '"claim_deployed_success_if_fetch_fails": true',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
