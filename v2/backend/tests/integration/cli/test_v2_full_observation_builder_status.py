"""Tests for the V2 full observation builder.

Paper-only. No torch import. No legacy filesystem read. No checkpoint
load. Deterministic given identical inputs.
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path


def _sample_feature_snapshot() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "feature_snapshot_id": "v2_fsnap_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        "feature_freshness_state": "CURRENT",
        "features": {
            "ret_pct": 0.0021,
            "log_return": 0.0021,
            "body_pct": 0.45,
            "range_pct": 0.6,
            "gap_pct": 0.0,
            "true_range_pct": 0.55,
            "ema_12": 3500.0,
            "ema_26": 3490.0,
            "macd": 1.2,
            "macd_signal": 1.1,
            "macd_hist": 0.1,
            "rsi_14": 55.0,
            "bb_width_pct": 0.7,
            "htf_ret_pct": 0.01,
            "htf_rsi_14": 60.0,
            "bid_ask_spread_bps": 1.2,
            "depth_imbalance": 0.1,
            "micro_price": 3499.5,
            "toxicity_proxy": 0.05,
            "funding_rate": 0.0001,
            "oi_change_pct": 0.005,
            "last_liq_bps_24h": 12.0,
            "paper_position_present": False,
        },
    }


def _builder():
    return importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )


def test_target_dim_is_1911_and_compact_is_26() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
    )
    assert result.target_full_observation_dim == 1911
    assert result.compact_observation_dim == 26
    assert len(result.field_values) == 1911
    assert len(result.field_names) == 1911
    assert len(result.field_sources) == 1911


def test_no_silent_zero_fill_for_unknown_fields() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
    )
    # Generated count must be far less than 1911 — most positions stay None.
    assert result.generated_full_observation_dim < 200
    assert result.missing_dim_count > 1700
    assert result.zero_filled_field_count == 0
    # No None has been replaced with 0.0 silently — count None positions
    # equal missing_dim_count.
    none_count = sum(1 for v in result.field_values if v is None)
    assert none_count == result.missing_dim_count


def test_state_partial_when_categories_missing() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="ETHUSDT",
        timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={"accepted_count": 0, "blocked_count": 0, "held_by_paper_fill_gate_count": 0},
        risk_decisions=[],
        orchestrator_decisions={"considered_count": 0, "bucket_winners": [], "stale_proposal_ids": []},
        trainer_heartbeat={"predictions_count": 0, "predictions_with_open_gate": []},
        prediction={"paper_fill_allowed": True},
    )
    assert result.state == "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS"
    assert "onchain_btc" in result.explicit_missing_categories
    assert "onchain_eth" in result.explicit_missing_categories
    assert "unified_features" in result.partial_categories
    # checkpoint compatibility is never claimed from a partial build.
    # Slot 0 now belongs to the binance_klines sub-family; the source may be
    # the V2 ticker, the V2 feature snapshot (when ticker missing), or the
    # explicit MISSING label.
    assert result.field_sources[0] in {
        "V2_MARKET_TICKER_24HR",
        "V2_NATIVE_FEATURE_SNAPSHOT",
        "MISSING_FROM_V2_BINANCE_KLINE_PROJECTION",
    }


def test_deterministic_for_identical_inputs() -> None:
    mod = _builder()
    snap = _sample_feature_snapshot()
    a = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT", timeframe="1m",
        feature_snapshot=snap,
        paper_positions=[{"symbol": "BTCUSDT", "side": "long",
                          "expected_move_after_cost_bps": 12.5,
                          "confidence_calibrated": 0.7}],
        paper_ledger={"accepted_count": 1, "blocked_count": 0,
                      "held_by_paper_fill_gate_count": 0},
        risk_decisions=[{"symbol": "BTCUSDT", "pre_trade_allowed": True,
                         "fee_gate_allowed": True, "churn_blocked": False}],
        orchestrator_decisions={"considered_count": 1, "bucket_winners": [{}],
                                "stale_proposal_ids": []},
        trainer_heartbeat={"predictions_count": 3,
                           "predictions_with_open_gate": ["BTCUSDT", "ETHUSDT"]},
        prediction={"paper_fill_allowed": True},
    )
    b = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT", timeframe="1m",
        feature_snapshot=snap,
        paper_positions=[{"symbol": "BTCUSDT", "side": "long",
                          "expected_move_after_cost_bps": 12.5,
                          "confidence_calibrated": 0.7}],
        paper_ledger={"accepted_count": 1, "blocked_count": 0,
                      "held_by_paper_fill_gate_count": 0},
        risk_decisions=[{"symbol": "BTCUSDT", "pre_trade_allowed": True,
                         "fee_gate_allowed": True, "churn_blocked": False}],
        orchestrator_decisions={"considered_count": 1, "bucket_winners": [{}],
                                "stale_proposal_ids": []},
        trainer_heartbeat={"predictions_count": 3,
                           "predictions_with_open_gate": ["BTCUSDT", "ETHUSDT"]},
        prediction={"paper_fill_allowed": True},
    )
    assert a.field_values == b.field_values
    assert a.field_names == b.field_names
    assert a.field_sources == b.field_sources


def test_onchain_categories_marked_source_missing() -> None:
    mod = _builder()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT", timeframe="1m",
        feature_snapshot=_sample_feature_snapshot(),
        paper_positions=[],
        paper_ledger={},
        risk_decisions=[],
        orchestrator_decisions={},
        trainer_heartbeat={},
        prediction={},
    )
    onchain_btc_sources = [
        result.field_sources[i]
        for i, name in enumerate(result.field_names)
        if name.startswith("onchain_btc")
    ]
    onchain_eth_sources = [
        result.field_sources[i]
        for i, name in enumerate(result.field_names)
        if name.startswith("onchain_eth")
    ]
    assert onchain_btc_sources, "expected onchain_btc slots"
    assert onchain_eth_sources, "expected onchain_eth slots"
    assert all(s == "ONCHAIN_FEATURE_SOURCE_MISSING" for s in onchain_btc_sources)
    assert all(s == "ONCHAIN_FEATURE_SOURCE_MISSING" for s in onchain_eth_sources)


def test_complete_state_requires_all_1911_dims_filled() -> None:
    mod = _builder()
    snap = _sample_feature_snapshot()
    result = mod.build_full_observation_for_symbol(
        symbol="BTCUSDT", timeframe="1m",
        feature_snapshot=snap,
        paper_positions=[],
        paper_ledger={"accepted_count": 0, "blocked_count": 0,
                      "held_by_paper_fill_gate_count": 0},
        risk_decisions=[],
        orchestrator_decisions={"considered_count": 0, "bucket_winners": [],
                                "stale_proposal_ids": []},
        trainer_heartbeat={"predictions_count": 0,
                           "predictions_with_open_gate": []},
        prediction={"paper_fill_allowed": True},
    )
    assert result.state != "FULL_OBSERVATION_BUILDER_COMPLETE"
    assert result.generated_full_observation_dim < 1911


def test_status_payload_safety_invariants() -> None:
    mod = _builder()
    payload = mod.build_full_observation_status()
    assert payload["target_full_observation_dim"] == 1911
    assert payload["compact_observation_dim"] == 26
    assert payload["checkpoint_compatibility_claimed"] is False
    assert payload["policy_architecture_parity_claimed"] is False
    assert payload["no_torch_imported"] is True
    assert payload["no_pickle_loaded"] is True
    assert payload["no_legacy_filesystem_read"] is True
    assert payload["no_zero_fill_for_unknown_fields"] is True
    assert payload["no_legacy_features_consumed_as_current_truth"] is True
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert isinstance(payload["event_dependent_families"], list)
    assert payload["next_required_family"] != "liquidations"
    assert isinstance(payload["conditionally_undefined_families"], list)


def test_module_does_not_import_torch() -> None:
    sys.modules.pop("torch", None)
    importlib.import_module(
        "v2.backend.app.services.rl_core.full_observation_builder"
    )
    importlib.import_module(
        "v2.backend.app.cli.v2_full_observation_builder_status"
    )
    assert "torch" not in sys.modules


def test_cli_writes_three_payloads(tmp_path: Path, monkeypatch) -> None:
    cli = importlib.import_module(
        "v2.backend.app.cli.v2_full_observation_builder_status"
    )
    worklog = tmp_path / "wl/full.json"
    rl_core = tmp_path / "rl_core/full.json"
    dash = tmp_path / "dash/op.json"
    monkeypatch.setattr(cli, "WORKLOG_STATUS", worklog)
    monkeypatch.setattr(cli, "PUBLIC_RL_CORE", rl_core)
    monkeypatch.setattr(cli, "PUBLIC_DASHBOARD", dash)
    rc = cli.main(["--once", "--symbols", "BTCUSDT,ETHUSDT"])
    assert rc == 0
    a = json.loads(worklog.read_text())
    b = json.loads(rl_core.read_text())
    c = json.loads(dash.read_text())
    assert a == b == c
    assert a["target_full_observation_dim"] == 1911
    assert a["state"] in {
        "FULL_OBSERVATION_BUILDER_PARTIAL_MISSING_FIELDS",
        "FULL_OBSERVATION_BUILDER_COMPLETE",
    }
