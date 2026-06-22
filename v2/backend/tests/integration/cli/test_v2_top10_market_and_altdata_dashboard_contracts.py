"""Tests for top-10 market and alternative-data dashboard contracts."""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def _contracts():
    return importlib.import_module(
        "v2.backend.app.services.alternative_data.top10_dashboard_contracts"
    )


def _cli():
    return importlib.import_module(
        "v2.backend.app.cli.v2_top10_market_and_altdata_dashboard_contracts"
    )


EXPECTED_IDS = [
    "binance_spot_12h_volume_leaders",
    "binance_futures_12h_volume_leaders",
    "binance_spot_12h_most_traded",
    "binance_futures_12h_most_traded",
    "binance_spot_12h_volatility_leaders",
    "binance_futures_12h_volatility_leaders",
    "liquidation_tape_top_symbols",
    "funding_oi_movers",
    "nansen_smart_money_top_symbols",
    "lunarcrush_social_momentum_top_symbols",
]


def test_exact_top10_dashboard_ids_and_order() -> None:
    payload = _contracts().build_top10_dashboard_contracts(env={})
    assert payload["dashboard_count"] == 10
    assert [row["id"] for row in payload["dashboards"]] == EXPECTED_IDS


def test_binance_contracts_use_12h_v2_market_rules() -> None:
    payload = _contracts().build_top10_dashboard_contracts(env={})
    rows = {row["id"]: row for row in payload["dashboards"]}
    for panel_id in EXPECTED_IDS[:6]:
        row = rows[panel_id]
        assert row["enabled"] is True
        assert "12h" in row["data_source_rule"]
        assert any(src.startswith("v2:market:") for src in row["primary_v2_sources"])
        assert "missing_source" in row["required_fields"]
        assert "stale_flag" in row["required_fields"]
    assert rows["binance_spot_12h_volume_leaders"]["market_type"] == "spot"
    assert rows["binance_futures_12h_volume_leaders"]["market_type"] == "futures"


def test_altdata_dashboards_disabled_with_present_keys_until_clients_pass(
    monkeypatch,
) -> None:
    payload = _contracts().build_top10_dashboard_contracts(
        env={
            "NANSEN_API_KEY": "raw_nansen_value",
            "LUNARCRUSH_API_KEY": "raw_lunar_value",
        }
    )
    body = json.dumps(payload)
    assert "raw_nansen_value" not in body
    assert "raw_lunar_value" not in body
    rows = {row["id"]: row for row in payload["dashboards"]}
    for panel_id in (
        "nansen_smart_money_top_symbols",
        "lunarcrush_social_momentum_top_symbols",
    ):
        row = rows[panel_id]
        assert row["enabled"] is False
        assert row["empty_until_provider_client_codex_pass"] is True
        assert row["provider_client_codex_pass_required"] is True
        assert row["provider_key_present"] is True
        assert row["disabled_reason"] == "KEY_PRESENT_NO_CLIENT_YET"
        assert row["credential_value"] == "NEVER"
        assert row["may_not_override_strict_paper_fill_gate"] is True
        assert row["may_not_authorize_live_or_canary"] is True
        assert row["may_not_place_orders"] is True


def test_altdata_dashboards_report_missing_source_when_keys_absent(
    tmp_path: Path, monkeypatch
) -> None:
    monkeypatch.chdir(tmp_path)
    payload = _contracts().build_top10_dashboard_contracts(env={})
    rows = {row["id"]: row for row in payload["dashboards"]}
    assert rows["nansen_smart_money_top_symbols"]["disabled_reason"] == "MISSING_SOURCE"
    assert rows["lunarcrush_social_momentum_top_symbols"]["disabled_reason"] == "MISSING_SOURCE"


def test_payload_safety_invariants() -> None:
    payload = _contracts().build_top10_dashboard_contracts(env={})
    assert payload["provider_clients_implemented"] is False
    assert payload["provider_network_calls_attempted"] is False
    assert payload["alternative_data_dashboards_enabled"] is False
    assert payload["raw_values_exposed"] is False
    assert payload["paid_tier_enabled"] is False
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False
    assert payload["may_not_override_strict_paper_fill_gate"] is True
    assert payload["writes_old_redis"] is False
    assert payload["exchange_mutation"] is False
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False


def test_run_once_writes_required_artifacts(tmp_path: Path, monkeypatch) -> None:
    cli = _cli()
    monkeypatch.setattr(cli, "WORKLOG_CONTRACTS", tmp_path / "work/top10_dashboard_contracts.json")
    monkeypatch.setattr(cli, "WORKLOG_REPORT", tmp_path / "work/TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS.md")
    monkeypatch.setattr(cli, "WORKLOG_GO_NO_GO", tmp_path / "work/GO_NO_GO.md")
    monkeypatch.setattr(cli, "PUBLIC_PAYLOAD", tmp_path / "public/operator_dashboard_payload.json")
    payload = cli.run_once()
    assert payload["go_no_go"] == "V2_TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS_READY"
    contracts = json.loads((tmp_path / "work/top10_dashboard_contracts.json").read_text())
    public = json.loads((tmp_path / "public/operator_dashboard_payload.json").read_text())
    assert contracts["dashboard_count"] == 10
    assert public["dashboard_ids"] == EXPECTED_IDS
    assert (tmp_path / "work/GO_NO_GO.md").read_text().strip() == payload["go_no_go"]
    assert "GO/NO-GO" in (tmp_path / "work/TOP10_MARKET_AND_ALTDATA_DASHBOARD_CONTRACTS.md").read_text()


def test_no_torch_network_or_exchange_clients_imported() -> None:
    for name in ("torch", "requests", "httpx", "aiohttp", "websockets", "ccxt"):
        sys.modules.pop(name, None)
    importlib.import_module("v2.backend.app.services.alternative_data.top10_dashboard_contracts")
    importlib.import_module("v2.backend.app.cli.v2_top10_market_and_altdata_dashboard_contracts")
    for name in ("torch", "requests", "httpx", "aiohttp", "websockets", "ccxt"):
        assert name not in sys.modules
