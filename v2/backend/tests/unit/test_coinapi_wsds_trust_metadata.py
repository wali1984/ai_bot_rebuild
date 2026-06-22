from __future__ import annotations

from app.services.native_ingestors.coinapi_wsds import normalize_wsds_snapshot


def test_coinapi_wsds_microfeat_payloads_include_trust_timestamps() -> None:
    normalized = normalize_wsds_snapshot(
        symbol="BTCUSDT",
        snapshot={"updated_ts_ms": 1_700_000_000_000, "best_bid_px": 100, "best_ask_px": 101},
        timeframes=("1m",),
    )

    payload = normalized["microfeat_payloads"]["v2:features:microfeat:BTCUSDT:1m"]

    assert payload["source_event_time"] == 1_700_000_000_000
    assert payload["available_at"] == 1_700_000_000_000
    assert payload["feature_cutoff"] == 1_700_000_000_000
    assert payload["generated_at"] == 1_700_000_000_000
    assert payload["feature_eligible"] is True
    assert payload["trainer_consumable"] is False
    assert payload["prediction_eligible"] is False
    assert payload["trust_block_reasons"] == []


def test_coinapi_wsds_microfeat_without_timestamp_is_ineligible() -> None:
    normalized = normalize_wsds_snapshot(
        symbol="BTCUSDT",
        snapshot={"best_bid_px": 100, "best_ask_px": 101},
        timeframes=("1m",),
    )

    payload = normalized["microfeat_payloads"]["v2:features:microfeat:BTCUSDT:1m"]

    assert payload["available_at"] is None
    assert payload["feature_cutoff"] is None
    assert payload["feature_eligible"] is False
    assert payload["trainer_consumable"] is False
    assert payload["prediction_eligible"] is False
    assert payload["trust_block_reasons"] == ["MISSING_TRUST_TIMESTAMPS"]
