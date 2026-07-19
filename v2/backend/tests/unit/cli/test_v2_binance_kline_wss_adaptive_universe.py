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
    monkeypatch.setattr(module, "_runtime_cycle_seconds", lambda _args: -1.0)
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
