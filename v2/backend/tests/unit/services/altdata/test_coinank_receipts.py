from __future__ import annotations

import ast
import json
from pathlib import Path
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
