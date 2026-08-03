from __future__ import annotations

import json
from typing import Any

import pytest

from v2.backend.app.cli import v2_native_ingestors_live_loop as loop


class FakeRedis:
    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self.store = {
            key: json.dumps(value, separators=(",", ":"))
            for key, value in (initial or {}).items()
        }

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = value


class RawRedis:
    def __init__(self, raw: str | bytes) -> None:
        self.raw = raw

    def get(self, key: str) -> str | bytes:
        return self.raw


def _clock_ms(epoch_seconds: float) -> int:
    return int(epoch_seconds * 1_000)


def _long_short_payload(newest_event: float) -> dict[str, Any]:
    event_times = [newest_event - (offset * 300.0) for offset in reversed(range(4))]
    return {
        "symbol": "BTCUSDT",
        "period": "5m",
        "longShortRatio": "1.2",
        "longAccount": "0.54545",
        "shortAccount": "0.45455",
        "long_short_ratio": 1.2,
        "long_account_ratio": 0.54545,
        "short_account_ratio": 0.45455,
        "timestamp": _clock_ms(newest_event),
        "event_time": _clock_ms(newest_event),
        "generated_at": _clock_ms(newest_event + 0.5),
        "ingested_at": _clock_ms(newest_event + 1.0),
        "available_at": _clock_ms(newest_event + 1.0),
        "source": "binance_global_long_short_account_ratio_rest_fallback",
        "transport": "rest_fallback",
        "cadence_evidence": {"event_times_epoch_seconds": event_times},
    }


def _oi_history(newest_event: float) -> list[dict[str, Any]]:
    return [
        {
            "symbol": "BTCUSDT",
            "period": "5m",
            "sumOpenInterest": str(100 + index),
            "timestamp": _clock_ms(event_time),
            "event_time": _clock_ms(event_time),
            "generated_at": _clock_ms(event_time + 0.5),
            "ingested_at": _clock_ms(event_time + 1.0),
            "available_at": _clock_ms(event_time + 1.0),
            "source": "binance_open_interest_history_rest_fallback",
            "transport": "rest_fallback",
        }
        for index, event_time in enumerate(
            newest_event - (offset * 300.0) for offset in reversed(range(4))
        )
    ]


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_twenty_two_hour_cache_cannot_regain_freshness_from_ttl_or_bundle_rewrite(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    stale_event = now - (22 * 60 * 60)
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    value = (
        _long_short_payload(stale_event)
        if source_family == "long_short"
        else _oi_history(stale_event)
    )
    redis_client = FakeRedis()
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: True)
    keys_written: list[str] = []
    loop._write_symbol_bundle(
        redis_client,
        "BTCUSDT",
        {source_family: value},
        keys_written,
    )
    stored = json.loads(redis_client.store[key])
    before_clocks = value if isinstance(value, dict) else value[-1]
    after_clocks = stored if isinstance(stored, dict) else stored[-1]
    for field in ("event_time", "generated_at", "ingested_at", "available_at"):
        assert after_clocks[field] == before_clocks[field]
    assert key in keys_written
    diagnostics: dict[str, Any] = {}

    if source_family == "long_short":
        result = loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
    else:
        result = loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )

    assert result is None
    assert diagnostics["status"] == "UNAVAILABLE"
    assert diagnostics["reason"] == "SOURCE_EVENT_STALE_BY_OBSERVED_CADENCE"
    assert diagnostics["source_receipt_authority"] is False
    assert diagnostics["trainer_authority"] is False


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_recent_cache_is_accepted_only_from_observed_cadence_and_exact_clocks(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    newest_event = now - 10.0
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    value = (
        _long_short_payload(newest_event)
        if source_family == "long_short"
        else _oi_history(newest_event)
    )
    redis_client = FakeRedis({key: value})
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: True)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
    )

    assert result is not None
    assert diagnostics["status"] == "AVAILABLE"
    assert diagnostics["source_freshness"]["cadence_proven"] is True
    assert diagnostics["source_freshness"]["adaptive_max_age_seconds"] == 300.0
    assert diagnostics["source_freshness"]["readiness_eligible"] is True
    accepted = result if isinstance(result, dict) else result[-1]
    original = value if isinstance(value, dict) else value[-1]
    for field in ("event_time", "generated_at", "ingested_at", "available_at"):
        assert accepted[field] == original[field]
    if source_family == "long_short":
        assert diagnostics["all_required_features_available"] is True
        assert set(diagnostics["feature_availability"]) == {
            "long_short_ratio",
            "long_account_ratio",
            "short_account_ratio",
        }
        assert all(
            field["status"] == "AVAILABLE" and field["readiness_eligible"] is True
            for field in diagnostics["feature_availability"].values()
        )


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("invalid", "SOURCE_CADENCE_CLOCK_INVALID"),
        ("nonfinite", "SOURCE_CADENCE_CLOCK_INVALID"),
        ("future", "SOURCE_CADENCE_CLOCK_IN_FUTURE"),
        ("duplicate", "SOURCE_CADENCE_CLOCK_DUPLICATE"),
        ("unordered", "SOURCE_CADENCE_CLOCK_ORDER_INVALID"),
        ("detached", "SOURCE_EVENT_NOT_BOUND_TO_NEWEST_CADENCE_CLOCK"),
        ("oversized", "SOURCE_CADENCE_EVIDENCE_TOO_LARGE"),
    ],
)
def test_cadence_evidence_is_strictly_bounded_ordered_and_bound_to_payload_event(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_reason: str,
) -> None:
    now = 1_800_000_000.0
    payload = _long_short_payload(now - 10.0)
    clocks = list(payload["cadence_evidence"]["event_times_epoch_seconds"])
    if case == "invalid":
        clocks[1] = "not-a-clock"
    elif case == "nonfinite":
        clocks[1] = float("inf")
    elif case == "future":
        clocks[1] = now + 1.0
    elif case == "duplicate":
        clocks[2] = clocks[1]
    elif case == "unordered":
        clocks[1], clocks[2] = clocks[2], clocks[1]
    elif case == "detached":
        clocks[-1] -= 1.0
    else:
        newest = now - 10.0
        clocks = [
            newest - ((loop.SOURCE_CADENCE_MAX_CLOCKS - index) * 300.0)
            for index in range(loop.SOURCE_CADENCE_MAX_CLOCKS + 1)
        ]
    monkeypatch.setattr(loop.time, "time", lambda: now)

    fresh, freshness, cadence = loop._source_freshness(
        payload,
        clocks,
        period="5m",
    )

    assert fresh is False
    assert freshness["status"] == "UNAVAILABLE"
    assert freshness["reason"] == expected_reason
    assert freshness["readiness_eligible"] is False
    assert cadence["proven"] is False
    assert cadence["reason"] == expected_reason


@pytest.mark.parametrize(
    ("case", "expected_reason"),
    [
        ("duplicate", "SOURCE_CADENCE_CLOCK_DUPLICATE"),
        ("unordered", "SOURCE_CADENCE_CLOCK_ORDER_INVALID"),
    ],
)
def test_open_interest_history_received_order_cannot_be_repaired_by_sorting(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_reason: str,
) -> None:
    now = 1_800_000_000.0
    rows = _oi_history(now - 10.0)
    if case == "duplicate":
        for field in ("timestamp", "event_time"):
            rows[2][field] = rows[1][field]
    else:
        rows[1], rows[2] = rows[2], rows[1]
    key = "v2:market:open_interest_hist:BTCUSDT:5m"
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    diagnostics: dict[str, Any] = {}

    result = loop._fetch_open_interest_hist(
        "BTCUSDT",
        redis_client=FakeRedis({key: rows}),
        diagnostics=diagnostics,
    )

    assert result is None
    assert diagnostics["reason"] == expected_reason


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
@pytest.mark.parametrize(
    ("field", "bad_value", "expected_reason"),
    [
        ("symbol", "ETHUSDT", "SOURCE_SYMBOL_MISMATCH"),
        ("period", "1h", "SOURCE_PERIOD_MISMATCH"),
        ("source", "untrusted_source", "SOURCE_IDENTITY_UNEXPECTED"),
        ("transport", "provider_backup_cache", "SOURCE_TRANSPORT_IDENTITY_MISMATCH"),
    ],
)
def test_cache_source_identity_must_match_requested_family_symbol_and_period(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
    field: str,
    bad_value: str,
    expected_reason: str,
) -> None:
    now = 1_800_000_000.0
    value: dict[str, Any] | list[dict[str, Any]] = (
        _long_short_payload(now - 10.0)
        if source_family == "long_short"
        else _oi_history(now - 10.0)
    )
    payload = value if isinstance(value, dict) else value[-1]
    payload[field] = bad_value
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["status"] == "UNAVAILABLE"
    assert diagnostics["reason"] == expected_reason
    assert diagnostics["source_receipt_authority"] is False
    assert diagnostics["trainer_authority"] is False


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("symbol", "btcusdt", "SOURCE_SYMBOL_MISMATCH"),
        ("symbol", " BTCUSDT ", "SOURCE_SYMBOL_MISMATCH"),
        ("symbol", 1, "SOURCE_SYMBOL_MISMATCH"),
        ("period", "5M", "SOURCE_PERIOD_MISMATCH"),
        ("period", " 5m ", "SOURCE_PERIOD_MISMATCH"),
        ("period", 5, "SOURCE_PERIOD_MISMATCH"),
    ],
)
def test_source_identity_does_not_accept_normalized_aliases(
    field: str,
    value: Any,
    reason: str,
) -> None:
    payload = _long_short_payload(1_800_000_000.0)
    payload[field] = value

    assert (
        loop._source_identity_reason(
            payload,
            expected_symbol="BTCUSDT",
            expected_period="5m",
            source_transports=loop.LONG_SHORT_SOURCE_TRANSPORTS,
        )
        == reason
    )


@pytest.mark.parametrize(
    "raw",
    [
        '{"symbol":"BTCUSDT","symbol":"ETHUSDT"}',
        ("[" * 1_100) + "0" + ("]" * 1_100),
        '{"value":' + ("9" * 1_000) + "}",
        '{"value":NaN}',
    ],
)
def test_source_cache_json_rejects_ambiguous_or_hostile_shapes(raw: str) -> None:
    payload, reason = loop._read_bounded_source_cache_json(RawRedis(raw), "v2:test")

    assert payload is None
    assert reason == "SOURCE_CACHE_JSON_INVALID"


def test_open_interest_history_cannot_mix_individually_allowed_source_identities(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_800_000_000.0
    rows = _oi_history(now - 10.0)
    rows[0]["source"] = "coinank_open_interest_kline_backup"
    rows[0]["transport"] = "provider_backup_cache"
    key = "v2:market:open_interest_hist:BTCUSDT:5m"
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    diagnostics: dict[str, Any] = {}

    result = loop._fetch_open_interest_hist(
        "BTCUSDT",
        redis_client=FakeRedis({key: rows}),
        diagnostics=diagnostics,
    )

    assert result is None
    assert diagnostics["reason"] == "SOURCE_IDENTITY_INCONSISTENT_WITHIN_HISTORY"


@pytest.mark.parametrize(
    ("case", "expected_reason", "unavailable_fields"),
    [
        ("missing_long", "LONG_ACCOUNT_RATIO_MISSING", {"long_account_ratio"}),
        ("domain", "LONG_ACCOUNT_RATIO_OUT_OF_DOMAIN", {"long_account_ratio"}),
        (
            "sum",
            "LONG_SHORT_ACCOUNT_RATIOS_SUM_INCONSISTENT",
            {"long_account_ratio", "short_account_ratio"},
        ),
        (
            "ratio",
            "LONG_SHORT_RATIO_INCONSISTENT_WITH_ACCOUNTS",
            {"long_short_ratio"},
        ),
    ],
)
def test_long_short_requires_complete_domain_consistent_feature_triplet(
    monkeypatch: pytest.MonkeyPatch,
    case: str,
    expected_reason: str,
    unavailable_fields: set[str],
) -> None:
    now = 1_800_000_000.0
    payload = _long_short_payload(now - 10.0)
    if case == "missing_long":
        payload.pop("longAccount")
        payload.pop("long_account_ratio")
    elif case == "domain":
        payload["longAccount"] = payload["long_account_ratio"] = 1.1
    elif case == "sum":
        payload["longAccount"] = payload["long_account_ratio"] = 0.7
        payload["shortAccount"] = payload["short_account_ratio"] = 0.4
        payload["longShortRatio"] = payload["long_short_ratio"] = 1.75
    else:
        payload["longShortRatio"] = payload["long_short_ratio"] = 9.0
    key = "v2:market:long_short:BTCUSDT"
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    diagnostics: dict[str, Any] = {}

    result = loop._fetch_long_short_ratio(
        "BTCUSDT",
        redis_client=FakeRedis({key: payload}),
        diagnostics=diagnostics,
    )

    assert result is None
    assert diagnostics["status"] == "UNAVAILABLE"
    assert diagnostics["reason"] == expected_reason
    assert diagnostics["all_required_features_available"] is False
    assert set(diagnostics["feature_availability"]) == {
        "long_short_ratio",
        "long_account_ratio",
        "short_account_ratio",
    }
    assert {
        field
        for field, availability in diagnostics["feature_availability"].items()
        if availability["status"] == "UNAVAILABLE"
    } == unavailable_fields


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_source_cache_body_is_byte_bounded_before_json_parsing(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    redis_client = FakeRedis()
    redis_client.store[key] = " " * (loop.SOURCE_CACHE_MAX_BYTES + 1)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    monkeypatch.setattr(loop, "_coinank_oi_hist_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda *_args, **_kwargs: pytest.fail("oversized cache must not reach REST"),
    )
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["reason"] == "SOURCE_CACHE_PAYLOAD_BYTES_EXCEEDED"


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_cache_row_or_evidence_count_is_bounded_before_copying(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    newest = now - 10.0
    if source_family == "long_short":
        value: dict[str, Any] | list[dict[str, Any]] = _long_short_payload(newest)
        value["cadence_evidence"]["event_times_epoch_seconds"] = [
            newest - ((loop.SOURCE_CADENCE_MAX_CLOCKS - index) * 300.0)
            for index in range(loop.SOURCE_CADENCE_MAX_CLOCKS + 1)
        ]
        expected_reason = "SOURCE_CADENCE_EVIDENCE_TOO_LARGE"
        key = "v2:market:long_short:BTCUSDT"
    else:
        template = _oi_history(newest)[-1]
        rows = []
        for index in range(loop.SOURCE_CADENCE_MAX_CLOCKS + 1):
            event = newest - ((loop.SOURCE_CADENCE_MAX_CLOCKS - index) * 300.0)
            row = dict(template)
            row["timestamp"] = row["event_time"] = _clock_ms(event)
            row["generated_at"] = _clock_ms(event + 0.5)
            row["ingested_at"] = row["available_at"] = _clock_ms(event + 1.0)
            rows.append(row)
        value = rows
        expected_reason = "OPEN_INTEREST_HISTORY_ROW_COUNT_EXCEEDED"
        key = "v2:market:open_interest_hist:BTCUSDT:5m"
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    monkeypatch.setattr(loop, "_coinank_oi_hist_rows", lambda *_args, **_kwargs: None)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["reason"] == expected_reason


@pytest.mark.parametrize(
    ("mutated_field", "expected_reason"),
    [
        ("event_time", "SOURCE_EVENT_TIME_IN_FUTURE"),
        ("ingested_at", "SOURCE_INGESTED_AT_IN_FUTURE"),
        ("available_at", "SOURCE_AVAILABLE_AT_IN_FUTURE"),
        ("generated_at", "SOURCE_GENERATED_AT_IN_FUTURE"),
    ],
)
@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_future_source_clocks_are_typed_unavailable(
    monkeypatch: pytest.MonkeyPatch,
    mutated_field: str,
    expected_reason: str,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    value: dict[str, Any] | list[dict[str, Any]] = (
        _long_short_payload(now - 10.0)
        if source_family == "long_short"
        else _oi_history(now - 10.0)
    )
    payload = value if isinstance(value, dict) else value[-1]
    payload[mutated_field] = _clock_ms(now + 1.0)
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    redis_client = FakeRedis({key: value})
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: True)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=redis_client, diagnostics=diagnostics
        )
    )
    assert result is None
    assert diagnostics["reason"] == expected_reason


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_present_invalid_rest_clock_is_not_laundered_with_observation_time(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    newest_event = now - 10.0
    rows = [
        {
            "symbol": "BTCUSDT",
            "timestamp": _clock_ms(newest_event - (offset * 300.0)),
            "longShortRatio": "1.2",
            "longAccount": "0.55",
            "shortAccount": "0.45",
            "sumOpenInterest": "100",
            "ingested_at": 0,
        }
        for offset in reversed(range(4))
    ]
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_utc_iso_precise", lambda: _clock_ms(now - 5.0))
    monkeypatch.setenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, "true")
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: False)
    monkeypatch.setattr(loop, "_coinank_oi_hist_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(loop, "_http_get_json", lambda *_args, **_kwargs: rows)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=FakeRedis(), diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=FakeRedis(), diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["reason"] == "SOURCE_INGESTED_AT_INVALID"


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_generated_after_ingestion_is_typed_clock_order_invalid(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    value: dict[str, Any] | list[dict[str, Any]] = (
        _long_short_payload(now - 10.0)
        if source_family == "long_short"
        else _oi_history(now - 10.0)
    )
    payload = value if isinstance(value, dict) else value[-1]
    payload["generated_at"] = _clock_ms(now - 7.0)
    payload["ingested_at"] = _clock_ms(now - 8.0)
    payload["available_at"] = _clock_ms(now - 6.0)
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: True)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["reason"] == "SOURCE_GENERATED_AT_ORDER_INVALID"


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_nonpositive_derivative_value_is_unavailable_not_a_neutral_signal(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    now = 1_800_000_000.0
    value: dict[str, Any] | list[dict[str, Any]] = (
        _long_short_payload(now - 10.0)
        if source_family == "long_short"
        else _oi_history(now - 10.0)
    )
    payload = value if isinstance(value, dict) else value[-1]
    value_field = (
        "long_short_ratio" if source_family == "long_short" else "sumOpenInterest"
    )
    payload[value_field] = 0.0
    if source_family == "long_short":
        payload["longShortRatio"] = 0.0
    key = (
        "v2:market:long_short:BTCUSDT"
        if source_family == "long_short"
        else "v2:market:open_interest_hist:BTCUSDT:5m"
    )
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: True)
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=FakeRedis({key: value}), diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["reason"] in {
        "LONG_SHORT_RATIO_OUT_OF_DOMAIN",
        "OPEN_INTEREST_HISTORY_VALUE_INVALID",
    }


def test_partial_bundle_exposes_exact_unavailable_source_families(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_800_000_000.0
    stale_event = now - (22 * 60 * 60)
    redis_client = FakeRedis(
        {
            "v2:market:long_short:BTCUSDT": _long_short_payload(stale_event),
            "v2:market:open_interest_hist:BTCUSDT:5m": _oi_history(stale_event),
        }
    )
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: True)
    for name in (
        "_fetch_ticker_24hr",
        "_fetch_funding",
        "_fetch_open_interest",
        "_fetch_klines",
        "_fetch_orderbook_top",
    ):
        monkeypatch.setattr(loop, name, lambda *_args, **_kwargs: None)

    bundle = loop._fetch_symbol_bundle(
        "BTCUSDT", kline_timeframes=(), redis_client=redis_client
    )

    assert bundle["partial_bundle"] is True
    assert bundle["long_short"] is None
    assert bundle["open_interest_hist"] is None
    assert bundle["fetch_errors"]["long_short"] == (
        "SOURCE_EVENT_STALE_BY_OBSERVED_CADENCE"
    )
    assert bundle["fetch_errors"]["open_interest_hist"] == (
        "SOURCE_EVENT_STALE_BY_OBSERVED_CADENCE"
    )
    assert bundle["symbol_info"]["long_short_readiness_eligible"] is False
    assert bundle["symbol_info"]["open_interest_hist_readiness_eligible"] is False
    assert bundle["symbol_info"]["accepted_source_field_count"] == 0
    assert bundle["symbol_info"]["source_bundle_available"] is False


@pytest.mark.parametrize("source_family", ["long_short", "open_interest_hist"])
def test_optional_derivative_rest_is_deferred_without_consuming_canonical_budget(
    monkeypatch: pytest.MonkeyPatch,
    source_family: str,
) -> None:
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    monkeypatch.setattr(loop, "_rest_fallback_disabled", lambda: False)
    monkeypatch.setattr(loop, "_coinank_oi_hist_rows", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda *_args, **_kwargs: pytest.fail(
            "optional derivative request consumed canonical OHLCV budget"
        ),
    )
    diagnostics: dict[str, Any] = {}

    result = (
        loop._fetch_long_short_ratio(
            "BTCUSDT", redis_client=FakeRedis(), diagnostics=diagnostics
        )
        if source_family == "long_short"
        else loop._fetch_open_interest_hist(
            "BTCUSDT", redis_client=FakeRedis(), diagnostics=diagnostics
        )
    )

    assert result is None
    assert diagnostics["reason"] == (
        "OPTIONAL_DERIVATIVE_REST_DEFERRED_FOR_CANONICAL_OHLCV"
    )
    assert diagnostics["rest_fallback_deferred_reason"] == (
        "CANONICAL_OHLCV_SHARED_BUDGET_PRIORITY"
    )
    assert diagnostics["source_receipt_authority"] is False
    assert diagnostics["trainer_authority"] is False


def test_coinank_history_provider_remains_available_while_optional_rest_is_deferred(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    now = 1_800_000_000.0
    provider_rows = _oi_history(now - 10.0)
    for row in provider_rows:
        row["source"] = "coinank_open_interest_kline_backup"
        row["transport"] = "provider_backup_cache"
    monkeypatch.setattr(loop.time, "time", lambda: now)
    monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    monkeypatch.setattr(
        loop, "_coinank_oi_hist_rows", lambda *_args, **_kwargs: provider_rows
    )
    monkeypatch.setattr(
        loop,
        "_http_get_json",
        lambda *_args, **_kwargs: pytest.fail("provider candidate must precede REST"),
    )

    result = loop._fetch_open_interest_hist(
        "BTCUSDT", redis_client=FakeRedis(), diagnostics={}
    )

    assert result is not None
    assert result[-1]["source_freshness"]["readiness_eligible"] is True


@pytest.mark.parametrize("raw", [None, "", "0", "false", "garbage"])
def test_optional_derivative_rest_env_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    raw: str | None,
) -> None:
    if raw is None:
        monkeypatch.delenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raising=False)
    else:
        monkeypatch.setenv(loop.OPTIONAL_DERIVATIVE_REST_ENV, raw)

    assert loop._optional_derivative_rest_allowed() is False


def test_heartbeat_cannot_claim_live_or_trainer_readiness_without_valid_sources(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    redis_client = FakeRedis()
    monkeypatch.setattr(loop, "_connect_redis", lambda: redis_client)
    monkeypatch.setattr(
        loop,
        "_fetch_symbol_bundle",
        lambda *_args, **_kwargs: {
            "symbol": "BTCUSDT",
            "fetch_errors": {"long_short": "SOURCE_EVENT_TIME_MISSING"},
            "partial_bundle": True,
            "symbol_info": {
                "symbol": "BTCUSDT",
                "partial_bundle": True,
                "accepted_source_field_count": 0,
                "cache_primary_field_count": 0,
                "rest_fallback_field_count": 0,
                "all_requested_source_fields_available": False,
            },
        },
    )

    heartbeat = loop.run_once(("BTCUSDT",), kline_timeframes=())

    assert heartbeat["schema_version"] == "v2_native_ingestors_live_v2"
    assert heartbeat["schema_compatibility"] == {
        "previous_version": "v2_native_ingestors_live_v1",
        "legacy_field_names_preserved": True,
        "read_compatibility": "FIELD_COMPATIBLE_SEMANTICS_FAIL_CLOSED",
        "changed_semantic_fields": [
            "classification",
            "live_data_enabled",
            "live_decision_input_enabled",
        ],
    }
    assert heartbeat["classification"] == "BLOCKED_BY_NETWORK_OR_API"
    assert heartbeat["source_data_available"] is False
    assert heartbeat["live_data_enabled"] is False
    assert heartbeat["live_decision_input_enabled"] is False
    assert heartbeat["trainer_input_enabled"] is False
    assert heartbeat["source_receipt_authority"] is False
    assert heartbeat["trainer_authority"] is False


def test_fetch_in_progress_payload_is_not_a_false_live_heartbeat() -> None:
    payload = loop._build_fetch_in_progress_payload(("BTCUSDT",))

    assert payload["schema_version"] == "v2_native_ingestors_live_v2"
    assert payload["schema_compatibility"]["previous_version"] == (
        "v2_native_ingestors_live_v1"
    )
    assert payload["schema_compatibility"]["legacy_field_names_preserved"] is True
    assert payload["schema_compatibility"]["read_compatibility"] == (
        "FIELD_COMPATIBLE_SEMANTICS_FAIL_CLOSED"
    )
    # V1 field names remain present for readers, but V2 gives them honest
    # fail-closed readiness semantics.
    assert set(("symbols", "classification", "live_data_enabled")) <= set(payload)
    assert payload["live_data_enabled"] is False
    assert payload["live_decision_input_enabled"] is False
    assert payload["trainer_input_enabled"] is False
    assert payload["source_receipt_authority"] is False
    assert payload["optional_derivative_rest_fallback_allowed"] is False
    assert payload["optional_derivative_rest_priority"] == (
        "DEFER_TO_CANONICAL_OHLCV_BY_DEFAULT"
    )
