"""Fail-closed tests for the paper entry gate's preloaded evidence boundary."""

from __future__ import annotations

from typing import Any

import pytest

from v2.backend.app.services.paper_trade_management.entry_gate import (
    evaluate_entry_gate,
)
from v2.backend.app.services.paper_trade_management.outcome_memory import (
    OutcomeMemoryBucket,
)


class _RedisMustNotBeRead:
    def __init__(self) -> None:
        self.get_calls: list[str] = []

    def get(self, key: str) -> str:
        self.get_calls.append(key)
        raise AssertionError(f"late Redis read after evidence preload: {key}")


def _healthy_outcome_bucket() -> OutcomeMemoryBucket:
    return OutcomeMemoryBucket(
        symbol="ETHUSDT",
        timeframe="1h",
        trade_count=12,
        rolling_win_rate=0.58,
        rolling_ev_bps=4.0,
        data_source="PRELOADED_TEST_SNAPSHOT",
    )


def _healthy_side_performance() -> dict[str, Any]:
    return {
        "schema_version": "paper_side_performance_v1",
        "sides": {
            "LONG": {
                "trade_count": 12,
                "expectancy_bps": 3.0,
                "profit_factor": 1.2,
                "brier_score": 0.10,
            },
            "SHORT": {
                "trade_count": 12,
                "expectancy_bps": 4.0,
                "profit_factor": 1.3,
                "brier_score": 0.10,
            },
        },
    }


def _preloaded_short_trend_kwargs(redis_client: Any) -> dict[str, Any]:
    return {
        "symbol": "ETHUSDT",
        "timeframe": "1h",
        "side": "short",
        "strategy_mode": "trend_mode",
        "confidence_calibrated": 0.75,
        "expected_move_after_cost_bps": -12.0,
        "outcome_memory_bucket": _healthy_outcome_bucket(),
        "side_performance": _healthy_side_performance(),
        "cascade_context": {
            "cascade_context_status": "PROXY_CONFIRMED",
            "cascade_risk_score": 0.45,
            "event_time": "2026-07-17T11:59:55.000000Z",
            "feature_cutoff": "2026-07-17T11:59:55.000000Z",
            "ingested_at": "2026-07-17T11:59:56.000000Z",
            "generated_at": "2026-07-17T11:59:57.000000Z",
            "available_at": "2026-07-17T11:59:58.000000Z",
            "decision_time": "2026-07-17T12:00:00.000000Z",
            "decision_time_safe": True,
        },
        "adaptive_confidence_floors": (0.60, 0.62),
        "runtime_evidence_preloaded": True,
        "redis_client": redis_client,
    }


def test_preloaded_evidence_is_immutable_against_late_redis_failure() -> None:
    redis_client = _RedisMustNotBeRead()

    first = evaluate_entry_gate(**_preloaded_short_trend_kwargs(redis_client))
    second = evaluate_entry_gate(**_preloaded_short_trend_kwargs(redis_client))

    assert first["allowed"] is True
    assert second == first
    assert first["runtime_evidence_preloaded"] is True
    assert first["confidence_floor"] == 0.62
    assert first["confidence_floor_source"] == "PRELOADED_ADAPTIVE_TUNING"
    assert redis_client.get_calls == []


@pytest.mark.parametrize(
    ("missing_input", "expected_reason"),
    [
        (
            "cascade_context",
            "RUNTIME_EVIDENCE_PRELOAD_MISSING:CASCADE_CONTEXT",
        ),
        (
            "adaptive_confidence_floors",
            "RUNTIME_EVIDENCE_PRELOAD_MISSING:ADAPTIVE_CONFIDENCE_FLOORS",
        ),
        (
            "outcome_memory_bucket",
            "RUNTIME_EVIDENCE_PRELOAD_MISSING:OUTCOME_MEMORY_BUCKET",
        ),
        (
            "side_performance",
            "RUNTIME_EVIDENCE_PRELOAD_MISSING:SIDE_PERFORMANCE",
        ),
    ],
)
def test_missing_relevant_preloaded_evidence_blocks_without_redis_fallback(
    missing_input: str,
    expected_reason: str,
) -> None:
    redis_client = _RedisMustNotBeRead()
    kwargs = _preloaded_short_trend_kwargs(redis_client)
    kwargs[missing_input] = None

    result = evaluate_entry_gate(**kwargs)

    assert result["allowed"] is False
    assert expected_reason in result["reasons"]
    assert redis_client.get_calls == []


@pytest.mark.parametrize(
    "invalid_floors",
    [
        (float("nan"), 0.60),
        (0.60, float("inf")),
        (-0.01, 0.60),
        (0.60, 1.01),
        (True, 0.60),
        ("not-a-number", 0.60),
        (0.60,),
    ],
)
def test_invalid_preloaded_adaptive_floors_fail_closed(
    invalid_floors: tuple[Any, ...],
) -> None:
    redis_client = _RedisMustNotBeRead()
    kwargs = _preloaded_short_trend_kwargs(redis_client)
    kwargs["adaptive_confidence_floors"] = invalid_floors

    result = evaluate_entry_gate(**kwargs)

    assert result["allowed"] is False
    assert "RUNTIME_EVIDENCE_PRELOAD_MISSING:ADAPTIVE_CONFIDENCE_FLOORS" in result["reasons"]
    assert result["confidence_floor_source"] == ("PRELOADED_RUNTIME_EVIDENCE_MISSING")
    assert redis_client.get_calls == []


def test_preloaded_non_short_trend_candidate_does_not_require_cascade_context() -> None:
    redis_client = _RedisMustNotBeRead()
    kwargs = _preloaded_short_trend_kwargs(redis_client)
    kwargs.update(
        side="long",
        strategy_mode="mean_reversion_mode",
        expected_move_after_cost_bps=12.0,
        cascade_context=None,
    )

    result = evaluate_entry_gate(**kwargs)

    assert result["allowed"] is True
    assert not any("CASCADE_CONTEXT" in reason for reason in result["reasons"])
    assert redis_client.get_calls == []
