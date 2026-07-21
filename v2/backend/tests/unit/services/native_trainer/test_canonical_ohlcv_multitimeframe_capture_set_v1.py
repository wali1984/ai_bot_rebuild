from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.native_trainer import (
    canonical_ohlcv_multitimeframe_capture_set_v1 as capture_set_module,
)
from v2.backend.app.services.native_trainer.adaptive_ohlcv_feature_selection_profile_v1 import (
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID,
    ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_atomic_receipt_adapter import (
    CanonicalOhlcvAtomicReceiptCapture,
    capture_canonical_closed_ohlcv_atomic_receipts,
)
from v2.backend.app.services.native_trainer.canonical_ohlcv_multitimeframe_capture_set_v1 import (
    CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID,
    CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256,
    CAPTURE_SET_CLOCK_FIELDS,
    CAPTURE_SET_REQUIRED_LOOKBACKS,
    CAPTURE_SET_REQUIRED_TIMEFRAMES,
    CanonicalOhlcvMultitimeframeCaptureSetV1,
    CanonicalOhlcvMultitimeframeCaptureSetV1Error,
    build_canonical_ohlcv_multitimeframe_capture_set_v1,
    canonical_ohlcv_multitimeframe_capture_set_v1_contract,
    canonical_ohlcv_multitimeframe_capture_set_v1_policy_contract,
)
from v2.backend.app.services.native_trainer.immutable_source_payload_store import (
    ImmutableSourcePayloadStore,
)
from v2.backend.app.services.native_trainer.model_ta_technical_dependency_contract import (
    EXISTING_CORE_MINIMUM_SOURCE_ROWS,
    TRUE_1H_TA_MINIMUM_ROWS,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)

SYMBOL = "BTCUSDT"
SOURCE_ROW_COUNT = EXISTING_CORE_MINIMUM_SOURCE_ROWS
DECISION = datetime(2026, 7, 21, 12, 0, 0, 900_000, tzinfo=UTC)
GENERATED = datetime(2026, 7, 21, 12, 0, 0, 700_000, tzinfo=UTC)
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class _FakePipeline:
    def __init__(self, responses: list[object]) -> None:
        self.responses = responses

    def type(self, _key: str) -> _FakePipeline:
        return self

    def getrange(self, _key: str, _start: int, _end: int) -> _FakePipeline:
        return self

    def pttl(self, _key: str) -> _FakePipeline:
        return self

    def time(self) -> _FakePipeline:
        return self

    def execute(self) -> list[object]:
        return list(self.responses)

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class _FakeClient:
    def __init__(self, responses: list[object]) -> None:
        self.pipeline_instance = _FakePipeline(responses)

    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _FakePipeline:
        assert transaction is True
        return self.pipeline_instance


def _clock(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _datetime_ms(value: int) -> datetime:
    return _EPOCH + timedelta(milliseconds=value)


def _to_ms(value: datetime) -> int:
    return int((value - _EPOCH).total_seconds() * 1_000)


def _latest_open_ms(timeframe: str, *, decision: datetime = DECISION) -> int:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    return (_to_ms(decision) // duration_ms) * duration_ms - duration_ms


def _rest_source_row(open_time_ms: int, *, timeframe: str) -> list[object]:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    return [
        open_time_ms,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "12.0",
        open_time_ms + duration_ms - 1,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]


def _canonical_rest(open_time_ms: int, *, timeframe: str) -> dict[str, Any]:
    close_time_ms = open_time_ms + TIMEFRAME_DURATION_MS[timeframe] - 1
    return canonical_from_binance_rest(
        _rest_source_row(open_time_ms, timeframe=timeframe),
        symbol=SYMBOL,
        timeframe=timeframe,
        ingested_at=close_time_ms + 20,
    ).to_dict()


def _canonical_wss(open_time_ms: int, *, timeframe: str) -> dict[str, Any]:
    close_time_ms = open_time_ms + TIMEFRAME_DURATION_MS[timeframe] - 1
    producer_event_time_ms = close_time_ms + 10
    message = {
        "E": producer_event_time_ms,
        "k": {
            "s": SYMBOL,
            "i": timeframe,
            "t": open_time_ms,
            "T": close_time_ms,
            "o": "101.0",
            "h": "103.0",
            "l": "100.0",
            "c": "102.0",
            "v": "14.0",
            "q": "1428.0",
            "n": 12,
            "V": "7.0",
            "Q": "714.0",
            "B": "0",
            "x": True,
        },
    }
    return canonical_from_binance_wss(
        message,
        symbol=SYMBOL,
        timeframe=timeframe,
        ingested_at=producer_event_time_ms + 10,
    ).to_dict()


def _rows(
    timeframe: str,
    *,
    latest_open_ms: int | None = None,
    latest_is_wss: bool = True,
) -> list[dict[str, Any]]:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    final_open_ms = latest_open_ms if latest_open_ms is not None else _latest_open_ms(timeframe)
    first_open_ms = final_open_ms - (SOURCE_ROW_COUNT - 1) * duration_ms
    rows = [
        _canonical_rest(first_open_ms + ordinal * duration_ms, timeframe=timeframe)
        for ordinal in range(SOURCE_ROW_COUNT)
    ]
    if latest_is_wss:
        rows[-1] = _canonical_wss(final_open_ms, timeframe=timeframe)
    return rows


def _payload(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(rows, ensure_ascii=True, indent=2).encode("ascii")


def _capture(
    tmp_path: Path,
    *,
    timeframe: str,
    rows: list[dict[str, Any]] | None = None,
    store_name: str | None = None,
) -> tuple[CanonicalOhlcvAtomicReceiptCapture, ImmutableSourcePayloadStore]:
    source_rows = rows if rows is not None else _rows(timeframe)
    payload = _payload(source_rows)
    latest_close_ms = int(source_rows[-1]["candle_close_time"])
    observed = _datetime_ms(latest_close_ms + 500)
    server_seconds = int(observed.timestamp())
    client = _FakeClient([b"string", payload, 600_000, (server_seconds, 123_456)])
    store = ImmutableSourcePayloadStore(tmp_path / (store_name or f"source-payloads-{timeframe}"))
    capture = capture_canonical_closed_ohlcv_atomic_receipts(
        client,
        store,
        expected_symbol=SYMBOL,
        expected_timeframe=timeframe,
        consumer_clock=lambda: observed,
    )
    return capture, store


def _capture_pair(
    tmp_path: Path,
    *,
    latest_5m_open_ms: int | None = None,
    latest_5m_is_wss: bool = True,
    latest_1h_is_wss: bool = True,
) -> tuple[
    tuple[CanonicalOhlcvAtomicReceiptCapture, CanonicalOhlcvAtomicReceiptCapture],
    tuple[ImmutableSourcePayloadStore, ImmutableSourcePayloadStore],
]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    rows_5m = _rows(
        "5m",
        latest_open_ms=latest_5m_open_ms,
        latest_is_wss=latest_5m_is_wss,
    )
    rows_1h = _rows("1h", latest_is_wss=latest_1h_is_wss)
    capture_5m, store_5m = _capture(
        tmp_path,
        timeframe="5m",
        rows=rows_5m,
    )
    capture_1h, store_1h = _capture(
        tmp_path,
        timeframe="1h",
        rows=rows_1h,
    )
    return (capture_5m, capture_1h), (store_5m, store_1h)


def _build(
    tmp_path: Path,
    *,
    captures: tuple[
        CanonicalOhlcvAtomicReceiptCapture,
        CanonicalOhlcvAtomicReceiptCapture,
    ]
    | None = None,
    generated_at: datetime = GENERATED,
    decision_time: datetime = DECISION,
    typed_negative_timeframes: tuple[str, ...] = (),
    store_name: str = "capture-set",
) -> tuple[CanonicalOhlcvMultitimeframeCaptureSetV1, ImmutableSourcePayloadStore]:
    atomic_captures = captures if captures is not None else _capture_pair(tmp_path)[0]
    store = ImmutableSourcePayloadStore(tmp_path / store_name)
    artifact = build_canonical_ohlcv_multitimeframe_capture_set_v1(
        profile=ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1,
        atomic_captures=atomic_captures,
        capture_set_store=store,
        generated_at=_clock(generated_at),
        decision_time=_clock(decision_time),
        typed_negative_timeframes=typed_negative_timeframes,
    )
    return artifact, store


def test_happy_path_is_exact_authenticated_causal_capture_set(tmp_path: Path) -> None:
    artifact, store = _build(tmp_path)
    contract = canonical_ohlcv_multitimeframe_capture_set_v1_contract(artifact)

    assert artifact.profile_id == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_ID
    assert artifact.profile_sha256 == ADAPTIVE_OHLCV_FEATURE_SELECTION_PROFILE_V1_SHA256
    assert artifact.required_timeframes == CAPTURE_SET_REQUIRED_TIMEFRAMES
    assert artifact.required_lookbacks == CAPTURE_SET_REQUIRED_LOOKBACKS
    assert tuple(len(item.rows) for item in artifact.timeframe_captures) == (71, 34)
    assert artifact.timeframe_captures[0].atomic_selected_start_ordinal == 0
    assert artifact.timeframe_captures[1].atomic_selected_start_ordinal == 37
    assert all(
        item.rows[-1].source_transport == "binance_wss" for item in artifact.timeframe_captures
    )
    assert all(item.rows[-1].is_backfilled is False for item in artifact.timeframe_captures)
    assert all(
        item.rows[0].source_transport == "binance_rest" for item in artifact.timeframe_captures
    )
    assert all(item.rows[0].is_backfilled is True for item in artifact.timeframe_captures)
    assert artifact.timeframe_captures[1].feature_cutoff <= (
        artifact.timeframe_captures[0].feature_cutoff
    )

    assert set(contract["timestamps"]) == set(CAPTURE_SET_CLOCK_FIELDS)
    assert contract["timestamps"]["execution_time"] is None
    assert contract["timestamps"]["feature_cutoff"] < contract["timestamps"]["decision_time"]
    assert contract["market_performance_thresholds"] == []
    assert contract["market_performance_thresholds_applied"] is False
    assert contract["typed_negatives"]["count"] == 0
    assert contract["proof_scope"] == {
        "atomic_capture_factory_verified": True,
        "hermetic_policy_dependency_bound": True,
        "hermetic_replay_executed": False,
        "multi_timeframe_atomic_read_claimed": False,
        "row_cas_readback_verified": True,
        "row_receipts_verified": True,
        "upstream_transport_authenticity_claimed": False,
    }
    assert all(
        value is False for key, value in contract["authorization"].items() if key != "audit_only"
    )
    assert contract["authorization"]["audit_only"] is True
    assert (
        contract["capture_set_sha256"]
        == hashlib.sha256(artifact.capture_set_manifest_json.encode("ascii")).hexdigest()
    )
    assert store.get(
        artifact.capture_set_manifest_address.payload_sha256,
        expected_byte_count=artifact.capture_set_manifest_byte_count,
    ) == artifact.capture_set_manifest_json.encode("ascii")


def test_policy_pins_formula_derived_minimum_history_and_has_no_market_gate() -> None:
    policy = canonical_ohlcv_multitimeframe_capture_set_v1_policy_contract()

    assert policy["policy_id"] == CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_ID
    assert policy["required_lookbacks"] == [
        {"row_count": EXISTING_CORE_MINIMUM_SOURCE_ROWS, "timeframe": "5m"},
        {"row_count": TRUE_1H_TA_MINIMUM_ROWS, "timeframe": "1h"},
    ]
    assert policy["market_performance_thresholds_applied"] is False
    encoded = json.dumps(
        policy,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")
    assert hashlib.sha256(encoded).hexdigest() == (
        CANONICAL_OHLCV_MULTITIMEFRAME_CAPTURE_SET_V1_POLICY_SHA256
    )


@pytest.mark.parametrize(
    ("decision_shift", "reason"),
    [
        (timedelta(milliseconds=-901), "unfinished_or_future_candle"),
        (timedelta(milliseconds=-890), "row_available_after_decision"),
        (timedelta(minutes=5), "stale_latest_candle"),
    ],
)
def test_unfinished_available_after_decision_and_stale_data_fail_closed(
    tmp_path: Path,
    decision_shift: timedelta,
    reason: str,
) -> None:
    captures = _capture_pair(tmp_path)[0]
    shifted_decision = DECISION + decision_shift

    with pytest.raises(CanonicalOhlcvMultitimeframeCaptureSetV1Error, match=reason):
        _build(
            tmp_path,
            captures=captures,
            generated_at=shifted_decision,
            decision_time=shifted_decision,
        )


def test_latest_rest_is_rejected_and_latest_wss_is_accepted(tmp_path: Path) -> None:
    rest_captures = _capture_pair(tmp_path / "rest", latest_5m_is_wss=False)[0]

    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="latest_live_wss_required",
    ):
        _build(tmp_path / "rest", captures=rest_captures)

    wss_artifact, _ = _build(tmp_path / "wss")
    assert all(
        capture.rows[-1].source_transport == "binance_wss"
        for capture in wss_artifact.timeframe_captures
    )


def test_cross_timeframe_inventory_and_cutoff_order_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captures = _capture_pair(tmp_path / "ordered")[0]
    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="atomic_capture_order_invalid",
    ):
        _build(tmp_path / "ordered", captures=(captures[1], captures[0]))

    earlier_5m_open = _latest_open_ms("5m") - TIMEFRAME_DURATION_MS["5m"]
    crossed = _capture_pair(
        tmp_path / "crossed",
        latest_5m_open_ms=earlier_5m_open,
    )[0]
    monkeypatch.setattr(
        capture_set_module,
        "_validate_decision_relative_timeframe",
        lambda *_args, **_kwargs: None,
    )
    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="cross_timeframe_order_invalid",
    ):
        _build(tmp_path / "crossed", captures=crossed)


def test_nonfinite_values_lineage_substitution_and_typed_negatives_are_rejected(
    tmp_path: Path,
) -> None:
    artifact, _ = _build(tmp_path)
    row = artifact.timeframe_captures[0].rows[0]

    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="row_ohlcv_nonfinite",
    ):
        replace(row, close=float("nan"))
    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="row_identity_sha256_invalid",
    ):
        replace(row, row_identity_sha256="0" * 64)

    captures = _capture_pair(tmp_path / "typed-negative")[0]
    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="required_typed_negative_forbidden",
    ):
        _build(
            tmp_path / "typed-negative",
            captures=captures,
            typed_negative_timeframes=("1h",),
        )


def test_source_row_and_capture_set_cas_tampering_are_detected(tmp_path: Path) -> None:
    captures, source_stores = _capture_pair(tmp_path / "source-tamper")
    selected = captures[0].selected_candles[0]
    source_path = source_stores[0].path_for(selected.source_payload_address.payload_sha256)
    source_bytes = source_path.read_bytes()
    os.chmod(source_path, 0o600)
    source_path.write_bytes(bytes([source_bytes[0] ^ 1]) + source_bytes[1:])
    os.chmod(source_path, 0o400)
    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="atomic_capture_revalidation_failed",
    ):
        _build(tmp_path / "source-tamper", captures=captures)

    artifact, store = _build(tmp_path / "set-tamper")
    set_path = store.path_for(artifact.capture_set_sha256)
    set_bytes = set_path.read_bytes()
    os.chmod(set_path, 0o600)
    set_path.write_bytes(bytes([set_bytes[0] ^ 1]) + set_bytes[1:])
    os.chmod(set_path, 0o400)
    with pytest.raises(
        CanonicalOhlcvMultitimeframeCaptureSetV1Error,
        match="capture_set_cas_readback_failed",
    ):
        canonical_ohlcv_multitimeframe_capture_set_v1_contract(artifact)


def test_identity_is_deterministic_and_contract_copy_is_detached(tmp_path: Path) -> None:
    captures = _capture_pair(tmp_path)[0]
    first, _ = _build(tmp_path, captures=captures, store_name="set-first")
    second, _ = _build(tmp_path, captures=captures, store_name="set-second")

    assert first == second
    assert first.capture_set_sha256 == second.capture_set_sha256
    assert first.capture_set_manifest_json == second.capture_set_manifest_json
    assert first.capture_set_manifest_address == second.capture_set_manifest_address

    detached = canonical_ohlcv_multitimeframe_capture_set_v1_contract(first)
    detached["timeframes"][0]["rows"][0]["ohlcv"]["close"] = -1
    fresh = canonical_ohlcv_multitimeframe_capture_set_v1_contract(first)
    assert fresh["timeframes"][0]["rows"][0]["ohlcv"]["close"] > 0
