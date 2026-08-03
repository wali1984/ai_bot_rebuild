from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from v2.backend.app.services.a_plus_trade_gate.service import (
    APlusGateConfig,
    _fresh,
    _htf_check,
    _regime_check,
    _tape_check,
    load_a_plus_context,
)


class FakeRedis:
    def __init__(self, payloads: dict[str, object]) -> None:
        self.payloads = {
            key: json.dumps(value)
            for key, value in payloads.items()
        }

    def get(self, key: str) -> str | None:
        return self.payloads.get(key)


def test_load_a_plus_context_falls_back_to_1m_microstructure_trust() -> None:
    redis = FakeRedis(
        {
            "v2:microstructure:trust_score:BTCUSDT:1m": {
                "generated_utc": "2026-07-06T12:00:00Z",
                "microstructure_trust_score": 0.73,
            }
        }
    )

    context = load_a_plus_context(redis, symbol="btcusdt", timeframe="15m")

    assert context["microstructure_trust"]["microstructure_trust_score"] == 0.73
    assert context["microstructure_trust_source_key"] == (
        "v2:microstructure:trust_score:BTCUSDT:1m"
    )
    assert context["microstructure_trust_lookup_keys"] == [
        "v2:microstructure:trust_score:BTCUSDT:15m",
        "v2:microstructure:trust_score:BTCUSDT:1m",
        "v2:microstructure:feed_quality:binance:BTCUSDT",
    ]


def _run_freshness_guard(
    context_name: str,
    payload: dict[str, object],
    *,
    now: datetime,
) -> dict[str, object]:
    config = APlusGateConfig()
    if context_name == "regime":
        return _regime_check(
            regime_decision=payload,
            strategy_id="trend_mode",
            side="long",
            trade_tape={},
            microstructure_trust={},
            now=now,
            config=config,
        )
    if context_name == "htf":
        return _htf_check(
            htf_context=payload,
            cross_asset=None,
            side="long",
            entry_timeframe_trend="UP",
            now=now,
            config=config,
        )
    return _tape_check(
        trade_tape=payload,
        side="long",
        now=now,
        config=config,
    )


@pytest.mark.parametrize(
    ("context_name", "expected_reason"),
    (
        ("regime", "REGIME_DECISION_STALE"),
        ("htf", "HTF_CONTEXT_STALE"),
        ("tape", "TRADE_TAPE_STALE"),
    ),
)
@pytest.mark.parametrize("clock_field", ("generated_utc", "available_at"))
@pytest.mark.parametrize(
    "adversarial_timestamp",
    (
        "2026-07-06T12:00:00",
        "2026-07-06T12:00:01Z",
    ),
    ids=("naive", "future"),
)
def test_context_freshness_rejects_naive_and_future_clocks(
    context_name: str,
    expected_reason: str,
    clock_field: str,
    adversarial_timestamp: str,
) -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
    payload: dict[str, object] = {"generated_utc": "2026-07-06T11:59:59Z"}
    payload[clock_field] = adversarial_timestamp

    result = _run_freshness_guard(context_name, payload, now=now)

    assert result["passed"] is False
    assert result["missing_evidence"] is True
    assert result["reason"] == expected_reason


def test_fresh_keeps_generation_and_availability_as_distinct_required_clocks() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    assert _fresh(
        {
            "generated_utc": "2026-07-06T11:59:50Z",
            "available_at": "2026-07-06T11:59:51Z",
        },
        max_age_seconds=30.0,
        now=now,
    ) is True
    assert _fresh(
        {"available_at": "2026-07-06T11:59:51Z"},
        max_age_seconds=30.0,
        now=now,
    ) is False
    assert _fresh(
        {
            "generated_utc": "2026-07-06T11:00:00Z",
            "available_at": "2026-07-06T11:59:59Z",
        },
        max_age_seconds=30.0,
        now=now,
    ) is False


def test_fresh_accepts_fresh_legacy_generation_clock_without_relabelling_it() -> None:
    now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)

    assert _fresh(
        {"generated_utc": "2026-07-06T11:59:59Z"},
        max_age_seconds=30.0,
        now=now,
    ) is True
