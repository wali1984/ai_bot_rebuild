from __future__ import annotations

# mypy: disable-error-code=misc
import copy
import hashlib
import json
from dataclasses import FrozenInstanceError
from typing import Any, cast

import pytest
from app.services.market_state_integrity.canonical_candles import (
    canonical_candle_id,
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from app.services.native_trainer.ohlcv_closed_window_schema import (
    MAX_OHLCV_CLOSED_PAYLOAD_BYTES,
    MAX_OHLCV_CLOSED_ROWS,
    SUPPORTED_TRAINER_TIMEFRAMES,
    TIMEFRAME_DURATION_MS,
    OHLCVClosedWindowValidationError,
    require_contiguous_window,
    validate_ohlcv_closed_window,
)

SYMBOL = "BTCUSDT"
BASE_MS = 1_800_000_000_000


def _aligned_base(timeframe: str) -> int:
    duration = cast(int, TIMEFRAME_DURATION_MS[timeframe])
    return (BASE_MS // duration) * duration


def _rest_source_row(open_time: int, timeframe: str) -> list[object]:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    close_time = open_time + duration - 1
    return [
        open_time,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "12.0",
        close_time,
        "1206.0",
        10,
        "6.0",
        "603.0",
        "0",
    ]


def _canonical_rest(index: int, timeframe: str = "1m") -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    open_time = _aligned_base(timeframe) + (index * duration)
    close_time = open_time + duration - 1
    return cast(
        dict[str, Any],
        canonical_from_binance_rest(
            _rest_source_row(open_time, timeframe),
            symbol=SYMBOL,
            timeframe=timeframe,
            ingested_at=close_time + 200,
        ).to_dict(),
    )


def _canonical_wss(index: int, timeframe: str = "1m") -> dict[str, Any]:
    duration = TIMEFRAME_DURATION_MS[timeframe]
    open_time = _aligned_base(timeframe) + (index * duration)
    close_time = open_time + duration - 1
    event_time = close_time + 105
    message = {
        "E": event_time,
        "k": {
            "s": SYMBOL,
            "i": timeframe,
            "t": open_time,
            "T": close_time,
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
    return cast(
        dict[str, Any],
        canonical_from_binance_wss(
            message,
            symbol=SYMBOL,
            timeframe=timeframe,
            ingested_at=event_time + 127,
        ).to_dict(),
    )


def _payload(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _valid_rows(timeframe: str = "1m") -> list[dict[str, Any]]:
    return [
        _canonical_rest(0, timeframe),
        _canonical_wss(1, timeframe),
        _canonical_wss(2, timeframe),
    ]


def _recompute_candle_id(row: dict[str, Any]) -> None:
    row["candle_id"] = canonical_candle_id(row)


def _assert_invalid(payload: object, **kwargs: object) -> None:
    call_kwargs: dict[str, object] = {"symbol": SYMBOL, "timeframe": "1m"}
    call_kwargs.update(kwargs)
    with pytest.raises(OHLCVClosedWindowValidationError):
        validate_ohlcv_closed_window(payload, **call_kwargs)


def test_actual_canonical_mixed_rest_wss_window_binds_all_evidence() -> None:
    rows = _valid_rows()
    raw = _payload(rows)

    result = validate_ohlcv_closed_window(
        raw,
        symbol=SYMBOL,
        timeframe="1m",
        required_contiguous_lookback=3,
    )

    assert len(rows[0]) == 32
    assert rows[0]["venue"] == "binance_usdm"
    assert rows[0]["product_type"] == "USD-M"
    assert len(rows[0]["ohlcv"]) == 9
    assert result.source_key == "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    assert result.exact_payload_sha256 == hashlib.sha256(raw).hexdigest()
    assert result.exact_payload_byte_count == len(raw)
    assert result.row_count == 3
    assert result.rows[0].source == "binance_rest"
    assert result.rows[-1].source == "binance_wss"
    assert result.first_economic_close_time == rows[0]["candle_close_time"]
    assert result.latest_economic_close_time == rows[-1]["candle_close_time"]
    assert result.latest_producer_event_time == rows[-1]["event_time"]
    assert result.max_ingested_at == max(row["ingested_at"] for row in rows)
    assert result.max_available_at == max(row["available_at"] for row in rows)
    assert result.binance_rest_row_count == 1
    assert result.binance_wss_row_count == 2
    assert result.gap_count == 0
    assert result.gap_indices == ()
    assert result.gap_missing_interval_counts == ()
    assert result.missing_interval_count == 0
    assert result.contiguous_suffix_count == 3
    assert result.required_contiguous_lookback == 3
    assert result.required_contiguous_window_satisfied is True
    assert result.redis_read_receipt_emitted is False
    assert result.immutable_cas_captured is False
    assert result.consumer_eligible is False
    assert result.trainer_admission_granted is False
    assert result.live_execution_authorized is False


def test_transitional_legacy_rows_are_exactly_bounded_and_product_claims_fail_closed() -> None:
    legacy = _canonical_wss(0)
    legacy.pop("venue")
    legacy.pop("product_type")
    validate_ohlcv_closed_window(
        _payload([legacy]),
        symbol=SYMBOL,
        timeframe="1m",
    )

    partial = _canonical_wss(0)
    partial.pop("product_type")
    _assert_invalid(_payload([partial]))

    wrong_product = _canonical_wss(0)
    wrong_product["product_type"] = "SPOT"
    with pytest.raises(
        OHLCVClosedWindowValidationError,
        match="ohlcv_closed_product_binding_invalid",
    ):
        validate_ohlcv_closed_window(
            _payload([wrong_product]),
            symbol=SYMBOL,
            timeframe="1m",
        )


@pytest.mark.parametrize("timeframe", SUPPORTED_TRAINER_TIMEFRAMES)
def test_every_trainer_timeframe_uses_its_exact_alignment(timeframe: str) -> None:
    rows = _valid_rows(timeframe)
    result = validate_ohlcv_closed_window(
        _payload(rows),
        symbol=SYMBOL,
        timeframe=timeframe,
        required_contiguous_lookback=len(rows),
    )

    assert result.timeframe == timeframe
    assert result.contiguous_suffix_count == len(rows)
    assert all(row.timeframe == timeframe for row in result.rows)


def test_gaps_are_explicit_and_only_the_contiguous_suffix_is_usable() -> None:
    # Mirrors the observed shape of current 1m/15m histories: older rows may
    # contain a missing interval while a newer suffix remains contiguous.
    rows = [
        _canonical_rest(0),
        _canonical_rest(2),
        _canonical_wss(3),
        _canonical_wss(5),
        _canonical_wss(6),
    ]
    result = validate_ohlcv_closed_window(_payload(rows), symbol=SYMBOL, timeframe="1m")

    assert result.gap_count == 2
    assert result.gap_indices == (1, 3)
    assert result.gap_missing_interval_counts == (1, 1)
    assert result.missing_interval_count == 2
    assert result.contiguous_suffix_count == 2
    assert result.required_contiguous_window_satisfied is None
    assert (
        require_contiguous_window(
            result,
            required_contiguous_lookback=2,
        ).required_contiguous_lookback
        == 2
    )
    with pytest.raises(
        OHLCVClosedWindowValidationError,
        match="required_contiguous_window_unavailable",
    ):
        require_contiguous_window(result, required_contiguous_lookback=3)
    with pytest.raises(
        OHLCVClosedWindowValidationError,
        match="required_contiguous_window_unavailable",
    ):
        validate_ohlcv_closed_window(
            _payload(rows),
            symbol=SYMBOL,
            timeframe="1m",
            required_contiguous_lookback=3,
        )


def test_missing_interval_count_records_multi_slot_gap() -> None:
    rows = [_canonical_rest(0), _canonical_wss(4), _canonical_wss(5)]
    result = validate_ohlcv_closed_window(_payload(rows), symbol=SYMBOL, timeframe="1m")

    assert result.gap_indices == (1,)
    assert result.gap_missing_interval_counts == (3,)
    assert result.missing_interval_count == 3
    assert result.contiguous_suffix_count == 2


@pytest.mark.parametrize(
    ("total_field", "taker_field", "reason"),
    [
        (
            "volume",
            "taker_buy_base_vol",
            "ohlcv_closed_taker_buy_base_exceeds_volume",
        ),
        (
            "quote_volume",
            "taker_buy_quote_vol",
            "ohlcv_closed_taker_buy_quote_exceeds_quote_volume",
        ),
    ],
)
def test_taker_buy_volume_cannot_exceed_the_corresponding_total(
    total_field: str,
    taker_field: str,
    reason: str,
) -> None:
    row = _canonical_wss(0)
    total = cast(float, row[total_field])
    invalid_taker = total + 1.0
    row[taker_field] = invalid_taker
    nested = cast(dict[str, Any], row["ohlcv"])
    nested[taker_field] = invalid_taker

    with pytest.raises(OHLCVClosedWindowValidationError, match=f"^{reason}$"):
        validate_ohlcv_closed_window(
            _payload([row]),
            symbol=SYMBOL,
            timeframe="1m",
        )


def test_latest_producer_event_time_is_the_honest_cross_row_maximum() -> None:
    rows = [_canonical_wss(0), _canonical_wss(1)]
    delayed_event_time = cast(int, rows[1]["available_at"]) + 1_000
    rows[0]["event_time"] = delayed_event_time
    rows[0]["ingested_at"] = delayed_event_time
    rows[0]["available_at"] = delayed_event_time
    rows[0]["source_sequence_id"] = str(delayed_event_time)

    result = validate_ohlcv_closed_window(
        _payload(rows),
        symbol=SYMBOL,
        timeframe="1m",
    )

    assert result.rows[0].event_time > result.rows[1].event_time
    assert result.latest_producer_event_time == result.rows[0].event_time
    assert result.latest_producer_event_time == max(row.event_time for row in result.rows)


def test_future_economic_window_remains_schema_only_and_nonconsumable() -> None:
    far_future_row = _canonical_rest(120_000_000)

    result = validate_ohlcv_closed_window(
        _payload([far_future_row]),
        symbol=SYMBOL,
        timeframe="1m",
    )

    assert result.latest_economic_close_time > 9_000_000_000_000
    assert result.exact_source_schema_validated is True
    assert result.producer_finality_contract_validated is True
    assert result.redis_read_receipt_emitted is False
    assert result.immutable_cas_captured is False
    assert result.consumer_eligible is False
    assert result.trainer_admission_granted is False
    assert result.live_execution_authorized is False


class _HostileObject:
    def __getattribute__(self, name: str) -> Any:
        if name == "__class__":
            raise AssertionError("hostile __class__ hook executed")
        return object.__getattribute__(self, name)


class _HostileBytes(bytes):
    def decode(self, *_args: object, **_kwargs: object) -> str:
        raise AssertionError("hostile bytes hook executed")

    def startswith(self, *_args: object, **_kwargs: object) -> bool:
        raise AssertionError("hostile bytes hook executed")


class _HostileString(str):
    def isascii(self) -> bool:
        raise AssertionError("hostile string hook executed")

    def __hash__(self) -> int:
        raise AssertionError("hostile string hook executed")


class _HostileInt(int):
    def __le__(self, _other: object) -> bool:
        raise AssertionError("hostile numeric hook executed")


class _HostileDict(dict[object, object]):
    def __getattribute__(self, name: str) -> Any:
        if name == "__class__":
            raise AssertionError("hostile mapping hook executed")
        return super().__getattribute__(name)


def test_exact_bytes_boundary_totalizes_hostile_objects() -> None:
    for payload in (
        _HostileObject(),
        _HostileBytes(b"[]"),
        _HostileDict(),
        bytearray(b"[]"),
        memoryview(b"[]"),
    ):
        _assert_invalid(payload)


def test_symbol_timeframe_lookback_and_artifact_boundaries_reject_subclasses() -> None:
    raw = _payload(_valid_rows())
    _assert_invalid(raw, symbol=_HostileString(SYMBOL))
    _assert_invalid(raw, timeframe=_HostileString("1m"))
    _assert_invalid(raw, required_contiguous_lookback=_HostileInt(1))
    with pytest.raises(OHLCVClosedWindowValidationError):
        require_contiguous_window(
            _HostileDict(),
            required_contiguous_lookback=1,
        )

    validated = validate_ohlcv_closed_window(raw, symbol=SYMBOL, timeframe="1m")
    object.__setattr__(validated, "contiguous_suffix_count", _HostileInt(1))
    with pytest.raises(OHLCVClosedWindowValidationError):
        require_contiguous_window(validated, required_contiguous_lookback=1)


@pytest.mark.parametrize(
    "required",
    [0, -1, True, 1.0, "1", (1 << 63)],
)
def test_required_lookback_requires_positive_exact_signed64_int(required: object) -> None:
    _assert_invalid(_payload(_valid_rows()), required_contiguous_lookback=required)


def test_required_lookback_totalizes_hostile_object() -> None:
    _assert_invalid(
        _payload(_valid_rows()),
        required_contiguous_lookback=_HostileObject(),
    )


@pytest.mark.parametrize("timeframe", ["3m", "30m", "2h", "1d", "1M", " 1m", "1m ", 1, True])
def test_unsupported_or_nonexact_timeframe_is_rejected(timeframe: object) -> None:
    _assert_invalid(_payload(_valid_rows()), timeframe=timeframe)


@pytest.mark.parametrize(
    "symbol", ["btcusdt", "BTC-USDT", " BTCUSDT", "BTCUSDT ", "A", "", 1, True]
)
def test_noncanonical_symbol_binding_is_rejected(symbol: object) -> None:
    _assert_invalid(_payload(_valid_rows()), symbol=symbol)


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"\xef\xbb\xbf[]",
        b"\xff",
        b"NaN",
        b"[NaN]",
        b"[Infinity]",
        b"[-Infinity]",
        b"[]{}",
        b"[",
        b"{}",
        b"null",
        (b"[" * 2_000) + (b"]" * 2_000),
    ],
)
def test_strict_utf8_and_json_contract_rejects_invalid_forms(payload: bytes) -> None:
    _assert_invalid(payload)


def test_duplicate_json_object_keys_are_rejected_before_schema_validation() -> None:
    raw = _payload([_canonical_rest(0)])
    needle = b'"symbol":"BTCUSDT"'
    assert raw.count(needle) == 1
    duplicate = raw.replace(needle, needle + b"," + needle)

    with pytest.raises(OHLCVClosedWindowValidationError, match="duplicate_object_key"):
        validate_ohlcv_closed_window(duplicate, symbol=SYMBOL, timeframe="1m")


def test_duplicate_or_nonincreasing_rows_are_rejected() -> None:
    first = _canonical_rest(0)
    _assert_invalid(_payload([first, copy.deepcopy(first)]))
    _assert_invalid(_payload([_canonical_wss(1), _canonical_rest(0)]))


@pytest.mark.parametrize(
    ("mutator", "reason"),
    [
        (lambda row: row.__setitem__("symbol", "ETHUSDT"), "source_binding"),
        (lambda row: row.__setitem__("exchange", "kucoin"), "source_binding"),
        (lambda row: row.__setitem__("timeframe", "5m"), "source_binding"),
        (lambda row: row.__setitem__("open_time", row["open_time"] + 1), "time_alias"),
        (lambda row: row.__setitem__("close_time", row["close_time"] - 1), "time_alias"),
        (lambda row: row.__setitem__("ts", row["ts"] + 1), "time_alias"),
        (lambda row: row.__setitem__("is_closed", False), "finality_flags"),
        (lambda row: row.__setitem__("closed_candle", False), "finality_flags"),
        (lambda row: row.__setitem__("candle_closed_confirmed", False), "finality_flags"),
        (lambda row: row.__setitem__("feature_eligible", False), "finality_flags"),
    ],
)
def test_binding_alias_and_finality_tampering_fails_closed(
    mutator: Any,
    reason: str,
) -> None:
    row = _canonical_rest(0)
    mutator(row)
    with pytest.raises(OHLCVClosedWindowValidationError, match=reason):
        validate_ohlcv_closed_window(_payload([row]), symbol=SYMBOL, timeframe="1m")


def test_open_alignment_and_exact_close_duration_are_enforced() -> None:
    misaligned = _canonical_rest(0)
    misaligned["candle_open_time"] += 1
    misaligned["open_time"] += 1
    misaligned["ts"] += 1
    _recompute_candle_id(misaligned)
    with pytest.raises(OHLCVClosedWindowValidationError, match="open_alignment"):
        validate_ohlcv_closed_window(_payload([misaligned]), symbol=SYMBOL, timeframe="1m")

    wrong_close = _canonical_rest(0)
    wrong_close["candle_close_time"] -= 1
    wrong_close["close_time"] -= 1
    wrong_close["event_time"] -= 1
    wrong_close["source_sequence_id"] = str(wrong_close["event_time"])
    _recompute_candle_id(wrong_close)
    with pytest.raises(OHLCVClosedWindowValidationError, match="close_alignment"):
        validate_ohlcv_closed_window(_payload([wrong_close]), symbol=SYMBOL, timeframe="1m")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row.__setitem__("is_backfilled", False),
        lambda row: row.__setitem__("event_time", row["candle_close_time"] + 1),
        lambda row: row.__setitem__("available_at", row["ingested_at"] + 1),
        lambda row: row.__setitem__("source_sequence_id", "0"),
        lambda row: row.__setitem__("source", "binance_wss"),
    ],
)
def test_rest_source_clock_flag_and_sequence_coupling_is_exact(mutator: Any) -> None:
    row = _canonical_rest(0)
    mutator(row)
    with pytest.raises(OHLCVClosedWindowValidationError):
        validate_ohlcv_closed_window(_payload([row]), symbol=SYMBOL, timeframe="1m")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row.__setitem__("is_backfilled", True),
        lambda row: row.__setitem__("event_time", row["candle_close_time"] - 1),
        lambda row: row.__setitem__("ingested_at", row["event_time"] - 1),
        lambda row: row.__setitem__("available_at", row["ingested_at"] + 1),
        lambda row: row.__setitem__("source_sequence_id", "0"),
        lambda row: row.__setitem__("source", "other"),
    ],
)
def test_wss_source_clock_flag_and_sequence_coupling_is_exact(mutator: Any) -> None:
    row = _canonical_wss(0)
    mutator(row)
    with pytest.raises(OHLCVClosedWindowValidationError):
        validate_ohlcv_closed_window(_payload([row]), symbol=SYMBOL, timeframe="1m")


@pytest.mark.parametrize(
    "bad_hash",
    ["A" * 64, "0" * 63, "0" * 65, "g" * 64, "", 1, True],
)
def test_raw_payload_hash_requires_lowercase_sha256(bad_hash: object) -> None:
    row = _canonical_rest(0)
    row["raw_payload_hash"] = bad_hash
    _assert_invalid(_payload([row]))


def test_candle_id_uses_current_24_character_canonical_abi() -> None:
    row = _canonical_rest(0)
    assert row["candle_id"] == canonical_candle_id(row)
    result = validate_ohlcv_closed_window(_payload([row]), symbol=SYMBOL, timeframe="1m")
    assert result.rows[0].candle_id == row["candle_id"]

    row["candle_id"] = "0" * 24
    with pytest.raises(OHLCVClosedWindowValidationError, match="candle_id_mismatch"):
        validate_ohlcv_closed_window(_payload([row]), symbol=SYMBOL, timeframe="1m")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row["ohlcv"].__setitem__("close", row["close"] + 1.0),
        lambda row: row["ohlcv"].__setitem__("close", int(row["close"])),
        lambda row: row.__setitem__("num_trades", row["num_trades"] + 1),
        lambda row: row["ohlcv"].__setitem__("unexpected", 1),
        lambda row: row["ohlcv"].__delitem__("volume"),
        lambda row: row.__setitem__("ohlcv", []),
    ],
)
def test_nested_ohlcv_schema_and_exact_top_level_equality(mutator: Any) -> None:
    row = _canonical_rest(0)
    mutator(row)
    _assert_invalid(_payload([row]))


@pytest.mark.parametrize(
    "mutator",
    [
        lambda row: row.__setitem__("open", 0.0),
        lambda row: row.__setitem__("high", 100.0),
        lambda row: row.__setitem__("low", 102.0),
        lambda row: row.__setitem__("volume", -1.0),
        lambda row: row.__setitem__("quote_volume", -1.0),
        lambda row: row.__setitem__("taker_buy_base_vol", -1.0),
        lambda row: row.__setitem__("taker_buy_quote_vol", -1.0),
        lambda row: row.__setitem__("num_trades", -1),
        lambda row: row.__setitem__("close", True),
    ],
)
def test_prices_ohlc_volumes_trades_and_exact_numeric_types_are_enforced(mutator: Any) -> None:
    row = _canonical_rest(0)
    mutator(row)
    # Keep nested equality when the intended failure is the numeric invariant.
    if "open" in row["ohlcv"] and type(row["open"]) in (int, float):
        row["ohlcv"]["open"] = row["open"]
    if "high" in row["ohlcv"] and type(row["high"]) in (int, float):
        row["ohlcv"]["high"] = row["high"]
    if "low" in row["ohlcv"] and type(row["low"]) in (int, float):
        row["ohlcv"]["low"] = row["low"]
    for key in (
        "volume",
        "quote_volume",
        "taker_buy_base_vol",
        "taker_buy_quote_vol",
        "num_trades",
    ):
        if key in row["ohlcv"]:
            row["ohlcv"][key] = row[key]
    _assert_invalid(_payload([row]))


def test_json_float_overflow_is_rejected_as_nonfinite() -> None:
    raw = _payload([_canonical_rest(0)])
    needle = b'"open":100.0'
    assert raw.count(needle) == 2
    _assert_invalid(raw.replace(needle, b'"open":1e999'))


def test_row_and_nested_field_sets_are_exact() -> None:
    row = _canonical_rest(0)
    extra = copy.deepcopy(row)
    extra["extra"] = 1
    _assert_invalid(_payload([extra]))

    missing = copy.deepcopy(row)
    del missing["available_at"]
    _assert_invalid(_payload([missing]))


def test_row_count_boundaries_reject_empty_and_more_than_1500_before_rows() -> None:
    _assert_invalid(b"[]")
    too_many_empty_rows = json.dumps([{}] * (MAX_OHLCV_CLOSED_ROWS + 1)).encode("utf-8")
    assert len(too_many_empty_rows) < MAX_OHLCV_CLOSED_PAYLOAD_BYTES
    with pytest.raises(OHLCVClosedWindowValidationError, match="row_count_invalid"):
        validate_ohlcv_closed_window(too_many_empty_rows, symbol=SYMBOL, timeframe="1m")


def test_exact_one_mib_payload_is_accepted_and_one_byte_more_is_rejected() -> None:
    base = _payload([_canonical_rest(0)])
    exact_max = base + (b" " * (MAX_OHLCV_CLOSED_PAYLOAD_BYTES - len(base)))
    assert len(exact_max) == MAX_OHLCV_CLOSED_PAYLOAD_BYTES

    result = validate_ohlcv_closed_window(exact_max, symbol=SYMBOL, timeframe="1m")

    assert result.exact_payload_byte_count == MAX_OHLCV_CLOSED_PAYLOAD_BYTES
    assert result.exact_payload_sha256 == hashlib.sha256(exact_max).hexdigest()
    _assert_invalid(exact_max + b" ")


def test_payload_digest_is_deterministic_and_binds_exact_whitespace_bytes() -> None:
    raw = _payload(_valid_rows())
    first = validate_ohlcv_closed_window(raw, symbol=SYMBOL, timeframe="1m")
    second = validate_ohlcv_closed_window(raw, symbol=SYMBOL, timeframe="1m")
    whitespace_variant = validate_ohlcv_closed_window(
        raw + b"\n",
        symbol=SYMBOL,
        timeframe="1m",
    )

    assert first == second
    assert first.exact_payload_sha256 == second.exact_payload_sha256
    assert whitespace_variant.rows == first.rows
    assert whitespace_variant.exact_payload_sha256 != first.exact_payload_sha256


def test_artifact_and_rows_are_frozen() -> None:
    result = validate_ohlcv_closed_window(
        _payload([_canonical_rest(0)]),
        symbol=SYMBOL,
        timeframe="1m",
    )

    with pytest.raises(FrozenInstanceError):
        result.row_count = 0
    with pytest.raises(FrozenInstanceError):
        result.rows[0].symbol = "ETHUSDT"
    with pytest.raises(FrozenInstanceError):
        result.rows[0].ohlcv.close = 1.0
