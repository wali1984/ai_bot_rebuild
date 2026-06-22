"""P0.2F integration tests: trainer output contract + strict paper fill gate."""
from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[5]


def _snapshot_fixture() -> dict:
    return {
        "schema_version": "v2_native_feature_snapshot_v1",
        "worker_id": "v2_feature_pipeline_native",
        "feature_snapshot_id": "v2_fsnap_p0_2f_test_abcdef",
        "generated_at": "2026-05-16T00:00:00+00:00",
        "symbol": "BTCUSDT", "timeframe": "1m",
        "features": {
            "ret_pct": 0.001, "log_return": 0.00099, "range_pct": 0.005,
            "body_pct": 0.0008, "true_range_pct": 0.006, "gap_pct": 0.0,
            "ema_12": 100.4, "ema_26": 100.2, "rsi_14": 55.0,
            "macd": 0.05, "macd_signal": 0.04, "macd_hist": 0.01,
            "bb_width_pct": 0.012, "htf_ret_pct": 0.002, "htf_rsi_14": 60.0,
            "bid_ask_spread_bps": 5.0, "depth_imbalance": 0.1, "micro_price": 100.0,
            "toxicity_proxy": 0.2, "funding_rate": 0.0001, "oi_change_pct": 0.01,
            "last_liq_bps_24h": 5.0, "paper_position_present": 0,
        },
        "feature_count": 23,
        "categories_present": [
            "ohlcv_derived","ta_indicators","multi_timeframe","microstructure",
            "funding_oi_liquidation","portfolio_aware","freshness",
        ],
        "missing_feature_flags": [], "stale_feature_flags": [],
        "feature_freshness_state": "CURRENT", "trainer_consumable": True,
        "live_gate": "blocked_human_only", "live_symbols": [],
    }


def _valid_record():
    """Build a synthetic TrainerOutputRecord with strong positive edge."""
    from v2.backend.app.services.rl_core.trainer_output import (
        FeatureAttribution,
        TrainerOutputRecord,
        TRAINER_SOURCE,
        ATTRIBUTION_METHOD,
    )

    return TrainerOutputRecord(
        prediction_id="v2_native_pred_test_id_0001",
        feature_snapshot_id="v2_fsnap_test_abcdef",
        trainer_source=TRAINER_SOURCE,
        checkpoint_id=None,
        checkpoint_blocker="CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED",
        expected_move_bps=75.0,
        expected_move_after_cost_bps=50.0,
        confidence_raw=0.7,
        confidence_calibrated=0.6,
        confidence_temperature=1.5,
        confidence_used_calibration=True,
        top_positive_features=(FeatureAttribution(feature_name="rsi_14", sensitivity=0.4),),
        top_negative_features=(FeatureAttribution(feature_name="oi_change_pct", sensitivity=-0.3),),
        attribution_method=ATTRIBUTION_METHOD,
        missing_feature_flags=(),
        stale_feature_flags=(),
        policy_action_labels=("hold", "long", "short", "close", "hedge"),
        policy_action_probabilities=(0.1, 0.6, 0.1, 0.1, 0.1),
        hedge_action_classification="FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE",
        selected_action="long",
        generated_utc="2026-05-16T05:55:00Z",
        feature_freshness_state="CURRENT",
        prediction_live_gate="blocked_human_only",
        prediction_live_symbols=(),
    )


# ---------- emit_trainer_output contract ----------


def test_emit_trainer_output_returns_full_contract() -> None:
    from v2.backend.app.services.rl_core.trainer_output import emit_trainer_output

    rec = emit_trainer_output(_snapshot_fixture())
    assert rec.trainer_source == "V2_NATIVE_RL_CORE"
    assert rec.feature_snapshot_id.endswith("p0_2f_test_abcdef")
    assert rec.checkpoint_id is None
    assert rec.checkpoint_blocker == "CHECKPOINT_WEIGHT_BLOB_OPERATOR_REQUIRED"
    assert 0.0 < rec.confidence_raw <= 1.0
    assert 0.0 < rec.confidence_calibrated <= 1.0
    assert rec.confidence_used_calibration is True or rec.confidence_temperature == 1.0
    assert len(rec.policy_action_probabilities) == 5
    assert len(rec.top_positive_features) >= 1
    assert len(rec.top_negative_features) >= 1
    assert rec.attribution_method == \
        "simple_sensitivity_finite_difference_on_selected_action_prob"
    assert rec.hedge_action_classification == "FAIL_CLOSED_UNTIL_PAPER_HEDGE_ENGINE"
    assert rec.feature_freshness_state == "CURRENT"
    assert rec.prediction_live_gate == "blocked_human_only"
    assert rec.prediction_live_symbols == ()
    assert abs((rec.expected_move_bps - rec.expected_move_after_cost_bps) - 12.0) < 1e-6


# ---------- strict paper fill gate: pass path ----------


def test_validate_for_paper_fill_gate_opens_for_strong_positive_edge() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = _valid_record()
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_gate_status"] == "TRAINER_OUTPUT_PRESENT_PAPER_FILL_GATE_OPEN"
    assert res["paper_fill_allowed"] is True
    assert res["paper_fill_gate_block_reasons"] == ()
    assert res["blockers"] == ()


# ---------- strict paper fill gate: block paths ----------


def test_block_when_record_missing() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    res = validate_for_paper_fill_gate(None)
    assert res["paper_fill_gate_status"] == "BLOCKED_BY_TRAINER_OUTPUT_MISSING"
    assert res["paper_fill_allowed"] is False
    assert "MISSING_PREDICTION_ID_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_prediction_id_missing() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), prediction_id="")
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "MISSING_PREDICTION_ID_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_feature_snapshot_id_missing() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), feature_snapshot_id="")
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "MISSING_FEATURE_SNAPSHOT_ID_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_trainer_source_missing() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), trainer_source="")
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "MISSING_TRAINER_SOURCE_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_expected_move_after_cost_negative() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), expected_move_after_cost_bps=-68.46)
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert res["paper_fill_gate_status"] == "BLOCKED_BY_TRAINER_OUTPUT_MALFORMED"
    assert "NEGATIVE_EXPECTED_MOVE_AFTER_COST_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_expected_move_after_cost_zero() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), expected_move_after_cost_bps=0.0)
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    # zero is below default threshold of 8 bps
    assert "EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_expected_move_after_cost_below_threshold() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), expected_move_after_cost_bps=4.0)
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_expected_move_after_cost_missing_via_nan() -> None:
    import math

    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), expected_move_after_cost_bps=float("nan"))
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "MISSING_EXPECTED_MOVE_AFTER_COST_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_feature_freshness_not_current() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), feature_freshness_state="STALE")
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "FEATURE_FRESHNESS_NOT_CURRENT_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_missing_feature_flags_non_empty() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), missing_feature_flags=("rsi_14_missing",))
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "MISSING_FEATURE_FLAGS_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_stale_feature_flags_non_empty() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), stale_feature_flags=("funding_stale",))
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "STALE_FEATURE_FLAGS_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_confidence_calibrated_out_of_range() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), confidence_calibrated=1.5)
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "CONFIDENCE_MISSING_OR_INVALID_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_live_gate_not_blocked() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), prediction_live_gate="allowed")
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "LIVE_GATE_NOT_BLOCKED_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_when_live_symbols_not_empty() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), prediction_live_symbols=("BTCUSDT",))
    res = validate_for_paper_fill_gate(rec)
    assert res["paper_fill_allowed"] is False
    assert "LIVE_SYMBOLS_NOT_EMPTY_BLOCK" in res["paper_fill_gate_block_reasons"]


def test_block_threshold_can_be_overridden() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        validate_for_paper_fill_gate,
    )

    rec = replace(_valid_record(), expected_move_after_cost_bps=10.0)
    res_strict = validate_for_paper_fill_gate(rec, expected_move_after_cost_min_bps=15.0)
    assert res_strict["paper_fill_allowed"] is False
    assert "EDGE_AFTER_COST_BELOW_THRESHOLD_BLOCK" in res_strict["paper_fill_gate_block_reasons"]
    res_lax = validate_for_paper_fill_gate(rec, expected_move_after_cost_min_bps=5.0)
    assert res_lax["paper_fill_allowed"] is True


# ---------- invariants + forbidden imports ----------


def test_trainer_output_invariants_snapshot_holds_safety() -> None:
    from v2.backend.app.services.rl_core.trainer_output import (
        trainer_output_invariants_snapshot,
    )

    s = trainer_output_invariants_snapshot()
    assert s["trainer_source"] == "V2_NATIVE_RL_CORE"
    assert s["live_gate"] == "blocked_human_only"
    assert s["live_symbols"] == []
    assert s["loads_legacy_log_lines_for_confidence"] is False
    assert s["expected_move_derivation_source"] == \
        "v2_native_policy_expected_move_scalar_head"


def test_p0_2f_module_has_no_forbidden_imports() -> None:
    text = (REPO / "v2/backend/app/services/rl_core/trainer_output.py").read_text()
    for forbidden in (
        "import torch", "from torch",
        "import numpy", "from numpy",
        "import stable_baselines3", "from stable_baselines3",
        "import gymnasium", "from gymnasium",
        "import redis", "from redis",
        "import ccxt", "from ccxt",
        "import binance",
    ):
        assert forbidden not in text, f"trainer_output.py contains forbidden: {forbidden}"
