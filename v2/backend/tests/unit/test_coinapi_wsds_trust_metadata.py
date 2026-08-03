from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

import pytest
from app.services.native_ingestors.coinapi_wsds import (
    PROVIDER_IDENTITY_SCHEMA_VERSION,
    WSDS_RAW_QUARANTINE_FIELDS,
    build_coinapi_wsds_status,
    normalize_wsds_snapshot,
    parse_provider_timestamp,
)


def _valid_snapshot() -> dict[str, object]:
    return {
        "coinapi_symbol_id": "BINANCEFTS_PERP_BTC_USDT",
        "coinapi_exchange_id": "BINANCEFTS",
        "coinapi_market_type": "PERP",
        "source_event_time": "2026-07-20T12:00:00.000000100Z",
        "source_event_ts_ms": 1_784_548_800_000,
        "source_event_ts_ns": 1_784_548_800_000_000_100,
        "provider_received_time": "2026-07-20T12:00:00.000000200Z",
        "observed_at": "2026-07-20T12:00:00.000001Z",
        "ingested_at": "2026-07-20T12:00:00.000002Z",
        "generated_at": "2026-07-20T12:00:00.000003Z",
        "available_at": None,
        "best_bid_px": 100,
        "best_ask_px": 101,
        "best_bid_sz": 2,
        "best_ask_sz": 3,
        "mid_px": 100.5,
        "spread_bps": 10_000.0 / 100.5,
        "microprice": 100.4,
        "book_bid_sum_5": 2,
        "book_ask_sum_5": 3,
        "imbalance_5": -0.2,
    }


@pytest.mark.parametrize(
    "value",
    (
        datetime(1, 1, 1, tzinfo=timezone(timedelta(hours=23, minutes=59))),
        datetime(9999, 12, 31, 23, 59, 59, tzinfo=timezone(-timedelta(hours=23, minutes=59))),
    ),
)
def test_provider_datetime_rejects_utc_normalization_overflow(value: datetime) -> None:
    assert parse_provider_timestamp(value) is None


def test_coinapi_wsds_normalizes_only_to_raw_quarantine_without_receipt() -> None:
    normalized = normalize_wsds_snapshot(
        symbol="BTCUSDT",
        snapshot=_valid_snapshot(),
        timeframes=("1m",),
    )

    assert normalized["quarantine_key"] == (
        "v2:quarantine:coinapi:wsds:raw:v4:BINANCEFTS_PERP_BTC_USDT:BTCUSDT"
    )
    assert "microfeat_payloads" not in normalized
    assert "market_key" not in normalized
    payload = normalized["quarantine_payload"]
    assert set(payload) == WSDS_RAW_QUARANTINE_FIELDS
    assert payload["schema_version"] == "v2_coinapi_wsds_raw_quarantine_v3"
    assert payload["provider_identity_schema_version"] == PROVIDER_IDENTITY_SCHEMA_VERSION
    assert payload["coinapi_symbol_id"] == "BINANCEFTS_PERP_BTC_USDT"
    assert payload["coinapi_exchange_id"] == "BINANCEFTS"
    assert payload["coinapi_market_type"] == "PERP"
    assert payload["source_event_time"] == "2026-07-20T12:00:00.0000001Z"
    assert payload["source_event_ts_ns"] == 1_784_548_800_000_000_100
    assert payload["provider_received_time"] == "2026-07-20T12:00:00.0000002Z"
    assert payload["observed_at"] == "2026-07-20T12:00:00.000001Z"
    assert payload["ingested_at"] == "2026-07-20T12:00:00.000002Z"
    assert payload["generated_at"] == "2026-07-20T12:00:00.000003Z"
    assert payload["spread_bps"] == 10_000.0 / 100.5
    assert "spread" not in payload
    assert payload["available_at"] is None
    assert payload["feature_cutoff"] is None
    assert payload["postcommit_receipt_present"] is False
    assert payload["feature_eligible"] is False
    assert payload["trainer_consumable"] is False
    assert payload["prediction_eligible"] is False
    assert payload["quarantine_only"] is True
    assert payload["optional_enrichment"] is True
    assert payload["required_for_trainer_admission"] is False
    assert payload["system_availability_blocking"] is False
    assert payload["absence_blocks_trainer"] is False


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("source_event_time", None, "source_event_time must be"),
        ("provider_received_time", None, "provider_received_time must be"),
        ("available_at", "2026-07-20T12:00:01Z", "available_at must remain null"),
        ("best_bid_px", True, "best_bid_px is required"),
        ("best_bid_px", 10**400, "best_bid_px is required"),
        ("best_ask_sz", False, "best_ask_sz is required"),
        ("book_bid_sum_5", math.inf, "book_bid_sum_5 is required"),
        ("spread_bps", math.nan, "spread_bps must be finite"),
    ],
)
def test_coinapi_wsds_normalizer_rejects_dirty_fields(
    field: str,
    value: object,
    match: str,
) -> None:
    snapshot = _valid_snapshot()
    snapshot[field] = value

    with pytest.raises(ValueError, match=match):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=snapshot)


def test_coinapi_wsds_normalizer_requires_strict_distinct_local_clocks() -> None:
    equal_local = _valid_snapshot()
    equal_local["ingested_at"] = equal_local["observed_at"]
    inverted_provider = _valid_snapshot()
    inverted_provider["provider_received_time"] = "2026-07-20T11:59:59Z"

    with pytest.raises(ValueError, match="observed < ingested < generated"):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=equal_local)
    with pytest.raises(ValueError, match="source_event <= provider_received"):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=inverted_provider)


def test_coinapi_wsds_normalizer_rejects_mismatched_exact_event_identities() -> None:
    mismatched_ns = _valid_snapshot()
    mismatched_ns["source_event_ts_ns"] = 1_784_548_800_000_000_101
    mismatched_ms = _valid_snapshot()
    mismatched_ms["source_event_ts_ms"] = 1_784_548_800_001
    boolean_ns = _valid_snapshot()
    boolean_ns["source_event_ts_ns"] = True

    with pytest.raises(ValueError, match="source_event_ts_ns does not match"):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=mismatched_ns)
    with pytest.raises(ValueError, match="source_event_ts_ms does not match"):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=mismatched_ms)
    with pytest.raises(ValueError, match="exact nonnegative integer"):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=boolean_ns)


def test_coinapi_wsds_normalizer_preserves_authenticated_zero_depth_as_zero() -> None:
    snapshot = _valid_snapshot()
    snapshot.update(
        {
            "best_bid_sz": 0,
            "best_ask_sz": 0,
            "book_bid_sum_5": 0,
            "book_ask_sum_5": 0,
            "microprice": None,
            "imbalance_5": None,
        }
    )

    market = normalize_wsds_snapshot(
        symbol="BTCUSDT",
        snapshot=snapshot,
        timeframes=("1m",),
    )["quarantine_payload"]

    assert market["best_bid_sz"] == 0.0
    assert market["best_ask_sz"] == 0.0
    assert market["book_bid_sum_5"] == 0.0
    assert market["book_ask_sum_5"] == 0.0
    assert market["microprice"] is None
    assert market["imbalance_5"] is None


@pytest.mark.parametrize(
    "symbol",
    ("btcusdt", " BTCUSDT", "BTC:EVILUSDT", "BTCUSD", "BTC_USDT"),
)
def test_coinapi_wsds_normalizer_rejects_noncanonical_symbol(symbol: str) -> None:
    with pytest.raises(ValueError, match="uppercase"):
        normalize_wsds_snapshot(symbol=symbol, snapshot=_valid_snapshot())


def test_coinapi_wsds_normalizer_rejects_unapproved_timeframe() -> None:
    with pytest.raises(ValueError, match="approved"):
        normalize_wsds_snapshot(
            symbol="BTCUSDT",
            snapshot=_valid_snapshot(),
            timeframes=("1m:evil",),
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("coinapi_symbol_id", "COINBASE_SPOT_BTC_USDT"),
        ("coinapi_symbol_id", "BINANCEFTS_PERP_ETH_USDT"),
        ("coinapi_exchange_id", "COINBASE"),
        ("coinapi_market_type", "SPOT"),
    ],
)
def test_coinapi_wsds_normalizer_rejects_mismatched_provider_identity(
    field: str,
    value: object,
) -> None:
    snapshot = _valid_snapshot()
    snapshot[field] = value

    with pytest.raises(ValueError, match="provider identity"):
        normalize_wsds_snapshot(symbol="BTCUSDT", snapshot=snapshot)


def test_coinapi_wsds_status_declares_cold_bootstrap_namespace_migration() -> None:
    status = build_coinapi_wsds_status(
        credential_env_present=True,
        operator_paid_streaming_approved=True,
    )

    assert status["provider_identity_schema_version"] == PROVIDER_IDENTITY_SCHEMA_VERSION
    assert status["quarantine_namespace_version"] == "v4"
    assert status["legacy_namespace_reads_enabled"] is False
    assert status["legacy_namespace_migration_mode"] == "COLD_BOOTSTRAP_REQUIRED"
