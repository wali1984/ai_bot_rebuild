"""Tests for the V2-native dynamic ingestor runtime + 25-symbol expansion."""
from __future__ import annotations

import json
from pathlib import Path

from v2.backend.app.services.native_dynamic_runtime.dynamic_runtime import (
    KNOWN_UNIVERSE,
    TIMEFRAMES,
    V2_NATIVE_ACTIVE_SYMBOLS,
    build_operator_dashboard_payload,
    build_phase_1_binance_ohlcv,
    build_phase_2_binance_orderbook,
    build_phase_3_feature_pipeline_expansion,
    build_phase_4_ta_dynamic_service,
    build_phase_5_coverage_and_refresh,
    default_paths,
    run_dynamic_runtime_packet,
)
from v2.backend.app.services.native_runtime_migration.contracts import (
    FRESHNESS_FRESH,
    SOURCE_V2_NATIVE,
)
from v2.backend.app.services.native_runtime_migration.safety import (
    LIVE_GATE_BLOCKED,
)


def test_phase_1_ohlcv_contract_is_disabled_and_no_credentials():
    p = build_phase_1_binance_ohlcv()
    assert p["client_contract"]["enabled"] is False
    assert p["client_contract"]["live_network_feed_started"] is False
    assert p["client_contract"]["auth_required"] is False
    assert p["client_contract"]["credential_env_var_name"] is None
    assert p["client_contract"]["order_endpoints_forbidden"] is True
    # 25 symbols * 4 timeframes envelopes.
    assert p["per_symbol_envelope_count"] == len(KNOWN_UNIVERSE) * len(TIMEFRAMES)
    # No envelope marks bridge data as V2_NATIVE because no V2-native
    # OHLCV exists yet.
    for env in p["per_symbol_envelopes"]:
        assert env["source_label"] != SOURCE_V2_NATIVE


def test_phase_2_orderbook_contract_disabled():
    p = build_phase_2_binance_orderbook()
    assert p["client_contract"]["enabled"] is False
    assert p["client_contract"]["live_network_feed_started"] is False
    assert p["per_symbol_envelope_count"] == len(KNOWN_UNIVERSE)
    for env in p["per_symbol_envelopes"]:
        assert env["source_label"] != SOURCE_V2_NATIVE


def test_phase_3_feature_pipeline_native_only_for_active_symbols():
    p = build_phase_3_feature_pipeline_expansion()
    for env in p["per_symbol_envelopes"]:
        if env["symbol"] in V2_NATIVE_ACTIVE_SYMBOLS:
            assert env["source_label"] == SOURCE_V2_NATIVE
            assert env["freshness_state"] == FRESHNESS_FRESH
        else:
            assert env["source_label"] != SOURCE_V2_NATIVE
    assert p["btc_eth_sol_regression_protected"] is True


def test_phase_4_ta_native_only_for_active_symbols():
    p = build_phase_4_ta_dynamic_service()
    for env in p["per_symbol_envelopes"]:
        if env["symbol"] in V2_NATIVE_ACTIVE_SYMBOLS:
            assert env["source_label"] == SOURCE_V2_NATIVE
        else:
            assert env["source_label"] != SOURCE_V2_NATIVE


def test_phase_5_coverage_table_lists_all_symbols_and_families(tmp_path: Path):
    p = build_phase_5_coverage_and_refresh(tmp_path)
    assert set(p["universe"]) == set(KNOWN_UNIVERSE)
    table = p["per_family_table"]
    assert set(table.keys()) == set(KNOWN_UNIVERSE)
    families = p["families"]
    for sym in KNOWN_UNIVERSE:
        assert set(table[sym].keys()) == set(families)
        # Active symbols must show V2_NATIVE_ACTIVE on price/ta/features
        if sym in V2_NATIVE_ACTIVE_SYMBOLS:
            assert table[sym]["price"] == "V2_NATIVE_ACTIVE"
            assert table[sym]["ta"] == "V2_NATIVE_ACTIVE"
            assert table[sym]["features"] == "V2_NATIVE_ACTIVE"
            # Prediction must stay BRIDGE_ONLY (honest)
            assert table[sym]["prediction"] == "BRIDGE_ONLY"
            # OHLCV/orderbook must stay CONTRACT_DEFINED_CLIENT_DISABLED
            assert table[sym]["ohlcv"] == "CONTRACT_DEFINED_CLIENT_DISABLED"
            assert table[sym]["orderbook"] == "CONTRACT_DEFINED_CLIENT_DISABLED"
    assert p["live_symbols_unchanged"] is True
    assert p["bridge_data_labeled_as_v2_native"] is False


def test_operator_dashboard_payload_blocks_production_and_no_controls(tmp_path: Path):
    p1 = build_phase_1_binance_ohlcv()
    p2 = build_phase_2_binance_orderbook()
    p3 = build_phase_3_feature_pipeline_expansion()
    p4 = build_phase_4_ta_dynamic_service()
    p5 = build_phase_5_coverage_and_refresh(tmp_path)
    dash = build_operator_dashboard_payload(p1, p2, p3, p4, p5)
    sb = dash["safety_scoreboard"]
    assert sb["live_gate"] == LIVE_GATE_BLOCKED
    assert sb["live_symbols"] == []
    assert sb["approves_live"] is False
    assert sb["did_not_start_live_network_feed"] is True
    assert sb["did_not_claim_trainer_native_readiness"] is True
    assert sb["did_not_claim_full_migration"] is True
    assert dash["bridge_data_labeled_as_v2_native"] is False
    assert dash["trainer_native_readiness_claimed"] is False
    assert dash["full_migration_claimed"] is False
    assert dash["controls_present"] is False
    assert dash["fake_readiness"] is False


def test_run_dynamic_runtime_packet_emits_all_required_artifacts(tmp_path: Path):
    paths = default_paths(tmp_path)
    result = run_dynamic_runtime_packet(paths)
    assert result.go_no_go == (
        "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_READY"
    )
    assert (paths.packet_dir / "GO_NO_GO.md").read_text().strip() == result.go_no_go
    for required in [
        "V2_NATIVE_DYNAMIC_INGESTOR_RUNTIME_AND_SYMBOL_EXPANSION_REPORT.md",
        "phase_1_binance_ohlcv.json",
        "phase_2_binance_orderbook.json",
        "phase_3_feature_pipeline_dynamic_expansion.json",
        "phase_4_ta_dynamic_service.json",
        "phase_5_coverage_and_downstream_refresh.json",
    ]:
        assert (paths.packet_dir / required).exists(), required
    assert (paths.public_dir / "operator_dashboard_payload.json").exists()


def test_emitted_artifacts_carry_no_truthy_approval_or_native_claims(tmp_path: Path):
    paths = default_paths(tmp_path)
    run_dynamic_runtime_packet(paths)
    forbidden = [
        '"approves_live": true',
        '"approves_canary": true',
        '"approves_legacy_shutdown": true',
        '"approves_redis_trim": true',
        '"did_not_start_live_network_feed": false',
        '"did_not_claim_trainer_native_readiness": false',
        '"did_not_claim_full_migration": false',
        '"trainer_native_readiness_claimed": true',
        '"full_migration_claimed": true',
        '"bridge_data_labeled_as_v2_native": true',
        '"live_network_feed_started": true',
        '"enabled": true',
    ]
    for f in list(paths.packet_dir.rglob("*")) + list(paths.public_dir.rglob("*")):
        if not f.is_file():
            continue
        text = f.read_text(encoding="utf-8", errors="ignore")
        for token in forbidden:
            assert token not in text, f"{token} in {f}"
