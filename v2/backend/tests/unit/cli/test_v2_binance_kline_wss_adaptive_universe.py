from __future__ import annotations

import argparse
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.cli import v2_binance_kline_wss_loop as module


def _args(**overrides: object) -> argparse.Namespace:
    values: dict[str, object] = {
        "symbols": "auto",
        "max_symbols": 0,
        "timeframes": "1m,5m",
        "max_streams_per_connection": 3,
        "total_seconds": 86_400.0,
        "max_seconds_per_session": 600.0,
        "universe_refresh_seconds": 600.0,
        "loop": True,
    }
    values.update(overrides)
    return argparse.Namespace(**values)


def test_runtime_stream_plan_re_resolves_current_adaptive_universe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolved = iter(
        (
            ("BTCUSDT",),
            ("BTCUSDT", "ETHUSDT", "SOLUSDT"),
        )
    )
    monkeypatch.setattr(
        module,
        "_resolve_symbols",
        lambda *_args, **_kwargs: next(resolved),
    )
    args = _args()

    first_symbols, first_timeframes, first_chunks = module._runtime_stream_plan(args)
    second_symbols, second_timeframes, second_chunks = module._runtime_stream_plan(args)

    assert first_symbols == ("BTCUSDT",)
    assert second_symbols == ("BTCUSDT", "ETHUSDT", "SOLUSDT")
    assert first_timeframes == second_timeframes == ("1m", "5m")
    assert first_chunks == [("btcusdt@kline_1m", "btcusdt@kline_5m")]
    assert second_chunks == [
        (
            "btcusdt@kline_1m",
            "btcusdt@kline_5m",
            "ethusdt@kline_1m",
        ),
        (
            "ethusdt@kline_5m",
            "solusdt@kline_1m",
            "solusdt@kline_5m",
        ),
    ]


@pytest.mark.parametrize("max_candles", [0, -1, True, 1501])
def test_runtime_stream_plan_rejects_invalid_closed_window_row_bound(
    max_candles: object,
) -> None:
    with pytest.raises(ValueError, match="^closed_window_max_candles_invalid$"):
        module._runtime_stream_plan(_args(max_candles=max_candles))


def test_runtime_stream_plan_rejects_noncanonical_trainer_timeframe() -> None:
    with pytest.raises(ValueError, match="^closed_window_timeframe_unsupported$"):
        module._runtime_stream_plan(_args(timeframes="1m,3m", max_candles=100))


def test_runtime_stream_plan_bounds_status_key_cardinality(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    symbols = tuple(
        f"S{index}USDT" for index in range(module.CLOSED_WINDOW_MAX_STATUS_BLOCKED_KEYS + 1)
    )
    monkeypatch.setattr(
        module,
        "_resolve_symbols",
        lambda *_args, **_kwargs: symbols,
    )

    with pytest.raises(
        ValueError,
        match="^closed_window_stream_count_exceeds_status_resource_bound$",
    ):
        module._runtime_stream_plan(_args(timeframes="1m", max_candles=100))


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({}, 600.0),
        ({"universe_refresh_seconds": 300.0}, 300.0),
        ({"universe_refresh_seconds": 0.0}, 15.0),
        ({"total_seconds": 120.0}, 120.0),
        ({"loop": False}, 86_400.0),
        ({"loop": False, "total_seconds": 1.0}, 15.0),
    ],
)
def test_runtime_cycle_seconds_is_transport_only_and_bounded(
    overrides: dict[str, object],
    expected: float,
) -> None:
    assert module._runtime_cycle_seconds(_args(**overrides)) == expected


def test_default_refresh_derives_from_existing_websocket_session_rollover() -> None:
    args = _args(
        universe_refresh_seconds=None,
        max_seconds_per_session=345.0,
    )

    assert module._runtime_cycle_seconds(args) == 345.0


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
@pytest.mark.parametrize(
    ("field", "expected_error"),
    [
        ("total_seconds", "total_seconds_must_be_finite_number"),
        (
            "universe_refresh_seconds",
            "universe_refresh_seconds_must_be_finite_number",
        ),
        ("max_seconds_per_session", "max_seconds_per_session_must_be_finite_number"),
    ],
)
def test_runtime_cycle_seconds_rejects_nonfinite_transport_cadence(
    field: str,
    expected_error: str,
    value: float,
) -> None:
    overrides: dict[str, object] = {field: value}
    if field == "max_seconds_per_session":
        overrides["universe_refresh_seconds"] = None

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        module._runtime_cycle_seconds(_args(**overrides))


def test_runtime_cycle_seconds_normalizes_direct_conversion_errors() -> None:
    with pytest.raises(
        ValueError,
        match="^universe_refresh_seconds_must_be_finite_number$",
    ):
        module._runtime_cycle_seconds(_args(universe_refresh_seconds="not-a-number"))


@pytest.mark.parametrize(
    ("field", "expected_error"),
    [
        ("total_seconds", "total_seconds_must_be_finite_number"),
        (
            "universe_refresh_seconds",
            "universe_refresh_seconds_must_be_finite_number",
        ),
        ("max_seconds_per_session", "max_seconds_per_session_must_be_finite_number"),
    ],
)
def test_runtime_cycle_seconds_totalizes_hostile_conversion_objects(
    field: str,
    expected_error: str,
) -> None:
    def hostile_class(_value: object) -> type[object]:
        raise RuntimeError("SENSITIVE_CADENCE_CLASS_SECRET")

    def hostile_float(_value: object) -> float:
        raise RuntimeError("SENSITIVE_CADENCE_FLOAT_SECRET")

    hostile_cadence_type: Any = type(
        "HostileCadence",
        (),
        {
            "__class__": property(hostile_class),
            "__float__": hostile_float,
        },
    )

    overrides: dict[str, object] = {field: hostile_cadence_type()}
    if field == "max_seconds_per_session":
        overrides["universe_refresh_seconds"] = None

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        module._runtime_cycle_seconds(_args(**overrides))


def test_observed_close_wave_target_snaps_to_midpoint_within_maximum() -> None:
    observed_rollover_start = 3 * 3_600.0 + 5 * 60.0
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=observed_rollover_start,
        maximum_seconds=600.0,
        timeframes=("1m", "5m", "15m"),
    )

    observed_close_wave_target = 3 * 3_600.0 + 15 * 60.0
    assert observed_close_wave_target % 60 == 0.0
    assert observed_close_wave_target % 300 == 0.0
    assert observed_close_wave_target % 900 == 0.0
    assert plan.deadline_epoch_seconds == observed_close_wave_target - 30.0
    assert plan.deadline_epoch_seconds - plan.planned_at_epoch_seconds == 570.0
    assert plan.shortest_timeframe_seconds == 60
    assert plan.close_boundary_distance_seconds == 30.0
    assert plan.plan_mode == module.ROLLOVER_EXACT_MIDPOINT_MODE
    assert plan.deadline_epoch_seconds <= observed_close_wave_target
    for timeframe in ("1m", "5m", "15m"):
        interval = module.TIMEFRAME_DURATION_MS[timeframe] // 1000
        offset = plan.deadline_epoch_seconds % interval
        assert min(offset, interval - offset) >= 30.0


def test_rollover_deadline_is_deterministic_from_clock_and_timeframes() -> None:
    first = module._plan_rollover_deadline(
        now_epoch_seconds=1_815.25,
        maximum_seconds=600.0,
        timeframes=("5m", "15m"),
    )
    second = module._plan_rollover_deadline(
        now_epoch_seconds=1_815.25,
        maximum_seconds=600.0,
        timeframes=("5m", "15m"),
    )

    assert first == second
    assert first.deadline_epoch_seconds == 2_250.0


@pytest.mark.parametrize("now_epoch_seconds", [1_800.0, 1_801.0, 1_829.9, 1_830.0, 1_831.0])
def test_rollover_deadline_never_exceeds_maximum_when_midpoint_is_available(
    now_epoch_seconds: float,
) -> None:
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=now_epoch_seconds,
        maximum_seconds=600.0,
        timeframes=("1m", "5m", "15m"),
    )

    planned_duration = plan.deadline_epoch_seconds - now_epoch_seconds
    assert 0.0 < planned_duration <= plan.maximum_seconds
    assert plan.deadline_epoch_seconds % 60 == 30.0


@pytest.mark.parametrize("timeframe", ["15m", "1h", "4h"])
def test_rollover_deadline_uses_bounded_fallback_for_short_supported_sessions(
    timeframe: str,
) -> None:
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=1_801.0,
        maximum_seconds=15.0,
        timeframes=(timeframe,),
    )

    assert 1_801.0 < plan.deadline_epoch_seconds <= 1_816.0
    assert plan.deadline_epoch_seconds == 1_816.0
    assert plan.plan_mode == module.ROLLOVER_MAXIMUM_FALLBACK_MODE
    assert plan.close_boundary_distance_seconds > 0.0


@pytest.mark.parametrize(
    ("timeframe", "now_epoch_seconds", "boundary_epoch_seconds"),
    [
        ("15m", 1_785.0, 1_800.0),
        ("1h", 3_585.0, 3_600.0),
        ("4h", 14_385.0, 14_400.0),
    ],
)
def test_rollover_deadline_moves_inside_window_when_maximum_is_close_boundary(
    timeframe: str,
    now_epoch_seconds: float,
    boundary_epoch_seconds: float,
) -> None:
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=now_epoch_seconds,
        maximum_seconds=15.0,
        timeframes=(timeframe,),
    )

    assert plan.deadline_epoch_seconds == now_epoch_seconds + 7.5
    assert plan.deadline_epoch_seconds <= boundary_epoch_seconds
    assert plan.plan_mode == module.ROLLOVER_BOUNDARY_FALLBACK_MODE
    assert plan.close_boundary_distance_seconds == 7.5


@pytest.mark.parametrize(
    ("overrides", "expected_error"),
    [
        ({"now_epoch_seconds": float("nan")}, "rollover_now_epoch_seconds_invalid"),
        ({"now_epoch_seconds": -1.0}, "rollover_now_epoch_seconds_invalid"),
        ({"now_epoch_seconds": 10**1_000}, "rollover_now_epoch_seconds_invalid"),
        ({"maximum_seconds": float("inf")}, "rollover_maximum_seconds_invalid"),
        ({"maximum_seconds": 0.0}, "rollover_maximum_seconds_invalid"),
        ({"maximum_seconds": 10**1_000}, "rollover_maximum_seconds_invalid"),
        ({"timeframes": ()}, "rollover_timeframes_invalid"),
        ({"timeframes": ("1m", "3m")}, "rollover_timeframes_invalid"),
        ({"timeframes": ["1m"]}, "rollover_timeframes_invalid"),
    ],
)
def test_rollover_deadline_rejects_invalid_inputs(
    overrides: dict[str, object],
    expected_error: str,
) -> None:
    inputs: dict[str, object] = {
        "now_epoch_seconds": 1_800.0,
        "maximum_seconds": 600.0,
        "timeframes": ("1m", "5m"),
    }
    inputs.update(overrides)

    with pytest.raises(ValueError, match=f"^{expected_error}$"):
        module._plan_rollover_deadline(**inputs)  # type: ignore[arg-type]


def test_rollover_deadline_rejects_hostile_subclasses_without_invocation() -> None:
    class HostileFloat(float):
        def __float__(self) -> float:
            raise RuntimeError("SENSITIVE_ROLLOVER_SECRET")

    class HostileString(str):
        def __hash__(self) -> int:
            raise RuntimeError("SENSITIVE_TIMEFRAME_SECRET")

    with pytest.raises(
        ValueError,
        match="^rollover_now_epoch_seconds_invalid$",
    ):
        module._plan_rollover_deadline(
            now_epoch_seconds=HostileFloat(1_800.0),
            maximum_seconds=600.0,
            timeframes=("1m",),
        )
    with pytest.raises(
        ValueError,
        match="^rollover_maximum_seconds_invalid$",
    ):
        module._plan_rollover_deadline(
            now_epoch_seconds=1_800.0,
            maximum_seconds=HostileFloat(600.0),
            timeframes=("1m",),
        )
    with pytest.raises(ValueError, match="^rollover_timeframes_invalid$"):
        module._plan_rollover_deadline(
            now_epoch_seconds=1_800.0,
            maximum_seconds=600.0,
            timeframes=(HostileString("1m"),),
        )


def test_rollover_telemetry_is_explicitly_mitigation_not_continuity_proof() -> None:
    stats: dict[str, Any] = {}
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=1_800.0,
        maximum_seconds=600.0,
        timeframes=("1m", "5m"),
    )

    module._record_rollover_deadline(stats, plan=plan, scope="cycle")

    assert stats["rollover_timing_policy"] == (
        "SHORTEST_TIMEFRAME_MIDPOINT_WITH_BOUNDED_FALLBACK_V2"
    )
    assert stats["rollover_gap_classification"] == "MITIGATION_NOT_CONTINUITY_PROOF"
    assert stats["rollover_continuity_guaranteed"] is False
    assert stats["rollover_cycle_deadlines_planned"] == 1
    assert stats["rollover_last_cycle_deadline_epoch_seconds"] == 2_370.0
    assert stats["rollover_last_cycle_planned_duration_seconds"] == 570.0
    assert stats["rollover_last_cycle_configured_maximum_seconds"] == 600.0
    assert stats["rollover_last_cycle_plan_mode"] == (
        module.ROLLOVER_EXACT_MIDPOINT_MODE
    )
    assert stats["rollover_planned_close_boundary_distance_seconds"] == 30.0
    assert stats["rollover_deadline_enforcement_clock"] == "MONOTONIC"


def test_rollover_telemetry_measures_observed_reconnect_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_times = iter((2_370.25, 2_372.75))
    observed_monotonic = iter((100.25, 102.75))
    monkeypatch.setattr(module.time, "time", lambda: next(observed_times))
    monkeypatch.setattr(
        module.time,
        "monotonic",
        lambda: next(observed_monotonic),
    )
    stats: dict[str, Any] = {}

    module._record_rollover_disconnect(
        stats,
        chunk_id=4,
        monotonic_deadline_seconds=100.0,
        timeframes=("1m", "5m"),
    )
    module._record_rollover_reconnect(stats, chunk_id=4)

    assert stats["rollover_deadline_disconnects"] == 1
    assert stats["rollover_reconnect_gap_observations"] == 1
    assert stats["rollover_reconnect_gap_clock"] == "MONOTONIC"
    assert stats["rollover_last_reconnect_gap_seconds_by_chunk"] == {"4": 2.5}
    assert stats["rollover_max_reconnect_gap_seconds"] == 2.5
    assert stats["rollover_last_actual_disconnect_lateness_seconds_by_chunk"] == {
        "4": 0.25
    }
    assert stats[
        "rollover_last_actual_disconnect_close_boundary_distance_seconds_by_chunk"
    ] == {"4": 29.75}


def test_rollover_telemetry_reports_fallback_plan_mode_and_distance() -> None:
    stats: dict[str, Any] = {}
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=1_785.0,
        maximum_seconds=15.0,
        timeframes=("15m",),
    )

    module._record_rollover_deadline(
        stats,
        plan=plan,
        scope="session",
        chunk_id=0,
    )

    assert stats["rollover_last_session_plan_mode_by_chunk"] == {
        "0": module.ROLLOVER_BOUNDARY_FALLBACK_MODE
    }
    assert stats[
        "rollover_last_session_planned_close_boundary_distance_seconds_by_chunk"
    ] == {"0": 7.5}


def test_epoch_plan_is_bound_once_to_monotonic_runtime_clock() -> None:
    plan = module._plan_rollover_deadline(
        now_epoch_seconds=1_800.0,
        maximum_seconds=600.0,
        timeframes=("1m", "5m"),
    )

    deadline = module._monotonic_deadline_from_plan(
        plan=plan,
        now_monotonic_seconds=42.0,
    )

    assert deadline == 612.0


@pytest.mark.asyncio
async def test_chunk_consumer_derives_its_session_deadline_from_timeframes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class PlannedDeadlineObserved(RuntimeError):
        pass

    def observe_plan(**kwargs: object) -> module._RolloverDeadlinePlan:
        calls.append(kwargs)
        raise PlannedDeadlineObserved

    monkeypatch.setattr(module, "_plan_rollover_deadline", observe_plan)

    with pytest.raises(PlannedDeadlineObserved):
        await module._consume_chunk(
            chunk_id=0,
            streams=("btcusdt@kline_1m", "btcusdt@kline_5m"),
            redis_client=None,
            stats={},
            ws_base="wss://example.invalid/",
            ttl_seconds=900,
            max_candles=100,
            max_seconds_per_session=600.0,
            timeframes=("1m", "5m"),
            stop_at_monotonic=module.time.monotonic() + 600.0,
            label_pipeline=None,
        )

    assert len(calls) == 1
    observed_maximum = calls[0]["maximum_seconds"]
    assert isinstance(observed_maximum, int | float)
    assert 0.0 < float(observed_maximum) <= 600.0
    assert calls[0]["timeframes"] == ("1m", "5m")


@pytest.mark.asyncio
async def test_chunk_runtime_bounds_open_receive_and_close_with_monotonic_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, float] = {}

    class Clock:
        monotonic_seconds = 100.0
        epoch_seconds = 1_801.0

        @classmethod
        def monotonic(cls) -> float:
            return cls.monotonic_seconds

        @classmethod
        def time(cls) -> float:
            return cls.epoch_seconds

    class FakeWebSocket:
        async def recv(self) -> str:
            return "unused"

    class Connection:
        async def __aenter__(self) -> FakeWebSocket:
            Clock.epoch_seconds = 1_801.1
            return FakeWebSocket()

        async def __aexit__(
            self,
            exc_type: object,
            exc: object,
            traceback: object,
        ) -> bool:
            Clock.monotonic_seconds = 115.25
            Clock.epoch_seconds = 1_816.25
            return False

    class FakeWebsockets:
        @staticmethod
        def connect(*_args: Any, **kwargs: Any) -> Connection:
            observed["open_timeout"] = float(kwargs["open_timeout"])
            observed["close_timeout"] = float(kwargs["close_timeout"])
            return Connection()

    async def timeout_receive(awaitable: Any, **kwargs: Any) -> None:
        observed["receive_timeout"] = float(kwargs["timeout"])
        awaitable.close()
        raise module.asyncio.TimeoutError

    monkeypatch.setattr(module, "websockets", FakeWebsockets())
    monkeypatch.setattr(module.time, "time", Clock.time)
    monkeypatch.setattr(module.time, "monotonic", Clock.monotonic)
    monkeypatch.setattr(module.asyncio, "wait_for", timeout_receive)
    stats: dict[str, Any] = {}

    await module._consume_chunk(
        chunk_id=0,
        streams=("btcusdt@kline_15m",),
        redis_client=None,
        stats=stats,
        ws_base="wss://example.invalid/",
        ttl_seconds=900,
        max_candles=100,
        max_seconds_per_session=15.0,
        timeframes=("15m",),
        stop_at_monotonic=115.0,
        label_pipeline=None,
    )

    assert observed == {
        "open_timeout": 13.5,
        "close_timeout": 0.3,
        "receive_timeout": 13.5,
    }
    assert stats["session_timeouts"] == 1
    assert stats["rollover_last_actual_disconnect_lateness_seconds_by_chunk"] == {
        "0": 0.25
    }
    assert stats[
        "rollover_last_actual_disconnect_close_boundary_distance_seconds_by_chunk"
    ] == {"0": 16.25}


@pytest.mark.asyncio
async def test_chunk_retry_sleep_cannot_cross_monotonic_session_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monotonic_clock = [100.0]
    sleeps: list[float] = []

    class FailingWebsockets:
        @staticmethod
        def connect(*_args: Any, **_kwargs: Any) -> None:
            raise OSError("injected connect failure")

    async def bounded_sleep(seconds: float) -> None:
        sleeps.append(seconds)
        monotonic_clock[0] = 101.0

    monkeypatch.setattr(module, "websockets", FailingWebsockets())
    monkeypatch.setattr(module.time, "time", lambda: 1_801.0)
    monkeypatch.setattr(module.time, "monotonic", lambda: monotonic_clock[0])
    monkeypatch.setattr(module.asyncio, "sleep", bounded_sleep)

    await module._consume_chunk(
        chunk_id=0,
        streams=("btcusdt@kline_15m",),
        redis_client=None,
        stats={},
        ws_base="wss://example.invalid/",
        ttl_seconds=900,
        max_candles=100,
        max_seconds_per_session=15.0,
        timeframes=("15m",),
        stop_at_monotonic=101.0,
        label_pipeline=None,
    )

    assert sleeps == [1.0]


@pytest.mark.asyncio
async def test_run_loop_re_resolves_and_reports_added_and_removed_symbols(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    plans: Iterator[tuple[tuple[str, ...], tuple[str, ...], list[tuple[str, ...]]]] = iter(
        (
            (("BTCUSDT",), ("1m",), []),
            (("BTCUSDT", "ETHUSDT"), ("1m",), []),
            (("ETHUSDT",), ("1m",), []),
        )
    )
    exit_codes: Iterator[int] = iter((0, 2))
    written: list[dict[str, Any]] = []

    class _RedisHolder:
        reconnects = 0

        def ensure(self) -> object:
            return object()

    monkeypatch.setattr(module, "websockets", object())
    monkeypatch.setattr(module, "_RedisHolder", _RedisHolder)
    monkeypatch.setattr(module, "_runtime_stream_plan", lambda _args: next(plans))
    monkeypatch.setattr(module, "_runtime_cycle_seconds", lambda _args: 1.0)
    monkeypatch.setattr(
        module,
        "_plan_rollover_deadline",
        lambda **_kwargs: module._RolloverDeadlinePlan(
            planned_at_epoch_seconds=29.0,
            deadline_epoch_seconds=30.0,
            planned_duration_seconds=1.0,
            maximum_seconds=1.0,
            shortest_timeframe_seconds=60,
            close_boundary_distance_seconds=30.0,
            plan_mode=module.ROLLOVER_EXACT_MIDPOINT_MODE,
        ),
    )
    monkeypatch.setattr(
        module,
        "_monotonic_deadline_from_plan",
        lambda **_kwargs: module.time.monotonic() - 1.0,
    )
    monkeypatch.setattr(
        module,
        "_runtime_cycle_exit_code",
        lambda **_kwargs: next(exit_codes),
    )
    monkeypatch.setattr(
        module,
        "_write_status",
        lambda payload, _paths: written.append(payload),
    )
    monkeypatch.setattr(module, "_safe_set_json", lambda *_args, **_kwargs: True)

    args = _args(
        ws_base="wss://example.invalid/",
        ttl_seconds=900,
        max_candles=100,
        heartbeat_interval_seconds=30.0,
        enable_canonical_5m_label_archive=False,
        status_path=str(tmp_path / "status.json"),
        public_path=str(tmp_path / "public.json"),
        worklog_path=str(tmp_path / "worklog.json"),
    )

    assert await module.run_loop(args) == 2
    assert written
    assert written[-1]["symbols"] == ["ETHUSDT"]
    assert written[-1]["stats"]["universe_refresh_count"] == 2
    assert written[-1]["stats"]["universe_changed"] is True
    assert written[-1]["stats"]["universe_added_symbols"] == []
    assert written[-1]["stats"]["universe_removed_symbols"] == ["BTCUSDT"]
    assert written[-1]["stats"]["universe_refresh_seconds"] == 1.0
    assert written[-1]["stats"]["universe_refresh_configured_maximum_seconds"] == 1.0
    assert written[-1]["stats"]["universe_refresh_seconds_semantics"] == (
        "CONFIGURED_MAXIMUM_NOT_ACTUAL_PLANNED_DURATION"
    )
    assert written[-1]["stats"]["rollover_last_cycle_planned_duration_seconds"] == 1.0
