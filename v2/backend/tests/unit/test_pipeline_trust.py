from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

import pytest

from app.cli.verify_pipeline_trust import main

BASE_MS = 1_700_000_000_000
CLOSE_MS = BASE_MS + 3_600_000
DECISION_MS = CLOSE_MS + 1_000
SYMBOL = "BTCUSDT"

TF_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
}


def wrapped(key: str, value: Any) -> dict[str, Any]:
    return {"record_type": key, "value": value}


def candle(
    timeframe: str,
    open_time: int,
    *,
    exchange: str = "binance",
    closed: bool = True,
    close_price: float = 100.5,
    volume: float = 10.0,
) -> dict[str, Any]:
    open_price = 100.0
    high = max(open_price, close_price) + 1.0
    low = min(open_price, close_price) - 1.0
    return {
        "exchange": exchange,
        "symbol": SYMBOL,
        "timeframe": timeframe,
        "open_time": open_time,
        "close_time": open_time + TF_MS[timeframe],
        "open": open_price,
        "high": high,
        "low": low,
        "close": close_price,
        "volume": volume,
        "closed_candle": closed,
    }


def clean_candles() -> list[dict[str, Any]]:
    return [
        candle("1h", CLOSE_MS - TF_MS["1h"]),
        candle("15m", CLOSE_MS - TF_MS["15m"]),
        candle("5m", CLOSE_MS - TF_MS["5m"]),
        candle("1m", CLOSE_MS - TF_MS["1m"]),
    ]


def clean_feature(**overrides: Any) -> dict[str, Any]:
    feature = {
        "symbol": SYMBOL,
        "timeframe": "1m",
        "generated_at": DECISION_MS,
        "feature_cutoff": CLOSE_MS,
        "available_at": CLOSE_MS,
        "source_candle_timestamps": [CLOSE_MS],
        "feature_version": "synthetic-v1",
        "feature_hash": "feature-clean-1",
        "feature_freshness_state": "CURRENT",
        "stale_feature_flags": [],
        "features": {"ret_pct": 0.005, "range_pct": 0.01},
    }
    feature.update(overrides)
    return feature


def clean_decision(**overrides: Any) -> dict[str, Any]:
    decision = {
        "prediction_id": "synthetic-prediction-clean-1",
        "symbol": SYMBOL,
        "timeframe": "1m",
        "decision_time": DECISION_MS,
        "decision_cutoff": CLOSE_MS,
        "feature_hash": "feature-clean-1",
        "masa_generated_at": CLOSE_MS,
        "masa_feature_cutoff": CLOSE_MS,
        "masa_forecast_horizon": "1m",
        "ppo_observation_time": CLOSE_MS,
        "ppo_feature_cutoff": CLOSE_MS,
        "selected_action": "hold",
        "masa_signal": 0.5,
        "blocked": False,
        "block_reason": "none",
    }
    decision.update(overrides)
    return decision


def clean_training_sample(**overrides: Any) -> dict[str, Any]:
    sample = {
        "sample_id": "synthetic-sample-clean-1",
        "symbol": SYMBOL,
        "timeframe": "1m",
        "row_classification": "TRAINABLE",
        "used_for_training": True,
        "feature_cutoff": CLOSE_MS,
        "label_start_time": CLOSE_MS,
        "label_end_time": CLOSE_MS + 60_000,
        "prediction_horizon_seconds": 60,
        "features": {"ret_pct": 0.005, "range_pct": 0.01},
        "fee_bps": 5,
        "slippage_bps": 2,
        "execution_result": {"fill_status": "hold", "reason": "hold"},
    }
    sample.update(overrides)
    return sample


def clean_execution(**overrides: Any) -> dict[str, Any]:
    execution = {
        "execution_id": "synthetic-execution-clean-1",
        "position_before": "flat",
        "requested_action": "hold",
        "position_after": "flat",
        "exchange_response": {"status": "not_submitted", "reason": "hold"},
        "fill_status": "none",
        "local_position": "flat",
        "exchange_position": "flat",
    }
    execution.update(overrides)
    return execution


def clean_config(**overrides: Any) -> dict[str, Any]:
    config = {
        "worker_id": "v2_config_admin_manager",
        "live_gate": "blocked_human_only",
        "current_gate_state": "blocked_human_only",
        "settings_by_risk_class": {"safe": 3, "dangerous": 0},
        "dangerous_settings_pending_approval": [],
        "approval_token_created": False,
        "approval_token_self_creatable": False,
        "secrets_written_to_payload": False,
        "old_redis_write": False,
        "exchange_action_taken": False,
        "leverage_or_margin_change": False,
    }
    config.update(overrides)
    return config


def evidence_records(
    *,
    candles: list[dict[str, Any]] | None = None,
    features: list[dict[str, Any]] | None = None,
    decisions: list[dict[str, Any]] | None = None,
    training_samples: list[dict[str, Any]] | None = None,
    execution_records: list[dict[str, Any]] | None = None,
    config_records: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    return [
        wrapped("candles", clean_candles() if candles is None else candles),
        wrapped("features", [clean_feature()] if features is None else features),
        wrapped("model_decisions", [clean_decision()] if decisions is None else decisions),
        wrapped("training_samples", [clean_training_sample()] if training_samples is None else training_samples),
        wrapped("execution_records", [clean_execution()] if execution_records is None else execution_records),
        wrapped("config_admin", [clean_config()] if config_records is None else config_records),
    ]


def run_case(tmp_path: Path, records: list[dict[str, Any]]) -> tuple[int, dict[str, Any], Path]:
    input_path = tmp_path / "synthetic_pipeline_trust.jsonl"
    output_dir = tmp_path / "report"
    input_path.write_text("\n".join(json.dumps(record) for record in records) + "\n", encoding="utf-8")
    exit_code = main(["--input", str(input_path), "--output-dir", str(output_dir)])
    report = json.loads((output_dir / "pipeline_trust_report.json").read_text(encoding="utf-8"))
    return exit_code, report, output_dir


def finding_ids(report: dict[str, Any]) -> set[str]:
    return {finding["check_id"] for finding in report["findings"]}


def finding_by_id(report: dict[str, Any], check_id: str) -> dict[str, Any]:
    for finding in report["findings"]:
        if finding["check_id"] == check_id:
            return finding
    raise AssertionError(f"missing finding {check_id}; available={sorted(finding_ids(report))}")


def assert_explicit_finding(report: dict[str, Any], check_id: str) -> None:
    finding = finding_by_id(report, check_id)
    assert finding["status"] in {"FAIL", "WARN", "PASS"}, f"{check_id} has no explicit status"
    assert finding["severity"], f"{check_id} has no severity"
    assert finding["affected_modules"], f"{check_id} has no affected modules"
    assert finding["recommended_fix"], f"{check_id} has no recommended fix"


def assert_critical_exit_matches_report(exit_code: int, report: dict[str, Any]) -> None:
    critical_failures = report["summary"]["critical_failures"]
    if critical_failures:
        assert exit_code != 0, "critical trust failures must cause a non-zero verifier exit"
    else:
        assert exit_code == 0, "verifier should exit zero when no critical failures are present"


def assert_blocked_decision_is_logged(report: dict[str, Any], check_id: str) -> None:
    finding = finding_by_id(report, check_id)
    assert finding["status"] == "FAIL", f"{check_id} must fail for dirty evidence"
    assert finding["title"], f"{check_id} must state the safety condition"
    assert finding["example_records"], f"{check_id} must include example records"
    assert finding["recommended_fix"], f"{check_id} must include explicit failure remediation"


def assert_clean_replayable(report: dict[str, Any], output_dir: Path) -> None:
    assert report["summary"]["critical_failures"] == 0
    assert (output_dir / "pipeline_trust_report.json").exists()
    assert (output_dir / "pipeline_trust_report.md").exists()
    assert_explicit_finding(report, "feature_integrity.pass")
    assert_explicit_finding(report, "masa_ppo.pass")
    assert_explicit_finding(report, "training_samples.pass")
    assert_explicit_finding(report, "execution.pass")
    assert_explicit_finding(report, "config.pass")


def scenario_missing_candle() -> list[dict[str, Any]]:
    candles = clean_candles()
    candles.extend(
        [
            candle("1m", CLOSE_MS - 180_000),
            candle("1m", CLOSE_MS - 60_000),
        ]
    )
    return evidence_records(
        candles=candles,
        training_samples=[
            clean_training_sample(
                sample_id="missing-candle-dirty-training",
                row_classification="MISSING_MASKED",
                missing_candles=True,
                used_for_training=True,
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="missing_candle")],
    )


def scenario_duplicate_candle() -> list[dict[str, Any]]:
    duplicate = candle("1m", CLOSE_MS - TF_MS["1m"])
    return evidence_records(
        candles=clean_candles() + [duplicate],
        training_samples=[clean_training_sample(used_for_training=False, trainer_consumable=False)],
        decisions=[clean_decision(blocked=True, block_reason="duplicate_candle")],
    )


def scenario_out_of_order_candle() -> list[dict[str, Any]]:
    candles = [
        candle("1h", CLOSE_MS - TF_MS["1h"]),
        candle("15m", CLOSE_MS - TF_MS["15m"]),
        candle("5m", CLOSE_MS - TF_MS["5m"]),
        candle("1m", CLOSE_MS - TF_MS["1m"]),
        candle("1m", CLOSE_MS - 2 * TF_MS["1m"]),
    ]
    return evidence_records(
        candles=candles,
        training_samples=[clean_training_sample(used_for_training=False, trainer_consumable=False)],
        decisions=[clean_decision(blocked=True, block_reason="out_of_order_candle")],
    )


def scenario_unfinished_higher_timeframe() -> list[dict[str, Any]]:
    candles = clean_candles()
    candles[0] = candle("1h", CLOSE_MS - TF_MS["1h"], closed=False)
    return evidence_records(candles=candles, decisions=[clean_decision(blocked=True, block_reason="unfinished_htf")])


def scenario_future_feature_available_at() -> list[dict[str, Any]]:
    return evidence_records(
        features=[clean_feature(available_at=DECISION_MS + 60_000)],
        decisions=[clean_decision(blocked=True, block_reason="feature_available_after_decision")],
    )


def scenario_masa_future_cutoff() -> list[dict[str, Any]]:
    return evidence_records(
        decisions=[
            clean_decision(
                blocked=True,
                block_reason="masa_future_cutoff",
                masa_feature_cutoff=DECISION_MS + 60_000,
            )
        ]
    )


def scenario_masa_ppo_cutoff_mismatch() -> list[dict[str, Any]]:
    return evidence_records(
        decisions=[
            clean_decision(
                blocked=True,
                block_reason="masa_ppo_cutoff_mismatch",
                masa_feature_cutoff=CLOSE_MS - 60_000,
                ppo_feature_cutoff=CLOSE_MS,
            )
        ]
    )


def scenario_null_features() -> list[dict[str, Any]]:
    return evidence_records(
        features=[clean_feature(features={"ret_pct": None, "range_pct": 0.01})],
        training_samples=[
            clean_training_sample(
                sample_id="null-feature-dirty-training",
                row_classification="TRAINABLE",
                used_for_training=True,
                features={"ret_pct": None, "range_pct": 0.01},
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="invalid_feature_values")],
    )


def scenario_backfilled_marked_live() -> list[dict[str, Any]]:
    return evidence_records(
        training_samples=[
            clean_training_sample(
                sample_id="backfilled-live-dirty-training",
                row_classification="TRAINABLE",
                used_for_training=True,
                source_mode="live",
                backfilled=True,
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="backfilled_marked_live")],
    )


def scenario_stale_event_message() -> list[dict[str, Any]]:
    return evidence_records(
        features=[
            clean_feature(
                feature_freshness_state="STALE",
                stale_feature_flags=["v2:market:ohlcv:binance:BTCUSDT:1m"],
            )
        ],
        training_samples=[
            clean_training_sample(
                sample_id="stale-event-dirty-training",
                row_classification="STALE_MASKED",
                used_for_training=True,
                stale_feature_flags=["v2:market:ohlcv:binance:BTCUSDT:1m"],
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="stale_event_message")],
    )


def scenario_source_disagreement() -> list[dict[str, Any]]:
    candles = [
        candle("1h", CLOSE_MS - TF_MS["1h"]),
        candle("15m", CLOSE_MS - TF_MS["15m"]),
        candle("5m", CLOSE_MS - TF_MS["5m"]),
        candle("1m", CLOSE_MS - TF_MS["1m"], exchange="binance", close_price=100.0),
        candle("1m", CLOSE_MS - TF_MS["1m"], exchange="kucoin", close_price=112.0),
        candle("1m", CLOSE_MS - TF_MS["1m"], exchange="coinapi", close_price=88.0),
        candle("1m", CLOSE_MS - TF_MS["1m"], exchange="coinank", close_price=125.0),
    ]
    return evidence_records(
        candles=candles,
        training_samples=[clean_training_sample(used_for_training=False, trainer_consumable=False)],
        decisions=[clean_decision(blocked=True, block_reason="source_disagreement")],
    )


def scenario_invalid_position_transition() -> list[dict[str, Any]]:
    return evidence_records(
        execution_records=[
            clean_execution(
                position_before="long",
                requested_action="open_short",
                position_after="short",
                fill_status="filled",
                local_position="short",
                exchange_position="short",
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="invalid_position_transition")],
    )


def scenario_local_exchange_drift() -> list[dict[str, Any]]:
    return evidence_records(
        execution_records=[
            clean_execution(
                position_before="long",
                requested_action="hold",
                position_after="long",
                fill_status="none",
                local_position="long",
                exchange_position="flat",
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="position_drift")],
    )


def scenario_partial_fill_handled() -> list[dict[str, Any]]:
    return evidence_records(
        execution_records=[
            clean_execution(
                position_before="flat",
                requested_action="open_long",
                position_after={"side": "long", "qty": 0.5},
                fill_status="partial_filled",
                partial_fill_handled=True,
                filled_qty=0.5,
                remaining_qty=0.5,
                average_fill_price=100.25,
                fee_bps=5,
                local_position={"side": "long", "qty": 0.5},
                exchange_position={"side": "long", "qty": 0.5},
            )
        ],
        training_samples=[
            clean_training_sample(
                sample_id="partial-fill-actual-training",
                execution_result={"fill_status": "partial_filled", "filled_qty": 0.5, "remaining_qty": 0.5},
                fee_bps=5,
                slippage_bps=2,
            )
        ],
    )


def scenario_rejected_canceled_order_clean() -> list[dict[str, Any]]:
    return evidence_records(
        execution_records=[
            clean_execution(
                position_before="flat",
                requested_action="open_long",
                position_after="flat",
                fill_status="rejected",
                exchange_response={"status": "rejected", "reason": "synthetic_reject"},
                local_position="flat",
                exchange_position="flat",
            )
        ],
        training_samples=[
            clean_training_sample(
                sample_id="rejected-order-not-trained",
                used_for_training=False,
                trainer_consumable=False,
                fill_status="rejected",
                execution_result={"fill_status": "rejected"},
            )
        ],
    )


def scenario_rejected_canceled_order_false_positive_training() -> list[dict[str, Any]]:
    return evidence_records(
        execution_records=[
            clean_execution(
                position_before="flat",
                requested_action="open_long",
                position_after="flat",
                fill_status="rejected",
                exchange_response={"status": "rejected", "reason": "synthetic_reject"},
                local_position="flat",
                exchange_position="flat",
            )
        ],
        training_samples=[
            clean_training_sample(
                sample_id="rejected-order-false-positive-training",
                used_for_training=True,
                fill_status="rejected",
                positive_training_sample=True,
                label_action="open_long",
                execution_result={"fill_status": "rejected"},
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="rejected_order_false_positive_training")],
    )


def scenario_config_admin_unsafe_mutation() -> list[dict[str, Any]]:
    return evidence_records(
        config_records=[
            clean_config(
                live_gate="enabled",
                dangerous_settings_pending_approval=["live_order_submit_enabled"],
                approval_token_created=True,
                secrets_written_to_payload=True,
                old_redis_write=True,
                exchange_action_taken=True,
                leverage_or_margin_change=True,
            )
        ],
        decisions=[clean_decision(blocked=True, block_reason="unsafe_config_admin_state")],
    )


DIRTY_OR_FLAGGED_SCENARIOS: list[tuple[str, Callable[[], list[dict[str, Any]]], set[str]]] = [
    ("missing_candle", scenario_missing_candle, {"candle_integrity.missing", "training_samples.dirty_accepted"}),
    ("duplicate_candle", scenario_duplicate_candle, {"candle_integrity.duplicates"}),
    ("out_of_order_candle", scenario_out_of_order_candle, {"candle_integrity.out_of_order"}),
    ("unfinished_higher_timeframe_candle", scenario_unfinished_higher_timeframe, {"mtf_alignment.unfinished_higher_tf"}),
    ("future_feature_available_at", scenario_future_feature_available_at, {"feature_integrity.future_use"}),
    ("masa_future_cutoff", scenario_masa_future_cutoff, {"masa_ppo.masa_future_cutoff"}),
    ("masa_ppo_cutoff_mismatch", scenario_masa_ppo_cutoff_mismatch, {"masa_ppo.cutoff_mismatch"}),
    ("nan_inf_null_features", scenario_null_features, {"feature_integrity.invalid_values", "training_samples.dirty_accepted"}),
    ("backfilled_data_marked_live", scenario_backfilled_marked_live, {"training_samples.backfilled_accepted"}),
    ("stale_redis_event_message", scenario_stale_event_message, {"feature_integrity.stale", "training_samples.dirty_accepted"}),
    ("source_disagreement", scenario_source_disagreement, {"candle_integrity.source_disagreement"}),
    ("invalid_position_transition", scenario_invalid_position_transition, {"execution.invalid_transition"}),
    ("local_exchange_position_drift", scenario_local_exchange_drift, {"execution.position_drift"}),
    (
        "config_admin_unsafe_mutation",
        scenario_config_admin_unsafe_mutation,
        {"config.secrets_in_payload", "config.self_approval", "config.mutation_marker"},
    ),
]


def test_clean_data_path_is_accepted_and_replayable(tmp_path: Path) -> None:
    exit_code, report, output_dir = run_case(tmp_path, evidence_records())

    assert exit_code == 0
    assert_clean_replayable(report, output_dir)


@pytest.mark.parametrize(("scenario_name", "factory", "required_findings"), DIRTY_OR_FLAGGED_SCENARIOS)
def test_dirty_or_corrupted_data_is_flagged_before_training_and_execution(
    tmp_path: Path,
    scenario_name: str,
    factory: Callable[[], list[dict[str, Any]]],
    required_findings: set[str],
) -> None:
    exit_code, report, _output_dir = run_case(tmp_path, factory())

    assert required_findings <= finding_ids(report), f"{scenario_name} missing required findings"
    for check_id in required_findings:
        assert_explicit_finding(report, check_id)
        if finding_by_id(report, check_id)["status"] == "FAIL":
            assert_blocked_decision_is_logged(report, check_id)
    assert_critical_exit_matches_report(exit_code, report)


@pytest.mark.parametrize(
    ("scenario_name", "factory", "forbidden_findings"),
    [
        ("partial_fill", scenario_partial_fill_handled, {"execution.partial_unhandled", "training_samples.missing_execution_result"}),
        ("rejected_canceled_order", scenario_rejected_canceled_order_clean, {"execution.rejected_changed_position", "training_samples.rejected_order_positive"}),
    ],
)
def test_handled_execution_edge_cases_are_accepted_without_false_training_or_position_updates(
    tmp_path: Path,
    scenario_name: str,
    factory: Callable[[], list[dict[str, Any]]],
    forbidden_findings: set[str],
) -> None:
    exit_code, report, output_dir = run_case(tmp_path, factory())

    assert exit_code == 0, scenario_name
    assert_clean_replayable(report, output_dir)
    assert not (forbidden_findings & finding_ids(report)), f"{scenario_name} produced forbidden safety findings"


def test_rejected_or_canceled_order_cannot_become_false_positive_training_sample(tmp_path: Path) -> None:
    exit_code, report, _output_dir = run_case(tmp_path, scenario_rejected_canceled_order_false_positive_training())

    assert exit_code != 0
    assert_blocked_decision_is_logged(report, "training_samples.rejected_order_positive")
    assert_critical_exit_matches_report(exit_code, report)
