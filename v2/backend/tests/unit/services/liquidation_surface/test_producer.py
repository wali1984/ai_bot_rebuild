from __future__ import annotations

import json
from types import MappingProxyType, SimpleNamespace
from typing import Any

import pytest
from v2.backend.app.services.binance_usdm_leverage_bracket_evidence import (
    build_evidence_security_context,
)
from v2.backend.app.services.liquidation_surface import producer
from v2.backend.app.services.liquidation_surface.contracts import LeverageBracket
from v2.backend.app.services.liquidation_surface.producer import (
    AdaptiveOISelection,
    ExactRedisSnapshot,
    LiquidationSurfaceProducerError,
    MarkPriceHistory,
    build_lane_candidate,
    publication_scope_metadata,
    read_exact_redis_snapshot,
    redis_now_ms,
    redis_utc_now,
    require_publication_scope_binding,
    run_producer_cycle,
    select_adaptive_coinank_open_interest,
)
from v2.backend.app.services.liquidation_surface.publication import (
    build_surface_publication_security_context,
)

SYMBOL = "BTCUSDT"
BASE_MS = 1_800_000_000_000


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _candle(index: int, *, timeframe: str = "1m") -> dict[str, object]:
    duration = 60_000
    open_time = BASE_MS + index * duration
    close_time = open_time + duration - 1
    return {
        "symbol": SYMBOL,
        "exchange": "binance",
        "timeframe": timeframe,
        "candle_open_time": open_time,
        "candle_close_time": close_time,
        "event_time": close_time,
        "ingested_at": close_time + 10,
        "available_at": close_time + 20,
        "is_closed": True,
        "closed_candle": True,
        "candle_closed_confirmed": True,
        "feature_eligible": True,
        "source": "binance_wss",
        "source_sequence_id": str(close_time),
        "raw_payload_hash": f"{index + 1:064x}",
        "open": 100.0 + index,
        "high": 102.0 + index,
        "low": 99.0 + index,
        "close": 101.0 + index,
        "quote_volume": 1_000.0,
        "taker_buy_quote_vol": 600.0,
    }


def _mark(event_time: int, price: float) -> bytes:
    return _json_bytes(
        {
            "schema_version": "binance_usdm_mark_price_wss_v1",
            "symbol": SYMBOL,
            "source": "binance_usdm_wss_mark_price_all_symbols",
            "transport": "websocket_primary",
            "event_time": event_time,
            "available_at": event_time + 10,
            "markPrice": price,
        }
    )


def _oi_payload(timeframe: str, *, begin: int, fetched_at: int) -> bytes:
    duration = producer._TIMEFRAME_MS[timeframe]  # noqa: SLF001
    return _json_bytes(
        {
            "ts_ms": fetched_at,
            "request_started_at_ms": fetched_at - 100,
            "symbol": SYMBOL,
            "exchange": "Binance",
            "family": "open_interest",
            "endpoint": "openInterest_kline",
            "interval": timeframe,
            "request_parameters": {
                "exchange": "Binance",
                "symbol": SYMBOL,
                "interval": timeframe,
                "productType": "SWAP",
                "size": 15,
            },
            "data": {
                "success": True,
                "code": "1",
                "data": [
                    {"begin": begin, "close": "100"},
                    {"begin": begin + duration, "close": "110"},
                ],
            },
        }
    )


def _bracket_context():
    return build_evidence_security_context(
        trader_id="trader-wajidali1984",
        credential_ref="ALPHAFORGE_BINANCE_WAJIDALI1984_READONLY",
        base_url="https://fapi.binance.com",
        credential_account_specific=True,
        hmac_key="bracket-test-key-material-that-is-long-enough",
        auth_key_id="bracket-test-v1",
    )


def _publication_context(bracket_context=None):
    context = bracket_context or _bracket_context()
    return build_surface_publication_security_context(
        scope_metadata=publication_scope_metadata(context),
        hmac_key="publication-test-key-material-long-enough",
        auth_key_id="publication-test-v1",
    )


class _SnapshotPipe:
    def __init__(self, values: dict[str, bytes | None]) -> None:
        self.values = values
        self.keys: tuple[str, ...] = ()
        self.operations: list[str] = []

    def mget(self, keys: tuple[str, ...]) -> None:
        self.operations.append("mget")
        self.keys = keys

    def time(self) -> None:
        self.operations.append("time")

    def execute(self) -> list[object]:
        assert self.operations == ["mget", "time"]
        return [[self.values.get(key) for key in self.keys], (1_800_000_001, 250_000)]


class _SnapshotRedis:
    def __init__(self, values: dict[str, bytes | None]) -> None:
        self.values = values

    def pipeline(self, *, transaction: bool) -> _SnapshotPipe:
        assert transaction is True
        return _SnapshotPipe(self.values)


def test_exact_snapshot_reads_binary_bytes_before_redis_clock() -> None:
    snapshot = read_exact_redis_snapshot(
        _SnapshotRedis({"a": b"one", "b": None}),
        keys=("a", "b"),
    )

    assert snapshot.values == {"a": b"one", "b": None}
    assert snapshot.consumer_observed_at_ms == 1_800_000_001_250
    with pytest.raises(TypeError):
        snapshot.values["a"] = b"changed"  # type: ignore[index]


def test_redis_clock_uses_conservative_millisecond_ceiling() -> None:
    redis_client = SimpleNamespace(time=lambda: (1_800_000_001, 250_001))

    assert redis_now_ms(redis_client) == 1_800_000_001_251
    assert redis_utc_now(redis_client).timestamp() == pytest.approx(1_800_000_001.250001)


def test_exact_snapshot_rejects_decoded_or_duplicate_inputs() -> None:
    with pytest.raises(
        LiquidationSurfaceProducerError,
        match="REDIS_BINARY_RESPONSE_REQUIRED",
    ):
        read_exact_redis_snapshot(_SnapshotRedis({"a": "decoded"}), keys=("a",))  # type: ignore[dict-item]
    with pytest.raises(LiquidationSurfaceProducerError, match="KEYS_INVALID"):
        read_exact_redis_snapshot(_SnapshotRedis({}), keys=("a", "a"))


def test_mark_history_keeps_only_two_distinct_exact_events() -> None:
    history = MarkPriceHistory()
    first = _mark(BASE_MS + 1, 101.0)
    second = _mark(BASE_MS + 2, 102.0)
    third = _mark(BASE_MS + 3, 103.0)
    history.record(symbol=SYMBOL, value=first, observed_at_ms=BASE_MS + 100)
    history.record(symbol=SYMBOL, value=first, observed_at_ms=BASE_MS + 200)
    history.record(symbol=SYMBOL, value=second, observed_at_ms=BASE_MS + 300)
    history.record(symbol=SYMBOL, value=third, observed_at_ms=BASE_MS + 400)

    samples = history.latest(SYMBOL)
    assert tuple(row.raw for row in samples) == (second, third)
    assert history.two_sample_symbol_count((SYMBOL, "ETHUSDT")) == 1


def test_adaptive_oi_uses_latest_cutoff_then_finest_valid_resolution() -> None:
    observed = BASE_MS + 3_000_000
    five_key = f"latest:coinank:open_interest:{SYMBOL}:5m"
    hour_key = f"latest:coinank:open_interest:{SYMBOL}:1h"
    selection = select_adaptive_coinank_open_interest(
        symbol=SYMBOL,
        snapshot=ExactRedisSnapshot(
            values=MappingProxyType(
                {
                    five_key: _oi_payload("5m", begin=BASE_MS, fetched_at=observed - 1),
                    hour_key: _oi_payload("1h", begin=BASE_MS - 3_300_000, fetched_at=observed - 1),
                }
            ),
            consumer_observed_at_ms=observed,
        ),
    )

    assert selection.source_timeframe == "5m"
    assert len(selection.observations) == 2
    assert selection.valid_candidate_count == 2
    assert selection.missing_candidate_count == 4


def test_adaptive_oi_missing_or_invalid_is_explicitly_maskable() -> None:
    key = f"latest:coinank:open_interest:{SYMBOL}:5m"
    selection = select_adaptive_coinank_open_interest(
        symbol=SYMBOL,
        snapshot=ExactRedisSnapshot(
            values=MappingProxyType({key: b"not-json"}),
            consumer_observed_at_ms=BASE_MS + 1,
        ),
    )

    assert selection.observations == ()
    assert selection.source_timeframe is None
    assert selection.valid_candidate_count == 0
    assert selection.rejection_counts == {"REDIS_VALUE_NOT_STRICT_JSON": 1}


def test_degraded_lane_has_no_proxy_levels_or_trainer_authority() -> None:
    history = MarkPriceHistory()
    empty_oi = AdaptiveOISelection(
        observations=(),
        source_timeframe=None,
        valid_candidate_count=0,
        missing_candidate_count=6,
        rejection_counts=MappingProxyType({}),
    )
    payload, diagnostics = build_lane_candidate(
        symbol=SYMBOL,
        timeframe="1m",
        candle_raw=_json_bytes([_candle(0), _candle(1)]),
        source_observed_at_ms=BASE_MS + 200_000,
        mark_history=history,
        oi_selection=empty_oi,
        bracket_result={"status": "MISSING", "observations": ()},
        as_of_time_ms=BASE_MS + 200_000,
        generated_at_ms=BASE_MS + 200_001,
    )

    assert payload["trainer_semantic_eligible"] is False
    assert payload["trainer_authority"] is False
    assert payload["long_levels"] == []
    assert payload["short_levels"] == []
    assert payload["exchange_max_initial_leverage"] is None
    assert diagnostics["mark_price_count"] == 0
    assert diagnostics["open_interest_count"] == 0
    assert diagnostics["bracket_count"] == 0


def test_lane_without_finalized_candles_is_quarantined() -> None:
    with pytest.raises(
        LiquidationSurfaceProducerError,
        match="FINALIZED_CANDLE_SOURCE_MISSING",
    ):
        build_lane_candidate(
            symbol=SYMBOL,
            timeframe="1m",
            candle_raw=None,
            source_observed_at_ms=BASE_MS,
            mark_history=MarkPriceHistory(),
            oi_selection=AdaptiveOISelection((), None, 0, 6, MappingProxyType({})),
            bracket_result={},
            as_of_time_ms=BASE_MS,
            generated_at_ms=BASE_MS,
        )


def test_authenticated_bracket_crossing_lane_clock_is_omitted_not_fatal() -> None:
    as_of = BASE_MS + 200_000
    expired = LeverageBracket(
        venue="binance_usdm",
        symbol=SYMBOL,
        bracket_id=1,
        notional_floor=0.0,
        notional_cap=1_000_000.0,
        initial_leverage=20,
        maintenance_margin_rate=0.004,
        fetched_at_ms=as_of - 1_000,
        ingested_at_ms=as_of - 900,
        available_at_ms=as_of - 800,
        expires_at_ms=as_of,
        source_key="v2:binance_usdm:leverage_bracket:test:BTCUSDT",
        source_sha256="d" * 64,
    )

    payload, diagnostics = build_lane_candidate(
        symbol=SYMBOL,
        timeframe="1m",
        candle_raw=_json_bytes([_candle(0), _candle(1)]),
        source_observed_at_ms=as_of,
        mark_history=MarkPriceHistory(),
        oi_selection=AdaptiveOISelection((), None, 0, 6, MappingProxyType({})),
        bracket_result={
            "status": "READY",
            "evidence_authenticated": True,
            "observations": (expired,),
        },
        as_of_time_ms=as_of,
        generated_at_ms=as_of + 1,
    )

    assert payload["trainer_semantic_eligible"] is False
    assert payload["long_levels"] == []
    assert payload["short_levels"] == []
    assert diagnostics["bracket_count"] == 0
    assert diagnostics["bracket_lane_admission_status"] == (
        "OMITTED_MISSING_INVALID_OR_OUTSIDE_LANE_CLOCK"
    )


def test_publication_scope_is_derived_from_exact_bracket_binding() -> None:
    bracket_context = _bracket_context()
    publication_context = _publication_context(bracket_context)
    require_publication_scope_binding(
        bracket_security_context=bracket_context,
        publication_security_context=publication_context,
    )

    other = build_evidence_security_context(
        trader_id="trader-other",
        credential_ref="OTHER_BINANCE_READONLY",
        base_url="https://fapi.binance.com",
        credential_account_specific=True,
        hmac_key="other-bracket-test-key-material-long-enough",
        auth_key_id="bracket-test-v1",
    )
    with pytest.raises(
        LiquidationSurfaceProducerError,
        match="PUBLICATION_BRACKET_SCOPE_BINDING_MISMATCH",
    ):
        require_publication_scope_binding(
            bracket_security_context=other,
            publication_security_context=publication_context,
        )


class _CycleRedis:
    def __init__(self, *, clock_step_ms: int = 1) -> None:
        # Keep the Redis decision clock causally after the snapshot's source
        # observation time.  A clock before ``available_at`` must fail closed.
        self.clock = BASE_MS + 300_000
        self.clock_step_ms = clock_step_ms
        self.status_writes: list[tuple[str, bytes, int]] = []

    def time(self) -> tuple[int, int]:
        self.clock += self.clock_step_ms
        return self.clock // 1_000, (self.clock % 1_000) * 1_000

    def get(self, _key: str) -> None:
        return None

    def set(self, key: str, value: bytes, *, ex: int) -> bool:
        self.status_writes.append((key, value, ex))
        return True


@pytest.mark.parametrize(
    (
        "clock_step_ms",
        "receipt_ttl_seconds",
        "expected_status",
        "expected_reason",
        "continuous_coverage",
    ),
    [
        (
            1,
            producer.DEFAULT_RECEIPT_TTL_SECONDS,
            "COMPLETE",
            "ALL_LANES_PUBLISHED_WITH_CONTINUOUS_POINTER_COVERAGE",
            True,
        ),
        (
            2_000,
            1,
            "PARTIAL",
            "RECEIPT_TTL_DID_NOT_OUTLIVE_FULL_UNIVERSE_CYCLE",
            False,
        ),
    ],
)
def test_cycle_counts_publication_and_reports_pointer_coverage(
    monkeypatch: pytest.MonkeyPatch,
    clock_step_ms: int,
    receipt_ttl_seconds: int,
    expected_status: str,
    expected_reason: str,
    continuous_coverage: bool,
) -> None:
    redis_client = _CycleRedis(clock_step_ms=clock_step_ms)
    candle_key = f"v2:market:ohlcv_closed:binance:{SYMBOL}:1m"
    mark_key = f"v2:market:mark_price:{SYMBOL}"

    def snapshot(_client: Any, *, keys: tuple[str, ...]) -> ExactRedisSnapshot:
        values = {
            key: (
                _json_bytes([_candle(0), _candle(1)])
                if key == candle_key
                else _mark(BASE_MS + 1, 101.0)
                if key == mark_key
                else None
            )
            for key in keys
        }
        return ExactRedisSnapshot(MappingProxyType(values), BASE_MS + 200_000)

    monkeypatch.setattr(producer, "read_exact_redis_snapshot", snapshot)
    def publish(_client: Any, candidate: dict[str, Any], **_kwargs: Any) -> Any:
        return SimpleNamespace(
            trainer_authority=False,
            pointer_class="observation",
            receipt={
                "trainer_source_bundle_sha256": candidate["trainer_source_bundle"][
                    "bundle_sha256"
                ],
                "trainer_storage_candidate_eligible": False,
            },
        )

    monkeypatch.setattr(producer, "publish_liquidation_surface", publish)

    result = run_producer_cycle(
        redis_client,
        symbols=(SYMBOL,),
        timeframes=("1m",),
        bracket_security_context=_bracket_context(),
        publication_security_context=_publication_context(),
        mark_history=MarkPriceHistory(),
        receipt_ttl_seconds=receipt_ttl_seconds,
    )

    assert result["status"] == expected_status
    assert result["reason"] == expected_reason
    assert result["lane_count"] == 1
    assert result["published_lane_count"] == 1
    assert result["trainer_semantic_candidate_count"] == 0
    assert result["trainer_authority_count"] == 0
    assert result["observation_pointer_count"] == 1
    assert result["verified_prepared_source_bundle_count"] == 1
    assert (result["receipt_ttl_margin_ms"] > 0) is continuous_coverage
    assert result["continuous_pointer_coverage"] is continuous_coverage
    assert result["prediction_authority"] is False
    assert result["paper_trading_authority"] is False
    assert result["live_trading_authority"] is False
    assert len(redis_client.status_writes) == 1


def test_cycle_rejects_any_publication_that_claims_trainer_authority(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        producer,
        "read_exact_redis_snapshot",
        lambda _client, *, keys: ExactRedisSnapshot(
            MappingProxyType(
                {
                    key: _json_bytes([_candle(0), _candle(1)])
                    if "ohlcv_closed" in key
                    else _mark(BASE_MS + 1, 101.0)
                    if "mark_price" in key
                    else None
                    for key in keys
                }
            ),
            BASE_MS + 200_000,
        ),
    )
    monkeypatch.setattr(
        producer,
        "publish_liquidation_surface",
        lambda *_args, **_kwargs: SimpleNamespace(
            trainer_authority=True,
            pointer_class="trainer_eligible",
        ),
    )

    with pytest.raises(
        LiquidationSurfaceProducerError,
        match="PUBLICATION_UNEXPECTED_TRAINER_AUTHORITY",
    ):
        run_producer_cycle(
            _CycleRedis(),
            symbols=(SYMBOL,),
            timeframes=("1m",),
            bracket_security_context=_bracket_context(),
            publication_security_context=_publication_context(),
            mark_history=MarkPriceHistory(),
        )
