from __future__ import annotations

import json

from v2.backend.app.cli import v2_feature_pipeline_native_loop as loop


class _FakeRedis:
    def __init__(self) -> None:
        self.writes: dict[str, tuple[str, int | None]] = {}

    def set(self, key: str, value: str, ex: int | None = None) -> bool:
        self.writes[key] = (value, ex)
        return True

    def get(self, key: str) -> str | None:
        return None


def test_long_short_ratio_payload_becomes_named_features() -> None:
    features = loop._features_from_market(
        {
            "ticker_24hr": {},
            "funding": {},
            "open_interest": {},
            "_long_short": {
                "longShortRatio": "1.50",
                "longAccount": "0.60",
                "shortAccount": "0.40",
            },
        }
    )

    assert features["long_short_ratio"] == 1.5
    assert features["long_account_ratio"] == 0.6
    assert features["short_account_ratio"] == 0.4


def test_feature_pipeline_uses_latest_closed_kline_for_core_ohlc() -> None:
    closed = [1000, "10", "12", "9", "11", "100", 1999, "1100", 10, "40", "440", "0"]
    unclosed = [2000, "99", "100", "98", "99", "1", 2999, "99", 1, "0", "0", "0"]

    klines, latest = loop._closed_klines([closed, unclosed], decision_ms=2500)
    features = loop._features_from_market({"ticker_24hr": {}, "funding": {}, "_klines": klines})

    assert latest == closed
    assert features["open"] == 10.0
    assert features["high"] == 12.0
    assert features["low"] == 9.0
    assert features["close"] == 11.0
    assert features["volume"] == 100.0


def test_feature_pipeline_normalizes_explicit_market_cost_evidence() -> None:
    features = loop._features_from_market(
        {
            "ticker_24hr": {},
            "funding": {"lastFundingRate": "0.0001"},
            "fee_bps": "4.5",
            "expected_slippage_bps": "1.25",
            "_orderbook": {
                "bids": [["100", "2"], ["99", "1"]],
                "asks": [["100.2", "3"], ["101", "2"]],
            },
        }
    )

    assert round(features["actual_observed_spread_entry_bps"], 8) == 19.98001998
    assert round(features["bid_ask_spread_bps"], 8) == 19.98001998
    assert features["bid_depth_usd"] == 299.0
    assert features["ask_depth_usd"] == 502.6
    assert features["orderbook_depth_usd"] == 299.0
    assert features["fee_bps"] == 4.5
    assert features["expected_slippage_bps"] == 1.25
    assert features["expected_funding_bps"] == 1.0


def test_feature_pipeline_sources_missing_cost_fields_transparently() -> None:
    # When the market snapshot omits cost fields, the pipeline must never
    # fabricate observed data. Each field is either (a) filled from a known,
    # transparently-tagged source or (b) left None when it is genuinely absent:
    #   - fee_bps: a known configured taker fee (not market data) -> filled from
    #     the paper fee schedule with a CONFIGURED_* provenance tag.
    #   - expected_slippage_bps: MODELED from the observed orderbook spread with
    #     a MODELED_FROM_OBSERVED_* provenance tag (the orderbook is present).
    #   - expected_funding_bps: genuinely-absent market data -> stays None.
    features = loop._features_from_market(
        {
            "ticker_24hr": {},
            "funding": {},
            "_orderbook": {
                "bids": [["100", "2"]],
                "asks": [["100.2", "3"]],
            },
        }
    )

    # Observed fields still come from real orderbook data.
    assert features["actual_observed_spread_entry_bps"] is not None
    assert features["orderbook_depth_usd"] is not None

    # Known configured cost -> filled, but transparently sourced (not fabricated).
    assert features["fee_bps"] == loop._configured_fee_bps()
    assert features["_fee_bps_source"] == loop.CONFIGURED_FEE_BPS_SOURCE

    # Slippage MODELED from the present spread, with a transparent source tag.
    assert features["expected_slippage_bps"] is not None
    assert features["_expected_slippage_source"].startswith("MODELED_FROM_OBSERVED_SPREAD")

    # Funding is genuinely absent -> must NOT be fabricated.
    assert features["expected_funding_bps"] is None
    assert features.get("_expected_funding_source") is None


def test_feature_pipeline_archives_snapshot_by_exact_feature_snapshot_id(monkeypatch, tmp_path) -> None:
    fake = _FakeRedis()
    closed = [1000, "10", "12", "9", "11", "100", 1999, "1100", 10, "40", "440", "0"]

    monkeypatch.setattr(loop, "_connect_redis", lambda: fake)
    monkeypatch.setattr(loop, "_read_market", lambda _r, _symbol: {"ticker_24hr": {}})
    monkeypatch.setattr(loop, "_read_klines", lambda _r, _symbol, _timeframe: [closed])
    monkeypatch.setattr(loop, "_read_orderbook", lambda _r, _symbol: None)
    monkeypatch.setattr(loop, "_read_oi_hist", lambda _r, _symbol: None)
    monkeypatch.setattr(loop, "_read_long_short", lambda _r, _symbol: None)
    monkeypatch.setattr(
        loop,
        "_read_liq_notional_24h",
        lambda _r, _symbol, *, decision_ms=None: None,
    )
    monkeypatch.setattr(
        loop,
        "_merge_external_v2_features",
        lambda _r, _symbol, _timeframe, _features, **_kwargs: {
            "sources_present": [],
            "fields_merged": [],
            "market_structure_ohlcv_binding": None,
        },
    )
    monkeypatch.setattr(loop, "SNAPSHOT_PATH", tmp_path / "latest_feature_snapshot.json")

    status = loop.run_once(("BTCUSDT",), "1m")

    latest_key = "v2:features:latest:BTCUSDT:1m"
    assert latest_key in fake.writes
    latest_payload = json.loads(fake.writes[latest_key][0])
    snapshot_id = latest_payload["feature_snapshot_id"]
    archive_key = loop._feature_snapshot_archive_key(snapshot_id)

    assert archive_key in fake.writes
    assert fake.writes[archive_key][1] == loop.FEATURE_SNAPSHOT_ARCHIVE_TTL_SECONDS
    assert json.loads(fake.writes[archive_key][0]) == latest_payload
    assert archive_key in status["v2_features_keys_written"]
    assert archive_key.startswith("v2:features:snapshot:v2_fsnap_")
    assert all(key.startswith("v2:") for key in fake.writes)
