"""Tests for V2 native trainer dataset + baseline model (paper / shadow)."""
from __future__ import annotations

import json
import random
from pathlib import Path

import pytest

from v2.backend.app.services.native_trainer.baseline_model import (
    ACTION_FLAT,
    ACTION_LONG,
    DEFAULT_CALIBRATION_BIN_COUNT,
    FALLBACK_ROUND_TRIP_COST_BPS,
    NON_TRAINABLE_LABELS_FOR_CALIBRATION,
    REQUIRED_PUBLISHABLE_FIELDS,
    V2BaselinePublisher,
    build_baseline_prediction,
    evaluate_all_baselines,
    is_baseline_prediction_publishable,
    publish_baseline_predictions,
    train_logistic_model,
)
from v2.backend.app.services.native_trainer.dataset_builder import (
    LIVE_GATE_BLOCKED,
    MIN_TRAIN_ROWS_FOR_READINESS,
    ROW_CLASSIFICATIONS,
    ROW_HELD_OUT_VALIDATION,
    ROW_INSUFFICIENT_EVIDENCE,
    ROW_LABEL_MISSING,
    ROW_MISSING_FEATURES,
    ROW_TRAINABLE,
    DatasetRow,
    LabelRow,
    V2OnlyReader,
    _index_labels_by_snapshot,
    build_dataset_for_universe,
    build_dataset_row,
    build_quality_report,
    default_dataset_paths,
    emit_dataset_artifacts,
    load_label_rows,
)
import v2.backend.app.services.native_trainer.dataset_builder as dataset_builder_module
from v2.backend.app.services.native_trainer.packet import (
    GO_NO_GO_READY,
    default_packet_paths,
    emit_packet,
)


# ---------------------------------------------------------------------------
# In-memory v2:* client
# ---------------------------------------------------------------------------


class _InMemoryClient:
    def __init__(self):
        self._store: dict[str, str] = {}

    def get(self, key):
        return self._store.get(key)

    def set(self, key, value):
        self._store[key] = value
        return True


# ---------------------------------------------------------------------------
# V2OnlyReader
# ---------------------------------------------------------------------------


def test_reader_refuses_non_v2_key():
    reader = V2OnlyReader(client=None)
    with pytest.raises(ValueError, match="non_v2_read_rejected"):
        reader.get_json("legacy:something")
    assert reader.non_v2_read_attempts == 1


def test_reader_returns_none_when_no_client():
    reader = V2OnlyReader(client=None)
    assert reader.get_json("v2:features:latest:BTCUSDT:1m") is None
    assert reader.reads_missing == 1


def test_reader_parses_json_from_client():
    client = _InMemoryClient()
    client.set(
        "v2:features:latest:BTCUSDT:1m",
        json.dumps({"feature_snapshot_id": "x", "freshness_state": "FRESH"}),
    )
    reader = V2OnlyReader(client=client)
    out = reader.get_json("v2:features:latest:BTCUSDT:1m")
    assert out == {"feature_snapshot_id": "x", "freshness_state": "FRESH"}


# ---------------------------------------------------------------------------
# Row construction + classification
# ---------------------------------------------------------------------------


def _label_row(snapshot_id: str, label: str, after_cost: float | None) -> LabelRow:
    return LabelRow(
        feature_snapshot_id=snapshot_id,
        symbol="BTCUSDT",
        timeframe="1m",
        label=label,
        after_cost_return_bps=after_cost,
        max_favorable_bps=None,
        max_adverse_bps=None,
        paper_gate_status=None,
        paper_gate_block_reasons=[],
        risk_decision_context=None,
        legacy_reference_action=None,
    )


def test_row_classifies_insufficient_evidence_when_no_features():
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features=None, ta=None, altdata=None, risk_decision=None,
        label_row=None,
    )
    assert row.classification == ROW_INSUFFICIENT_EVIDENCE
    assert row.feature_freshness_state == "MISSING_OR_STALE"
    assert "v2_features_latest_missing" in row.missing_feature_flags


def test_row_classifies_missing_features_when_indicators_absent():
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {}},
        altdata=None, risk_decision=None, label_row=None,
    )
    assert row.classification == ROW_MISSING_FEATURES


def test_row_classifies_label_missing_when_features_present_but_no_label():
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
        altdata=None, risk_decision=None, label_row=None,
    )
    assert row.classification == ROW_LABEL_MISSING


def test_row_classifies_trainable_or_held_out_when_features_and_label_present():
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
        altdata=None, risk_decision=None,
        label_row=_label_row("x", "true_positive_after_cost_gain", 12.0),
    )
    assert row.classification in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION}


def test_row_uses_live_feature_snapshot_schema_without_ta_key():
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={
            "feature_snapshot_id": "x",
            "feature_freshness_state": "CURRENT",
            "features": {
                "ema_12": 100.0,
                "ema_26": 99.5,
                "rsi_14": 51.0,
                "macd": 0.2,
                "macd_signal": 0.1,
                "atr_14": 1.0,
                "long_short_ratio": 1.5,
                "long_account_ratio": 0.6,
                "short_account_ratio": 0.4,
            },
        },
        ta=None,
        altdata=None,
        risk_decision=None,
        label_row=_label_row("x", "true_positive_after_cost_gain", 12.0),
    )
    assert row.classification in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION}
    assert row.feature_vector["ema_9"] == 100.0
    assert row.feature_vector["ema_21"] == 99.5
    assert row.feature_vector["ema_spread"] == 0.5
    assert row.feature_vector["rsi_14"] == 51.0
    assert row.feature_vector["long_short_ratio"] == 1.5
    assert row.feature_vector["long_account_ratio"] == 0.6
    assert row.feature_vector["short_account_ratio"] == 0.4


def test_row_exposes_altdata_symbol_score_components_as_features():
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={
            "feature_snapshot_id": "x",
            "feature_freshness_state": "CURRENT",
            "features": {
                "ema_12": 100.0,
                "ema_26": 99.5,
                "rsi_14": 51.0,
                "macd": 0.2,
                "macd_signal": 0.1,
            },
        },
        ta=None,
        altdata={
            "altdata_symbol_score": 0.71,
            "public_intel_score": 0.62,
            "coingecko_discovery_score": 0.8,
            "defillama_liquidity_score": 0.44,
            "whale_wall_score": 0.86,
            "whale_bid_pressure_score": 0.9,
            "provider_available": {
                "public_intel": True,
                "coingecko": True,
                "whale_walls": True,
            },
            "input_presence": {
                "public_intel": True,
                "coingecko": True,
                "whale_walls": True,
                "market": True,
            },
        },
        risk_decision=None,
        label_row=_label_row("x", "true_positive_after_cost_gain", 12.0),
    )
    assert row.feature_vector["altdata_symbol_score"] == 0.71
    assert row.feature_vector["public_intel_score"] == 0.62
    assert row.feature_vector["coingecko_discovery_score"] == 0.8
    assert row.feature_vector["defillama_liquidity_score"] == 0.44
    assert row.feature_vector["whale_wall_score"] == 0.86
    assert row.feature_vector["whale_bid_pressure_score"] == 0.9
    assert row.feature_vector["provider_available_public_intel"] == 1.0
    assert row.feature_vector["provider_available_whale_walls"] == 1.0
    assert row.feature_vector["input_present_whale_walls"] == 1.0
    assert row.feature_vector["input_present_market"] == 1.0
    assert "altdata_symbol_score" in row.altdata_context


def test_row_with_label_insufficient_evidence_is_classified_insufficient_evidence():
    """Codex remediation regression — never collapse insufficient_evidence into LABEL_MISSING."""
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
        altdata=None, risk_decision=None,
        label_row=_label_row("x", "insufficient_evidence", None),
    )
    assert row.classification == ROW_INSUFFICIENT_EVIDENCE
    assert row.classification != ROW_LABEL_MISSING


def test_row_with_no_label_is_classified_label_missing():
    """LABEL_MISSING is reserved for rows where no label/evidence row exists."""
    row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
        altdata=None, risk_decision=None,
        label_row=None,
    )
    assert row.classification == ROW_LABEL_MISSING


def test_quality_counters_separate_insufficient_evidence_from_label_missing():
    rows = [
        # Two explicit insufficient_evidence rows
        build_dataset_row(
            symbol="BTCUSDT", timeframe="1m",
            features={"feature_snapshot_id": "a", "freshness_state": "FRESH"},
            ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
            altdata=None, risk_decision=None,
            label_row=_label_row("a", "insufficient_evidence", None),
        ),
        build_dataset_row(
            symbol="ETHUSDT", timeframe="5m",
            features={"feature_snapshot_id": "b", "freshness_state": "FRESH"},
            ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
            altdata=None, risk_decision=None,
            label_row=_label_row("b", "insufficient_evidence", None),
        ),
        # One label-missing row (no label_row)
        build_dataset_row(
            symbol="SOLUSDT", timeframe="1m",
            features={"feature_snapshot_id": "c", "freshness_state": "FRESH"},
            ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
            altdata=None, risk_decision=None,
            label_row=None,
        ),
    ]
    quality = build_quality_report(rows)
    assert quality.insufficient_evidence_rows == 2
    assert quality.label_missing_rows == 1
    # The headline counters must not double-count.
    assert quality.insufficient_evidence_rows + quality.label_missing_rows == 3
    # The label_distribution must agree with the headline counter.
    assert quality.label_distribution.get("insufficient_evidence", 0) == (
        quality.insufficient_evidence_rows
    )


def test_baseline_evaluator_does_not_train_on_insufficient_evidence_rows():
    """Insufficient-evidence rows must never reach the training loop."""
    insufficient_row = build_dataset_row(
        symbol="BTCUSDT", timeframe="1m",
        features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
        ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
        altdata=None, risk_decision=None,
        label_row=_label_row("x", "insufficient_evidence", None),
    )
    rows = [insufficient_row] + [
        _synthetic_trainable_row(i, positive=(i % 2 == 0)) for i in range(80)
    ]
    eval_result = evaluate_all_baselines(rows, minimum_train_rows=32)
    # train_count must equal the number of TRAINABLE rows, not include the
    # insufficient-evidence row.
    assert eval_result.train_count == 80


def test_baseline_calibration_constants_keep_non_trainable_labels_explicit():
    assert "insufficient_evidence" in NON_TRAINABLE_LABELS_FOR_CALIBRATION
    assert FALLBACK_ROUND_TRIP_COST_BPS == 7.0
    assert DEFAULT_CALIBRATION_BIN_COUNT == 5


def test_replay_bundle_row_with_null_outcome_label_insufficient_stays_insufficient(tmp_path):
    """A replay bundle with label=insufficient_evidence and after_cost=null must classify INSUFFICIENT_EVIDENCE."""
    from v2.backend.app.services.native_trainer.dataset_builder import (
        build_rows_from_replay_bundles,
    )
    bundles_path = tmp_path / "replay_outcome_bundles.jsonl"
    bundles_path.write_text(
        json.dumps({
            "feature_snapshot_id": "BTCUSDT:1m:2026-05-23T04:53:32Z",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "label": "insufficient_evidence",
            "generated_at": "2026-05-23T04:53:32Z",
            "future_outcomes": {
                "1m": {"after_cost_return_bps": None},
                "5m": {"after_cost_return_bps": None},
            },
            "orchestrator_decision": {"bucket_winners": [
                {"symbol": "BTCUSDT", "winner_confidence_calibrated": 0.6,
                 "winner_expected_move_after_cost_bps": 12.0,
                 "winner_freshness_seconds": 5.0}
            ]},
        }) + "\n",
        encoding="utf-8",
    )
    replay_rows = build_rows_from_replay_bundles(bundles_path)
    assert len(replay_rows) == 1
    assert replay_rows[0].label == "insufficient_evidence"
    assert replay_rows[0].classification == ROW_INSUFFICIENT_EVIDENCE


def test_row_classifications_set_is_exhaustive_and_disjoint():
    # The constants tuple must contain every legal value used in the row
    # classifier, no duplicates.
    assert len(ROW_CLASSIFICATIONS) == len(set(ROW_CLASSIFICATIONS))
    assert ROW_TRAINABLE in ROW_CLASSIFICATIONS
    assert ROW_HELD_OUT_VALIDATION in ROW_CLASSIFICATIONS


# ---------------------------------------------------------------------------
# Quality report
# ---------------------------------------------------------------------------


def test_quality_report_counts_rows_per_classification():
    rows = [
        build_dataset_row(
            symbol="BTCUSDT", timeframe="1m",
            features=None, ta=None, altdata=None, risk_decision=None,
            label_row=None,
        ),
        build_dataset_row(
            symbol="ETHUSDT", timeframe="5m",
            features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
            ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
            altdata=None, risk_decision=None,
            label_row=_label_row("x", "true_positive_after_cost_gain", 8.0),
        ),
    ]
    quality = build_quality_report(rows)
    assert quality.total_rows == 2
    assert sum(quality.classifications.values()) == 2
    assert quality.minimum_train_rows_threshold == MIN_TRAIN_ROWS_FOR_READINESS
    assert quality.minimum_sample_satisfied is False  # only 1 trainable row


# ---------------------------------------------------------------------------
# load_label_rows
# ---------------------------------------------------------------------------


def test_load_label_rows_reads_jsonl_and_picks_primary_window(tmp_path):
    bundles_path = tmp_path / "replay_outcome_bundles.jsonl"
    bundles_path.write_text(
        json.dumps({
            "feature_snapshot_id": "snap1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "label": "true_positive_after_cost_gain",
            "generated_at": "2026-06-19T12:05:00Z",
            "bundle_generated_at": "2026-06-19T12:05:00Z",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:59Z",
            "entry_feature_generated_at": "2026-06-19T11:59:58Z",
            "feature_cutoff": "2026-06-19T11:59:00Z",
            "candle_open_time": "2026-06-19T11:58:00Z",
            "candle_close_time": "2026-06-19T11:59:00Z",
            "entry_feature_candle_closed_confirmed": True,
            "future_outcomes": {
                "1m": {"after_cost_return_bps": None},
                "5m": {"after_cost_return_bps": 12.5, "max_favorable_bps": 30.0},
            },
        }) + "\n",
        encoding="utf-8",
    )
    rows = load_label_rows(bundles_path)
    assert len(rows) == 1
    assert rows[0].after_cost_return_bps == 12.5
    assert rows[0].max_favorable_bps == 30.0
    assert rows[0].side == "long"
    assert rows[0].decision_time == "2026-06-19T12:00:00Z"
    assert rows[0].available_at == "2026-06-19T11:59:59Z"
    assert rows[0].entry_feature_generated_at == "2026-06-19T11:59:58Z"
    assert rows[0].feature_cutoff == "2026-06-19T11:59:00Z"
    assert rows[0].entry_feature_candle_closed_confirmed is True
    assert rows[0].bundle_generated_at == "2026-06-19T12:05:00Z"


def test_build_rows_from_replay_bundles_preserves_entry_pit_metadata(tmp_path):
    from v2.backend.app.services.native_trainer.dataset_builder import (
        build_rows_from_replay_bundles,
    )

    bundles_path = tmp_path / "replay_outcome_bundles.jsonl"
    bundles_path.write_text(
        json.dumps({
            "feature_snapshot_id": "BTCUSDT:1m:2026-06-19T12:00:00Z",
            "prediction_id": "pred-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "short",
            "label": "true_positive_after_cost_gain",
            "generated_at": "2026-06-19T12:05:00Z",
            "bundle_generated_at": "2026-06-19T12:05:00Z",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:59Z",
            "entry_feature_generated_at": "2026-06-19T11:59:58Z",
            "feature_cutoff": "2026-06-19T11:59:00Z",
            "candle_open_time": "2026-06-19T11:58:00Z",
            "candle_close_time": "2026-06-19T11:59:00Z",
            "entry_feature_candle_closed_confirmed": True,
            "future_outcomes": {
                "5m": {
                    "after_cost_return_bps": 14.0,
                    "max_favorable_bps": 21.0,
                    "max_adverse_bps": 3.0,
                },
            },
            "orchestrator_decision": {"bucket_winners": [
                {"symbol": "BTCUSDT", "winner_confidence_calibrated": 0.7,
                 "winner_expected_move_after_cost_bps": 15.0,
                 "winner_freshness_seconds": 4.0}
            ]},
        }) + "\n",
        encoding="utf-8",
    )

    row = build_rows_from_replay_bundles(bundles_path)[0]
    payload = row.to_jsonable()
    assert row.classification in {ROW_TRAINABLE, ROW_HELD_OUT_VALIDATION}
    assert payload["side"] == "short"
    assert payload["action"] == "short"
    assert payload["generated_at"] == "2026-06-19T12:05:00Z"
    assert payload["bundle_generated_at"] == "2026-06-19T12:05:00Z"
    assert payload["decision_time"] == "2026-06-19T12:00:00Z"
    assert payload["available_at"] == "2026-06-19T11:59:59Z"
    assert payload["entry_feature_available_at"] == "2026-06-19T11:59:59Z"
    assert payload["entry_feature_generated_at"] == "2026-06-19T11:59:58Z"
    assert payload["feature_cutoff"] == "2026-06-19T11:59:00Z"
    assert payload["entry_feature_cutoff"] == "2026-06-19T11:59:00Z"
    assert payload["candle_closed_confirmed"] is True
    assert payload["entry_feature_candle_closed_confirmed"] is True


def test_baseline_evaluator_row_loader_preserves_entry_pit_metadata():
    from v2.backend.app.cli.v2_native_trainer_baseline_evaluator import _row_from_dict

    row = _row_from_dict({
        "row_id": "row-1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_snapshot_id": "snap-1",
        "generated_at": "2026-06-19T12:05:00Z",
        "feature_vector": {"ema_spread": 1.0, "rsi_14": 55.0},
        "missing_feature_flags": [],
        "stale_feature_flags": [],
        "feature_freshness_state": "FRESH",
        "label": "true_positive_after_cost_gain",
        "after_cost_return_bps": 12.0,
        "classification": ROW_TRAINABLE,
        "source_lineage": ["replay_outcome_bundles.jsonl"],
        "side": "long",
        "action": "long",
        "decision_time": "2026-06-19T12:00:00Z",
        "available_at": "2026-06-19T11:59:59Z",
        "feature_cutoff": "2026-06-19T11:59:00Z",
        "entry_feature_available_at": "2026-06-19T11:59:59Z",
        "entry_feature_generated_at": "2026-06-19T11:59:58Z",
        "entry_feature_cutoff": "2026-06-19T11:59:00Z",
        "entry_feature_candle_closed_confirmed": True,
        "bundle_generated_at": "2026-06-19T12:05:00Z",
    })

    assert row.side == "long"
    assert row.decision_time == "2026-06-19T12:00:00Z"
    assert row.available_at == "2026-06-19T11:59:59Z"
    assert row.entry_feature_generated_at == "2026-06-19T11:59:58Z"
    assert row.entry_feature_cutoff == "2026-06-19T11:59:00Z"
    assert row.entry_feature_candle_closed_confirmed is True
    assert row.bundle_generated_at == "2026-06-19T12:05:00Z"


def test_load_label_rows_returns_empty_when_file_missing(tmp_path):
    rows = load_label_rows(tmp_path / "missing.jsonl")
    assert rows == []


# ---------------------------------------------------------------------------
# build_dataset_for_universe + reader audit
# ---------------------------------------------------------------------------


def test_universe_sweep_only_touches_v2_keys():
    client = _InMemoryClient()
    client.set(
        "v2:features:latest:BTCUSDT:1m",
        json.dumps({"feature_snapshot_id": "snap-btc-1m", "freshness_state": "FRESH"}),
    )
    client.set(
        "v2:features:ta:BTCUSDT:1m",
        json.dumps({"indicators": {"ema_9": 101.0, "ema_21": 100.0, "rsi_14": 55.0}}),
    )
    reader = V2OnlyReader(client=client)
    result = build_dataset_for_universe(
        reader=reader,
        universe=["BTCUSDT", "ETHUSDT"],
        timeframes=["1m"],
    )
    assert len(result.rows) == 2
    assert reader.non_v2_read_attempts == 0


def test_universe_sweep_defaults_to_dynamic_symbol_resolver(monkeypatch):
    monkeypatch.setattr(
        dataset_builder_module,
        "resolve_symbols_with_provenance",
        lambda include_baseline=True: {
            "symbols": ["BTCUSDT", "NEWDYNUSDT"],
            "symbol_profile": "dynamic_or_baseline",
            "count": 2,
            "source_path": "test_symbol_universe_status.json",
        },
    )
    result = build_dataset_for_universe(reader=V2OnlyReader(client=None), timeframes=["1m"])
    assert result.universe == ["BTCUSDT", "NEWDYNUSDT"]
    assert result.symbol_resolution["symbol_profile"] == "dynamic_or_baseline"


# ---------------------------------------------------------------------------
# Logistic baseline + evaluation
# ---------------------------------------------------------------------------


def _synthetic_trainable_row(idx: int, *, positive: bool) -> DatasetRow:
    return DatasetRow(
        row_id=f"row-{idx}",
        symbol="BTCUSDT",
        timeframe="1m",
        feature_snapshot_id=f"snap-{idx}",
        generated_at="2026-05-23T00:00:00Z",
        feature_vector={
            "ema_9": 100.0,
            "ema_21": 99.5,
            "ema_spread": 1.0 if positive else -1.0,
            "rsi_14": 60.0 if positive else 40.0,
            "macd": 0.5 if positive else -0.5,
            "macd_signal": 0.0,
            "atr_14": 1.0,
            "vol_zscore": 0.5 if positive else -0.5,
            "feature_freshness_seconds": 5.0,
        },
        missing_feature_flags=[],
        stale_feature_flags=[],
        feature_freshness_state="FRESH",
        label=(
            "true_positive_after_cost_gain"
            if positive
            else "false_negative_after_cost_loss"
        ),
        after_cost_return_bps=12.0 if positive else -8.0,
        max_favorable_bps=15.0 if positive else 2.0,
        max_adverse_bps=2.0 if positive else 12.0,
        paper_gate_status=None,
        paper_gate_block_reasons=[],
        risk_decision_context=None,
        altdata_context=None,
        legacy_reference_action=None,
        classification=ROW_TRAINABLE,
        source_lineage=[],
    )


def _synthetic_held_out_row(idx: int, *, positive: bool) -> DatasetRow:
    row = _synthetic_trainable_row(idx, positive=positive)
    row.classification = ROW_HELD_OUT_VALIDATION
    return row


def test_logistic_model_separates_positive_from_negative_on_synthetic_data():
    random.seed(0)
    train_rows = [
        _synthetic_trainable_row(i, positive=(i % 2 == 0))
        for i in range(128)
    ]
    model = train_logistic_model(train_rows, epochs=200)
    pos_proba = model.predict_proba([1.0, 10.0, 0.5, 1.0, 0.5])
    neg_proba = model.predict_proba([-1.0, -10.0, -0.5, 1.0, -0.5])
    assert pos_proba > neg_proba


def test_evaluate_all_baselines_emits_metrics_for_each_strategy():
    rows = [
        _synthetic_trainable_row(i, positive=(i % 2 == 0))
        for i in range(80)
    ] + [
        _synthetic_held_out_row(i + 1000, positive=(i % 2 == 0))
        for i in range(20)
    ]
    eval_result = evaluate_all_baselines(rows, minimum_train_rows=32)
    names = [m.name for m in eval_result.metrics]
    assert "hold_baseline" in names
    assert "contract_only_publisher_baseline" in names
    assert "simple_v2_native_baseline_ema_or_rsi" in names
    assert "legacy_reference_action_mirror_only" in names
    assert "v2_native_logistic_baseline_trained" in names
    assert eval_result.trained_model is not None


def test_evaluate_skips_training_when_below_minimum_train_rows():
    rows = [_synthetic_trainable_row(0, positive=True)]
    eval_result = evaluate_all_baselines(rows, minimum_train_rows=64)
    assert eval_result.minimum_sample_satisfied is False
    assert eval_result.trained_model is None
    assert eval_result.publishable_baseline_available is False


# ---------------------------------------------------------------------------
# Baseline prediction payload contract
# ---------------------------------------------------------------------------


def test_baseline_prediction_contains_required_fields_and_safety_pins():
    row = _synthetic_trainable_row(0, positive=True)
    model = train_logistic_model([row], epochs=1)
    payload = build_baseline_prediction(row=row, model=model)
    for field_name in REQUIRED_PUBLISHABLE_FIELDS:
        assert field_name in payload, f"missing required field: {field_name}"
    assert payload["paper_fill_allowed"] is False
    assert payload["live_gate"] == LIVE_GATE_BLOCKED
    assert payload["live_symbols"] == []
    assert payload["approves_live"] is False
    assert payload["approves_canary"] is False
    assert payload["approves_legacy_shutdown"] is False
    assert payload["approves_redis_trim"] is False
    assert payload["trainer_source"] == "V2_NATIVE_BASELINE_PAPER_SHADOW"
    assert payload["model_source"] == "BASELINE_NOT_PRODUCTION"
    assert payload["model_readiness"] == "NOT_PRODUCTION_READY"


def test_is_baseline_prediction_publishable_rejects_unsafe_payload():
    row = _synthetic_trainable_row(0, positive=True)
    model = train_logistic_model([row], epochs=1)
    payload = build_baseline_prediction(row=row, model=model)
    assert is_baseline_prediction_publishable(payload)
    # Now break the safety pins.
    bad = dict(payload)
    bad["paper_fill_allowed"] = True
    assert is_baseline_prediction_publishable(bad) is False
    bad2 = dict(payload)
    bad2["live_gate"] = "OPEN"
    assert is_baseline_prediction_publishable(bad2) is False


# ---------------------------------------------------------------------------
# V2BaselinePublisher
# ---------------------------------------------------------------------------


def test_publisher_refuses_non_v2_keys_and_counts_attempts():
    publisher = V2BaselinePublisher(client=_InMemoryClient())
    payload = build_baseline_prediction(
        row=_synthetic_trainable_row(0, positive=True),
        model=train_logistic_model(
            [_synthetic_trainable_row(0, positive=True)], epochs=1
        ),
    )
    ok = publisher.publish("legacy:prediction:BTCUSDT", payload)
    assert ok is False
    assert publisher.audit.old_redis_write_attempts == 1


def test_publisher_preserves_existing_stronger_prediction():
    client = _InMemoryClient()
    publisher = V2BaselinePublisher(client=client)
    # Seed a stronger existing prediction.
    client.set(
        "v2:prediction:BTCUSDT:1m",
        json.dumps({"trainer_source": "V2_NATIVE_TRAINER_FROZEN_CHECKPOINT"}),
    )
    rows = [
        _synthetic_trainable_row(i, positive=(i % 2 == 0))
        for i in range(80)
    ]
    model = train_logistic_model(rows, epochs=50)
    out = publish_baseline_predictions(
        rows=rows,
        model=model,
        publisher=publisher,
        timeframes=["1m"],
    )
    assert out["preserved_count"] >= 1
    assert out["old_redis_write_attempts"] == 0


def test_publisher_writes_only_v2_keys_when_publishing():
    publisher = V2BaselinePublisher(client=_InMemoryClient())
    rows = [
        _synthetic_trainable_row(i, positive=(i % 2 == 0))
        for i in range(80)
    ]
    model = train_logistic_model(rows, epochs=50)
    publish_baseline_predictions(
        rows=rows, model=model, publisher=publisher, timeframes=["1m"],
    )
    for k in publisher.audit.keys_written:
        assert k.startswith("v2:prediction:")


# ---------------------------------------------------------------------------
# End-to-end packet emission
# ---------------------------------------------------------------------------


def test_emit_packet_writes_all_required_artifacts(tmp_path):
    rows = [
        _synthetic_trainable_row(i, positive=(i % 2 == 0))
        for i in range(80)
    ] + [
        _synthetic_held_out_row(i + 1000, positive=(i % 2 == 0))
        for i in range(20)
    ]
    quality = build_quality_report(rows)
    eval_result = evaluate_all_baselines(rows, minimum_train_rows=32)
    paths = default_packet_paths(tmp_path)
    from v2.backend.app.services.native_trainer.dataset_builder import (
        DatasetBuildResult,
    )
    build_result = DatasetBuildResult(rows=rows)
    result = emit_packet(
        paths=paths,
        build_result=build_result,
        quality=quality,
        eval_result=eval_result,
        publisher_result=None,
    )
    assert result.go_no_go == GO_NO_GO_READY
    for p in result.paths_written:
        assert Path(p).exists(), f"missing artifact: {p}"
    go_no_go_text = (paths.packet_dir / "GO_NO_GO.md").read_text(encoding="utf-8")
    assert go_no_go_text.strip() == GO_NO_GO_READY
    dashboard = json.loads(
        (paths.packet_dir / "operator_dashboard_payload.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard["safety_scoreboard"]["approves_live"] is False
    assert dashboard["live_gate"] == LIVE_GATE_BLOCKED
    assert dashboard["v2_native_trainer_ready"] is False
    assert dashboard["model_parity_claimed"] is False
    assert dashboard["checkpoint_compatibility_claimed"] is False


def test_dataset_artifacts_round_trip_through_disk(tmp_path):
    rows = [
        build_dataset_row(
            symbol="BTCUSDT", timeframe="1m",
            features={"feature_snapshot_id": "x", "freshness_state": "FRESH"},
            ta={"indicators": {"ema_9": 100.0, "ema_21": 99.5, "rsi_14": 51.0}},
            altdata=None, risk_decision=None,
            label_row=_label_row("x", "true_positive_after_cost_gain", 8.0),
        )
    ]
    quality = build_quality_report(rows)
    paths = default_dataset_paths(tmp_path)
    from v2.backend.app.services.native_trainer.dataset_builder import (
        DatasetBuildResult,
    )
    build_result = DatasetBuildResult(rows=rows)
    written = emit_dataset_artifacts(
        paths=paths, result=build_result, quality=quality,
    )
    rows_jsonl = paths.packet_dir / "v2_native_trainer_dataset_rows.jsonl"
    assert rows_jsonl in written
    # Confirm each row is JSON-decodable line-by-line.
    decoded = [
        json.loads(line)
        for line in rows_jsonl.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    assert len(decoded) == 1
    assert decoded[0]["symbol"] == "BTCUSDT"
    assert decoded[0]["label"] == "true_positive_after_cost_gain"


def test_dataset_artifacts_emit_compact_replay_evidence_sidecar(tmp_path):
    from v2.backend.app.services.native_trainer.dataset_builder import (
        DatasetBuildResult,
        build_rows_from_replay_bundles,
    )

    bundles_path = tmp_path / "replay_outcome_bundles.jsonl"
    bundles_path.write_text(
        json.dumps({
            "feature_snapshot_id": "BTCUSDT:1m:2026-06-19T12:00:00Z",
            "prediction_id": "pred-sidecar-1",
            "symbol": "BTCUSDT",
            "timeframe": "1m",
            "side": "long",
            "label": "true_positive_after_cost_gain",
            "generated_at": "2026-06-19T12:05:00Z",
            "bundle_generated_at": "2026-06-19T12:05:00Z",
            "decision_time": "2026-06-19T12:00:00Z",
            "available_at": "2026-06-19T11:59:59Z",
            "entry_feature_generated_at": "2026-06-19T11:59:58Z",
            "feature_cutoff": "2026-06-19T11:59:00Z",
            "candle_open_time": "2026-06-19T11:58:00Z",
            "candle_close_time": "2026-06-19T11:59:00Z",
            "entry_feature_candle_closed_confirmed": True,
            "future_outcomes": {
                "5m": {"after_cost_return_bps": 14.0},
            },
            "orchestrator_decision": {"bucket_winners": [
                {"symbol": "BTCUSDT", "winner_confidence_calibrated": 0.7,
                 "winner_expected_move_after_cost_bps": 15.0,
                 "winner_freshness_seconds": 4.0}
            ]},
        }) + "\n",
        encoding="utf-8",
    )
    rows = build_rows_from_replay_bundles(bundles_path)
    quality = build_quality_report(rows)
    paths = default_dataset_paths(tmp_path)

    written = emit_dataset_artifacts(
        paths=paths,
        result=DatasetBuildResult(rows=rows),
        quality=quality,
    )

    replay_rows = paths.packet_dir / "v2_native_trainer_replay_evidence_rows.jsonl"
    replay_status = paths.packet_dir / "v2_native_trainer_replay_evidence_status.json"
    public_replay_rows = paths.public_dir / "v2_native_trainer_replay_evidence_rows.jsonl"
    public_replay_status = paths.public_dir / "v2_native_trainer_replay_evidence_status.json"
    assert replay_rows in written
    assert replay_status in written
    assert public_replay_rows in written
    assert public_replay_status in written

    decoded_rows = [
        json.loads(line)
        for line in replay_rows.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    status = json.loads(replay_status.read_text(encoding="utf-8"))
    assert len(decoded_rows) == 1
    assert decoded_rows[0]["counterfactual_source_kind"] == "native_trainer_replay_dataset"
    assert decoded_rows[0]["decision_time"] == "2026-06-19T12:00:00Z"
    assert decoded_rows[0]["entry_feature_generated_at"] == "2026-06-19T11:59:58Z"
    assert decoded_rows[0]["entry_feature_candle_closed_confirmed"] is True
    assert status["event_time_valid_label_count"] == 1
    assert status["live_gate"] == LIVE_GATE_BLOCKED
    assert status["approves_live"] is False


def test_emitted_dashboard_carries_safety_block(tmp_path):
    """The lane is analysis-only — safety pins must always hold."""
    rows: list[DatasetRow] = []
    quality = build_quality_report(rows)
    eval_result = evaluate_all_baselines(rows, minimum_train_rows=64)
    paths = default_packet_paths(tmp_path)
    from v2.backend.app.services.native_trainer.dataset_builder import (
        DatasetBuildResult,
    )
    build_result = DatasetBuildResult(rows=rows)
    emit_packet(
        paths=paths,
        build_result=build_result,
        quality=quality,
        eval_result=eval_result,
        publisher_result=None,
    )
    dashboard = json.loads(
        (paths.packet_dir / "operator_dashboard_payload.json").read_text(
            encoding="utf-8"
        )
    )
    assert dashboard["safety_scoreboard"]["approves_live"] is False
    assert (
        dashboard["safety_scoreboard"]["did_not_claim_trainer_native_readiness"]
        is True
    )
    assert (
        dashboard["safety_scoreboard"]["did_not_use_raw_legacy_redis_as_current_truth"]
        is True
    )


def test_no_emitted_artifact_carries_forbidden_trainer_source(tmp_path):
    rows = [
        _synthetic_trainable_row(i, positive=(i % 2 == 0))
        for i in range(64)
    ]
    quality = build_quality_report(rows)
    eval_result = evaluate_all_baselines(rows, minimum_train_rows=32)
    paths = default_packet_paths(tmp_path)
    from v2.backend.app.services.native_trainer.dataset_builder import (
        DatasetBuildResult,
    )
    build_result = DatasetBuildResult(rows=rows)
    emit_packet(
        paths=paths,
        build_result=build_result,
        quality=quality,
        eval_result=eval_result,
        publisher_result=None,
    )
    forbidden = ("V2_NATIVE_TRAINER_READY", "V2_NATIVE_TRAINER_ACTIVE")
    for artifact in paths.packet_dir.glob("*.json"):
        text = artifact.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{artifact.name} leaks forbidden token {token}"


# ---------------------------------------------------------------------------
# index_lanes wires the lane into the report center registry
# ---------------------------------------------------------------------------


def test_report_center_registry_includes_new_lane():
    from v2.backend.app.services.report_center.report_registry import LANES
    lane_ids = {lane.lane_id for lane in LANES}
    assert "v2_native_trainer_dataset_and_baseline_model" in lane_ids
