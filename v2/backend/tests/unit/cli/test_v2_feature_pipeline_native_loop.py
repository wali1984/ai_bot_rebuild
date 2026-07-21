from __future__ import annotations

import hashlib
import importlib
import json
import math
import re
from types import SimpleNamespace

import pytest

from v2.backend.app.services.market_state_integrity.canonical_candles import (
    REQUIRED_DECISION_TIMEFRAMES,
    canonical_from_binance_rest,
    canonical_from_binance_wss,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)

_TEST_NOW_MS = 1_800_000_030_000


@pytest.fixture(autouse=True)
def _stable_feature_clock(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    monkeypatch.setattr(mod.time, "time", lambda: _TEST_NOW_MS / 1000.0)
    monkeypatch.setattr(mod, "_utc_iso", lambda: mod._ms_to_utc_iso(_TEST_NOW_MS))


def _latest_finalized_close_ms(mod, timeframe: str) -> int:
    return mod._expected_latest_finalized_close_ms(
        decision_ms=_TEST_NOW_MS,
        timeframe=timeframe,
    )


def _exact_candle_clocks(
    close_ms: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    event_ms: int | None = None,
    ingested_ms: int | None = None,
    available_ms: int | None = None,
) -> dict[str, int | str | bool]:
    resolved_event_ms = event_ms if event_ms is not None else close_ms + 100
    resolved_ingested_ms = (
        ingested_ms if ingested_ms is not None else resolved_event_ms + 100
    )
    return {
        "event_time": resolved_event_ms,
        "ingested_at": resolved_ingested_ms,
        "available_at": (
            available_ms
            if available_ms is not None
            else max(close_ms, resolved_event_ms, resolved_ingested_ms)
        ),
        "symbol": symbol,
        "exchange": "binance",
        "timeframe": timeframe,
        "source": "binance_wss",
        "is_backfilled": False,
        "is_closed": True,
        "feature_eligible": True,
        "source_sequence_id": str(resolved_event_ms),
        "raw_payload_hash": "a" * 64,
    }


def _canonical_closed_row(
    close_ms: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    source: str = "binance_wss",
    open_price: float = 99.0,
    high_price: float = 101.0,
    low_price: float = 98.0,
    close_price: float = 100.0,
    volume: float = 1_000.0,
    quote_volume: float = 100_000.0,
    num_trades: int = 20,
    taker_buy_base_vol: float = 500.0,
    taker_buy_quote_vol: float = 50_000.0,
    event_lag_ms: int = 100,
    ingestion_lag_ms: int = 200,
) -> dict:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    open_ms = close_ms - duration_ms + 1
    if source == "binance_rest":
        return canonical_from_binance_rest(
            [
                open_ms,
                str(open_price),
                str(high_price),
                str(low_price),
                str(close_price),
                str(volume),
                close_ms,
                str(quote_volume),
                num_trades,
                str(taker_buy_base_vol),
                str(taker_buy_quote_vol),
                "0",
            ],
            symbol=symbol,
            timeframe=timeframe,
            ingested_at=close_ms + ingestion_lag_ms,
        ).to_dict()
    event_ms = close_ms + event_lag_ms
    return canonical_from_binance_wss(
        {
            "E": event_ms,
            "k": {
                "s": symbol,
                "i": timeframe,
                "t": open_ms,
                "T": close_ms,
                "o": str(open_price),
                "h": str(high_price),
                "l": str(low_price),
                "c": str(close_price),
                "v": str(volume),
                "q": str(quote_volume),
                "n": num_trades,
                "V": str(taker_buy_base_vol),
                "Q": str(taker_buy_quote_vol),
                "B": "0",
                "x": True,
            },
        },
        symbol=symbol,
        timeframe=timeframe,
        ingested_at=close_ms + ingestion_lag_ms,
    ).to_dict()


def _canonical_closed_window(
    latest_close_ms: int,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    count: int = 80,
    source: str = "binance_wss",
    latest_values: dict[str, float | int] | None = None,
) -> list[dict]:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    rows = [
        _canonical_closed_row(
            latest_close_ms - ((count - 1 - index) * duration_ms),
            symbol=symbol,
            timeframe=timeframe,
            source=source,
        )
        for index in range(count)
    ]
    if latest_values:
        rows[-1] = _canonical_closed_row(
            latest_close_ms,
            symbol=symbol,
            timeframe=timeframe,
            source=source,
            **latest_values,
        )
    return rows


class _FakeAtomicPipeline:
    def __init__(self, redis_client: FakeRedis) -> None:
        self.redis_client = redis_client
        self.commands: list[tuple[str, object, object | None, object | None]] = []

    def type(self, key: str) -> _FakeAtomicPipeline:
        self.commands.append(("type", key, None, None))
        return self

    def getrange(self, key: str, start: int, end: int) -> _FakeAtomicPipeline:
        self.commands.append(("getrange", key, start, end))
        return self

    def pttl(self, key: str) -> _FakeAtomicPipeline:
        self.commands.append(("pttl", key, None, None))
        return self

    def time(self) -> _FakeAtomicPipeline:
        self.commands.append(("time", "", None, None))
        return self

    def execute(self) -> list[object]:
        responses: list[object] = []
        for command, raw_key, first, second in self.commands:
            key = str(raw_key)
            if command == "type":
                responses.append(b"string" if key in self.redis_client.store else b"none")
            elif command == "getrange":
                value = self.redis_client.store.get(key)
                if value is None:
                    responses.append(b"")
                else:
                    assert type(value) in (str, bytes)
                    payload = value if type(value) is bytes else value.encode("utf-8")
                    assert type(first) is int and type(second) is int
                    responses.append(payload[first : second + 1])
            elif command == "pttl":
                if key not in self.redis_client.store:
                    responses.append(-2)
                else:
                    expiry = self.redis_client.expiries.get(key)
                    responses.append(-1 if expiry is None else int(expiry) * 1000)
            elif command == "time":
                responses.append(
                    (_TEST_NOW_MS // 1000, (_TEST_NOW_MS % 1000) * 1000)
                )
        return responses

    def reset(self) -> None:
        return None

    def close(self) -> None:
        return None


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.expiries: dict[str, int | None] = {}
        self.get_calls: list[str] = []
        self.pipeline_transactions: list[bool] = []

    def ping(self) -> bool:
        return True

    def get_connection_kwargs(self) -> dict[str, bool]:
        return {"decode_responses": False}

    def pipeline(self, *, transaction: bool) -> _FakeAtomicPipeline:
        assert transaction is True
        self.pipeline_transactions.append(transaction)
        return _FakeAtomicPipeline(self)

    def get(self, key: str) -> object | None:
        self.get_calls.append(key)
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.store[key] = value
        self.expiries[key] = ex
        return True

    def exists(self, key: str) -> int:
        return 1 if key in self.store else 0

    def hgetall(self, key: str) -> dict:
        return {}

    def xrange(self, key: str, min: str = "-", max: str = "+") -> list:  # noqa: A002
        return []

    def scan_iter(self, match: str | None = None, count: int = 500):  # noqa: ARG002
        if match is None:
            yield from list(self.store)
            return
        prefix = match.rstrip("*")
        for key in list(self.store):
            if match.endswith("*") and key.startswith(prefix):
                yield key
            elif key == match:
                yield key


class _DecodedRedisView:
    def get_connection_kwargs(self) -> dict[str, bool]:
        return {"decode_responses": True}


def _capture_market_structure_family_inputs(monkeypatch, mod) -> dict[str, dict]:
    captures: dict[str, dict] = {}

    def capture(family: str):
        def compute(**kwargs):
            captures[family] = {
                "candles": [dict(row) for row in kwargs.get("candles") or []],
                "price": kwargs.get("price"),
                "timeframe": kwargs.get("timeframe"),
            }
            return {}

        return compute

    for attribute, family in (
        ("compute_liquidity_zones", "liquidity_zones"),
        ("compute_structure", "structure"),
        ("compute_fvg", "fvg"),
        ("compute_vwap_features", "vwap"),
        ("compute_volume_profile", "volume_profile"),
        ("compute_cvd_features", "cvd"),
    ):
        monkeypatch.setattr(mod, attribute, capture(family))
    return captures


def _market_payload() -> dict:
    return {
        "price": 100.0,
        "ticker_24hr": {
            "lastPrice": "100.0",
            "openPrice": "99.0",
            "highPrice": "101.0",
            "lowPrice": "98.0",
            "prevClosePrice": "99.0",
            "quoteVolume": "1000000",
        },
        "funding": {"lastFundingRate": "0.0001", "markPrice": "100.0", "indexPrice": "100.0"},
        "open_interest": {},
    }


def test_utc_iso_preserves_millisecond_precision() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")

    value = mod._utc_iso()

    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}Z", value)


def test_ohlcv_binary_client_uses_dedicated_raw_view_for_decoded_client(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    decoded = _DecodedRedisView()
    raw = FakeRedis()
    created: list[bool] = []

    def connect_raw():
        created.append(True)
        return raw

    monkeypatch.setattr(mod, "_connect_ohlcv_binary_redis", connect_raw)

    assert mod._ohlcv_binary_client_for(decoded) is raw
    assert mod._ohlcv_binary_client_for(raw) is raw
    assert mod._ohlcv_binary_client_for(None) is None
    assert created == [True]


def test_unavailable_atomic_client_uses_hold_evaluation_clock() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")

    rows, lineage = mod._read_klines_with_lineage(  # noqa: SLF001
        None,
        "BTCUSDT",
        "1m",
    )

    assert rows is None
    assert lineage["selection_rejection_reasons"] == [
        "ATOMIC_OHLCV_RAW_REDIS_CLIENT_UNAVAILABLE"
    ]
    assert lineage["consumer_observation_cutoff_ms"] == _TEST_NOW_MS
    assert (
        lineage["consumer_observation_clock_source"]
        == "LOCAL_CLOCK_AT_HOLD_EVALUATION"
    )


def test_feature_snapshot_without_closed_ohlcv_is_not_trainer_consumable(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(
        ("BTCUSDT",),
        "1m",
        write_trainer_snapshot=False,
    )

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert payload["candle_closed_confirmed"] is False
    assert payload["feature_cutoff"] is None
    assert "ohlcv_closed_window" in payload["missing_feature_flags"]
    assert "candle_closed_confirmed" in payload["missing_feature_flags"]
    assert "feature_cutoff" in payload["missing_feature_flags"]


def test_feature_snapshot_with_closed_ohlcv_carries_cutoff(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(close_ms)
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    heartbeat = mod.run_once(
        ("BTCUSDT",),
        "1m",
        write_trainer_snapshot=False,
    )

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["schema_version"] == "v2_native_feature_snapshot_v2"
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "FEATURE_AVAILABILITY_UNVERIFIED"
    assert payload["candle_closed_confirmed"] is True
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(close_ms)  # noqa: SLF001
    assert payload["event_time"] == mod._ms_to_utc_iso(close_ms + 100)
    assert payload["ingested_at"] == mod._ms_to_utc_iso(close_ms + 200)
    assert payload["source_available_at"] == mod._ms_to_utc_iso(close_ms + 200)
    assert payload["exact_source_clock_valid"] is True
    assert payload["exact_source_clock_rejection_reasons"] == []
    assert payload["available_at"] is None
    assert payload["feature_available_at"] is None
    assert payload["exact_feature_availability_valid"] is False
    assert payload["exact_feature_availability_rejection_reasons"] == [
        "FEATURE_PUBLICATION_RECEIPT_REQUIRED"
    ]
    assert payload["required_model_feature_pit_coverage_valid"] is False
    assert payload["required_model_feature_pit_rejection_reasons"] == [
        "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED"
    ]
    assert payload["feature_requirement_policy_id"] == (
        "v2_hybrid_feature_requirements_v2"
    )
    assert payload["model_feature_abi_slot_count"] == 446
    assert payload["required_model_feature_count"] == 383
    assert len(payload["required_model_feature_fields"]) == 383
    assert payload["optional_event_dependent_feature_count"] == 63
    assert len(payload["optional_event_dependent_feature_fields"]) == 63
    assert "gap_pct" not in payload["required_model_feature_fields"]
    assert "coinapi_wsds_tape_imbalance" not in payload[
        "required_model_feature_fields"
    ]
    assert "coinapi_wsds_tape_imbalance" in payload[
        "optional_event_dependent_feature_fields"
    ]
    assert "last_liq_bps_24h" in payload[
        "optional_event_dependent_feature_fields"
    ]
    assert "paper_position_present" in payload[
        "optional_event_dependent_feature_fields"
    ]
    assert "last_liq_bps_24h" not in payload[
        "required_model_feature_missing_fields"
    ]
    assert "paper_position_present" not in payload[
        "required_model_feature_missing_fields"
    ]
    assert payload["ohlcv_history_payload_receipts_valid"] is False
    assert payload["ohlcv_history_payload_receipt_rejection_reasons"] == [
        "IMMUTABLE_OHLCV_HISTORY_PAYLOAD_RECEIPTS_REQUIRED"
    ]
    selection = payload["ohlcv_consumer_selection"]
    assert selection["selection_mode"] == (
        "ATOMIC_CANONICAL_CLOSED_FULL_CONTIGUOUS_SUFFIX_BOUND"
    )
    assert selection["exact_source_schema_validated"] is True
    assert selection["entire_contiguous_suffix_bound"] is True
    assert selection["selected_row_count"] == 80
    assert selection["durable_source_receipt_emitted"] is False
    assert selection["feature_publication_receipt_emitted"] is False
    assert selection["consumer_eligible"] is False
    assert selection["trainer_admission_granted"] is False
    assert payload["latest_finalized_candle_available_at_decision"] is True
    assert payload["temporal_rejection_reasons"] == []
    assert heartbeat["classification"] == (
        "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD"
    )
    assert heartbeat["latest_candle_temporally_valid_count"] == 1
    assert heartbeat["exact_feature_availability_valid_count"] == 0
    assert heartbeat["required_model_feature_pit_coverage_valid_count"] == 0
    assert heartbeat["trainer_consumable_count"] == 0
    assert heartbeat["prediction_eligible_count"] == 0
    assert heartbeat["paper_eligible_count"] == 0
    assert heartbeat["publication_receipt_held_count"] == 1
    assert heartbeat["active_consumer_readiness"] == "HELD"
    assert heartbeat["trainer_release_ready"] is False


def test_run_once_wires_postcommit_receipt_without_promoting_consumers(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    # The production redis-py client exposes EVAL; this test double opts in so
    # run_once must use the new receipt boundary instead of the held legacy
    # projection path.
    fake.eval = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(close_ms)
    )
    captured: dict[str, object] = {}

    def publish(
        redis_client,
        snapshot_payload,
        *,
        archive_ttl_seconds,
        latest_ttl_seconds,
        producer_code_sha256,
        producer_config_sha256,
    ):
        snapshot = json.loads(snapshot_payload)
        captured.update(
            {
                "redis_client": redis_client,
                "snapshot": snapshot,
                "archive_ttl_seconds": archive_ttl_seconds,
                "latest_ttl_seconds": latest_ttl_seconds,
                "producer_code_sha256": producer_code_sha256,
                "producer_config_sha256": producer_config_sha256,
            }
        )
        return SimpleNamespace(
            receipt_key=(
                "v2:features:publication_receipt:"
                f"{snapshot['feature_snapshot_id']}"
            ),
            latest_receipt_pointer_key=(
                "v2:features:publication_receipt:latest:BTCUSDT:1m"
            ),
        )

    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)
    monkeypatch.setattr(mod, "publish_and_verify_feature_snapshot", publish)

    heartbeat = mod.run_once(
        ("BTCUSDT",),
        "1m",
        write_trainer_snapshot=False,
    )

    snapshot = captured["snapshot"]
    assert isinstance(snapshot, dict)
    assert captured["redis_client"] is fake
    assert captured["archive_ttl_seconds"] == mod.FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS
    assert captured["latest_ttl_seconds"] == mod.FEATURE_LATEST_TTL_SECONDS
    assert re.fullmatch(r"[0-9a-f]{64}", str(captured["producer_code_sha256"]))
    assert re.fullmatch(r"[0-9a-f]{64}", str(captured["producer_config_sha256"]))
    assert snapshot["trainer_consumable"] is False
    assert snapshot["valid_for_prediction"] is False
    assert snapshot["valid_for_paper"] is False
    assert heartbeat["postcommit_publication_receipt_count"] == 1
    assert heartbeat["postcommit_publication_receipt_failure_count"] == 0
    assert heartbeat["postcommit_publication_source_scope_complete_count"] == 0
    assert heartbeat["trainer_consumable_count"] == 0
    assert heartbeat["trainer_release_ready"] is False


def test_receipt_failure_preserves_held_latest_projection_without_archive_overwrite(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    receipt_module = importlib.import_module(
        "v2.backend.app.services.native_trainer.runtime_feature_publication_receipt"
    )
    fake = FakeRedis()
    fake.eval = lambda *_args, **_kwargs: None  # type: ignore[attr-defined]
    close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(close_ms)
    )

    def fail_publication(*_args, **_kwargs):
        raise receipt_module.FeaturePublicationReceiptIntegrityError(
            "simulated_receipt_failure"
        )

    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)
    monkeypatch.setattr(
        mod,
        "publish_and_verify_feature_snapshot",
        fail_publication,
    )

    heartbeat = mod.run_once(
        ("BTCUSDT",),
        "1m",
        write_trainer_snapshot=False,
    )

    latest = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    archive_key = mod._feature_snapshot_archive_key(latest["feature_snapshot_id"])
    assert latest["trainer_consumable"] is False
    assert latest["valid_for_prediction"] is False
    assert latest["valid_for_paper"] is False
    assert archive_key not in fake.store
    assert heartbeat["postcommit_publication_receipt_count"] == 0
    assert heartbeat["postcommit_publication_receipt_failure_count"] == 1
    assert heartbeat["postcommit_publication_receipt_failure_reasons"] == [
        "FeaturePublicationReceiptIntegrityError"
    ]
    assert heartbeat["trainer_consumable_count"] == 0
    assert heartbeat["trainer_release_ready"] is False


def test_feature_snapshot_does_not_promote_clock_aliases_to_exact(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        [
            {
                "open_time": close_ms - 60_000 + 1,
                "close_time": close_ms,
                "source_event_time_est": close_ms + 100,
                "source_received_time_est": close_ms + 200,
                "source_available_time": close_ms + 200,
                "source": "binance_wss",
                "is_backfilled": False,
                "symbol": "BTCUSDT",
                "exchange": "binance",
                "timeframe": "1m",
                "feature_eligible": True,
                "source_sequence_id": str(close_ms + 100),
                "raw_payload_hash": "a" * 64,
                "open": "99.0",
                "high": "101.0",
                "low": "98.0",
                "close": "100.0",
                "volume": "1000",
                "is_closed": True,
            }
        ]
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert payload["event_time"] is None
    assert payload["ingested_at"] is None
    assert payload["source_available_at"] is None
    selection = payload["ohlcv_consumer_selection"]
    assert selection["exact_source_schema_validated"] is False
    assert selection["entire_contiguous_suffix_bound"] is False
    assert selection["selection_rejection_reasons"] == [
        "ohlcv_closed_row_field_set_invalid"
    ]


def test_run_timeframes_aggregates_active_consumer_hold_truth(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    per_timeframe = iter(
        [
            {
                "started_at": "2026-07-18T02:00:00.000Z",
                "timeframe": "1m",
                "classification": "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD",
                "snapshots_built": 2,
                "latest_candle_temporally_valid_count": 2,
                "required_model_feature_value_contract_valid_count": 1,
                "required_model_feature_pit_coverage_valid_count": 0,
                "exact_feature_availability_valid_count": 0,
                "trainer_consumable_count": 0,
                "prediction_eligible_count": 0,
                "paper_eligible_count": 0,
                "publication_receipt_held_count": 2,
                "missing_symbols": [],
                "v2_features_keys_written": ["v2:features:latest:BTCUSDT:1m"],
            },
            {
                "started_at": "2026-07-18T02:00:01.000Z",
                "timeframe": "5m",
                "classification": "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD",
                "snapshots_built": 1,
                "latest_candle_temporally_valid_count": 1,
                "required_model_feature_value_contract_valid_count": 1,
                "required_model_feature_pit_coverage_valid_count": 0,
                "exact_feature_availability_valid_count": 0,
                "trainer_consumable_count": 0,
                "prediction_eligible_count": 0,
                "paper_eligible_count": 0,
                "publication_receipt_held_count": 1,
                "missing_symbols": ["ETHUSDT"],
                "v2_features_keys_written": ["v2:features:latest:BTCUSDT:5m"],
            },
        ]
    )
    monkeypatch.setattr(
        mod,
        "run_once",
        lambda symbols, timeframe, write_trainer_snapshot: next(per_timeframe),
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: None)

    aggregate = mod.run_timeframes(("BTCUSDT", "ETHUSDT"), ("1m", "5m"))

    assert aggregate["classification"] == (
        "NATIVE_V2_SNAPSHOTS_BUILT_CONSUMERS_HELD"
    )
    assert aggregate["snapshots_built"] == 3
    assert aggregate["latest_candle_temporally_valid_count"] == 3
    assert aggregate["required_model_feature_value_contract_valid_count"] == 2
    assert aggregate["required_model_feature_pit_coverage_valid_count"] == 0
    assert aggregate["exact_feature_availability_valid_count"] == 0
    assert aggregate["trainer_consumable_count"] == 0
    assert aggregate["publication_receipt_held_count"] == 3
    assert aggregate["active_consumer_readiness"] == "HELD"
    assert aggregate["trainer_release_ready"] is False


@pytest.mark.parametrize(
    ("clock_overrides", "expected_reason"),
    [
        (
            {"candle_open_time": 1_800_000_059_999},
            "CANDLE_OPEN_NOT_BEFORE_CLOSE",
        ),
        (
            {
                "event_time": 1_800_000_060_299,
                "ingested_at": 1_800_000_060_199,
                "available_at": 1_800_000_060_299,
            },
            "CANDLE_CLOSE_EVENT_INGEST_ORDER_INVALID",
        ),
        (
            {"available_at": 1_800_000_060_149},
            "SOURCE_AVAILABLE_AT_NOT_CANONICAL_MAX",
        ),
        (
            {
                "event_time": 1_800_000_061_399,
                "ingested_at": 1_800_000_061_499,
                "available_at": 1_800_000_061_499,
            },
            "SOURCE_AVAILABLE_AT_AFTER_FEATURE_GENERATED_AT",
        ),
    ],
)
def test_exact_candle_temporal_lineage_rejects_noncanonical_clocks(
    clock_overrides,
    expected_reason,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    row = {
        "candle_open_time": 1_800_000_000_000,
        "candle_close_time": 1_800_000_059_999,
        **_exact_candle_clocks(1_800_000_059_999),
    }
    row.update(clock_overrides)
    row["source_sequence_id"] = str(row["event_time"])

    lineage, reasons = mod._exact_candle_temporal_lineage(  # noqa: SLF001
        row,
        feature_generated_ms=1_800_000_060_999,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )

    assert lineage["exact_source_clock_valid"] is False
    assert expected_reason in reasons


@pytest.mark.parametrize(
    ("field", "value", "expected_reason"),
    [
        ("symbol", "ETHUSDT", "CANDLE_SYMBOL_BINDING_MISMATCH"),
        ("exchange", "bybit", "CANDLE_EXCHANGE_BINDING_MISMATCH"),
        ("timeframe", "5m", "CANDLE_TIMEFRAME_BINDING_MISMATCH"),
        ("source", "binance_rest", "LIVE_CANDLE_SOURCE_NOT_EXACT_BINANCE_WSS"),
        ("is_backfilled", True, "LIVE_CANDLE_BACKFILL_NOT_EXACT_OBSERVATION"),
        ("is_closed", False, "EXACT_CANDLE_FINALITY_FLAG_INVALID"),
        (
            "feature_eligible",
            False,
            "EXACT_CANDLE_FEATURE_ELIGIBILITY_INVALID",
        ),
        ("raw_payload_hash", "bad", "EXACT_CANDLE_RAW_PAYLOAD_HASH_INVALID"),
        (
            "source_sequence_id",
            "missing-wss-event-sequence",
            "EXACT_CANDLE_EVENT_SEQUENCE_BINDING_INVALID",
        ),
    ],
)
def test_exact_candle_temporal_lineage_binds_canonical_source_identity(
    field,
    value,
    expected_reason,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    close_ms = 1_800_000_059_999
    row = {
        "candle_open_time": 1_800_000_000_000,
        "candle_close_time": close_ms,
        **_exact_candle_clocks(close_ms),
    }
    row[field] = value

    lineage, reasons = mod._exact_candle_temporal_lineage(  # noqa: SLF001
        row,
        feature_generated_ms=close_ms + 1_000,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )

    assert lineage["exact_source_clock_valid"] is False
    assert expected_reason in reasons


def test_exact_candle_temporal_lineage_rejects_misaligned_interval() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    close_ms = 1_800_000_059_999
    row = {
        "candle_open_time": 1_800_000_000_001,
        "candle_close_time": close_ms,
        **_exact_candle_clocks(close_ms),
    }

    lineage, reasons = mod._exact_candle_temporal_lineage(  # noqa: SLF001
        row,
        feature_generated_ms=close_ms + 1_000,
        expected_symbol="BTCUSDT",
        expected_timeframe="1m",
    )

    assert lineage["exact_source_clock_valid"] is False
    assert "CANDLE_INTERVAL_OR_ALIGNMENT_INVALID" in reasons


def test_legacy_rl_core_and_authoritative_trainer_abi_are_not_conflated() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    observation = importlib.import_module(
        "v2.backend.app.services.rl_core.observation_builder"
    )
    ledger = importlib.import_module(
        "v2.backend.app.services.native_trainer.durable_feature_snapshot_ledger"
    )
    tensor_builder = importlib.import_module(
        "v2.backend.app.services.native_trainer.hybrid_cuda_trainer.tensor_builder"
    )

    assert (
        observation.OBSERVATION_FEATURE_ORDER[:23]
        == mod.LEGACY_RL_OBSERVATION_CORE_FIELDS
    )
    ordered_names = tuple(name for name, _source in tensor_builder.FEATURE_SPEC)
    requirement_classes = ledger.feature_requirement_classes_for_names(
        ordered_names
    )
    assert mod.TRAINER_REQUIRED_FEATURE_FIELDS == tuple(
        name
        for name, requirement in zip(
            ordered_names,
            requirement_classes,
            strict=True,
        )
        if requirement == "REQUIRED"
    )
    assert mod.TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS == tuple(
        name
        for name, requirement in zip(
            ordered_names,
            requirement_classes,
            strict=True,
        )
        if requirement == "OPTIONAL_EVENT_DEPENDENT"
    )
    assert len(ordered_names) == 446
    assert len(mod.TRAINER_REQUIRED_FEATURE_FIELDS) == 383
    assert len(mod.TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS) == 63
    assert "gap_pct" not in ordered_names
    assert "last_liq_bps_24h" in (
        mod.TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS
    )
    assert "paper_position_present" in (
        mod.TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS
    )


@pytest.mark.parametrize(
    "value",
    [
        True,
        1_800_000_000_000.0,
        float("nan"),
        float("inf"),
        "2027-01-15T08:00:00",
        10**100,
    ],
)
def test_exact_epoch_ms_rejects_noncanonical_or_unrepresentable_values(
    value,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")

    assert mod._exact_epoch_ms(value) is None  # noqa: SLF001


def test_bad_exact_clock_fails_one_symbol_closed_without_stopping_cycle(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.store[f"v2:market:prices:{symbol}"] = json.dumps(_market_payload())
    bad_rows = _canonical_closed_window(close_ms, symbol="BTCUSDT")
    bad_rows[-1]["candle_open_time"] = 10**100
    fake.store[
        "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    ] = json.dumps(bad_rows)
    fake.store[
        "v2:market:ohlcv_closed:binance:ETHUSDT:1m"
    ] = json.dumps(_canonical_closed_window(close_ms, symbol="ETHUSDT"))
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT", "ETHUSDT"), "1m", write_trainer_snapshot=False)

    btc = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    eth = json.loads(fake.store["v2:features:latest:ETHUSDT:1m"])
    assert btc["trainer_consumable"] is False
    assert btc["ohlcv_consumer_selection"]["exact_source_schema_validated"] is False
    assert btc["ohlcv_consumer_selection"]["selection_rejection_reasons"]
    assert eth["trainer_consumable"] is False
    assert eth["exact_source_clock_valid"] is True
    assert eth["exact_source_clock_rejection_reasons"] == []
    assert eth["ohlcv_consumer_selection"]["entire_contiguous_suffix_bound"] is True


@pytest.mark.parametrize("bad_close", [float("inf"), float("-inf"), 10**100])
def test_bad_close_clock_fails_one_symbol_closed_without_stopping_cycle(
    monkeypatch,
    bad_close,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.store[f"v2:market:prices:{symbol}"] = json.dumps(_market_payload())
    bad_rows = _canonical_closed_window(close_ms, symbol="BTCUSDT")
    bad_rows[-1]["candle_close_time"] = bad_close
    fake.store[
        "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    ] = json.dumps(bad_rows)
    fake.store[
        "v2:market:ohlcv_closed:binance:ETHUSDT:1m"
    ] = json.dumps(_canonical_closed_window(close_ms, symbol="ETHUSDT"))
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT", "ETHUSDT"), "1m", write_trainer_snapshot=False)

    btc = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    eth = json.loads(fake.store["v2:features:latest:ETHUSDT:1m"])
    assert btc["trainer_consumable"] is False
    assert btc["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert btc["ohlcv_consumer_selection"]["selection_rejection_reasons"]
    assert eth["exact_source_clock_valid"] is True
    assert eth["latest_candle_temporally_valid"] is True


def test_run_once_uses_selector_observation_clock_per_symbol(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.store[f"v2:market:prices:{symbol}"] = json.dumps(_market_payload())
    cutoffs = iter((_TEST_NOW_MS + 1_000, _TEST_NOW_MS + 2_000))
    observed: list[str] = []

    def capture_read(
        _redis,
        symbol,
        _timeframe="1m",
    ):
        observed.append(symbol)
        cutoff = next(cutoffs)
        return None, {
            "selection_mode": "TEST_NO_KLINES",
            "selected_source_keys": [],
            "raw_key_row_count": 0,
            "closed_key_row_count": 0,
            "selected_row_count": 0,
            "consumer_observation_cutoff_ms": cutoff,
        }

    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)
    monkeypatch.setattr(mod, "_read_klines_with_lineage", capture_read)

    mod.run_once(("BTCUSDT", "ETHUSDT"), "1m", write_trainer_snapshot=False)

    assert observed == ["BTCUSDT", "ETHUSDT"]


def test_feature_snapshot_fails_closed_when_generation_crosses_candle_boundary(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    boundary_ms = 1_800_000_060_000
    observation_ms = boundary_ms - 100
    generated_ms = boundary_ms + 100
    selected_close_ms = boundary_ms - 60_001
    monkeypatch.setattr(mod.time, "time", lambda: observation_ms / 1000.0)
    monkeypatch.setattr(mod, "_utc_iso", lambda: mod._ms_to_utc_iso(generated_ms))
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(selected_close_ms)
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["source_observation_time"] == mod._ms_to_utc_iso(observation_ms)
    assert payload["expected_latest_finalized_candle_close_time"] == mod._ms_to_utc_iso(
        boundary_ms - 1
    )
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(selected_close_ms)
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["ohlcv_consumer_selection"]["entire_contiguous_suffix_bound"] is True
    assert payload["temporal_rejection_reasons"] == [
        "FINALIZED_CANDLE_NOT_AVAILABLE_AT_DECISION"
    ]


def test_feature_snapshot_emits_closed_window_atr_percentile(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    latest_close_ms = _latest_finalized_close_ms(mod, "1m")
    rows = []
    for index in range(80):
        close_ms = latest_close_ms - (79 - index) * 60_000
        close = 100.0 + index * 0.2
        width = 0.8 + (index % 9) * 0.08
        rows.append(
            _canonical_closed_row(
                close_ms,
                open_price=close - 0.1,
                high_price=close + width,
                low_price=close - width * 0.7,
                close_price=close,
                volume=1000 + index,
            )
        )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(rows)
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert payload["trainer_consumable"] is False
    assert payload["latest_candle_temporally_valid"] is True
    assert payload["latest_unclosed_kline_excluded"] is False
    assert features["atr_percentile"] is not None
    assert 0.0 <= features["atr_percentile"] <= 1.0
    assert "atr_percentile" not in payload["missing_feature_flags"]


def test_feature_snapshot_skips_closed_candle_available_after_decision(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    now_ms = _TEST_NOW_MS
    newer_close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    rows = _canonical_closed_window(newer_close_ms)
    rows[-1] = _canonical_closed_row(
        newer_close_ms,
        open_price=100.0,
        high_price=102.0,
        low_price=99.0,
        close_price=101.0,
        volume=1200.0,
        ingestion_lag_ms=(now_ms + 60_000) - newer_close_ms,
    )
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(rows)
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert payload["feature_cutoff"] is None
    assert payload["ohlcv_consumer_selection"]["selection_rejection_reasons"] == [
        "feature_window_available_after_consumer_observation"
    ]
    assert payload["latest_unclosed_kline_excluded"] is False
    assert payload["future_available_finalized_kline_excluded_count"] == 0


def test_feature_snapshot_rejects_raw_ohlcv_without_exact_source_clocks(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    open_ms = close_ms - 60_000 + 1
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv:binance:BTCUSDT:1m"] = json.dumps(
        [[open_ms, "99.0", "101.0", "98.0", "100.0", "1000", close_ms, "100000", 20, "500", "50000", "0"]]
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert payload["feature_cutoff"] is None
    assert payload["feature_cutoff_est"] is None
    assert payload["exact_source_clock_valid"] is False
    assert payload["exact_source_clock_rejection_reasons"] == [
        "EXACT_CANDLE_CLOCK_PAYLOAD_REQUIRED"
    ]
    assert payload["ohlcv_consumer_selection"]["legacy_raw_key_considered"] is False
    assert payload["ohlcv_consumer_selection"]["selection_rejection_reasons"] == [
        "ATOMIC_OHLCV_CLOSED_SOURCE_KEY_MISSING"
    ]


def test_feature_snapshot_carries_point_in_time_cost_evidence_from_orderbook(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:orderbook:BTCUSDT"] = json.dumps(
        {
            "bids": [["99.95", "10"]],
            "asks": [["100.05", "10"]],
        }
    )
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(close_ms)
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert payload["trainer_consumable"] is False
    assert payload["latest_candle_temporally_valid"] is True
    assert features["fee_bps"] == mod._configured_fee_bps()  # noqa: SLF001
    assert abs(features["expected_slippage_bps"] - 5.0) < 1e-9
    assert "fee_bps" not in payload["missing_feature_flags"]
    assert "expected_slippage_bps" not in payload["missing_feature_flags"]
    assert payload["market_cost_evidence_source_fields"] == {
        "fee_bps": mod.CONFIGURED_FEE_BPS_SOURCE,
        "expected_slippage_bps": "MODELED_FROM_OBSERVED_SPREAD_VOLATILITY_LIQUIDITY(bid_ask_spread_bps)",
    }


def test_every_feature_built_from_selected_market_inputs_is_reserved() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")

    canonical_features = mod._features_from_market(_market_payload())  # noqa: SLF001

    assert set(canonical_features) <= set(mod.CANONICAL_MARKET_INPUT_FIELDS)
    assert set(canonical_features) <= set(mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS)


def test_external_enrichment_cannot_manufacture_reserved_feature_or_cost_evidence(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    injected = {
        field: float(index + 1)
        for index, field in enumerate(sorted(mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS))
    }
    injected["optional_external_signal"] = 0.73
    monkeypatch.setattr(
        mod,
        "_read_hash_key",
        lambda _redis, key: (
            injected
            if key == "v2:unified_features:BTCUSDT:1m"
            else None
        ),
    )
    features = {
        field: None for field in mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS
    }

    result = mod._merge_external_v2_features(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
        features,
        selected_closed_klines=[],
        ohlcv_selection_lineage={},
    )

    assert all(
        features[field] is None
        for field in mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS
    )
    assert features["optional_external_signal"] == 0.73
    assert "v2:unified_features" in result["sources_present"]


def test_live_ta_full_is_not_read_or_merged() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    ta_key = "v2:features:ta_full:BTCUSDT:1m"
    fake.store[ta_key] = json.dumps(
        {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "generated_utc": "2099-01-01T00:00:00Z",
            "source_label": "V2_FULL_TALIB_TA_LIVE",
            "indicators": {
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 99.0,
                "open_interest": 987654.0,
                "optional_external_signal": 0.73,
            },
        }
    )
    features = {
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "volume": None,
        "open_interest": None,
    }

    result = mod._merge_external_v2_features(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
        features,
        selected_closed_klines=[],
        ohlcv_selection_lineage={},
    )

    assert ta_key not in fake.get_calls
    assert all(value is None for value in features.values())
    assert "optional_external_signal" not in features
    assert "v2:features:ta_full" not in result["sources_present"]
    assert result["fields_merged"] == 0


def test_unified_enrichment_cannot_backfill_missing_canonical_open_interest(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    monkeypatch.setattr(
        mod,
        "_read_hash_key",
        lambda _redis, key: (
            {"open_interest": 987654.0}
            if key == "v2:unified_features:BTCUSDT:1m"
            else None
        ),
    )
    features = {"open_interest": None}

    result = mod._merge_external_v2_features(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
        features,
        selected_closed_klines=[],
        ohlcv_selection_lineage={},
    )

    assert "open_interest" in mod.CANONICAL_MARKET_INPUT_FIELDS
    assert features["open_interest"] is None
    assert result["fields_merged"] == 0
    assert "v2:unified_features" in result["sources_present"]


def test_snapshot_quarantines_missing_canonical_open_interest_despite_enrichment(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    provider_features = importlib.import_module(
        "v2.backend.app.services.provider_features"
    )
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(close_ms)
    )
    ta_key = "v2:features:ta_full:BTCUSDT:1m"
    fake.store[ta_key] = json.dumps(
        {
            "symbol": "ETHUSDT",
            "timeframe": "1h",
            "generated_utc": "2099-01-01T00:00:00Z",
            "source_label": "V2_FULL_TALIB_TA_LIVE",
            "indicators": {
                "open": 1.0,
                "mark_price": 2.0,
                "volume": 3.0,
                "open_interest": 987654.0,
            },
        }
    )
    original_read_hash = mod._read_hash_key  # noqa: SLF001

    def read_hash(redis_client, key):
        if key == "v2:unified_features:BTCUSDT:1m":
            return {
                "open": "4.0",
                "mark_price": "5.0",
                "volume": "6.0",
                "open_interest": "765432.0",
                "optional_external_signal": "0.5",
            }
        return original_read_hash(redis_client, key)

    monkeypatch.setattr(mod, "_read_hash_key", read_hash)
    monkeypatch.setattr(
        provider_features,
        "build_provider_consumer_context",
        lambda *_args, **_kwargs: {
            "provider_features": {
                "open": 7.0,
                "mark_price": 8.0,
                "volume": 9.0,
                "open_interest": 654321.0,
                "optional_provider_signal": 0.75,
            }
        },
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["features"]["open"] == 99.0
    assert payload["features"]["mark_price"] == 100.0
    assert payload["features"]["volume"] == 1000.0
    assert payload["features"]["open_interest"] is None
    assert payload["features"]["optional_external_signal"] == 0.5
    assert "optional_provider_signal" not in payload["features"]
    assert payload["provider_features"]["open_interest"] == 654321.0
    assert "v2:features:ta_full" not in payload["external_v2_sources_present"]
    assert "v2:unified_features" in payload["external_v2_sources_present"]
    assert "open_interest" in payload["missing_feature_flags"]
    assert "open_interest" in payload["required_model_feature_missing_fields"]
    assert payload["required_model_feature_value_contract_valid"] is False
    assert payload["required_model_feature_pit_coverage_valid"] is False
    assert payload["exact_feature_availability_valid"] is False
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False


def test_explicit_orderbook_imbalance_must_be_inside_unit_interval() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    market = _market_payload()
    market["_orderbook"] = {"depth_imbalance": "1.0001"}

    features = mod._features_from_market(market)  # noqa: SLF001

    assert features["depth_imbalance"] is None
    assert features["toxicity_proxy"] is None


def test_snapshot_core_book_and_cost_evidence_uses_only_selected_orderbook(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    market = _market_payload()
    market["funding"] = {}
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(market)
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(close_ms)
    )
    # This is the one payload selected by _read_orderbook for required/core
    # evidence.  Explicit recorder imbalance is valid without book arrays.
    fake.store["v2:market:orderbook:BTCUSDT"] = json.dumps(
        {
            "best_bid": "99.0",
            "best_ask": "101.0",
            "best_bid_size": "8.0",
            "best_ask_size": "2.0",
            "depth_imbalance": "0.6",
            "actual_observed_spread_entry_bps": "12.5",
            "bid_depth_usd": "800.0",
            "ask_depth_usd": "202.0",
            "orderbook_depth_usd": "202.0",
            "fee_bps": "3.1",
            "expected_slippage_bps": "4.2",
        }
    )
    # Optional enrichment reads this key first, but it is not authoritative for
    # reserved feature/cost fields and deliberately disagrees with every one.
    fake.store["v2:orderbook:features:binance:BTCUSDT"] = json.dumps(
        {
            "best_bid": "1.0",
            "best_ask": "2.0",
            "depth_imbalance": "-0.9",
            "bid_depth_usd": "9.0",
            "ask_depth_usd": "8.0",
            "orderbook_depth_usd": "7.0",
            "spread_bps": "999.0",
            "depth_slope": "0.33",
        }
    )
    fake.store["v2:features:ta_full:BTCUSDT:1m"] = json.dumps(
        {
            "indicators": {
                "ret_pct": "0.99",
                "funding_rate": "0.5",
                "expected_funding_bps": "5000.0",
                "paper_position_present": "1",
                "fee_bps": "91.0",
                "expected_slippage_bps": "92.0",
                "actual_observed_spread_entry_bps": "93.0",
                "toxicity_proxy": "0.95",
            }
        }
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert features["depth_imbalance"] == 0.6
    assert features["toxicity_proxy"] == 0.6
    assert features["micro_price"] == pytest.approx(100.6)
    assert features["bid_ask_spread_bps"] == 12.5
    assert features["actual_observed_spread_entry_bps"] == 12.5
    assert features["bid_depth_usd"] == 800.0
    assert features["ask_depth_usd"] == 202.0
    assert features["orderbook_depth_usd"] == 202.0
    assert features["fee_bps"] == 3.1
    assert features["expected_slippage_bps"] == 4.2
    assert features["expected_funding_bps"] is None
    assert features["funding_rate"] is None
    assert features["ret_pct"] == 0.0
    assert features["paper_position_present"] is None
    assert features["depth_slope"] == 0.33
    assert payload["market_cost_evidence_source_fields"] == {
        "fee_bps": "orderbook.fee_bps",
        "expected_slippage_bps": "orderbook.expected_slippage_bps",
    }
    assert payload["market_cost_evidence_missing_fields"] == [
        "expected_funding_bps"
    ]


def test_feature_snapshot_merges_realtime_ingestors_for_trainer(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    market = _market_payload()
    market["open_interest"] = {"openInterest": "123.45"}
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(market)
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(
            close_ms,
            latest_values={
                "volume": 100.0,
                "quote_volume": 10_000.0,
                "num_trades": 40,
                "taker_buy_base_vol": 60.0,
                "taker_buy_quote_vol": 6_000.0,
            },
        )
    )
    fake.store["v2:orderbook:features:binance:BTCUSDT"] = json.dumps(
        {
            "best_bid": "99.9",
            "best_ask": "100.1",
            "mid": "100.0",
            "best_bid_size": "5",
            "best_ask_size": "6",
            "spread_bps": "1.2",
            "depth_total_usd": "100000",
            "depth_5_bid_usd": "52000",
            "depth_5_ask_usd": "48000",
            "depth_20_bid_usd": "51000",
            "depth_20_ask_usd": "49000",
            "depth_imbalance": "0.02",
            "depth_slope": "0.12",
            "estimated_price_impact_bps": "0.9",
            "sequence_gap_flag": "0",
            "source_latency_ms": "11",
        }
    )
    fake.store["v2:microstructure:trust_score:BTCUSDT:1m"] = json.dumps(
        {
            "microstructure_trust_score": "0.73",
            "feed_latency_ms": "12",
            "spread_instability": "0.1",
            "depth_persistence": "0.82",
            "cancel_pressure": "0.2",
            "book_trade_divergence": "0.03",
            "cross_venue_confirmation": "0.91",
            "sweep_risk": "0.14",
            "post_sweep_reversal_probability": "0.23",
            "realized_slippage_error": "-0.4",
        }
    )
    fake.store["v2:microstructure:trade_tape_confirmation:BTCUSDT"] = json.dumps(
        {
            "book_trade_divergence_score": "0.04",
            "trade_imbalance": "0.12",
        }
    )
    fake.store["v2:altdata:public_intel:symbol:BTCUSDT"] = json.dumps(
        {
            "public_intel_score": "0.61",
            "defillama_liquidity_score": "0.71",
            "fear_greed_score": "0.52",
            "btc_mempool_pressure_score": "0.33",
        }
    )
    fake.store["v2:altdata:whale_walls:symbol:BTCUSDT"] = json.dumps(
        {
            "whale_wall_score": "0.7",
            "whale_bid_pressure_score": "0.65",
            "whale_ask_pressure_score": "0.35",
        }
    )
    fake.store["v2:altdata:symbol_score:BTCUSDT"] = json.dumps(
        {
            "surf_market_price_signal_score": "0.55",
            "coinglass_derivatives_score": "0.66",
            "coingecko_discovery_score": "0.44",
            "provider_availability_score": "0.9",
        }
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    features = payload["features"]
    assert payload["trainer_consumable"] is False
    assert payload["latest_candle_temporally_valid"] is True
    assert features["open_interest"] == 123.45
    assert features["taker_sell_base_vol"] == 40.0
    assert features["taker_sell_quote_vol"] == 4000.0
    assert features["taker_buy_ratio"] == 0.6
    assert features["ob_best_bid"] == 99.9
    assert features["ob_best_ask"] == 100.1
    assert features["best_bid_size"] == 5.0
    assert features["spread_bps"] == 1.2
    assert features["microprice"] == 100.0
    assert features["bid_depth_usd"] == 52000.0
    assert features["ask_depth_usd"] == 48000.0
    assert features["depth_imbalance"] == 0.02
    assert features["toxicity_proxy"] == 0.02
    assert abs(features["expected_slippage_bps"] - 0.6) < 1e-9
    assert features["microstructure_trust_score"] == 0.73
    assert features["feed_latency_ms"] == 12.0
    assert features["realized_slippage_error"] == -0.4
    assert features["depth_vs_tape_divergence"] == 0.04
    assert features["tape_imbalance"] == 0.12
    assert features["order_flow_imbalance"] == 0.12
    assert features["public_intel_score"] == 0.61
    assert features["whale_wall_score"] == 0.7
    assert features["surf_score"] == 0.55
    assert features["coinglass_derivatives_score"] == 0.66
    assert {
        "v2:orderbook:features",
        "v2:microstructure:trust_score",
        "v2:microstructure:trade_tape_confirmation",
        "v2:altdata:public_intel",
        "v2:altdata:whale_walls",
        "v2:altdata:symbol_score",
    }.issubset(set(payload["external_v2_sources_present"]))
    assert "open_interest" not in payload["missing_feature_flags"]
    assert "bid_depth_usd" not in payload["missing_feature_flags"]
    assert "ask_depth_usd" not in payload["missing_feature_flags"]
    assert "depth_imbalance" not in payload["missing_feature_flags"]
    assert "toxicity_proxy" not in payload["missing_feature_flags"]
    assert "public_intel_score" not in payload["missing_feature_flags"]
    assert "microstructure_trust_score" not in payload["missing_feature_flags"]


def test_feature_snapshot_does_not_use_future_raw_ohlcv(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m") + 60_000
    open_ms = close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv:binance:BTCUSDT:1m"] = json.dumps(
        [[open_ms, "99.0", "101.0", "98.0", "100.0", "1000", close_ms, "100000", 20, "500", "50000", "0"]]
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"


def test_feature_snapshot_with_stale_closed_ohlcv_is_not_consumable(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    stale_close_ms = _latest_finalized_close_ms(mod, "1m") - (100 * 60_000)
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(stale_close_ms)
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert payload["candle_closed_confirmed"] is False
    assert payload["feature_cutoff"] is None
    assert payload["feature_cutoff_est"] is None
    assert payload["stale_feature_flags"] == []
    assert payload["ohlcv_consumer_selection"]["selection_rejection_reasons"] == [
        "feature_window_tail_is_stale"
    ]


def test_finalized_raw_ohlcv_bridge_writes_closed_rows_and_skips_future() -> None:
    bridge = importlib.import_module("v2.backend.app.cli.v2_closed_candle_resampler")
    fake = FakeRedis()
    now_ms = 1_781_000_000_000
    closed_open = now_ms - 4 * 60 * 60 * 1000
    closed_close = now_ms - 1_000
    future_open = now_ms
    future_close = now_ms + 4 * 60 * 60 * 1000 - 1
    fake.store["v2:market:ohlcv:binance:BTCUSDT:4h"] = json.dumps(
        [
            [closed_open, "100", "102", "99", "101", "12", closed_close, "1200", 10, "6", "600", "0"],
            [future_open, "101", "103", "100", "102", "8", future_close, "816", 8, "4", "408", "0"],
        ]
    )

    result = bridge.copy_finalized_raw_ohlcv(
        fake,
        symbol="BTCUSDT",
        timeframe="4h",
        now_ms_value=now_ms,
    )

    rows = json.loads(fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:4h"])
    assert result["rows_after"] == 1
    assert result["skipped_future_or_open_rows"] == 1
    assert rows[0]["candle_closed_confirmed"] is True
    assert rows[0]["candle_close_time"] == closed_close
    assert rows[0]["close"] == 101.0


def test_feature_snapshot_accepts_only_selection_bound_rest_backfill_provenance(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "4h")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:4h"] = json.dumps(
        _canonical_closed_window(
            close_ms,
            timeframe="4h",
            source="binance_rest",
        )
    )
    unbound_latest = json.loads(
        fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:4h"]
    )[-1]
    _lineage, unbound_reasons = mod._exact_candle_temporal_lineage(  # noqa: SLF001
        unbound_latest,
        feature_generated_ms=_TEST_NOW_MS,
        expected_symbol="BTCUSDT",
        expected_timeframe="4h",
    )
    assert unbound_reasons == [
        "LIVE_CANDLE_SOURCE_NOT_EXACT_BINANCE_WSS",
        "LIVE_CANDLE_BACKFILL_NOT_EXACT_OBSERVATION",
    ]
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "4h", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:4h"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "FEATURE_AVAILABILITY_UNVERIFIED"
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(close_ms)  # noqa: SLF001
    assert payload["source"] == "binance_rest"
    assert payload["is_backfilled"] is True
    assert payload["ohlcv_consumer_selection"][
        "selected_source_provenance_counts"
    ] == {"binance_rest": 80}
    assert payload["ohlcv_consumer_selection"]["selected_backfilled_row_count"] == 80
    assert payload["exact_source_clock_valid"] is True
    assert payload["exact_source_clock_rejection_reasons"] == []
    assert payload["temporal_rejection_reasons"] == []


@pytest.mark.parametrize("timeframe", REQUIRED_DECISION_TIMEFRAMES)
def test_atomic_canonical_selection_binds_full_window_for_every_required_timeframe(
    timeframe: str,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_TEST_NOW_MS,
        timeframe=timeframe,
    )
    source_rows = _canonical_closed_window(
        latest_close_ms,
        timeframe=timeframe,
    )
    source_key = f"v2:market:ohlcv_closed:binance:BTCUSDT:{timeframe}"
    exact_payload = json.dumps(source_rows).encode("utf-8")
    fake.store[source_key] = exact_payload

    rows, lineage = fp._read_klines_with_lineage(  # noqa: SLF001
        fake,
        "BTCUSDT",
        timeframe,
    )

    assert rows is not None
    assert len(rows) == len(source_rows) == 80
    assert fake.pipeline_transactions == [True]
    assert lineage["selected_source_keys"] == [source_key]
    assert lineage["legacy_raw_key_considered"] is False
    assert lineage["exact_payload_sha256"] == hashlib.sha256(exact_payload).hexdigest()
    assert re.fullmatch(r"[0-9a-f]{64}", lineage["atomic_batch_material_sha256"])
    assert lineage["atomic_batch_material_json"] is None
    assert lineage["selected_candle_ids"] is None
    assert lineage["selected_first_candle_id"] == source_rows[0]["candle_id"]
    assert lineage["selected_latest_candle_id"] == source_rows[-1]["candle_id"]
    assert re.fullmatch(r"[0-9a-f]{64}", lineage["selected_rows_material_sha256"])
    assert lineage["selected_source_start_index"] == 0
    assert lineage["selected_source_end_index_exclusive"] == 80
    assert lineage["entire_contiguous_suffix_bound"] is True
    assert lineage["selection_rejection_reasons"] == []
    assert re.fullmatch(r"[0-9a-f]{64}", lineage["binding_selection_sha256"])
    assert lineage["binding_selection_material_json"] is None
    assert re.fullmatch(r"[0-9a-f]{64}", lineage["consumer_selection_sha256"])
    assert lineage["consumer_selection_material_json"] is None
    assert lineage["selection_material_retained_in_snapshot"] is False
    assert lineage["durable_source_receipt_emitted"] is False
    assert lineage["feature_publication_receipt_emitted"] is False
    assert lineage["consumer_eligible"] is False
    assert lineage["trainer_admission_granted"] is False


def test_atomic_selection_samples_consumer_clock_only_after_redis_response(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_TEST_NOW_MS,
        timeframe="1m",
    )
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = json.dumps(_canonical_closed_window(latest_close_ms))
    response_detached = False
    original_execute = _FakeAtomicPipeline.execute

    def execute_then_detach(pipeline):
        nonlocal response_detached
        result = original_execute(pipeline)
        response_detached = True
        return result

    def post_read_clock() -> float:
        assert response_detached is True
        return _TEST_NOW_MS / 1000.0

    monkeypatch.setattr(_FakeAtomicPipeline, "execute", execute_then_detach)
    monkeypatch.setattr(fp.time, "time", post_read_clock)

    rows, lineage = fp._read_klines_with_lineage(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
    )

    assert rows is not None
    assert lineage["consumer_observation_cutoff_ms"] == _TEST_NOW_MS
    assert (
        lineage["consumer_observation_clock_source"]
        == "LOCAL_CLOCK_AFTER_ATOMIC_RESPONSE"
    )


def test_atomic_selection_lineage_stays_compact_for_large_window() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_TEST_NOW_MS,
        timeframe="1m",
    )
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    source_rows = _canonical_closed_window(latest_close_ms, count=1_000)
    fake.store[source_key] = json.dumps(source_rows)

    rows, lineage = fp._read_klines_with_lineage(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
    )

    compact_lineage = json.dumps(
        lineage,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    assert rows is not None
    assert len(rows) == 1_000
    assert len(compact_lineage) < 8_000
    assert lineage["selected_candle_ids"] is None
    assert lineage["binding_selection_material_json"] is None
    assert lineage["consumer_selection_material_json"] is None


def test_atomic_canonical_selection_excludes_every_pre_gap_row() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    duration_ms = TIMEFRAME_DURATION_MS["1m"]
    latest_close_ms = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_TEST_NOW_MS,
        timeframe="1m",
    )
    suffix = _canonical_closed_window(latest_close_ms)
    prefix_latest_close = suffix[0]["candle_close_time"] - (2 * duration_ms)
    prefix = _canonical_closed_window(prefix_latest_close, count=10)
    source_rows = prefix + suffix
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = json.dumps(source_rows)

    rows, lineage = fp._read_klines_with_lineage(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
    )

    assert rows is not None
    assert [row["candle_id"] for row in rows] == [
        row["candle_id"] for row in suffix
    ]
    assert lineage["closed_key_row_count"] == 90
    assert lineage["selected_row_count"] == 80
    assert lineage["selected_source_start_index"] == 10
    assert lineage["selected_source_end_index_exclusive"] == 90
    assert lineage["source_gap_indices"] == [10]
    assert lineage["source_gap_missing_interval_counts"] == [1]


def test_atomic_canonical_selection_binds_mixed_rest_wss_provenance() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_TEST_NOW_MS,
        timeframe="1m",
    )
    source_rows = _canonical_closed_window(latest_close_ms)
    for index in range(20):
        source_rows[index] = _canonical_closed_row(
            source_rows[index]["candle_close_time"],
            source="binance_rest",
        )
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = json.dumps(source_rows)

    rows, lineage = fp._read_klines_with_lineage(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
    )

    assert rows is not None
    assert lineage["selected_source_provenance_counts"] == {
        "binance_rest": 20,
        "binance_wss": 60,
    }
    assert lineage["selected_backfilled_row_count"] == 20
    assert [row["source"] for row in rows[:20]] == [
        "binance_rest"
    ] * 20
    assert rows[-1]["source"] == "binance_wss"


def test_atomic_canonical_selection_enforces_end_exclusive_finality(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    duration_ms = TIMEFRAME_DURATION_MS["1m"]
    latest_close_ms = 1_800_000_059_999
    source_rows = [
        _canonical_closed_row(
            latest_close_ms - ((79 - index) * duration_ms),
            event_lag_ms=1,
            ingestion_lag_ms=1,
        )
        for index in range(80)
    ]
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"

    accepted = FakeRedis()
    accepted.store[source_key] = json.dumps(source_rows)
    monkeypatch.setattr(fp.time, "time", lambda: (latest_close_ms + 1) / 1000.0)
    rows, evidence = fp._read_klines_with_lineage(  # noqa: SLF001
        accepted,
        "BTCUSDT",
        "1m",
    )
    assert rows is not None
    assert evidence["entire_contiguous_suffix_bound"] is True

    rejected = FakeRedis()
    rejected.store[source_key] = json.dumps(source_rows)
    monkeypatch.setattr(fp.time, "time", lambda: latest_close_ms / 1000.0)
    rows, evidence = fp._read_klines_with_lineage(  # noqa: SLF001
        rejected,
        "BTCUSDT",
        "1m",
    )
    assert rows is None
    assert evidence["selection_rejection_reasons"] == [
        "feature_window_candle_not_final_at_consumer_observation"
    ]


def test_exact_payload_and_selection_hashes_change_with_source_identity() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    latest_close_ms = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
        decision_ms=_TEST_NOW_MS,
        timeframe="1m",
    )
    first_rows = _canonical_closed_window(latest_close_ms)
    second_rows = _canonical_closed_window(
        latest_close_ms,
        latest_values={"close_price": 100.25},
    )
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    first_redis = FakeRedis()
    second_redis = FakeRedis()
    first_redis.store[source_key] = json.dumps(first_rows)
    second_redis.store[source_key] = json.dumps(second_rows)

    first_selected, first = fp._read_klines_with_lineage(  # noqa: SLF001
        first_redis,
        "BTCUSDT",
        "1m",
    )
    second_selected, second = fp._read_klines_with_lineage(  # noqa: SLF001
        second_redis,
        "BTCUSDT",
        "1m",
    )

    assert first_selected is not None and second_selected is not None
    assert first["exact_payload_sha256"] != second["exact_payload_sha256"]
    assert first["selected_latest_candle_id"] != second["selected_latest_candle_id"]
    assert first["binding_selection_sha256"] != second["binding_selection_sha256"]
    assert first["consumer_selection_sha256"] != second["consumer_selection_sha256"]


def test_market_structure_families_use_atomic_rows_after_source_mutation(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = _latest_finalized_close_ms(fp, "1m")
    initial_rows = _canonical_closed_window(
        latest_close_ms,
        latest_values={"close_price": 101.25, "high_price": 102.0},
    )
    replacement_rows = _canonical_closed_window(
        latest_close_ms,
        latest_values={"close_price": 9_999.0, "high_price": 10_000.0},
    )
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    initial_payload = json.dumps(initial_rows)
    fake.store[source_key] = initial_payload
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    original_execute = _FakeAtomicPipeline.execute

    def capture_then_replace(pipeline):
        result = original_execute(pipeline)
        pipeline.redis_client.store[source_key] = json.dumps(replacement_rows)
        return result

    monkeypatch.setattr(_FakeAtomicPipeline, "execute", capture_then_replace)
    captures = _capture_market_structure_family_inputs(monkeypatch, fp)
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    fp.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    assert set(captures) == {
        "liquidity_zones",
        "structure",
        "fvg",
        "vwap",
        "volume_profile",
        "cvd",
    }
    initial_ids = [row["candle_id"] for row in initial_rows]
    for capture in captures.values():
        assert [row["candle_id"] for row in capture["candles"]] == initial_ids
        assert capture["candles"][-1]["close"] == 101.25
        assert capture["price"] == 101.25
        assert capture["timeframe"] == "1m"
    assert source_key not in fake.get_calls
    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["ohlcv_consumer_selection"]["exact_payload_sha256"] == (
        hashlib.sha256(initial_payload.encode("utf-8")).hexdigest()
    )
    assert snapshot["market_structure_ohlcv_binding"]["status"] == (
        "BOUND_TO_ATOMIC_CANONICAL_SELECTION"
    )


def test_market_structure_families_receive_only_bound_post_gap_suffix(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    duration_ms = TIMEFRAME_DURATION_MS["1m"]
    latest_close_ms = _latest_finalized_close_ms(fp, "1m")
    suffix = _canonical_closed_window(latest_close_ms)
    prefix = _canonical_closed_window(
        suffix[0]["candle_close_time"] - (2 * duration_ms),
        count=10,
    )
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = json.dumps(prefix + suffix)
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    captures = _capture_market_structure_family_inputs(monkeypatch, fp)
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    fp.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    suffix_ids = [row["candle_id"] for row in suffix]
    prefix_ids = {row["candle_id"] for row in prefix}
    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["ohlcv_consumer_selection"]["selected_source_start_index"] == 10
    assert snapshot["ohlcv_consumer_selection"]["selected_row_count"] == len(suffix)
    for capture in captures.values():
        captured_ids = [row["candle_id"] for row in capture["candles"]]
        assert captured_ids == suffix_ids
        assert prefix_ids.isdisjoint(captured_ids)


def test_market_structure_binding_rejects_in_process_row_mutation() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = _latest_finalized_close_ms(fp, "1m")
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = json.dumps(_canonical_closed_window(latest_close_ms))
    selected, lineage = fp._read_klines_with_lineage(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
    )
    assert selected is not None
    mutated = [dict(row) for row in selected]
    mutated[-1]["close"] = 9_999.0

    bound, binding = fp._bound_market_structure_candles(  # noqa: SLF001
        mutated,
        lineage,
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert bound == []
    assert binding["status"] == "HELD_UNBOUND_OHLCV_SELECTION"
    assert binding["selection_rejection_reasons"] == [
        "SELECTED_ROWS_MATERIAL_MISMATCH"
    ]


def test_market_structure_never_falls_back_when_atomic_selection_is_held(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    stale_close_ms = _latest_finalized_close_ms(fp, "1m") - (100 * 60_000)
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = json.dumps(_canonical_closed_window(stale_close_ms))
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    captures = _capture_market_structure_family_inputs(monkeypatch, fp)
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    fp.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    assert source_key not in fake.get_calls
    assert set(captures) == {
        "liquidity_zones",
        "structure",
        "fvg",
        "vwap",
        "volume_profile",
        "cvd",
    }
    assert all(capture["candles"] == [] for capture in captures.values())
    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["market_structure_ohlcv_binding"]["status"] == (
        "HELD_UNBOUND_OHLCV_SELECTION"
    )
    assert snapshot["market_structure_ohlcv_binding"][
        "selection_rejection_reasons"
    ]
    for field in (
        "liquidity_zone_above",
        "liquidity_zone_below",
        "distance_to_liquidity_zone_bps",
        "liquidity_sweep_risk",
        "fvg_size_bps",
        "distance_to_fvg_bps",
        "fvg_fill_percent",
    ):
        assert snapshot["features"].get(field) is None
    assert snapshot["trainer_consumable"] is False
    assert snapshot["valid_for_prediction"] is False
    assert snapshot["valid_for_paper"] is False


def test_market_structure_publications_share_selected_tail_identity(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = _latest_finalized_close_ms(fp, "15m")
    selected_rows = _canonical_closed_window(
        latest_close_ms,
        timeframe="15m",
    )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store[
        "v2:market:ohlcv_closed:binance:BTCUSDT:15m"
    ] = json.dumps(selected_rows)
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    fp.run_once(("BTCUSDT",), "15m", write_trainer_snapshot=False)

    publication_keys = (
        "v2:market:liquidity_zones:BTCUSDT",
        "v2:market:structure:BTCUSDT:15m",
        "v2:market:fvg:BTCUSDT:15m",
        "v2:market:vwap:BTCUSDT:15m",
        "v2:market:volume_profile:BTCUSDT:15m",
        "v2:market:cvd:BTCUSDT:15m",
        "v2:market:sweep_risk:BTCUSDT:15m",
    )
    for key in publication_keys:
        publication = json.loads(fake.store[key])
        binding = publication["ohlcv_selection_binding"]
        assert publication["timeframe"] == "15m"
        assert fp._parse_time_ms(publication["event_time"]) == (  # noqa: SLF001
            selected_rows[-1]["event_time"]
        )
        assert fp._parse_time_ms(publication["available_at"]) == (  # noqa: SLF001
            selected_rows[-1]["available_at"]
        )
        assert publication["timestamp_lineage"]["input_rows"] == len(selected_rows)
        assert publication["timestamp_lineage"]["usable_rows"] == len(selected_rows)
        assert binding["selected_latest_candle_id"] == selected_rows[-1]["candle_id"]
        assert binding["durable_source_receipt_emitted"] is False
        assert binding["feature_publication_receipt_emitted"] is False
        assert binding["trainer_admission_granted"] is False
        assert binding["live_execution_authorized"] is False


def test_unmanifested_external_values_cannot_release_snapshot(monkeypatch) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    latest_close_ms = _latest_finalized_close_ms(fp, "1m")
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps(
        _canonical_closed_window(latest_close_ms)
    )
    fake.store["v2:features:ta_full:BTCUSDT:1m"] = json.dumps(
        {"indicators": {"unmanifested_ta_signal": 0.75}}
    )
    original_features_from_market = fp._features_from_market  # noqa: SLF001

    def complete_required_features(market):
        features = original_features_from_market(market)
        for field in fp.TRAINER_REQUIRED_FEATURE_FIELDS:
            features[field] = 1.0
        return features

    original_read_hash = fp._read_hash_key  # noqa: SLF001

    def read_hash(redis_client, key):
        if key == "v2:unified_features:BTCUSDT:1m":
            return {"unmanifested_unified_signal": "0.5"}
        return original_read_hash(redis_client, key)

    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)
    monkeypatch.setattr(fp, "_features_from_market", complete_required_features)
    monkeypatch.setattr(fp, "_read_hash_key", read_hash)

    fp.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["required_model_feature_value_contract_valid"] is True
    assert snapshot["required_model_feature_pit_coverage_valid"] is False
    assert snapshot["required_model_feature_pit_rejection_reasons"] == [
        "REQUIRED_MODEL_FEATURE_PIT_LEDGER_REQUIRED"
    ]
    assert snapshot["exact_feature_availability_valid"] is False
    assert snapshot["exact_feature_availability_rejection_reasons"] == [
        "FEATURE_PUBLICATION_RECEIPT_REQUIRED"
    ]
    assert "unmanifested_ta_signal" not in snapshot["features"]
    assert snapshot["features"]["unmanifested_unified_signal"] == 0.5
    assert snapshot["trainer_consumable"] is False
    assert snapshot["valid_for_prediction"] is False
    assert snapshot["valid_for_paper"] is False


def test_required_candle_features_use_closed_window_not_24h_ticker() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    klines = [
        {
            "open": float(99 + index),
            "high": float(101 + index),
            "low": float(98 + index),
            "close": float(100 + index),
            "volume": 10.0,
        }
        for index in range(40)
    ]
    features = fp._features_from_market(
        {
            "ticker_24hr": {
                "lastPrice": "9999",
                "openPrice": "1",
                "highPrice": "10000",
                "lowPrice": "1",
                "prevClosePrice": "2",
            },
            "funding": {},
            "_klines": klines,
            "_paper_position_present": False,
        }
    )

    previous_close = 138.0
    latest_close = 139.0
    assert features["ret_pct"] == pytest.approx(
        (latest_close - previous_close) / previous_close
    )
    assert features["log_return"] == pytest.approx(
        math.log(latest_close / previous_close)
    )
    assert features["range_pct"] == pytest.approx((140.0 - 137.0) / latest_close)
    assert features["body_pct"] == pytest.approx((139.0 - 138.0) / latest_close)
    assert features["gap_pct"] == pytest.approx(0.0)
    expected_atr = fp._ta_atr(
        [float(101 + index) for index in range(40)],
        [float(98 + index) for index in range(40)],
        [float(100 + index) for index in range(40)],
        14,
    )
    assert expected_atr is not None
    assert features["true_range_pct"] == pytest.approx(expected_atr / latest_close)


def test_missing_required_inputs_remain_missing_instead_of_zero() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    features = fp._features_from_market(
        {
            "ticker_24hr": {},
            "funding": {},
            "_klines": [],
            "_orderbook": {},
        }
    )

    for field in (
        "ret_pct",
        "log_return",
        "range_pct",
        "body_pct",
        "true_range_pct",
        "gap_pct",
        "funding_rate",
        "micro_price",
        "paper_position_present",
    ):
        assert features[field] is None


def test_micro_price_is_size_weighted_book_price_not_ticker_last() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    features = fp._features_from_market(
        {
            "ticker_24hr": {"lastPrice": "9999"},
            "funding": {},
            "_orderbook": {
                "best_bid": 100.0,
                "best_ask": 102.0,
                "best_bid_size": 3.0,
                "best_ask_size": 1.0,
            },
            "_paper_position_present": 0,
        }
    )

    assert features["micro_price"] == pytest.approx(
        (100.0 * 1.0 + 102.0 * 3.0) / 4.0
    )
    assert features["micro_price"] != features["last_price"]
    assert features["paper_position_present"] == 0


@pytest.mark.parametrize(
    ("raw_value", "expected"),
    [(True, 1), (False, 0), (1, 1), (0, 0), ("0", None), (2, None)],
)
def test_paper_position_presence_requires_explicit_binary_state(
    raw_value: object,
    expected: int | None,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    features = fp._features_from_market(
        {
            "ticker_24hr": {},
            "funding": {},
            "_paper_position_present": raw_value,
        }
    )

    assert features["paper_position_present"] == expected


@pytest.mark.parametrize("raw", ["[]", b"[]"])
def test_paper_position_reader_accepts_explicit_empty_json_list(
    raw: str | bytes,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    fake.store[fp.PAPER_POSITIONS_SOURCE_KEY] = raw

    presence, status, row_count = fp._read_paper_position_presence(  # noqa: SLF001
        fake,
        ("BTCUSDT", "ETHUSDT"),
    )

    assert presence == {"BTCUSDT": 0, "ETHUSDT": 0}
    assert status == "VALID_EMPTY_LIST"
    assert row_count == 0
    assert fake.get_calls == [fp.PAPER_POSITIONS_SOURCE_KEY]


@pytest.mark.parametrize(
    ("raw", "expected_status"),
    [
        (None, "SOURCE_MISSING"),
        ("", "SOURCE_EMPTY"),
        (b"", "SOURCE_EMPTY"),
        (b"\xff", "INVALID_UTF8"),
        (123, "INVALID_PAYLOAD_TYPE"),
        ("{", "INVALID_JSON"),
        (json.dumps({"symbol": "BTCUSDT"}), "PAYLOAD_NOT_LIST"),
        (json.dumps([[]]), "ROW_NOT_MAPPING"),
        (json.dumps([{}]), "ROW_SYMBOL_INVALID"),
        (json.dumps([{"symbol": "btcusdt"}]), "ROW_SYMBOL_INVALID"),
        (json.dumps([{"symbol": "BTC/USDT"}]), "ROW_SYMBOL_INVALID"),
        (json.dumps([{"symbol": 123}]), "ROW_SYMBOL_INVALID"),
    ],
)
def test_paper_position_reader_fails_closed_on_invalid_source_value(
    raw: object | None,
    expected_status: str,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    if raw is not None:
        fake.store[fp.PAPER_POSITIONS_SOURCE_KEY] = raw

    presence, status, row_count = fp._read_paper_position_presence(  # noqa: SLF001
        fake,
        ("BTCUSDT",),
    )

    assert presence is None
    assert status == expected_status
    assert row_count is None
    assert fake.get_calls == [fp.PAPER_POSITIONS_SOURCE_KEY]


def test_paper_position_reader_fails_closed_on_redis_read_error() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    class ReadErrorRedis:
        def __init__(self) -> None:
            self.get_calls: list[str] = []

        def get(self, key: str) -> None:
            self.get_calls.append(key)
            raise RuntimeError("redis read failed")

    fake = ReadErrorRedis()

    presence, status, row_count = fp._read_paper_position_presence(  # noqa: SLF001
        fake,
        ("BTCUSDT",),
    )

    assert presence is None
    assert status == "READ_ERROR"
    assert row_count is None
    assert fake.get_calls == [fp.PAPER_POSITIONS_SOURCE_KEY]


def test_paper_position_reader_rejects_invalid_requested_symbol_without_read() -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    fake.store[fp.PAPER_POSITIONS_SOURCE_KEY] = "[]"

    presence, status, row_count = fp._read_paper_position_presence(  # noqa: SLF001
        fake,
        ("btcusdt",),
    )

    assert presence is None
    assert status == "INVALID_REQUESTED_SYMBOL"
    assert row_count is None
    assert fake.get_calls == []


@pytest.mark.parametrize(
    "raw",
    [
        json.dumps([{"symbol": "BTCUSDT", "position_id": "pos-btc"}]),
        json.dumps([{"symbol": "BTCUSDT", "position_id": "pos-btc"}]).encode(),
    ],
)
def test_run_once_reads_paper_positions_once_and_maps_each_requested_symbol(
    monkeypatch,
    raw: str | bytes,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    fake.store[fp.PAPER_POSITIONS_SOURCE_KEY] = raw
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.store[f"v2:market:prices:{symbol}"] = json.dumps(_market_payload())
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    heartbeat = fp.run_once(
        ("BTCUSDT", "ETHUSDT"),
        "1m",
        write_trainer_snapshot=False,
    )

    btc = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    eth = json.loads(fake.store["v2:features:latest:ETHUSDT:1m"])
    assert fake.get_calls.count(fp.PAPER_POSITIONS_SOURCE_KEY) == 1
    assert btc["features"]["paper_position_present"] == 1
    assert eth["features"]["paper_position_present"] == 0
    for snapshot in (btc, eth):
        assert snapshot["paper_position_source_key"] == fp.PAPER_POSITIONS_SOURCE_KEY
        assert snapshot["paper_position_value_source_status"] == ("VALID_POSITION_LIST")
        assert snapshot["paper_position_source_row_count"] == 1
        assert snapshot["paper_position_value_contract_valid"] is True
        assert snapshot["required_model_feature_pit_coverage_valid"] is False
        assert snapshot["trainer_consumable"] is False
        assert snapshot["valid_for_prediction"] is False
        assert snapshot["valid_for_paper"] is False
    assert heartbeat["paper_position_value_source_status"] == ("VALID_POSITION_LIST")
    assert heartbeat["paper_position_value_contract_valid"] is True
    assert heartbeat["required_model_feature_pit_coverage_valid_count"] == 0
    assert heartbeat["trainer_consumable_count"] == 0


def test_invalid_paper_position_source_remains_unknown_and_cannot_promote(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    fake.store[fp.PAPER_POSITIONS_SOURCE_KEY] = json.dumps(
        [{"symbol": "BTCUSDT"}, {"symbol": "not-canonical"}]
    )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    heartbeat = fp.run_once(
        ("BTCUSDT",),
        "1m",
        write_trainer_snapshot=False,
    )

    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["features"]["paper_position_present"] is None
    assert snapshot["paper_position_value_source_status"] == "ROW_SYMBOL_INVALID"
    assert snapshot["paper_position_value_contract_valid"] is False
    assert snapshot["required_model_feature_value_contract_valid"] is False
    assert snapshot["required_model_feature_pit_coverage_valid"] is False
    assert snapshot["exact_feature_availability_valid"] is False
    assert snapshot["trainer_consumable"] is False
    assert snapshot["valid_for_prediction"] is False
    assert snapshot["valid_for_paper"] is False
    assert heartbeat["trainer_release_ready"] is False
    assert heartbeat["active_consumer_readiness"] == "HELD"


def test_external_enrichment_cannot_override_canonical_paper_position_presence(
    monkeypatch,
) -> None:
    import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

    fake = FakeRedis()
    fake.store[fp.PAPER_POSITIONS_SOURCE_KEY] = json.dumps(
        [{"symbol": "BTCUSDT", "position_id": "pos-btc"}]
    )
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:features:ta_full:BTCUSDT:1m"] = json.dumps(
        {
            "indicators": {
                "paper_position_present": 0,
            }
        }
    )
    original_read_hash = fp._read_hash_key  # noqa: SLF001

    def read_hash(redis_client, key):
        if key == "v2:unified_features:BTCUSDT:1m":
            return {
                "paper_position_present": 0,
                "optional_external_signal": 0.75,
            }
        return original_read_hash(redis_client, key)

    monkeypatch.setattr(fp, "_read_hash_key", read_hash)
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    fp.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["features"]["paper_position_present"] == 1
    assert snapshot["features"]["optional_external_signal"] == 0.75
    assert snapshot["external_v2_feature_fields_merged"] == 1
    assert "v2:features:ta_full" not in snapshot["external_v2_sources_present"]
    assert "v2:unified_features" in snapshot["external_v2_sources_present"]
