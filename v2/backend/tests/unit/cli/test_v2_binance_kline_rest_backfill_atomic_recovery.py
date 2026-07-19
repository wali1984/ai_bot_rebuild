from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, NoReturn

import pytest

from v2.backend.app.cli import v2_binance_kline_rest_backfill as backfill
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.market_state_integrity.closed_window_redis_store import (
    ClosedWindowRedisStoreError,
    ClosedWindowRedisWriteResult,
)

OBSERVED_MS = 1_800_000_000_000


class _BinaryClient:
    def get_connection_kwargs(self) -> dict[str, Any]:
        return {"decode_responses": False}


def _rest_row(open_ms: int, duration_ms: int = 60_000) -> list[object]:
    return [
        open_ms,
        "100.0",
        "102.0",
        "99.0",
        "101.0",
        "10.0",
        open_ms + duration_ms - 1,
        "1005.0",
        7,
        "4.0",
        "402.0",
        "0",
    ]


def _canonical_rows(
    count: int,
    *,
    observed_ms: int = OBSERVED_MS,
    timeframe: str = "1m",
) -> list[dict[str, Any]]:
    duration_ms = backfill.TIMEFRAME_DURATION_MS[timeframe]
    first_open = observed_ms - (count * duration_ms)
    return [
        canonical_from_binance_rest(
            _rest_row(first_open + (index * duration_ms), duration_ms),
            symbol="BTCUSDT",
            timeframe=timeframe,
            ingested_at=observed_ms,
        ).to_dict()
        for index in range(count)
    ]


def _payload(rows: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        rows,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("ascii")


def _install_exact_read(
    monkeypatch: pytest.MonkeyPatch,
    rows: list[dict[str, Any]] | None,
) -> None:
    payload = _payload(rows) if rows is not None else None
    result = SimpleNamespace(
        present=payload is not None,
        exact_payload_bytes=payload,
        payload_byte_count=len(payload or b""),
        payload_sha256="a" * 64 if payload is not None else None,
    )
    monkeypatch.setattr(
        backfill,
        "read_atomic_redis_sources",
        lambda _client, _keys: SimpleNamespace(results=(result,)),
    )
    monkeypatch.setattr(backfill, "_consumer_observed_at_ms", lambda: OBSERVED_MS)


def _assessment(
    *,
    ready: bool,
    status: str,
    opens: frozenset[int] = frozenset(),
    rows: int = 0,
    error_code: str | None = None,
) -> backfill.ClosedWindowCacheAssessment:
    return backfill.ClosedWindowCacheAssessment(
        redis_key="v2:market:ohlcv_closed:binance:BTCUSDT:1m",
        symbol="BTCUSDT",
        timeframe="1m",
        status=status,
        ready=ready,
        consumer_observed_at_ms=OBSERVED_MS,
        expected_latest_finalized_close_time=OBSERVED_MS - 1,
        exact_payload_byte_count=1,
        exact_payload_sha256="a" * 64,
        row_count=rows,
        contiguous_suffix_count=rows,
        tail_missing_interval_count=0 if ready else 1,
        existing_open_times=opens,
        error_code=error_code,
        source_schema_validated=bool(rows),
        end_exclusive_finality_validated=bool(rows),
    )


def _write_result(*, replaced: bool = False, stored_rows: int = 71) -> ClosedWindowRedisWriteResult:
    return ClosedWindowRedisWriteResult(
        redis_key="v2:market:ohlcv_closed:binance:BTCUSDT:1m",
        attempts=1,
        existing_row_count=1,
        submitted_row_count=71,
        stored_row_count=stored_rows,
        rows_deduplicated_or_trimmed_for_row_limit=0,
        rows_trimmed_for_bytes=0,
        payload_sha256="b" * 64,
        payload_byte_count=1234,
        ttl_policy="set",
        ttl_seconds=86_400,
        previous_pttl_ms=-1,
        invalid_existing_replaced=replaced,
    )


def test_redis_factory_requires_binary_responses(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: dict[str, object] = {}

    def fake_from_url(url: str, **kwargs: object) -> object:
        captured.update(url=url, **kwargs)
        return object()

    monkeypatch.setattr(backfill.redis.Redis, "from_url", fake_from_url)
    backfill._redis_client()

    assert captured["decode_responses"] is False


def test_exact_cache_assessment_binds_full_latest_71_row_suffix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_exact_read(monkeypatch, _canonical_rows(71))

    result = backfill._assess_closed_window(_BinaryClient(), "BTCUSDT", "1m")

    assert result.ready is True
    assert result.status == "cache_ready"
    assert result.row_count == 71
    assert result.contiguous_suffix_count == 71
    assert result.tail_missing_interval_count == 0
    assert result.expected_latest_finalized_close_time == OBSERVED_MS - 1
    assert result.source_schema_validated is True
    assert result.end_exclusive_finality_validated is True
    assert len(result.existing_open_times) == 71


def test_exact_cache_assessment_rejects_short_suffix_after_internal_gap(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = _canonical_rows(72)
    del rows[-2]
    _install_exact_read(monkeypatch, rows)

    result = backfill._assess_closed_window(_BinaryClient(), "BTCUSDT", "1m")

    assert result.ready is False
    assert result.status == "cache_contiguous_suffix_short"
    assert result.row_count == 71
    assert result.contiguous_suffix_count == 1
    assert result.tail_missing_interval_count == 0


def test_canonicalization_is_end_exclusive_and_preserves_pit_clocks() -> None:
    observed_ms = OBSERVED_MS - 1
    previous_open = observed_ms - 119_999
    equality_open = observed_ms - 59_999

    rows = backfill._canonicalize_finalized_rest_rows(
        [_rest_row(previous_open), _rest_row(equality_open)],
        symbol="BTCUSDT",
        timeframe="1m",
        response_received_at_ms=observed_ms,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["candle_close_time"] == observed_ms - 60_000
    assert row["event_time"] == row["candle_close_time"]
    assert row["ingested_at"] == observed_ms
    assert row["available_at"] == observed_ms
    assert row["source"] == "binance_rest"


def test_http_reader_requests_only_cap_plus_one_and_rejects_oversize(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed_sizes: list[int] = []
    policy_calls: list[dict[str, object]] = []

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, size: int) -> bytes:
            observed_sizes.append(size)
            return b"x" * size

    def _require_policy(**kwargs: object) -> dict[str, object]:
        policy_calls.append(kwargs)
        return {}

    monkeypatch.setattr(backfill, "require_binance_rest_fallback", _require_policy)
    monkeypatch.setattr(backfill.urllib.request, "urlopen", lambda *_args, **_kwargs: _Response())

    with pytest.raises(
        backfill.KlineBackfillRecoveryError,
        match="^kline_backfill_http_payload_oversized$",
    ):
        backfill._http_get(
            "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT",
            retries=1,
        )

    assert observed_sizes == [backfill.MAX_HTTP_RESPONSE_BYTES + 1]
    assert policy_calls[0]["request_weight"] == 1
    assert policy_calls[0]["require_shared_budget"] is True


def test_http_reader_reserves_shared_budget_for_every_physical_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    policy_calls: list[dict[str, object]] = []
    request_calls = 0

    class _Response:
        def __enter__(self) -> _Response:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def read(self, _size: int) -> bytes:
            return b"[]"

    def _require_policy(**kwargs: object) -> dict[str, object]:
        policy_calls.append(kwargs)
        return {}

    def _urlopen(*_args: object, **_kwargs: object) -> _Response:
        nonlocal request_calls
        request_calls += 1
        if request_calls == 1:
            raise backfill.urllib.error.URLError("retryable")
        return _Response()

    monkeypatch.setattr(backfill, "require_binance_rest_fallback", _require_policy)
    monkeypatch.setattr(backfill.urllib.request, "urlopen", _urlopen)
    monkeypatch.setattr(backfill.time, "sleep", lambda _seconds: None)

    assert (
        backfill._http_get(
            "https://fapi.binance.com/fapi/v1/klines?symbol=BTCUSDT",
            retries=2,
        )
        == []
    )
    assert request_calls == 2
    assert len(policy_calls) == 2
    assert all(call["request_weight"] == 1 for call in policy_calls)
    assert all(call["require_shared_budget"] is True for call in policy_calls)


def test_symbol_discovery_uses_binary_scan_not_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _ScanClient(_BinaryClient):
        def scan_iter(self, *, match: str, count: int):  # type: ignore[no-untyped-def]
            assert match == "v2:market:kline_current:binance:*"
            assert count == backfill.REDIS_SCAN_COUNT_HINT
            yield b"v2:market:kline_current:binance:BTCUSDT:1m"

        def keys(self, *_args: object, **_kwargs: object) -> NoReturn:
            raise AssertionError("KEYS must never be used")

    monkeypatch.setattr(
        backfill,
        "_assess_closed_window",
        lambda *_args: _assessment(ready=False, status="cache_missing"),
    )

    assert backfill._missing_symbols(_ScanClient(), ("1m",)) == {"BTCUSDT": ["1m"]}


def test_ready_cache_skips_rest_and_never_claims_a_write(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    ready = _assessment(ready=True, status="cache_ready", rows=71)
    monkeypatch.setattr(backfill, "_assess_closed_window", lambda *_args: ready)
    monkeypatch.setattr(
        backfill,
        "_fetch_rest_klines",
        lambda *_args: pytest.fail("REST must not run for a ready exact cache"),
    )

    outcome = backfill._backfill_symbol_tf(_BinaryClient(), "BTCUSDT", "1m")

    assert outcome["recovery_status"] == "cache_ready_no_write"
    assert outcome["write_committed"] is False
    assert outcome["closed_ingested"] == 0
    assert outcome["rest_fallback_used"] is False


def test_invalid_existing_requires_explicit_replacement_before_rest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    invalid = _assessment(ready=False, status="cache_schema_invalid")
    monkeypatch.setattr(backfill, "_assess_closed_window", lambda *_args: invalid)
    monkeypatch.setattr(
        backfill,
        "_fetch_rest_klines",
        lambda *_args: pytest.fail("REST must not run without repair authority"),
    )

    with pytest.raises(
        backfill.KlineBackfillRecoveryError,
        match="^kline_backfill_invalid_existing_repair_not_authorized$",
    ):
        backfill._backfill_symbol_tf(_BinaryClient(), "BTCUSDT", "1m")


def test_unavailable_cache_assessment_blocks_before_rest_even_with_replacement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    unavailable = _assessment(
        ready=False,
        status="cache_assessment_unavailable",
        error_code="atomic_redis_source_read_pipeline_cleanup_failed",
    )
    monkeypatch.setattr(backfill, "_assess_closed_window", lambda *_args: unavailable)

    def _must_not_fetch(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("REST must not run when exact cache assessment is unavailable")

    monkeypatch.setattr(backfill, "_fetch_rest_klines", _must_not_fetch)

    with pytest.raises(
        backfill.KlineBackfillRecoveryError,
        match="^kline_backfill_cache_assessment_unavailable$",
    ):
        backfill._backfill_symbol_tf(
            _BinaryClient(),
            "BTCUSDT",
            "1m",
            replace_invalid_existing=True,
        )


@pytest.mark.parametrize("replace_invalid_existing", [False, True])
def test_nonready_cache_forces_rest_filters_overlap_and_merges_atomically(
    monkeypatch: pytest.MonkeyPatch,
    replace_invalid_existing: bool,
) -> None:
    raw_rows = [_rest_row(OBSERVED_MS - (index * 60_000)) for index in range(72, 0, -1)]
    overlap_open = int(raw_rows[0][0])
    before = _assessment(
        ready=False,
        status="cache_tail_stale",
        opens=frozenset({overlap_open}),
        rows=1,
    )
    after = _assessment(ready=True, status="cache_ready", rows=72)
    assessments = iter((before, after))
    monkeypatch.setattr(
        backfill,
        "_assess_closed_window",
        lambda *_args: next(assessments),
    )
    monkeypatch.setattr(backfill, "_fetch_rest_klines", lambda *_args: raw_rows)
    monkeypatch.setattr(backfill, "_consumer_observed_at_ms", lambda: OBSERVED_MS)
    call: dict[str, Any] = {}

    def fake_atomic(_client: object, **kwargs: Any) -> ClosedWindowRedisWriteResult:
        call.update(kwargs)
        return _write_result(replaced=replace_invalid_existing, stored_rows=72)

    monkeypatch.setattr(backfill, "atomic_merge_closed_window", fake_atomic)

    outcome = backfill._backfill_symbol_tf(
        _BinaryClient(),
        "BTCUSDT",
        "1m",
        replace_invalid_existing=replace_invalid_existing,
    )

    submitted = call["new_rows"]
    assert len(submitted) == 71
    assert all(row["candle_open_time"] != overlap_open for row in submitted)
    assert call["replace_invalid_existing"] is replace_invalid_existing
    assert call["ttl_policy"] == "set"
    assert call["ttl_seconds"] == 86_400
    assert call["minimum_rows_to_preserve"] == 71
    assert outcome["write_committed"] is True
    assert outcome["closed_ingested"] == 71
    assert outcome["cache_ready_after"] is True
    assert outcome["recovery_status"] == "write_committed_cache_ready"


def test_adaptive_ttl_scales_with_timeframe_when_floor_does_not_bind() -> None:
    assert backfill._adaptive_closed_window_ttl_seconds("1m", 1) == 180
    assert backfill._adaptive_closed_window_ttl_seconds("4h", 1) == 43_200


def test_errors_are_stable_codes_and_redact_transport_details() -> None:
    error = ClosedWindowRedisStoreError(
        "closed_window_redis_operation_failed:redis://user:secret@example"
    )
    assert backfill._stable_error_code(error) == "closed_window_redis_operation_failed"
    assert backfill._stable_error_code(RuntimeError("token=secret value")) == (
        "kline_backfill_internal_error"
    )
    assert backfill._stable_error_code(RuntimeError("secret")) == ("kline_backfill_internal_error")
    assert (
        backfill._stable_error_code(
            RuntimeError("REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION:999>120")
        )
        == "REST_FALLBACK_BUDGET_EXHAUSTED_BAN_PROTECTION"
    )


def test_replace_invalid_existing_authority_defaults_false() -> None:
    parameter = backfill._backfill_symbol_tf.__kwdefaults__
    assert parameter == {"replace_invalid_existing": False}


def test_assessment_value_cannot_grant_trainer_or_live_authority() -> None:
    ready = _assessment(ready=True, status="cache_ready", rows=71)
    assert ready.market_selection_threshold is False
    assert ready.trainer_admission_granted is False
    assert ready.live_execution_authorized is False
    assert replace(ready, status="cache_ready").trainer_admission_granted is False
