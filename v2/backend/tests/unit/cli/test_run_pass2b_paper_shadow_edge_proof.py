from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[5]))

from v2.backend.app.cli.run_pass2b_paper_shadow_edge_proof import run_edge_proof
from v2.backend.app.services.market_state_integrity.trust import TRUST_SCHEMA_VERSION


def wrap(category: str, redis_key: str, value: dict) -> dict:
    return {"category": category, "redis_key": redis_key, "value": value}


def trusted_prediction(**overrides):
    record = {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "decision_id": "d1",
        "prediction_id": "p1",
        "mtf_snapshot_id": "mtf1",
        "replay_snapshot_id": "rs1",
        "feature_cutoff": "2026-06-13T00:00:00Z",
        "available_at": "2026-06-13T00:00:01Z",
        "all_tf_candle_timestamps": [1, 2, 3, 4, 5],
        "routes_to_live": False,
        "live_order_allowed": False,
        "selected_action": "hold",
        "paper_fill_allowed": False,
        "paper_eligible": False,
        "symbol": "BTCUSDT",
    }
    record.update(overrides)
    return record


def replay_snapshot(prediction_id: str = "p1", replay_snapshot_id: str = "rs1", mtf_snapshot_id: str = "mtf1") -> dict:
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "prediction_id": prediction_id,
        "decision_id": "d1",
        "replay_snapshot_id": replay_snapshot_id,
        "mtf_snapshot_id": mtf_snapshot_id,
    }


def mtf_snapshot(mtf_snapshot_id: str = "mtf1") -> dict:
    return {
        "trust_schema_version": TRUST_SCHEMA_VERSION,
        "prediction_id": "p1",
        "decision_id": "d1",
        "mtf_snapshot_id": mtf_snapshot_id,
        "valid": True,
    }


def closed_trade(**overrides) -> dict:
    record = {
        "prediction_id": "p1",
        "decision_id": "d1",
        "replay_snapshot_id": "rs1",
        "mtf_snapshot_id": "mtf1",
        "trade_status": "closed",
        "symbol": "BTCUSDT",
        "side": "long",
        "gross_pnl": 10.0,
        "fees": 1.0,
        "slippage": 2.0,
        "entry_time": "2026-06-13T00:00:00Z",
        "exit_time": "2026-06-13T00:10:00Z",
    }
    record.update(overrides)
    return record


def bad_order(status: str) -> dict:
    return {
        "prediction_id": "p1",
        "decision_id": "d1",
        "replay_snapshot_id": "rs1",
        "mtf_snapshot_id": "mtf1",
        "order_status": status,
        "symbol": "BTCUSDT",
    }


def positive_training_sample() -> dict:
    return {
        "sample_id": "s1",
        "prediction_id": "p1",
        "decision_id": "d1",
        "replay_snapshot_id": "rs1",
        "mtf_snapshot_id": "mtf1",
        "accepted_for_training": True,
        "training_outcome": "positive",
    }


def write_evidence(
    tmp_path: Path,
    *,
    prediction: dict | None = None,
    include_replay: bool = True,
    include_mtf: bool = True,
    execution_records: list[dict] | None = None,
    training_samples: list[dict] | None = None,
    strict_critical_failures: int = 0,
) -> Path:
    run_dir = tmp_path / "evidence"
    run_dir.mkdir()
    prediction = prediction if prediction is not None else trusted_prediction()
    rows = {
        "masa_ppo.jsonl": [wrap("masa_ppo", "v2:prediction:BTCUSDT:1m", prediction)],
        "replay_snapshots.jsonl": [],
        "execution_records.jsonl": [wrap("execution_records", "v2:paper:intents", row) for row in (execution_records or [])],
        "training_samples.jsonl": [wrap("training_samples", "v2:trainer:samples:test", row) for row in (training_samples or [])],
    }
    if include_replay:
        rows["replay_snapshots.jsonl"].append(wrap("replay_snapshots", "v2:replay:snapshots:p1", replay_snapshot()))
    if include_mtf:
        rows["replay_snapshots.jsonl"].append(wrap("replay_snapshots", "v2:market:mtf_snapshot:mtf1", mtf_snapshot()))
    for name, values in rows.items():
        (run_dir / name).write_text("".join(json.dumps(value) + "\n" for value in values), encoding="utf-8")
    report_dir = run_dir / "report"
    report_dir.mkdir()
    (report_dir / "pipeline_trust_report.json").write_text(
        json.dumps({"summary": {"critical_failures": strict_critical_failures}}),
        encoding="utf-8",
    )
    return run_dir


def run(tmp_path: Path, **kwargs):
    evidence = write_evidence(tmp_path, **kwargs)
    return run_edge_proof(evidence_dir=evidence, min_trusted_decisions=1, min_closed_trades=1)


def test_trusted_decision_with_replay_and_mtf_is_included(tmp_path: Path) -> None:
    result = run(tmp_path)

    assert result["total_trusted_predictions"] == 1
    assert result["hold_no_trade_predictions"] == 1
    assert result["verdict"] == "INSUFFICIENT_SAMPLE"


def test_decision_missing_replay_snapshot_is_invalid(tmp_path: Path) -> None:
    result = run(tmp_path, include_replay=False)

    assert result["verdict"] == "EDGE_DATA_INVALID"
    assert result["decisions_missing_replay_snapshot"] == 1


def test_decision_missing_mtf_snapshot_is_invalid(tmp_path: Path) -> None:
    result = run(tmp_path, include_mtf=False)

    assert result["verdict"] == "EDGE_DATA_INVALID"
    assert result["decisions_missing_mtf_snapshot"] == 1


def test_stale_pre_v3_decision_is_excluded(tmp_path: Path) -> None:
    result = run(tmp_path, prediction=trusted_prediction(trust_schema_version="pipeline_trust_v2"))

    assert result["total_trusted_predictions"] == 0
    assert result["stale_pre_v3_predictions_excluded"] == 1
    assert result["verdict"] == "INSUFFICIENT_SAMPLE"


def test_live_order_record_is_excluded_from_trade_metrics(tmp_path: Path) -> None:
    result = run(tmp_path, execution_records=[closed_trade(places_real_order=True, exchange_action_taken=True)])

    assert result["live_order_records_excluded"] == 1
    assert result["closed_paper_trades"] == 0
    assert result["metrics"]["net_pnl_after_fees_slippage"] == 0


def test_hold_decision_is_not_included_in_trade_expectancy(tmp_path: Path) -> None:
    result = run(tmp_path)

    assert result["hold_no_trade_predictions"] == 1
    assert result["closed_paper_trades"] == 0
    assert result["metrics"]["expectancy_per_trade"] == 0


@pytest.mark.parametrize("status", ["rejected", "canceled", "expired", "blocked"])
def test_bad_order_status_cannot_create_positive_training_result(tmp_path: Path, status: str) -> None:
    result = run(
        tmp_path,
        prediction=trusted_prediction(selected_action="long", paper_fill_allowed=True, paper_eligible=True),
        execution_records=[bad_order(status)],
        training_samples=[positive_training_sample()],
    )

    assert result["verdict"] == "EDGE_DATA_INVALID"
    assert result["invalid_feedback_count"] == 1


def test_fees_and_slippage_are_subtracted_from_net_pnl(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        prediction=trusted_prediction(selected_action="long", paper_fill_allowed=True, paper_eligible=True),
        execution_records=[closed_trade(gross_pnl=10.0, fees=1.0, slippage=2.0)],
    )

    assert result["closed_paper_trades"] == 1
    assert result["metrics"]["net_pnl_after_fees_slippage"] == 7.0
    assert result["metrics"]["expectancy_per_trade"] == 7.0


def test_insufficient_sample_returns_insufficient_sample(tmp_path: Path) -> None:
    evidence = write_evidence(tmp_path, execution_records=[closed_trade()])
    result = run_edge_proof(evidence_dir=evidence, min_trusted_decisions=25, min_closed_trades=10)

    assert result["verdict"] == "INSUFFICIENT_SAMPLE"


def test_positive_expectancy_with_sufficient_sample_returns_edge_positive(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        prediction=trusted_prediction(selected_action="long", paper_fill_allowed=True, paper_eligible=True),
        execution_records=[closed_trade(gross_pnl=10.0, fees=1.0, slippage=1.0)],
    )

    assert result["verdict"] == "EDGE_POSITIVE"


def test_negative_expectancy_with_sufficient_sample_returns_edge_negative(tmp_path: Path) -> None:
    result = run(
        tmp_path,
        prediction=trusted_prediction(selected_action="long", paper_fill_allowed=True, paper_eligible=True),
        execution_records=[closed_trade(gross_pnl=-10.0, fees=1.0, slippage=1.0)],
    )

    assert result["verdict"] == "EDGE_NEGATIVE"


def test_strict_verifier_failure_returns_edge_data_invalid(tmp_path: Path) -> None:
    result = run(tmp_path, strict_critical_failures=1)

    assert result["verdict"] == "EDGE_DATA_INVALID"
