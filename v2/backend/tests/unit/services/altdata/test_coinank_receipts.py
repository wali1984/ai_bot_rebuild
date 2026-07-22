from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from v2.backend.app.services.altdata.coinank_receipts import (
    MAX_SIGNED_64_BIT_INTEGER,
    build_coinank_flat_snapshot,
    causal_request_receipt_fields,
    request_with_causal_receipt,
)
from v2.backend.app.services.liquidation_surface import (
    RawRedisEvidence,
    adapt_coinank_plan3_open_interest,
)

SYMBOL = "BTCUSDT"
TIMEFRAME = "5m"
DURATION_MS = 300_000
BASE_MS = 1_800_000_000_000
RUNTIME_PATH = (
    Path(__file__).resolve().parents[6]
    / "v2"
    / "legacy_owned_runtime"
    / "ingest"
    / "live_coinank.py"
)


class FakeResponse:
    status_code = 200


class FakeSession:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.call: dict[str, Any] | None = None

    def get(self, url: str, *, params: dict[str, Any], timeout: float) -> FakeResponse:
        self.events.append("network")
        self.call = {"url": url, "params": params, "timeout": timeout}
        return FakeResponse()


def _oi_params() -> dict[str, Any]:
    return {
        "exchange": "Binance",
        "symbol": SYMBOL,
        "interval": TIMEFRAME,
        "productType": "SWAP",
        "size": 3,
    }


def _oi_response() -> dict[str, Any]:
    return {
        "success": True,
        "code": "1",
        "data": [
            {"begin": BASE_MS, "close": "100"},
            {"begin": BASE_MS + DURATION_MS, "close": "120"},
            {"begin": BASE_MS + 2 * DURATION_MS, "close": "140"},
        ],
    }


def test_request_receipt_clocks_bracket_network_io_and_preserve_params() -> None:
    events: list[str] = []
    clock_values = iter((BASE_MS + 1, BASE_MS + 20))

    def now_ms() -> int:
        events.append("clock")
        return next(clock_values)

    session = FakeSession(events)
    params = _oi_params()

    response, receipt = request_with_causal_receipt(
        session,
        url="https://open-api.coinank.com/api/openInterest/kline",
        params=params,
        timeout=12,
        now_ms=now_ms,
    )

    assert response is not None
    assert events == ["clock", "network", "clock"]
    assert receipt == {
        "request_started_at_ms": BASE_MS + 1,
        "response_observed_at_ms": BASE_MS + 20,
    }
    assert session.call == {
        "url": "https://open-api.coinank.com/api/openInterest/kline",
        "params": params,
        "timeout": 12,
    }


def test_request_receipt_rejects_wall_clock_regression() -> None:
    values = iter((BASE_MS + 20, BASE_MS + 1))

    with pytest.raises(ValueError, match="COINANK_REQUEST_RECEIPT_CLOCK_ORDER_INVALID"):
        request_with_causal_receipt(
            FakeSession([]),
            url="https://open-api.coinank.com/api/openInterest/kline",
            params=_oi_params(),
            timeout=12,
            now_ms=lambda: next(values),
        )


@pytest.mark.parametrize(
    ("receipt", "persisted_at_ms", "error"),
    [
        ({}, BASE_MS + 30, "COINANK_REQUEST_STARTED_AT"),
        (
            {"request_started_at_ms": True, "response_observed_at_ms": BASE_MS + 20},
            BASE_MS + 30,
            "COINANK_REQUEST_STARTED_AT_NOT_INTEGER_MS",
        ),
        (
            {
                "request_started_at_ms": BASE_MS + 20,
                "response_observed_at_ms": BASE_MS + 10,
            },
            BASE_MS + 30,
            "COINANK_REQUEST_RECEIPT_CLOCK_ORDER_INVALID",
        ),
        (
            {
                "request_started_at_ms": BASE_MS + 10,
                "response_observed_at_ms": BASE_MS + 30,
            },
            BASE_MS + 20,
            "COINANK_REQUEST_RECEIPT_CLOCK_ORDER_INVALID",
        ),
        (
            {
                "request_started_at_ms": MAX_SIGNED_64_BIT_INTEGER + 1,
                "response_observed_at_ms": MAX_SIGNED_64_BIT_INTEGER + 1,
            },
            MAX_SIGNED_64_BIT_INTEGER + 1,
            "OUTSIDE_SIGNED_64_BIT_MS",
        ),
    ],
)
def test_request_receipt_fields_fail_closed(
    receipt: dict[str, Any],
    persisted_at_ms: int,
    error: str,
) -> None:
    with pytest.raises(ValueError, match=error):
        causal_request_receipt_fields(receipt, persisted_at_ms=persisted_at_ms)


def test_real_flat_snapshot_builder_passes_strict_plan3_oi_adapter() -> None:
    request_started_at_ms = BASE_MS + 2 * DURATION_MS + 1
    response_observed_at_ms = request_started_at_ms + 20
    persisted_at_ms = response_observed_at_ms + 10
    payload = build_coinank_flat_snapshot(
        persisted_at_ms=persisted_at_ms,
        request_receipt={
            "request_started_at_ms": request_started_at_ms,
            "response_observed_at_ms": response_observed_at_ms,
        },
        symbol=SYMBOL,
        exchange="Binance",
        family="open_interest",
        endpoint="openInterest_kline",
        endpoint_variant=None,
        request_parameters=_oi_params(),
        interval=TIMEFRAME,
        data=_oi_response(),
    )
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    evidence = RawRedisEvidence.from_value(
        key=f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}",
        value=raw,
        consumer_observed_at_ms=persisted_at_ms + 10,
    )

    rows = adapt_coinank_plan3_open_interest(
        evidence,
        symbol=SYMBOL,
        source_timeframe=TIMEFRAME,
    )

    assert [row.value for row in rows] == [100.0, 120.0]
    assert all(row.unit == "base_asset" for row in rows)
    assert payload["request_parameters"] == _oi_params()
    assert payload["request_started_at_ms"] < payload["response_observed_at_ms"]
    assert payload["response_observed_at_ms"] <= payload["ts_ms"]


def test_bar_closing_during_request_is_excluded_by_request_start_cutoff() -> None:
    closing_during_request = BASE_MS + 2 * DURATION_MS
    request_started_at_ms = closing_during_request - 10
    response_observed_at_ms = closing_during_request + 10
    persisted_at_ms = response_observed_at_ms + 10
    payload = build_coinank_flat_snapshot(
        persisted_at_ms=persisted_at_ms,
        request_receipt={
            "request_started_at_ms": request_started_at_ms,
            "response_observed_at_ms": response_observed_at_ms,
        },
        symbol=SYMBOL,
        exchange="Binance",
        family="open_interest",
        endpoint="openInterest_kline",
        endpoint_variant=None,
        request_parameters=_oi_params(),
        interval=TIMEFRAME,
        data=_oi_response(),
    )
    evidence = RawRedisEvidence.from_value(
        key=f"latest:coinank:open_interest:{SYMBOL}:{TIMEFRAME}",
        value=json.dumps(payload, separators=(",", ":")),
        consumer_observed_at_ms=persisted_at_ms + 10,
    )

    rows = adapt_coinank_plan3_open_interest(
        evidence,
        symbol=SYMBOL,
        source_timeframe=TIMEFRAME,
    )

    assert [row.feature_cutoff_ms for row in rows] == [BASE_MS + DURATION_MS]
    assert [row.value for row in rows] == [100.0]


def _function(tree: ast.Module, name: str) -> ast.FunctionDef:
    return next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == name
    )


def _call_lines(function: ast.FunctionDef, name: str) -> list[int]:
    lines: list[int] = []
    for node in ast.walk(function):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name):
            called = node.func.id
        elif isinstance(node.func, ast.Attribute):
            called = node.func.attr
        else:
            called = None
        if called == name:
            lines.append(node.lineno)
    return sorted(lines)


def _load_runtime_function(
    tree: ast.Module,
    name: str,
    namespace: dict[str, Any],
) -> Any:
    function = _function(tree, name)
    isolated = ast.Module(body=[function], type_ignores=[])
    ast.fix_missing_locations(isolated)
    exec(compile(isolated, str(RUNTIME_PATH), "exec"), namespace)  # noqa: S102
    return namespace[name]


def test_runtime_places_rate_gate_before_causal_network_wrapper() -> None:
    tree = ast.parse(RUNTIME_PATH.read_text(encoding="utf-8"))
    function = _function(tree, "fetch_endpoint")

    rate_gate_lines = _call_lines(function, "_rate_gate")
    request_lines = _call_lines(function, "request_with_causal_receipt")

    assert len(rate_gate_lines) == 1
    assert len(request_lines) == 1
    assert rate_gate_lines[0] < request_lines[0]


def test_runtime_is_hard_pinned_away_from_liquidation_heatmap_routes() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")

    assert "COINANK_ENABLE_PLAN4     = False" in source
    assert "/api/liqMap/" not in source
    assert "liqMap_getLiqHeatMapSymbol" not in source


def test_runtime_persistence_requires_receipts_and_redacts_header_values() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    persist = _function(tree, "persist")
    required_keywords = {
        argument.arg
        for argument, default in zip(
            persist.args.kwonlyargs,
            persist.args.kw_defaults,
            strict=True,
        )
        if default is None
    }

    assert "request_receipt" in required_keywords
    builder_lines = _call_lines(persist, "build_coinank_flat_snapshot")
    receipt_lines = _call_lines(persist, "causal_request_receipt_fields")
    write_lines = _call_lines(persist, "open") + _call_lines(persist, "set")
    assert len(builder_lines) == 2
    assert len(receipt_lines) == 1
    assert write_lines
    assert receipt_lines[0] < min(write_lines)
    assert "dict(SESSION.headers)" not in source
    assert "apikey_present=" in source


def test_runtime_wires_dynamic_universe_to_fair_5m_surface_lane() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    universe_resolver = _function(tree, "_liquidation_surface_oi_symbols")
    parameter_builder = _function(tree, "build_param_sets")
    runtime_loop = _function(tree, "loop")
    universe_source = ast.get_source_segment(source, universe_resolver) or ""
    builder_source = ast.get_source_segment(source, parameter_builder) or ""
    loop_source = ast.get_source_segment(source, runtime_loop) or ""

    assert len(_call_lines(universe_resolver, "resolve_symbols")) == 1
    assert "TRAINING_SYMBOLS" in universe_source
    assert "is_valid_runtime_symbol" in universe_source
    assert 'COINANK_LIQUIDATION_OI_SOURCE_TIMEFRAME = "5m"' in source
    assert "_liquidation_surface_oi_symbols()" in builder_source
    assert "dict.fromkeys" in builder_source
    assert "*INTERVALS_PRIORITY" in builder_source
    assert len(_call_lines(runtime_loop, "select_fair_rotating_batch")) == 1
    assert len(_call_lines(runtime_loop, "summarize_fair_lane_coverage")) == 1
    assert 'selection_class="surface_oi_source"' in loop_source
    assert '"surface_oi_fresh_coverage_ratio"' in loop_source
    assert 'request_receipt["request_started_at_ms"]' in loop_source
    assert "- 1" in loop_source


def test_real_runtime_parameter_builder_emits_5m_lane_for_all_159_symbols() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    symbols = [f"S{index}USDT" for index in range(159)]
    namespace: dict[str, Any] = {
        "WORKING_COINANK_ENDPOINTS": {
            "openInterest_kline": {"mode": "symbol_exchange_interval_end"}
        },
        "EXCHANGES": ["Binance"],
        "INTERVALS_PRIORITY": ["15m", "1h"],
        "COINANK_LIQUIDATION_OI_SOURCE_TIMEFRAME": "5m",
        "COINANK_CRITICAL_LIVE_ROW_LIMIT": 3,
        "CRITICAL_COINANK_SCHEDULER_ENDPOINTS": {"openInterest_kline"},
        "PRODUCT_TYPE": "SWAP",
        "COINANK_PARAM_SET_LIMIT": 0,
        "_liquidation_surface_oi_symbols": lambda: symbols,
        "_active_symbols_for_deep": lambda: ["BTCUSDT"],
        "_effective_end_time": lambda _tf, value: value,
        "_plan3_endtime_for_interval": lambda _tf: BASE_MS,
        "_get_max_size": lambda _tf, requested: requested,
        "_validate_params": lambda _key, _params: None,
    }
    build_param_sets = _load_runtime_function(
        tree,
        "build_param_sets",
        namespace,
    )

    params = build_param_sets("openInterest_kline")
    five_minute = [row for row in params if row["interval"] == "5m"]

    assert len(params) == 159 * 3
    assert len(five_minute) == 159
    assert {row["symbol"] for row in five_minute} == set(symbols)
    assert all(row["exchange"] == "Binance" for row in five_minute)
    assert all(row["productType"] == "SWAP" for row in five_minute)
    assert all(row["size"] == 3 for row in five_minute)


def test_real_runtime_universe_helper_unions_resolved_and_configured_symbols() -> None:
    source = RUNTIME_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    resolved = ["BTCUSDT", *(f"S{index}USDT" for index in range(158))]
    namespace: dict[str, Any] = {
        "_canonical_usdt": lambda value: str(value).strip().upper(),
        "resolve_symbols": lambda **_kwargs: resolved,
        "TRAINING_SYMBOLS": "EXTRAUSDT,BTCUSDT",
        "COINANK_SYMBOLS": ["SOLUSDT", "bad-symbol"],
        "is_valid_runtime_symbol": lambda value: (
            str(value).endswith("USDT") and "-" not in str(value)
        ),
        "logger": SimpleNamespace(warning=lambda _message: None),
    }
    namespace["_major_first"] = _load_runtime_function(
        tree,
        "_major_first",
        namespace,
    )
    resolve_oi_symbols = _load_runtime_function(
        tree,
        "_liquidation_surface_oi_symbols",
        namespace,
    )

    symbols = resolve_oi_symbols()

    assert len(symbols) == 161
    assert symbols[:3] == ["BTCUSDT", "SOLUSDT", "S0USDT"]
    assert "EXTRAUSDT" in symbols
    assert "bad-symbol" not in symbols
    assert len(symbols) == len(set(symbols))
