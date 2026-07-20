from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from v2.backend.app.cli import v2_full_talib_ta_loop as worker
from v2.backend.app.services.full_talib_ta import service as ta_service
from v2.backend.app.services.full_talib_ta.service import (
    FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS,
    build_full_talib_ta_payload,
    normalize_ohlcv_rows,
)
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)


def _klines(count: int = 120) -> list[list[Any]]:
    out: list[list[Any]] = []
    base_ts = 1_780_000_000_000
    for i in range(count):
        price = 100.0 + (i * 0.25) + ((-1) ** i) * 0.1
        out.append(
            [
                base_ts + i * 60_000,
                str(price - 0.2),
                str(price + 0.5),
                str(price - 0.7),
                str(price),
                str(1000.0 + i),
            ]
        )
    return out


def _canonical_closed_rows(
    count: int = 120,
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
) -> list[dict[str, Any]]:
    duration = int(TIMEFRAME_DURATION_MS[timeframe])
    base_ts = (1_750_000_000_000 // duration) * duration
    rows: list[dict[str, Any]] = []
    for index in range(count):
        open_time = base_ts + index * duration
        close_time = open_time + duration - 1
        price = 100.0 + index * 0.25
        source_row: list[Any] = [
            open_time,
            str(price - 0.2),
            str(price + 0.5),
            str(price - 0.7),
            str(price),
            str(1000.0 + index),
            close_time,
            str((1000.0 + index) * price),
            100 + index,
            str(500.0 + index),
            str((500.0 + index) * price),
            "0",
        ]
        rows.append(
            canonical_from_binance_rest(
                source_row,
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=close_time + 200,
            ).to_dict()
        )
    return rows


def _exact_json(rows: list[dict[str, Any]]) -> str:
    return json.dumps(rows, sort_keys=True, separators=(",", ":"))


def _utc(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


class FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.get_calls: list[str] = []
        self.set_calls: list[str] = []

    def get(self, key: str) -> Any:
        self.get_calls.append(key)
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.set_calls.append(key)
        self.store[key] = value
        if ex is not None:
            self.ttls[key] = int(ex)
        return True

    def scan_iter(self, match: str, count: int = 500):  # noqa: ARG002
        prefix = match[:-1] if match.endswith("*") else match
        for key in sorted(self.store):
            if key.startswith(prefix):
                yield key


def test_normalize_accepts_binance_kline_rows() -> None:
    candles = normalize_ohlcv_rows(_klines(3))
    assert len(candles) == 3
    assert candles[0].open > 0
    assert candles[-1].ts_ms is not None


def test_normalize_selects_mapping_fields_by_presence_and_preserves_zero() -> None:
    candles = normalize_ohlcv_rows(
        [
            {
                "ts_ms": 0,
                "timestamp": 999,
                "open": 1.0,
                "high": 2.0,
                "low": 0.5,
                "close": 1.5,
                "volume": 0.0,
                "v": 999.0,
            }
        ]
    )
    assert len(candles) == 1
    assert candles[0].ts_ms == 0
    assert candles[0].volume == 0.0


def test_full_talib_payload_reaches_legacy_field_depth() -> None:
    result = build_full_talib_ta_payload(
        symbol="BTCUSDT",
        timeframe="1m",
        candles=_klines(140),
        source_ohlcv_key="v2:market:ohlcv:binance:BTCUSDT:1m",
    )
    payload = result.to_payload(source_ohlcv_key="v2:market:ohlcv:binance:BTCUSDT:1m")
    assert payload["classification"] in {
        "V2_FULL_TALIB_TA_OK",
        "V2_FULL_TALIB_TA_PARTIAL_OK",
        "BLOCKED_TALIB_IMPORT_FAILED",
    }
    if payload["classification"] != "BLOCKED_TALIB_IMPORT_FAILED":
        assert payload["field_count"] >= 100
        assert payload["talib_function_count"] >= 150
        assert payload["computed_function_count"] >= 100
        assert payload["indicators"]["ta_RSI_14"] > 0
        assert "ta_MACD_12_26_9_macd" in payload["indicators"]
    else:
        assert "talib_import" in payload["skipped_functions"]
    assert payload["live_gate"] == "blocked_human_only"
    assert payload["live_symbols"] == []
    assert payload["writes_legacy_redis"] is False
    assert payload["places_real_order"] is False
    assert payload["trainer_consumable"] is False
    assert payload["consumer_eligible"] is False


def test_strict_latest_output_never_scans_backward_or_accepts_wrong_length() -> None:
    latest, status = ta_service._strict_latest_output(  # noqa: SLF001
        np.asarray([11.0, np.nan], dtype="float64"),
        source_row_count=2,
    )
    assert latest is None
    assert status == "NONFINITE_LATEST_OUTPUT"

    latest, status = ta_service._strict_latest_output(  # noqa: SLF001
        np.asarray([11.0], dtype="float64"),
        source_row_count=2,
    )
    assert latest is None
    assert status == "OUTPUT_LENGTH_MISMATCH"

    latest, status = ta_service._strict_latest_output(  # noqa: SLF001
        np.asarray([11.0, 12.0], dtype="float64"),
        source_row_count=2,
    )
    assert latest == 12.0
    assert status == "PRESENT_FINITE"

    indicators: dict[str, float] = {}
    rejections: dict[str, str] = {}
    accepted = ta_service._put(  # noqa: SLF001
        indicators,
        "ta_TEST",
        np.asarray([11.0, np.nan], dtype="float64"),
        source_row_count=2,
        rejected_outputs=rejections,
    )
    assert accepted is False
    assert "ta_TEST" not in indicators
    assert rejections == {"ta_TEST": "NONFINITE_LATEST_OUTPUT"}


def test_run_once_writes_v2_ta_keys_and_status(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    source_rows = _canonical_closed_rows(120)
    source_json = _exact_json(source_rows)
    fake.store[source_key] = source_json.encode("utf-8")
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")
    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )
    assert status["classification"] == ("V2_FULL_TALIB_TA_CLOSED_CANDIDATES_WRITTEN_NONCONSUMABLE")
    assert status["keys_written_count"] == 3
    assert "v2:features:ta:BTCUSDT:1m" in fake.store
    assert "v2:features:ta_closed:BTCUSDT:1m" in fake.store
    assert "v2:features:ta_full:BTCUSDT:1m" in fake.store
    assert "v2:technical_analysis:BTCUSDT:1m" not in fake.store
    assert "v2:technical_analysis:BTCUSDT:1m" not in fake.set_calls
    assert "v2:features:ta:heartbeat" in fake.store
    for key in fake.store:
        assert key.startswith("v2:")
    payload = json.loads(fake.store["v2:features:ta_closed:BTCUSDT:1m"])
    assert payload["source_ohlcv_key"] == source_key
    assert (
        payload["source_exact_payload_sha256"]
        == hashlib.sha256(source_json.encode("utf-8")).hexdigest()
    )
    assert payload["source_exact_payload_byte_count"] == len(source_json.encode("utf-8"))
    assert payload["source_row_count"] == 120
    assert payload["source_contiguous_suffix_count"] == 120
    assert payload["calculation_row_count"] == FULL_TALIB_TA_REQUIRED_CONTIGUOUS_ROWS == 89
    assert payload["calculation_normalized_row_count"] == 89
    assert payload["calculation_normalized_exact_source_identity"] is True
    assert payload["calculation_normalized_first_ts_ms"] == source_rows[-89]["candle_open_time"]
    assert payload["calculation_normalized_last_ts_ms"] == source_rows[-1]["candle_open_time"]
    assert payload["calculation_window_first_candle_id"] == source_rows[-89]["candle_id"]
    assert payload["latest_candle_id"] == source_rows[-1]["candle_id"]
    assert payload["latest_candle_raw_payload_hash"] == source_rows[-1]["raw_payload_hash"]
    assert payload["latest_candle_producer_event_time_ms"] == source_rows[-1]["event_time"]
    assert payload["latest_candle_ingested_at_ms"] == source_rows[-1]["ingested_at"]
    assert payload["latest_candle_available_at_ms"] == source_rows[-1]["available_at"]
    assert payload["source_economic_event_time_ms"] == source_rows[-1]["candle_close_time"]
    assert payload["source_producer_event_time_ms"] == max(row["event_time"] for row in source_rows)
    assert payload["source_ingested_at_ms"] == max(row["ingested_at"] for row in source_rows)
    assert payload["source_available_at_ms"] == max(row["available_at"] for row in source_rows)
    assert payload["source_economic_event_time"] == payload["source_event_time"]
    assert payload["source_event_time"] == payload["feature_cutoff"]
    assert _utc(payload["source_event_time"]) <= _utc(payload["source_producer_event_time"])
    assert _utc(payload["source_producer_event_time"]) <= _utc(payload["source_ingested_at"])
    assert _utc(payload["source_ingested_at"]) <= _utc(payload["source_available_at"])
    assert _utc(payload["source_available_at"]) <= _utc(payload["generated_at"])
    assert payload["available_at"] is None
    assert payload["publication_observed_at"] is None
    assert payload["redis_read_receipt_emitted"] is False
    assert payload["immutable_cas_captured"] is False
    assert payload["publication_committed"] is False
    assert payload["consumer_eligible"] is False
    assert payload["trainer_consumable"] is False
    assert payload["trainer_admission_granted"] is False
    assert payload["live_execution_authorized"] is False

    compatibility = json.loads(fake.store["v2:features:ta:BTCUSDT:1m"])
    assert compatibility["canonical_candidate_key"] == ("v2:features:ta_closed:BTCUSDT:1m")
    assert compatibility["compatibility_view"] is True
    assert compatibility["compatibility_unsafe_for_trainer"] is True
    assert compatibility["trainer_consumable"] is False
    assert compatibility["available_at"] is None
    full_compatibility = json.loads(fake.store["v2:features:ta_full:BTCUSDT:1m"])
    assert full_compatibility["compatibility_unsafe_for_trainer"] is True
    assert full_compatibility["consumer_eligible"] is False
    assert status["technical_analysis_write_attempted"] is False
    assert status["trainer_consumable"] is False
    assert json.loads((tmp_path / "public.json").read_text())["worker_id"] == worker.WORKER_ID


def test_run_once_never_reads_or_merges_live_ohlcv_even_on_timestamp_collision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1h"
    source_rows = _canonical_closed_rows(100, timeframe="1h")
    source_json = _exact_json(source_rows)
    fake.store[source_key] = source_json.encode("utf-8")
    live_key = "v2:market:ohlcv:binance:BTCUSDT:1h"
    fake.store[live_key] = json.dumps(
        [[source_rows[-1]["candle_open_time"], "1", "999999", "1", "999999", "1"]]
    )
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1h",
        redis_client=fake,
    )

    payload = json.loads(fake.store["v2:features:ta_closed:BTCUSDT:1h"])
    assert live_key not in fake.get_calls
    assert payload["source_ohlcv_key"] == source_key
    assert (
        payload["source_exact_payload_sha256"]
        == hashlib.sha256(source_json.encode("utf-8")).hexdigest()
    )
    assert payload["calculation_row_count"] == 89
    assert payload["latest_candle_id"] == source_rows[-1]["candle_id"]
    assert payload["indicators"].get("close") != 999999.0


def test_run_once_preserves_authenticated_zero_volume_in_exact_89_row_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    source_rows = _canonical_closed_rows(89)
    source_rows[-1]["volume"] = 0.0
    source_rows[-1]["taker_buy_base_vol"] = 0.0
    source_rows[-1]["ohlcv"]["volume"] = 0.0
    source_rows[-1]["ohlcv"]["taker_buy_base_vol"] = 0.0
    fake.store[source_key] = _exact_json(source_rows).encode("utf-8")
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )

    assert status["candidate_write_acknowledged_count"] == 1
    payload = json.loads(fake.store["v2:features:ta_closed:BTCUSDT:1m"])
    assert payload["calculation_row_count"] == 89
    assert payload["calculation_normalized_row_count"] == 89
    assert payload["calculation_normalized_exact_source_identity"] is True
    assert payload["indicators"]["volume"] == 0.0


def test_run_once_does_not_promote_discovered_symbols_or_their_timeframes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    authorized_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    obsolete_key = "v2:market:ohlcv_closed:binance:OBSOLETEUSDT:4h"
    fake.store[authorized_key] = _exact_json(_canonical_closed_rows(89)).encode("utf-8")
    fake.store[obsolete_key] = _exact_json(
        _canonical_closed_rows(89, symbol="OBSOLETEUSDT", timeframe="4h")
    ).encode("utf-8")
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        redis_client=fake,
    )

    assert status["symbols_requested"] == ["BTCUSDT"]
    assert status["symbols_processed"] == ["BTCUSDT"]
    assert "4h" not in status["timeframes_requested"]
    assert status["unauthorized_discovered_symbols_ignored"] == ["OBSOLETEUSDT"]
    assert status["redis_discovery_grants_symbol_authority"] is False
    assert obsolete_key not in fake.get_calls
    assert all(row["symbol"] == "BTCUSDT" for row in status["results"])
    assert not any("OBSOLETEUSDT" in key for key in status["keys_written"])


def test_run_once_does_not_fallback_to_features_or_self_refresh_ta(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    old_ta = json.dumps({"marker": "must-not-be-refreshed"})
    old_technical = json.dumps({"indicators": {"rsi_14": 98.0}})
    fake.store["v2:features:latest:BTCUSDT:1m"] = json.dumps({"features": {"rsi_14": 99.0}})
    fake.store["v2:features:ta:BTCUSDT:1m"] = old_ta
    fake.store["v2:technical_analysis:BTCUSDT:1m"] = old_technical
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )

    assert status["classification"] == "BLOCKED_NO_VALID_CLOSED_TA_CANDIDATES"
    assert status["keys_written_count"] == 0
    assert fake.store["v2:features:ta:BTCUSDT:1m"] == old_ta
    assert "v2:features:ta_full:BTCUSDT:1m" not in fake.store
    assert "v2:features:ta_closed:BTCUSDT:1m" not in fake.store
    assert "v2:features:latest:BTCUSDT:1m" not in fake.get_calls
    assert "v2:technical_analysis:BTCUSDT:1m" not in fake.get_calls
    assert fake.store["v2:technical_analysis:BTCUSDT:1m"] == old_technical
    assert "v2:technical_analysis:BTCUSDT:1m" not in fake.set_calls


def test_run_once_rejects_decoded_source_text_instead_of_reconstructing_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = _exact_json(_canonical_closed_rows(89))
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )

    assert status["classification"] == "BLOCKED_NO_VALID_CLOSED_TA_CANDIDATES"
    assert status["keys_written_count"] == 0
    assert status["results"][0]["rejection_reason"] == "exact_source_bytes_missing"
    assert "v2:features:ta_closed:BTCUSDT:1m" not in fake.store


def test_run_once_does_not_publish_compatibility_views_without_candidate_set_ack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class CandidateSetNotAcknowledgedRedis(FakeRedis):
        def set(self, key: str, value: str, ex: int | None = None) -> bool | None:
            if key.startswith("v2:features:ta_closed:"):
                return None
            return super().set(key, value, ex=ex)

    fake = CandidateSetNotAcknowledgedRedis()
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    fake.store[source_key] = _exact_json(_canonical_closed_rows(89)).encode("utf-8")
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )

    assert status["classification"] == "BLOCKED_NO_VALID_CLOSED_TA_CANDIDATES"
    assert status["candidate_write_acknowledged_count"] == 0
    assert status["keys_written_count"] == 0
    assert "v2:features:ta:BTCUSDT:1m" not in fake.store
    assert "v2:features:ta_full:BTCUSDT:1m" not in fake.store


def test_run_once_rejects_future_source_availability_anywhere_in_exact_window(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    source_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    source_rows = _canonical_closed_rows(89)
    future_ms = int(datetime.now(UTC).timestamp() * 1000) + 60_000
    source_rows[0]["ingested_at"] = future_ms
    source_rows[0]["available_at"] = future_ms
    fake.store[source_key] = _exact_json(source_rows).encode("utf-8")
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m",
        redis_client=fake,
    )

    assert status["classification"] == "BLOCKED_NO_VALID_CLOSED_TA_CANDIDATES"
    assert status["results"][0]["classification"] == ("BLOCKED_TA_CLOSED_CANDIDATE_CONTRACT")
    assert status["results"][0]["rejection_reason"] == (
        "full_talib_closed_candidate_source_available_after_generation"
    )
    assert "v2:features:ta_closed:BTCUSDT:1m" not in fake.store


def test_run_once_gracefully_rejects_source_binding_and_unsupported_timeframe(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = FakeRedis()
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = _exact_json(
        _canonical_closed_rows(89, symbol="ETHUSDT")
    ).encode("utf-8")
    fake.store["v2:market:ohlcv_closed:binance:BTCUSDT:3m"] = b"[]"
    monkeypatch.setattr(worker, "PUBLIC_STATUS_PATH", tmp_path / "public.json")
    monkeypatch.setattr(worker, "LOCAL_STATUS_PATH", tmp_path / "local.json")

    status = worker.run_once(
        symbols_arg="BTCUSDT",
        timeframes_arg="1m,3m",
        redis_client=fake,
    )

    assert status["classification"] == "BLOCKED_NO_VALID_CLOSED_TA_CANDIDATES"
    assert status["keys_written_count"] == 0
    reasons = {row["timeframe"]: row["rejection_reason"] for row in status["results"]}
    assert reasons["1m"] == "ohlcv_closed_source_binding_invalid"
    assert reasons["3m"] == "ohlcv_closed_timeframe_invalid"
