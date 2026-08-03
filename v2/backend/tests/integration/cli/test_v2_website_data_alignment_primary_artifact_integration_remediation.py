"""Tests for the V2 website primary artifact integration remediation."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from v2.backend.app.services.security.local_credentials_env_presence import (
    DEFAULT_LOCAL_CREDENTIALS_PATH,
    probe_local_credentials_env_presence,
)
from v2.backend.app.services.website_alignment.primary_artifact_integration_remediation import (
    build_integrated_redis_bridge_contracts,
    build_integrated_website_data_inventory,
    build_integration_status,
    default_paths,
    run_integration_packet,
)


REPO_ROOT = Path(__file__).resolve().parents[5]


def _seed_sidecar(tmp_root: Path) -> None:
    """Copy current sidecar artifacts under tmp_root so the integrator runs."""
    src_dir = (
        REPO_ROOT
        / "claude_worklog/final_readiness/"
        "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest"
    )
    dst_dir = (
        tmp_root
        / "claude_worklog/final_readiness/"
        "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest"
    )
    dst_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "full_route_coverage_inventory.json",
        "corrected_redis_bridge_contracts.json",
    ):
        text = (src_dir / name).read_text(encoding="utf-8")
        (dst_dir / name).write_text(text, encoding="utf-8")


def test_integrated_inventory_carries_all_44_registered_routes(tmp_path: Path):
    _seed_sidecar(tmp_path)
    sidecar = json.loads(
        (tmp_path
         / "claude_worklog/final_readiness/"
         "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest/"
         "full_route_coverage_inventory.json"
         ).read_text(encoding="utf-8")
    )
    inventory = build_integrated_website_data_inventory(sidecar)
    assert inventory["page_count"] >= 40
    assert inventory["registered_route_count"] >= 40
    assert inventory["unknown_route_count"] == 0


def test_integrated_redis_bridge_contracts_have_no_v2_native_for_legacy_keys(
    tmp_path: Path,
):
    _seed_sidecar(tmp_path)
    sidecar = json.loads(
        (tmp_path
         / "claude_worklog/final_readiness/"
         "v2_website_data_alignment_route_coverage_and_bridge_label_remediation/latest/"
         "corrected_redis_bridge_contracts.json"
         ).read_text(encoding="utf-8")
    )
    contracts = build_integrated_redis_bridge_contracts(sidecar)
    by_key = {row["legacy_key"]: row for row in contracts["rows"]}
    # The fixed labels must be bridge, not native.
    assert by_key["signals:trading"]["label"] == "V2_BRIDGE_FROM_LEGACY_REDIS"
    assert by_key["price:*"]["label"] == "V2_BRIDGE_FROM_LEGACY_REDIS"
    # The v2:* siblings must remain native.
    assert by_key["v2:orchestrator:decisions"]["label"] == "V2_NATIVE_PUBLIC_PAYLOAD"
    assert by_key["v2:market:prices:{symbol}"]["label"] == "V2_NATIVE_PUBLIC_PAYLOAD"
    assert contracts["no_v2_native_label_for_legacy_keys"] is True


def test_integration_status_records_before_and_after(tmp_path: Path):
    _seed_sidecar(tmp_path)
    paths = default_paths(tmp_path)
    run_integration_packet(paths)
    status = json.loads(
        (paths.packet_dir / "primary_artifact_integration_status.json").read_text(
            encoding="utf-8"
        )
    )
    assert status["previous_primary_page_count"] == 22
    assert status["previous_primary_signals_trading_label"] == "V2_NATIVE_PUBLIC_PAYLOAD"
    assert status["previous_primary_price_star_label"] == "V2_NATIVE_PUBLIC_PAYLOAD"
    assert status["integrated_primary_page_count"] >= 40
    assert status["integrated_primary_signals_trading_label"] != "V2_NATIVE_PUBLIC_PAYLOAD"
    assert status["integrated_primary_price_star_label"] != "V2_NATIVE_PUBLIC_PAYLOAD"
    assert status["primary_artifact_now_matches_sidecar"] is True
    assert status["stale_primary_payload_remaining"] is False


def test_run_integration_packet_refreshes_primary_artifacts(tmp_path: Path):
    _seed_sidecar(tmp_path)
    paths = default_paths(tmp_path)
    result = run_integration_packet(paths)
    assert result.go_no_go.endswith("READY")
    # Remediation packet artifacts present.
    for required in [
        "GO_NO_GO.md",
        ("V2_WEBSITE_DATA_ALIGNMENT_PRIMARY_ARTIFACT_INTEGRATION_"
         "REMEDIATION_REPORT.md"),
        "primary_artifact_integration_status.json",
        "integrated_website_data_inventory.json",
        "integrated_redis_bridge_contracts.json",
        "integrated_website_page_readiness_matrix.json",
        "operator_dashboard_payload.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    # Primary packet artifacts refreshed.
    primary_inventory = json.loads(
        (paths.primary_packet_dir / "website_data_inventory.json").read_text(
            encoding="utf-8"
        )
    )
    assert primary_inventory["page_count"] >= 40
    primary_contracts = json.loads(
        (paths.primary_packet_dir / "redis_bridge_contracts.json").read_text(
            encoding="utf-8"
        )
    )
    by_key = {row["legacy_key"]: row for row in primary_contracts["rows"]}
    assert by_key["signals:trading"]["label"] != "V2_NATIVE_PUBLIC_PAYLOAD"
    assert by_key["price:*"]["label"] != "V2_NATIVE_PUBLIC_PAYLOAD"


def test_emitted_artifacts_have_no_truthy_approval_or_stale_label(tmp_path: Path):
    _seed_sidecar(tmp_path)
    paths = default_paths(tmp_path)
    run_integration_packet(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"frontend_does_not_read_redis_directly": false',
        '"no_v2_native_label_for_legacy_keys": false',
        '"every_registered_route_has_inventory_entry": false',
        '"stale_primary_payload_remaining": true',
        # Specifically guard against the pre-remediation mislabel.
        '"legacy_key": "signals:trading", "label": "V2_NATIVE_PUBLIC_PAYLOAD"',
        '"legacy_key": "price:*", "label": "V2_NATIVE_PUBLIC_PAYLOAD"',
    ]
    for f in (
        list(paths.packet_dir.rglob("*"))
        + list(paths.primary_packet_dir.rglob("*"))
        + list(paths.primary_public_dir.rglob("*"))
    ):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"


# ---------------------------------------------------------------------------
# Secret loader presence-only tests
# ---------------------------------------------------------------------------


def test_local_credentials_loader_returns_names_only_for_synthetic_file(
    tmp_path: Path,
):
    target = tmp_path / DEFAULT_LOCAL_CREDENTIALS_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        "# comment line\n"
        "export FOO_API_KEY=sample_value_that_must_not_leak\n"
        "BAR_TOKEN=second_sample_value\n"
        "MALFORMED=\n"
        "\n",
        encoding="utf-8",
    )
    result = probe_local_credentials_env_presence(tmp_path)
    assert result.file_present is True
    assert result.raw_secret_value_read_or_emitted is False
    names = set(result.present_var_names)
    assert names == {"FOO_API_KEY", "BAR_TOKEN", "MALFORMED"}
    # No value substrings appear anywhere in the dataclass repr.
    text = repr(result)
    assert "sample_value_that_must_not_leak" not in text
    assert "second_sample_value" not in text


def test_local_credentials_loader_returns_missing_when_file_absent(tmp_path: Path):
    # Default repo_root with no .local_secrets dir present.
    result = probe_local_credentials_env_presence(tmp_path)
    assert result.file_present is False
    assert result.present_var_names == ()
    assert result.raw_secret_value_read_or_emitted is False
