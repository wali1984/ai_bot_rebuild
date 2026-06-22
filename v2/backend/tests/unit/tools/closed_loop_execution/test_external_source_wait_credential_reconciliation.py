"""Tests for external-source wait credential-name reconciliation."""

from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[6]
TOOLS_DIR = REPO_ROOT / "claude_worklog" / "tools"


def _load_module():
    sys.path.insert(0, str(TOOLS_DIR))
    try:
        sys.modules.pop("v2_external_source_wait_credential_reconciliation", None)
        return importlib.import_module("v2_external_source_wait_credential_reconciliation")
    finally:
        try:
            sys.path.remove(str(TOOLS_DIR))
        except ValueError:
            pass


def _write_external_packet(path: Path, families: list[str]) -> None:
    path.write_text(
        json.dumps(
            {
                "items": [
                    {
                        "blocker_id": "full_observation_builder.external_sources",
                        "source_families": families,
                        "source_requirement": "operator must approve external source",
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_scans_names_only_and_does_not_expose_raw_values(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    secret_file = tmp_path / "live_credentials.env"
    secret_file.write_text(
        "export TOKEN_METRICS_API_KEY=raw-token-value-must-not-appear\n"
        "GLASSNODE_KEY = another-raw-value-must-not-appear\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(mod, "LOCAL_SECRET_FILES", (secret_file,))
    index = mod.build_name_presence_index()
    rendered = json.dumps(index)
    assert "TOKEN_METRICS_API_KEY" in rendered
    assert "GLASSNODE_KEY" in rendered
    assert "raw-token-value-must-not-appear" not in rendered
    assert "another-raw-value-must-not-appear" not in rendered
    assert index["raw_values_read"] is False
    assert index["raw_values_printed"] is False


def test_alias_mapping_marks_provider_present_by_name(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    secret_file = tmp_path / "legacy.env"
    secret_file.write_text("TOKEN_METRICS_API_KEY=raw-value-must-not-appear\n", encoding="utf-8")
    packet = tmp_path / "external_packet.json"
    matrix = tmp_path / "matrix.json"
    _write_external_packet(packet, ["unified_feature_family.token_metrics"])
    matrix.write_text('{"matrix": []}', encoding="utf-8")
    monkeypatch.setattr(mod, "LOCAL_SECRET_FILES", (secret_file,))
    monkeypatch.setattr(mod, "EXTERNAL_PACKET", packet)
    monkeypatch.setattr(mod, "FAMILY_MATRIX", matrix)
    name_index = mod.build_name_presence_index()
    reconciliation, _, _ = mod.reconcile_sources(name_index, seed_tasks=False)
    family = reconciliation["items"][0]["family_rows"][0]
    provider = family["provider_rows"][0]
    assert family["key_present_by_name"] is True
    assert provider["provider"] == "tokenmetrics"
    assert provider["present_env_alias_names"] == ["TOKEN_METRICS_API_KEY"]
    assert "raw-value-must-not-appear" not in json.dumps(reconciliation)


def test_key_present_client_missing_seeds_safe_task(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    secret_file = tmp_path / "legacy_config.py"
    secret_file.write_text("GLASSNODE_KEY = 'raw-value-must-not-appear'\n", encoding="utf-8")
    packet = tmp_path / "external_packet.json"
    matrix = tmp_path / "matrix.json"
    _write_external_packet(packet, ["onchain_btc"])
    matrix.write_text('{"matrix": []}', encoding="utf-8")
    calls: list[tuple[str, str]] = []

    def fake_seed(provider: str, source_family: str):
        calls.append((provider, source_family))
        return {
            "seeded": True,
            "status": "NEW_PAIRED_TASKS_SEEDED",
            "implementation_task_id": "impl",
            "codex_review_task_id": "review",
        }

    monkeypatch.setattr(mod, "LOCAL_SECRET_FILES", (secret_file,))
    monkeypatch.setattr(mod, "EXTERNAL_PACKET", packet)
    monkeypatch.setattr(mod, "FAMILY_MATRIX", matrix)
    monkeypatch.setattr(mod, "seed_provider_adapter_task_if_safe", fake_seed)
    name_index = mod.build_name_presence_index()
    reconciliation, provider_gaps, seed_status = mod.reconcile_sources(name_index, seed_tasks=True)
    assert ("glassnode", "onchain_btc") in calls
    assert "glassnode" in provider_gaps["providers_with_key_present_client_missing"]
    assert seed_status["seeded_or_referenced_count"] == 1
    assert reconciliation["items"][0]["family_rows"][0]["classification"] == (
        "SOURCE_KEY_PRESENT_CLIENT_MISSING_TASK_SEEDED_OR_REFERENCED"
    )


def test_missing_key_is_operator_required_and_paid_feed_gated(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    packet = tmp_path / "external_packet.json"
    matrix = tmp_path / "matrix.json"
    _write_external_packet(packet, ["onchain_eth"])
    matrix.write_text('{"matrix": []}', encoding="utf-8")
    monkeypatch.setattr(mod, "LOCAL_SECRET_FILES", (tmp_path / "missing.env",))
    monkeypatch.setattr(mod, "EXTERNAL_PACKET", packet)
    monkeypatch.setattr(mod, "FAMILY_MATRIX", matrix)
    name_index = mod.build_name_presence_index()
    reconciliation, _, seed_status = mod.reconcile_sources(name_index, seed_tasks=True)
    family = reconciliation["items"][0]["family_rows"][0]
    assert family["classification"] == "SOURCE_MISSING_KEY_OPERATOR_REQUIRED"
    assert family["paid_tier_operator_gated"] is True
    assert seed_status["seeded_or_referenced_count"] == 0


def test_run_outputs_safe_dashboard_without_fake_completion(tmp_path, monkeypatch) -> None:
    mod = _load_module()
    packet = tmp_path / "external_packet.json"
    matrix = tmp_path / "matrix.json"
    _write_external_packet(packet, ["unified_feature_family.token_metrics"])
    matrix.write_text('{"matrix": []}', encoding="utf-8")
    monkeypatch.setattr(mod, "LOCAL_SECRET_FILES", (tmp_path / "missing.env",))
    monkeypatch.setattr(mod, "EXTERNAL_PACKET", packet)
    monkeypatch.setattr(mod, "FAMILY_MATRIX", matrix)
    monkeypatch.setattr(mod, "WORKLOG_DIR", tmp_path / "worklog")
    monkeypatch.setattr(mod, "PUBLIC_DIR", tmp_path / "public")
    status = mod.run_once(seed_tasks=False)
    rendered = json.dumps(json.loads((tmp_path / "worklog" / "operator_dashboard_payload.json").read_text()))
    assert status["go_no_go"] == mod.GO_READY
    assert status["live_gate"] == "blocked_human_only"
    assert status["live_symbols"] == []
    assert status["approves_live"] is False
    assert status["paid_feed_activation_attempted"] is False
    assert status["external_source_marked_complete_without_payload_count"] == 0
    assert "raw_key_values_exposed" in rendered
