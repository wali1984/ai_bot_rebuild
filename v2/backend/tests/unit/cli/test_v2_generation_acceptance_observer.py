from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.cli import v2_generation_acceptance_observer as observer


class FakeRedis:
    def __init__(self, values):
        self.values = {
            key: json.dumps(value) if not isinstance(value, str) else value
            for key, value in values.items()
        }
        self.writes = {}
        self.get_counts = {}

    def get(self, key):
        self.get_counts[key] = self.get_counts.get(key, 0) + 1
        return self.values.get(key)

    def getrange(self, key, start, end):
        value = self.values.get(key, "")
        return value[start : end + 1]

    def set(self, key, value, ex=None):
        self.writes[key] = (json.loads(value), ex)
        return True


def _values(*, admitted=False):
    cohort = "paper_serving_abi_v2:test"
    row = {
        "checkpoint_generation": 3,
        "paper_strategy_cohort_id": cohort,
        "prediction_id": "prediction-1",
        "intent_id": "intent-1",
        "preemptive_decision_id": "pec-1",
        "symbol": "BTCUSDT",
        "timeframe": "5m",
        "side": "long",
        "preemptive_action": "ALLOW" if admitted else "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
        "preemptive_allowed": admitted,
        "preemptive_block_reasons": [] if admitted else ["LOSS_PROBABILITY_TOO_HIGH"],
        "pre_trade_loss_probability": 0.7,
        "preemptive_decision_time": "2026-07-26T22:00:02Z",
        "preemptive_predicate_details": [
            {
                "predicate": "adaptive_model_loss_probability",
                "actual": 0.7,
                "required": "<0.65000000",
                "passed": False,
                "source_key": observer.ADAPTIVE_TUNING_KEY,
                "source_schema": "v2_adaptive_gate_tuning_state_v4",
                "source_timestamp": "2026-07-26T22:00:01Z",
                "decision_timestamp": "2026-07-26T22:00:02Z",
            }
        ],
        "expected_edge_after_cost_bps": 18.0,
        "exit_feasibility_score": 0.7,
        "confidence_overstatement_risk": 0.1,
        "continuous_edge_guardian_status": "ACTIVE",
    }
    return {
        observer.COHORT_KEY: {
            "checkpoint_generation": 3,
            "checkpoint_id": "checkpoint-3",
            "cohort_id": cohort,
        },
        observer.PREDICTION_STATUS_KEY: {
            "registry_generation": 3,
            "records_published": 10,
            "directional_records": 4,
        },
        observer.MATRIX_KEY: {
            "generated_utc": "2026-07-26T22:00:00Z",
            "candidate_count": 1,
            "rows": [row],
        },
        observer.PAPER_STATUS_KEY: {"cycle_state": "COMPLETED_CYCLE"},
        observer.ACCEPTED_FILLS_KEY: [],
        observer.OPEN_POSITIONS_KEY: [],
        observer.CLOSED_TRADES_KEY: [],
        observer.ACCOUNT_STATUS_KEY: {
            "used_margin_usd": 0.0,
            "newly_reserved_margin_usd": 0.0,
        },
        f"{observer.PAPER_SIGNALS_KEY}:BTCUSDT:5m": {
            "prediction_id": "prediction-1",
            "available_at": "2026-07-26T22:00:00Z",
            "ordinary_paper_effective_microstructure_action": "ALLOW",
        },
        observer.ADAPTIVE_TUNING_KEY: {
            "adaptive_loss_probability_threshold": 0.65,
        },
    }


def test_capture_cycle_preserves_generation_attribution() -> None:
    cycle = observer.capture_cycle(
        FakeRedis(_values()),
        observed_at=datetime(2026, 7, 26, 22, 0, 3, tzinfo=UTC),
    )

    assert cycle["generation_predictions"] == 10
    assert cycle["generation_directional_predictions"] == 4
    assert cycle["candidates_evaluated"] == 1
    assert cycle["candidates_admitted"] == 0
    assert cycle["rejections_by_reason"] == {"LOSS_PROBABILITY_TOO_HIGH": 1}
    attribution = cycle["candidate_attribution"][0]
    assert attribution["model_loss_probability"] == 0.7
    assert attribution["required_max_loss_probability"] == 0.65
    assert attribution["required_min_profit_probability"] == 0.35
    assert attribution["microstructure_action"] == "ALLOW"
    assert attribution["evidence_age_seconds"] == 2.0
    assert attribution["expected_edge_after_cost_bps"] == 18.0
    assert attribution["exit_feasibility_score"] == 0.7
    assert attribution["preemptive_predicate_details"][0]["actual"] == 0.7
    assert cycle["generic_microstructure_blocks"] == 0
    assert cycle["exact_predicate_details_present"] is True
    assert cycle["reservation_leak_count"] == 0


def test_capture_cycle_counts_only_unstructured_microstructure_blocks_as_generic() -> None:
    values = _values()
    row = values[observer.MATRIX_KEY]["rows"][0]
    row["preemptive_action"] = "BLOCK_MICROSTRUCTURE_UNSAFE"
    row["preemptive_predicate_details"] = [
        {
            "predicate": "microstructure_action",
            "actual": "SHADOW_ONLY",
            "required": "ALLOW_OR_REDUCE_SIZE",
            "passed": False,
            "source_key": "v2:microstructure:trust_score:BTCUSDT:5m",
            "source_schema": "microstructure_trust_score_v2",
            "source_timestamp": "2026-07-26T22:00:01Z",
            "decision_timestamp": "2026-07-26T22:00:02Z",
        }
    ]

    cycle = observer.capture_cycle(
        FakeRedis(values),
        observed_at=datetime(2026, 7, 26, 22, 0, 3, tzinfo=UTC),
    )

    assert cycle["generic_microstructure_blocks"] == 0
    attribution = cycle["candidate_attribution"][0]
    assert attribution["exact_microstructure_predicate_detail_present"] is True
    assert attribution["generic_microstructure_block"] is False


def test_status_classifies_only_after_both_bounds() -> None:
    first = datetime(2026, 7, 26, 20, 0, tzinfo=UTC)
    cycles = []
    for index in range(50):
        cycles.append(
            {
                "observed_utc": observer._iso(first + timedelta(minutes=index)),
                "cycle_generated_utc": observer._iso(
                    first + timedelta(minutes=index)
                ),
                "checkpoint_generation": 3,
                "checkpoint_id": "checkpoint-3",
                "cohort_id": "cohort-3",
                "generation_predictions": 10,
                "generation_directional_predictions": 4,
                "candidates_evaluated": 2,
                "candidates_admitted": 0,
                "rejections_by_reason": {"LOSS_PROBABILITY_TOO_HIGH": 2},
                "rejections_by_primary_action": {
                    "BLOCK_LOSS_PROBABILITY_TOO_HIGH": 2
                },
                "candidate_attribution": [
                    {
                        "symbol": "BTCUSDT",
                        "timeframe": "5m",
                        "blocker": "BLOCK_LOSS_PROBABILITY_TOO_HIGH",
                    }
                ],
            }
        )

    before_session = observer.build_status(
        cycles,
        minimum_cycles=50,
        minimum_observation_seconds=14_400,
        now=first + timedelta(hours=3),
    )
    complete = observer.build_status(
        cycles,
        minimum_cycles=50,
        minimum_observation_seconds=14_400,
        now=first + timedelta(hours=4),
    )

    assert before_session["cycle_requirement_satisfied"] is True
    assert before_session["market_session_requirement_satisfied"] is False
    assert before_session["classification"] == (
        "OBSERVING_BOUNDED_NATURAL_OPPORTUNITY_WINDOW"
    )
    assert complete["classification"] == "GENERATION_3_ADMISSION_STARVATION"
    assert complete["market_session_definition"] == (
        "ONE_FULL_MAXIMUM_ELIGIBLE_TIMEFRAME_WINDOW_1H_CONTINUOUS_CRYPTO_MARKET"
    )
    blocker = complete["blocker_attribution"]["BLOCK_LOSS_PROBABILITY_TOO_HIGH"]
    assert blocker["count"] == 50
    assert blocker["percentage_of_evaluated"] == 50.0
    assert blocker["symbols"] == {"BTCUSDT": 50}
    assert blocker["timeframes"] == {"5m": 50}


def test_observe_once_deduplicates_matrix_cycle(tmp_path) -> None:
    client = FakeRedis(_values(admitted=False))
    archive = tmp_path / "cycles.jsonl"
    status = tmp_path / "status.json"

    first = observer.observe_once(
        client,
        archive_path=archive,
        status_path=status,
        minimum_cycles=50,
        minimum_observation_seconds=14_400,
    )
    second = observer.observe_once(
        client,
        archive_path=archive,
        status_path=status,
        minimum_cycles=50,
        minimum_observation_seconds=14_400,
    )

    assert first["completed_cycles"] == 1
    assert second["completed_cycles"] == 1
    assert second["classification"] == "OBSERVING_BOUNDED_NATURAL_OPPORTUNITY_WINDOW"
    assert len(archive.read_text().splitlines()) == 1
    assert client.writes[observer.STATUS_KEY][1] == 900
    assert json.loads(status.read_text())["completed_cycles"] == 1
    assert client.get_counts[f"{observer.PAPER_SIGNALS_KEY}:BTCUSDT:5m"] == 1


def test_observe_once_fails_closed_when_generation_archive_changes(tmp_path) -> None:
    client = FakeRedis(_values())
    archive = tmp_path / "cycles.jsonl"
    archive.write_text(
        json.dumps(
            {
                "observed_utc": "2026-07-26T21:00:00Z",
                "cycle_generated_utc": "2026-07-26T21:00:00Z",
                "checkpoint_generation": 2,
                "checkpoint_id": "checkpoint-2",
                "cohort_id": "cohort-2",
            }
        )
        + "\n"
    )

    with pytest.raises(
        RuntimeError, match="OBSERVATION_GENERATION_OR_COHORT_CHANGED"
    ):
        observer.observe_once(
            client,
            archive_path=archive,
            status_path=tmp_path / "status.json",
            minimum_cycles=50,
            minimum_observation_seconds=14_400,
        )


def test_log_projection_excludes_large_attribution_payload() -> None:
    projected = observer._log_projection(  # noqa: SLF001
        {
            "classification": "OBSERVING_BOUNDED_NATURAL_OPPORTUNITY_WINDOW",
            "completed_cycles": 3,
            "candidate_attribution": [{"large": "payload"}],
            "blocker_attribution": {"large": "payload"},
            "places_real_order": False,
        }
    )

    assert projected == {
        "classification": "OBSERVING_BOUNDED_NATURAL_OPPORTUNITY_WINDOW",
        "completed_cycles": 3,
        "places_real_order": False,
    }


def test_restart_capture_persists_first_natural_governed_position(tmp_path) -> None:
    values = _values()
    cohort = "paper_serving_abi_v2:test"
    values[observer.OPEN_POSITIONS_KEY] = [
        {
            "position_id": "position-3",
            "checkpoint_generation": 3,
            "paper_strategy_cohort_id": cohort,
            "prediction_id": "prediction-3",
            "intent_id": "intent-3",
            "fill_id": "fill-3",
            "paper_only": True,
            "symbol": "BTCUSDT",
            "side": "long",
            "quantity": 0.01,
            "entry_price": 100_000.0,
            "mandatory_stop": 99_000.0,
        }
    ]
    values[observer.ACCEPTED_FILLS_KEY] = [
        {
            "fill_id": "fill-3",
            "checkpoint_generation": 3,
            "paper_strategy_cohort_id": cohort,
            "paper_only": True,
        }
    ]
    client = FakeRedis(values)
    capture_path = tmp_path / "restart.jsonl"

    first = observer.capture_restart_pending_if_needed(
        client, archive_path=capture_path
    )
    second = observer.capture_restart_pending_if_needed(
        client, archive_path=capture_path
    )

    assert first is not None
    assert first["position_ids"] == ["position-3"]
    assert first["generation_fills"][0]["fill_id"] == "fill-3"
    assert first["accounting_snapshot"]["used_margin_usd"] == 0.0
    assert first["places_real_order"] is False
    assert second is None
    assert len(capture_path.read_text().splitlines()) == 1
    assert client.writes[observer.RESTART_PENDING_KEY][1] == 900
