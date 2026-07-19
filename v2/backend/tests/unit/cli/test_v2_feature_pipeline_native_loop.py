from __future__ import annotations

import importlib
import json
import math
import re

import pytest

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


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, object] = {}
        self.expiries: dict[str, int | None] = {}
        self.get_calls: list[str] = []

    def ping(self) -> bool:
        return True

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
    open_ms = close_ms - 60_000 + 1
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "candle_open_time": open_ms,
            "candle_close_time": close_ms,
            **_exact_candle_clocks(close_ms),
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
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
        "v2_hybrid_feature_requirements_v1"
    )
    assert payload["model_feature_abi_slot_count"] == 446
    assert payload["required_model_feature_count"] == 384
    assert len(payload["required_model_feature_fields"]) == 384
    assert payload["optional_event_dependent_feature_count"] == 62
    assert len(payload["optional_event_dependent_feature_fields"]) == 62
    assert "gap_pct" not in payload["required_model_feature_fields"]
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
    assert payload["feature_freshness_state"] == "EXACT_SOURCE_CLOCK_INVALID"
    assert payload["event_time"] is None
    assert payload["ingested_at"] is None
    assert payload["source_available_at"] is None
    assert payload["exact_source_clock_rejection_reasons"] == [
        "EXACT_CANDLE_OPEN_TIME_MISSING_OR_INVALID",
        "EXACT_CANDLE_CLOSE_TIME_MISSING_OR_INVALID",
        "EXACT_EVENT_TIME_MISSING_OR_INVALID",
        "EXACT_INGESTED_AT_MISSING_OR_INVALID",
        "EXACT_SOURCE_AVAILABLE_AT_MISSING_OR_INVALID",
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
    assert len(mod.TRAINER_REQUIRED_FEATURE_FIELDS) == 384
    assert len(mod.TRAINER_OPTIONAL_EVENT_DEPENDENT_FEATURE_FIELDS) == 62
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
    bad_clocks = _exact_candle_clocks(close_ms, symbol="BTCUSDT")
    bad_clocks["candle_open_time"] = 10**100
    bad_clocks["candle_close_time"] = close_ms
    good_clocks = _exact_candle_clocks(close_ms, symbol="ETHUSDT")
    good_clocks["candle_open_time"] = close_ms - 60_000 + 1
    good_clocks["candle_close_time"] = close_ms
    for symbol, clocks in (("BTCUSDT", bad_clocks), ("ETHUSDT", good_clocks)):
        fake.store[
            f"v2:market:ohlcv_closed:binance:{symbol}:1m"
        ] = json.dumps(
            [
                {
                    **clocks,
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

    mod.run_once(("BTCUSDT", "ETHUSDT"), "1m", write_trainer_snapshot=False)

    btc = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    eth = json.loads(fake.store["v2:features:latest:ETHUSDT:1m"])
    assert btc["trainer_consumable"] is False
    assert "EXACT_CANDLE_OPEN_TIME_MISSING_OR_INVALID" in btc[
        "exact_source_clock_rejection_reasons"
    ]
    assert eth["trainer_consumable"] is False
    assert eth["exact_source_clock_valid"] is True
    assert eth["exact_source_clock_rejection_reasons"] == []


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
    bad_row = {
        "candle_open_time": close_ms - 60_000 + 1,
        "candle_close_time": bad_close,
        **_exact_candle_clocks(close_ms, symbol="BTCUSDT"),
        "open": "99.0",
        "high": "101.0",
        "low": "98.0",
        "close": "100.0",
        "volume": "1000",
    }
    good_row = {
        "candle_open_time": close_ms - 60_000 + 1,
        "candle_close_time": close_ms,
        **_exact_candle_clocks(close_ms, symbol="ETHUSDT"),
        "open": "99.0",
        "high": "101.0",
        "low": "98.0",
        "close": "100.0",
        "volume": "1000",
    }
    fake.store[
        "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    ] = json.dumps([bad_row])
    fake.store[
        "v2:market:ohlcv_closed:binance:ETHUSDT:1m"
    ] = json.dumps([good_row])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT", "ETHUSDT"), "1m", write_trainer_snapshot=False)

    btc = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    eth = json.loads(fake.store["v2:features:latest:ETHUSDT:1m"])
    assert btc["trainer_consumable"] is False
    assert btc["feature_freshness_state"] == "MISSING_CLOSED_OHLCV"
    assert btc["malformed_kline_excluded_count"] == 1
    assert eth["exact_source_clock_valid"] is True
    assert eth["latest_candle_temporally_valid"] is True


def test_run_once_uses_one_exact_cutoff_per_symbol_for_kline_selection(
    monkeypatch,
) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    for symbol in ("BTCUSDT", "ETHUSDT"):
        fake.store[f"v2:market:prices:{symbol}"] = json.dumps(_market_payload())
    cutoffs = iter((_TEST_NOW_MS + 1_000, _TEST_NOW_MS + 2_000))
    monkeypatch.setattr(mod.time, "time", lambda: next(cutoffs) / 1000.0)
    observed: list[tuple[str, int | None]] = []

    def capture_read(_redis, symbol, _timeframe="1m", *, decision_ms=None):
        observed.append((symbol, decision_ms))
        return None, {
            "selection_mode": "TEST_NO_KLINES",
            "selected_source_keys": [],
            "raw_key_row_count": 0,
            "closed_key_row_count": 0,
            "selected_row_count": 0,
        }

    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)
    monkeypatch.setattr(mod, "_read_klines_with_lineage", capture_read)

    mod.run_once(("BTCUSDT", "ETHUSDT"), "1m", write_trainer_snapshot=False)

    assert observed == [
        ("BTCUSDT", _TEST_NOW_MS + 1_000),
        ("ETHUSDT", _TEST_NOW_MS + 2_000),
    ]


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
        [
            {
                "candle_open_time": selected_close_ms - 59_999,
                "candle_close_time": selected_close_ms,
                **_exact_candle_clocks(selected_close_ms),
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
    assert payload["source_observation_time"] == mod._ms_to_utc_iso(observation_ms)
    assert payload["expected_latest_finalized_candle_close_time"] == mod._ms_to_utc_iso(
        boundary_ms - 1
    )
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(selected_close_ms)
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["temporal_rejection_reasons"] == [
        "FINALIZED_CANDLE_NOT_AVAILABLE_AT_DECISION"
    ]


def test_feature_snapshot_emits_closed_window_atr_percentile(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    latest_close_ms = _latest_finalized_close_ms(mod, "1m")
    rows = []
    for index in range(45):
        close_ms = latest_close_ms - (44 - index) * 60_000
        open_ms = close_ms - 60_000 + 1
        close = 100.0 + index * 0.2
        width = 0.8 + (index % 9) * 0.08
        rows.append(
            {
                "candle_open_time": open_ms,
                "candle_close_time": close_ms,
                **_exact_candle_clocks(close_ms),
                "open": f"{close - 0.1}",
                "high": f"{close + width}",
                "low": f"{close - width * 0.7}",
                "close": f"{close}",
                "volume": f"{1000 + index}",
                "is_closed": True,
            }
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
    older_close_ms = newer_close_ms - 60_000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "candle_open_time": older_close_ms - 60_000 + 1,
            "candle_close_time": older_close_ms,
            **_exact_candle_clocks(older_close_ms),
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        },
        {
            "candle_open_time": newer_close_ms - 60_000 + 1,
            "candle_close_time": newer_close_ms,
            **_exact_candle_clocks(
                newer_close_ms,
                ingested_ms=now_ms + 60_000,
                available_ms=now_ms + 60_000,
            ),
            "open": "100.0",
            "high": "102.0",
            "low": "99.0",
            "close": "101.0",
            "volume": "1200",
            "is_closed": True,
        },
    ])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["feature_freshness_state"] == (
        "FINALIZED_CANDLE_NOT_AVAILABLE_AT_DECISION"
    )
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(older_close_ms)  # noqa: SLF001
    assert payload["temporal_rejection_reasons"] == [
        "FINALIZED_CANDLE_NOT_AVAILABLE_AT_DECISION"
    ]
    assert payload["latest_unclosed_kline_excluded"] is False
    assert payload["future_available_finalized_kline_excluded_count"] == 1


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
    assert payload["feature_freshness_state"] == "EXACT_SOURCE_CLOCK_INVALID"
    assert payload["feature_cutoff"] is None
    assert payload["feature_cutoff_est"] == mod._ms_to_utc_iso(close_ms)
    assert payload["exact_source_clock_valid"] is False
    assert payload["exact_source_clock_rejection_reasons"] == [
        "EXACT_CANDLE_CLOCK_PAYLOAD_REQUIRED"
    ]
    assert "exact_source_clock_lineage" in payload["missing_feature_flags"]


def test_feature_snapshot_carries_point_in_time_cost_evidence_from_orderbook(monkeypatch) -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    close_ms = _latest_finalized_close_ms(mod, "1m")
    open_ms = close_ms - 60_000 + 1
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:orderbook:BTCUSDT"] = json.dumps(
        {
            "bids": [["99.95", "10"]],
            "asks": [["100.05", "10"]],
        }
    )
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "candle_open_time": open_ms,
            "candle_close_time": close_ms,
            **_exact_candle_clocks(close_ms),
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
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


def test_external_enrichment_cannot_manufacture_reserved_feature_or_cost_evidence() -> None:
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    injected = {
        field: float(index + 1)
        for index, field in enumerate(sorted(mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS))
    }
    injected["optional_external_signal"] = 0.73
    fake.store["v2:features:ta_full:BTCUSDT:1m"] = json.dumps(
        {"indicators": injected}
    )
    features = {
        field: None for field in mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS
    }

    result = mod._merge_external_v2_features(  # noqa: SLF001
        fake,
        "BTCUSDT",
        "1m",
        features,
    )

    assert all(
        features[field] is None
        for field in mod.EXTERNAL_ENRICHMENT_RESERVED_FIELDS
    )
    assert features["optional_external_signal"] == 0.73
    assert "v2:features:ta_full" in result["sources_present"]


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
    open_ms = close_ms - 60_000 + 1
    market = _market_payload()
    market["funding"] = {}
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(market)
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "candle_open_time": open_ms,
            "candle_close_time": close_ms,
            **_exact_candle_clocks(close_ms),
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
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
    assert features["ret_pct"] is None
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
    open_ms = close_ms - 60_000 + 1
    market = _market_payload()
    market["open_interest"] = {"openInterest": "123.45"}
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(market)
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "candle_open_time": open_ms,
            "candle_close_time": close_ms,
            **_exact_candle_clocks(close_ms),
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "100.0",
            "quote_volume": "10000.0",
            "num_trades": "40",
            "taker_buy_base_vol": "60.0",
            "taker_buy_quote_vol": "6000.0",
            "is_closed": True,
        }
    ])
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
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = json.dumps([
        {
            "open_time": 1_781_000_000_000,
            "close_time": 1_781_000_059_999,
            "open": "99.0",
            "high": "101.0",
            "low": "98.0",
            "close": "100.0",
            "volume": "1000",
            "is_closed": True,
        }
    ])
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_prediction"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "STALE_CLOSED_OHLCV"
    assert payload["candle_closed_confirmed"] is True
    assert payload["feature_cutoff"] is None
    assert payload["feature_cutoff_est"] == mod._ms_to_utc_iso(
        1_781_000_059_999
    )
    assert payload["stale_feature_flags"] == ["ohlcv_closed_window"]
    assert "ohlcv_closed_window_stale" in payload["missing_feature_flags"]


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


def test_feature_snapshot_rejects_rest_backfill_as_exact_live_evidence(
    monkeypatch,
) -> None:
    bridge = importlib.import_module("v2.backend.app.cli.v2_closed_candle_resampler")
    mod = importlib.import_module("v2.backend.app.cli.v2_feature_pipeline_native_loop")
    fake = FakeRedis()
    now_ms = _TEST_NOW_MS
    close_ms = _latest_finalized_close_ms(mod, "4h")
    open_ms = close_ms - 4 * 60 * 60 * 1000
    fake.store["v2:market:prices:BTCUSDT"] = json.dumps(_market_payload())
    fake.store["v2:market:ohlcv:binance:BTCUSDT:4h"] = json.dumps(
        [[open_ms, "99", "101", "98", "100", "1000", close_ms, "100000", 20, "500", "50000", "0"]]
    )
    bridge.copy_finalized_raw_ohlcv(
        fake,
        symbol="BTCUSDT",
        timeframe="4h",
        now_ms_value=now_ms,
    )
    monkeypatch.setattr(mod, "_connect_redis", lambda: fake)

    mod.run_once(("BTCUSDT",), "4h", write_trainer_snapshot=False)

    payload = json.loads(fake.store["v2:features:latest:BTCUSDT:4h"])
    assert payload["trainer_consumable"] is False
    assert payload["valid_for_paper"] is False
    assert payload["feature_freshness_state"] == "EXACT_SOURCE_CLOCK_INVALID"
    assert payload["feature_cutoff"] == mod._ms_to_utc_iso(close_ms)  # noqa: SLF001
    assert payload["source"] == "binance_rest"
    assert payload["is_backfilled"] is True
    assert payload["exact_source_clock_rejection_reasons"] == [
        "LIVE_CANDLE_SOURCE_NOT_EXACT_BINANCE_WSS",
        "LIVE_CANDLE_BACKFILL_NOT_EXACT_OBSERVATION",
    ]


class TestReadKlinesTieBreak:
    """F-0009: ohlcv_closed key history is TTL-truncated for intervals longer
    than the key TTL; on freshness ties _read_klines must prefer the deeper
    raw buffer so history-window features (atr_percentile) can compute."""

    class _FakeRedis:
        def __init__(self, store):
            self._store = store

        def get(self, key):
            return self._store.get(key)

    @staticmethod
    def _kline(close_ms: int) -> list:
        # 12-field Binance kline row; index 6 is close_time
        return [
            close_ms - 900_000 + 1,
            "1",
            "2",
            "0.5",
            "1.5",
            "10",
            close_ms,
            "10",
            5,
            "5",
            "5",
            "0",
        ]

    def test_tie_prefers_deeper_raw_buffer(self):
        import json as _json
        import time as _time
        import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

        now_ms = int(_time.time() * 1000)
        latest = now_ms - 10_000
        raw = [self._kline(latest - i * 900_000) for i in range(50)][::-1]
        closed = [self._kline(latest)]  # TTL-truncated: only the newest row
        store = {
            f"{fp.V2_REDIS_PREFIX}market:ohlcv:binance:XUSDT:15m": _json.dumps(raw),
            f"{fp.V2_REDIS_PREFIX}market:ohlcv_closed:binance:XUSDT:15m": _json.dumps(closed),
        }
        rows = fp._read_klines(self._FakeRedis(store), "XUSDT", "15m", decision_ms=now_ms)
        assert len(rows) == 50, "tie must resolve to the deeper raw buffer"

    def test_tie_retains_deep_history_but_uses_exact_canonical_latest(self):
        import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

        now_ms = _TEST_NOW_MS
        latest = fp._expected_latest_finalized_close_ms(  # noqa: SLF001
            decision_ms=now_ms,
            timeframe="15m",
        )
        raw = [self._kline(latest - i * 900_000) for i in range(50)][::-1]
        canonical_latest = {
            "candle_open_time": latest - 900_000 + 1,
            "candle_close_time": latest,
            **_exact_candle_clocks(
                latest,
                symbol="XUSDT",
                timeframe="15m",
            ),
        }
        store = {
            f"{fp.V2_REDIS_PREFIX}market:ohlcv:binance:XUSDT:15m": json.dumps(raw),
            f"{fp.V2_REDIS_PREFIX}market:ohlcv_closed:binance:XUSDT:15m": (
                json.dumps([canonical_latest])
            ),
        }

        rows, lineage = fp._read_klines_with_lineage(
            self._FakeRedis(store),
            "XUSDT",
            "15m",
            decision_ms=now_ms,
        )

        assert len(rows) == 50
        assert rows[-1] == canonical_latest
        assert lineage["selection_mode"] == (
            "HYBRID_RAW_HISTORY_CANONICAL_CLOSED_LATEST"
        )
        assert lineage["selected_source_keys"] == [
            f"{fp.V2_REDIS_PREFIX}market:ohlcv:binance:XUSDT:15m",
            f"{fp.V2_REDIS_PREFIX}market:ohlcv_closed:binance:XUSDT:15m",
        ]
        assert lineage["raw_key_row_count"] == 50
        assert lineage["closed_key_row_count"] == 1
        assert lineage["selected_row_count"] == 50

    def test_newer_closed_key_still_wins(self):
        import json as _json
        import time as _time
        import v2.backend.app.cli.v2_feature_pipeline_native_loop as fp

        now_ms = int(_time.time() * 1000)
        raw = [self._kline(now_ms - 900_000)]
        closed = [self._kline(now_ms - 10_000), self._kline(now_ms - 910_000)]
        store = {
            f"{fp.V2_REDIS_PREFIX}market:ohlcv:binance:XUSDT:15m": _json.dumps(raw),
            f"{fp.V2_REDIS_PREFIX}market:ohlcv_closed:binance:XUSDT:15m": _json.dumps(closed),
        }
        rows = fp._read_klines(self._FakeRedis(store), "XUSDT", "15m", decision_ms=now_ms)
        assert len(rows) == 2, "closed key with strictly newer candle must win"


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
                "optional_external_signal": 0.75,
            }
        }
    )
    monkeypatch.setattr(fp, "_connect_redis", lambda: fake)

    fp.run_once(("BTCUSDT",), "1m", write_trainer_snapshot=False)

    snapshot = json.loads(fake.store["v2:features:latest:BTCUSDT:1m"])
    assert snapshot["features"]["paper_position_present"] == 1
    assert snapshot["features"]["optional_external_signal"] == 0.75
    assert snapshot["external_v2_feature_fields_merged"] == 1
    assert "v2:features:ta_full" in snapshot["external_v2_sources_present"]
