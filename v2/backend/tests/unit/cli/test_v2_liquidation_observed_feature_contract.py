from __future__ import annotations

import importlib


class FakeRedis:
    def __init__(self) -> None:
        self.get_calls: list[str] = []
        self.xrange_calls = 0

    def get(self, key: str):
        self.get_calls.append(key)
        raise AssertionError("unauthenticated liquidation aggregates must not be read")

    def xrange(self, *_args, **_kwargs):
        self.xrange_calls += 1
        raise AssertionError("the 24h feature reader must never scan the stream")


def _loop():
    return importlib.import_module(
        "v2.backend.app.cli.v2_feature_pipeline_native_loop"
    )


def test_observed_aggregate_is_masked_without_authenticated_complete_capture() -> None:
    mod = _loop()
    redis = FakeRedis()

    value = mod._read_liq_notional_24h(  # noqa: SLF001
        redis,
        "btcusdt",
        decision_ms=1_800_000_100_000,
    )

    assert value is None
    assert redis.get_calls == []
    assert redis.xrange_calls == 0


def test_none_client_is_masked_not_zero_filled() -> None:
    mod = _loop()

    assert (
        mod._read_liq_notional_24h(  # noqa: SLF001
            None,
            "BTCUSDT",
            decision_ms=1_800_000_100_000,
        )
        is None
    )


def test_invalid_decision_clock_cannot_unmask_liquidation_feature() -> None:
    mod = _loop()
    redis = FakeRedis()

    assert (
        mod._read_liq_notional_24h(  # noqa: SLF001
            redis,
            "BTCUSDT",
            decision_ms=True,
        )
        is None
    )
    assert redis.get_calls == []


def test_legacy_aggregate_and_entire_stream_are_not_read() -> None:
    mod = _loop()
    redis = FakeRedis()

    assert (
        mod._read_liq_notional_24h(  # noqa: SLF001
            redis,
            "BTCUSDT",
            decision_ms=1_800_000_100_000,
        )
        is None
    )
    assert redis.get_calls == []
    assert redis.xrange_calls == 0
