"""Strategy supply engine invariants: USD-primary, honest rejections, no approval."""

from __future__ import annotations

import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.strategy_supply.edge_hypothesis_generator import (
    generate_hypotheses,
)


class FakeRedis:
    def __init__(self, data: dict[str, dict]) -> None:
        self._data = {k: json.dumps(v) for k, v in data.items()}
        self.read_keys: list[str] = []

    def get(self, key: str):
        self.read_keys.append(key)
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value


def _utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )


def _closed_ta_payload(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
) -> dict[str, object]:
    now = datetime.now(UTC)
    cutoff = now - timedelta(minutes=1)
    generated = now - timedelta(seconds=3)
    available = now - timedelta(seconds=2)
    return {
        "schema_version": "v2_full_talib_ta_closed_candidate_v1",
        "symbol": symbol,
        "timeframe": timeframe,
        "candle_closed_confirmed": True,
        "feature_cutoff": _utc(cutoff),
        "generated_at": _utc(generated),
        "available_at": _utc(available),
        "last_closed_candle_open_ts_ms": int(
            (cutoff - timedelta(minutes=1)).timestamp() * 1000
        ),
        "last_closed_candle_close_ts_ms": int(cutoff.timestamp() * 1000),
        "indicators": {"rsi_14": 50.0, "ta_NATR": 0.4},
    }


def _base_keys(symbol: str = "BTCUSDT") -> dict[str, dict]:
    return {
        f"v2:orderbook:top:binance:{symbol}": {
            "best_bid": 60000.0, "best_ask": 60006.0,
            "event_time": "2026-07-09T05:00:00Z",
        },
        f"v2:features:latest:{symbol}:1m": {"features": {"atr_bps": 40.0}, "atr_bps": 40.0},
        f"v2:features:ta_closed:{symbol}:1m": _closed_ta_payload(symbol=symbol),
        f"v2:features:coinglass:{symbol}:1m": _coinglass_v2_payload(symbol=symbol),
        f"v2:microstructure:trust_score:{symbol}:1m": {
            "composite_microstructure_trust_score": 0.74,
            "microstructure_trust_score": 0.74,
            "public_orderbook_trust_score": 0.74,
            "trade_tape_confirmation_score": 0.71,
            "available_at": "2026-07-09T05:59:00Z",
            "generated_at": "2026-07-09T05:59:00Z",
        },
        f"v2:liquidations:levels:{symbol}:1m": {
            "liquidation_is_stale": 0,
            "liquidation_levels_count_long": 3,
            "liquidation_levels_count_short": 2,
            "liquidation_cascade_risk": 0.12,
        },
    }


def _coinglass_v2_payload(
    *,
    symbol: str = "BTCUSDT",
    available_at: datetime | None = None,
) -> dict:
    available = available_at or (datetime.now(UTC) - timedelta(seconds=2))
    generated = available + timedelta(seconds=1)
    cutoff = available - timedelta(seconds=30)

    return {
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "provider": "coinglass",
        "symbol": symbol,
        "timeframe": "1m",
        "feature_cutoff": _utc(cutoff),
        "available_at": _utc(available),
        "generated_at": _utc(generated),
        "actual_payload_present": True,
        "provider_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "features": {
            "coinglass_long_ratio": 0.72,
            "coinglass_long_short_extreme_score": 0.8,
        },
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }


def _priced_keys() -> dict[str, dict]:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {
            "lastPrice": "60000",
            "bidPrice": "59997",
            "askPrice": "60003",
            "closeTime": 4102444800000,
        },
    }
    return keys


def _assert_no_gate_clean_positive(rows: list[dict[str, object]]) -> None:
    assert not [
        row
        for row in rows
        if row.get("side")
        and row.get("reason_if_rejected") in (None, "")
        and isinstance(row.get("expected_net_pnl_usd"), int | float)
        and float(row["expected_net_pnl_usd"]) > 0.0
    ]


def test_price_missing_yields_exact_reason():
    rows = generate_hypotheses(FakeRedis({}), "GHOSTUSDT", "1m")
    assert len(rows) == 1
    assert rows[0]["why_rejected"].startswith("PRICE_MISSING:")
    assert rows[0]["reason_if_rejected"].startswith("PRICE_MISSING:")
    assert rows[0]["expected_net_pnl_usd"] is None
    assert rows[0]["hypothesis_id"].startswith("hyp_")
    assert rows[0]["feature_vector_hash"].startswith("strategy_supply_")
    assert rows[0]["places_real_order"] is False


def test_price_missing_precedes_missing_closed_ta_evidence() -> None:
    rows = generate_hypotheses(FakeRedis({}), "GHOSTUSDT", "1m")

    assert rows[0]["reason_if_rejected"].startswith("PRICE_MISSING:")
    assert rows[0]["reason_if_rejected"] != "TA_CLOSED_SOURCE_MISSING"


def test_live_only_future_ta_never_falls_back_into_gate_clean_supply() -> None:
    keys = _priced_keys()
    keys.pop("v2:features:ta_closed:BTCUSDT:1m")
    keys["v2:features:ta:BTCUSDT:1m"] = {
        "schema_version": "v2_full_talib_ta_candidate_v1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "candle_closed_confirmed": False,
        "feature_cutoff": "2099-01-01T00:00:00Z",
        "generated_at": "2099-01-01T00:00:01Z",
        "available_at": "2099-01-01T00:00:02Z",
        "indicators": {"rsi_14": 20.0},
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert len(rows) == 1
    assert rows[0]["reason_if_rejected"] == "TA_CLOSED_SOURCE_MISSING"
    assert rows[0]["feature_point_in_time_evidence_valid"] is False
    assert rows[0]["candle_closed_confirmed"] is False
    assert rows[0]["ta_source_key"] == "v2:features:ta_closed:BTCUSDT:1m"
    _assert_no_gate_clean_positive(rows)


@pytest.mark.parametrize(
    ("mutation", "expected_reason"),
    [
        ("future_cutoff", "TA_CLOSED_CLOCK_ORDER_INVALID"),
        ("future_generated", "TA_CLOSED_CLOCK_ORDER_INVALID"),
        ("future_available", "TA_CLOSED_CLOCK_ORDER_INVALID"),
        ("available_before_generated", "TA_CLOSED_CLOCK_ORDER_INVALID"),
        ("symbol_mismatch", "TA_CLOSED_SYMBOL_MISMATCH"),
        ("timeframe_mismatch", "TA_CLOSED_TIMEFRAME_MISMATCH"),
        ("schema_mismatch", "TA_CLOSED_SCHEMA_INVALID"),
        ("finality_missing", "TA_CLOSED_FINALITY_UNPROVEN"),
        ("cutoff_missing", "TA_CLOSED_CLOCK_MISSING_OR_INVALID"),
        ("generated_missing", "TA_CLOSED_CLOCK_MISSING_OR_INVALID"),
        ("available_missing", "TA_CLOSED_CLOCK_MISSING_OR_INVALID"),
        ("close_time_missing", "TA_CLOSED_FINALITY_CLOCK_MISSING_OR_INVALID"),
        ("close_after_cutoff", "TA_CLOSED_CLOSE_AFTER_FEATURE_CUTOFF"),
    ],
)
def test_closed_ta_contract_tampering_never_becomes_gate_clean(
    mutation: str,
    expected_reason: str,
) -> None:
    keys = _priced_keys()
    key = "v2:features:ta_closed:BTCUSDT:1m"
    payload = dict(keys[key])
    future = _utc(datetime.now(UTC) + timedelta(hours=1))
    if mutation == "future_cutoff":
        payload["feature_cutoff"] = future
    elif mutation == "future_generated":
        payload["generated_at"] = future
    elif mutation == "future_available":
        payload["available_at"] = future
    elif mutation == "available_before_generated":
        payload["available_at"] = _utc(
            datetime.now(UTC) - timedelta(minutes=2)
        )
    elif mutation == "symbol_mismatch":
        payload["symbol"] = "ETHUSDT"
    elif mutation == "timeframe_mismatch":
        payload["timeframe"] = "5m"
    elif mutation == "schema_mismatch":
        payload["schema_version"] = "v2_full_talib_ta_closed_candidate_v0"
    elif mutation == "finality_missing":
        payload.pop("candle_closed_confirmed")
    elif mutation == "cutoff_missing":
        payload.pop("feature_cutoff")
    elif mutation == "generated_missing":
        payload.pop("generated_at")
    elif mutation == "available_missing":
        payload.pop("available_at")
    elif mutation == "close_time_missing":
        payload.pop("last_closed_candle_close_ts_ms")
    elif mutation == "close_after_cutoff":
        payload["last_closed_candle_close_ts_ms"] = int(
            (datetime.now(UTC) + timedelta(hours=1)).timestamp() * 1000
        )
    else:  # pragma: no cover - parameter table exhaustiveness
        raise AssertionError(mutation)
    keys[key] = payload

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert len(rows) == 1
    assert rows[0]["reason_if_rejected"] == expected_reason
    assert rows[0]["feature_point_in_time_evidence_valid"] is False
    assert rows[0]["side"] is None
    _assert_no_gate_clean_positive(rows)


def test_valid_closed_ta_preserves_exact_source_clocks_and_finality() -> None:
    keys = _priced_keys()
    source = keys["v2:features:ta_closed:BTCUSDT:1m"]

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    for row in directional:
        assert row["feature_point_in_time_evidence_valid"] is True
        assert row["feature_point_in_time_rejection_reason"] is None
        assert row["latest_unclosed_kline_excluded"] is True
        assert row["latest_unclosed_exclusion_method"] == "CONFIRMED_CLOSED_TA_SOURCE_KEY"
        assert row["candle_closed_confirmed"] is True
        assert row["entry_feature_candle_closed_confirmed"] is True
        assert datetime.fromisoformat(
            row["feature_cutoff"].replace("Z", "+00:00")
        ) == datetime.fromisoformat(
            str(source["feature_cutoff"]).replace("Z", "+00:00")
        )
        assert datetime.fromisoformat(
            row["source_generated_at"].replace("Z", "+00:00")
        ) == datetime.fromisoformat(
            str(source["generated_at"]).replace("Z", "+00:00")
        )
        assert datetime.fromisoformat(
            row["source_available_at"].replace("Z", "+00:00")
        ) == datetime.fromisoformat(
            str(source["available_at"]).replace("Z", "+00:00")
        )
        assert row["last_closed_candle_close_ts_ms"] == source[
            "last_closed_candle_close_ts_ms"
        ]


def test_atr_missing_yields_exact_reason():
    keys = _base_keys()
    keys.pop("v2:features:latest:BTCUSDT:1m")
    del keys["v2:features:ta_closed:BTCUSDT:1m"]["indicators"]["ta_NATR"]
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    assert rows[0]["why_rejected"] == "ATR_NOISE_MISSING_NO_STOP_BASIS"


def test_funding_squeeze_hypothesis_generated_with_usd_economics():
    # Note: orderbook staleness depends on wall-clock; use rest fallback keys too.
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    families = {r["strategy_family"] for r in rows}
    assert "funding_squeeze" in families or "long_short_imbalance_squeeze" in families
    for row in rows:
        if row.get("side") is None:
            continue
        assert row["expected_net_pnl_usd"] is not None
        assert row["expected_max_loss_usd"] > 0
        assert row["hypothesis_id"] == row["strategy_id"]
        assert row["strategy_subtype"]
        assert row["feature_vector_hash"].startswith("strategy_supply_")
        assert row["feature_cutoff"] <= row["decision_time"]
        assert row["available_at"] <= row["decision_time"]
        assert isinstance(row["provider_feature_hashes"], dict)
        assert row["current_price"] == 60000.0
        assert row["reason_if_rejected"] == row["why_rejected"]
        assert row["places_real_order"] is False
        assert row["routes_to_live"] is False
        assert row["counts_as_a_plus"] is False
        assert row["confidence_calibrated"] == round(1.0 - row["loss_probability"], 6)
        assert row["loss_probability_calibration"]["allocator_grade_microstructure_required"] == 70.0
        assert row["approves_trade_alone"] is False
        assert "allocator" in row["must_pass_gates"]
        # extreme positive funding => squeeze is short-side
        if row["strategy_family"] == "funding_squeeze":
            assert row["side"] == "short"
            assert row["expected_move_bps"] < 0
            assert row["expected_move_after_cost_bps"] < 0
            assert row["expected_short_net_edge_bps"] > 0
            assert row["short_expected_net_pnl_usd"] == row["expected_net_pnl_usd"]
            assert row["expected_long_net_edge_bps"] is None


def test_unverified_moralis_envelope_cannot_create_paper_hypothesis() -> None:
    keys = _base_keys()
    keys.pop("v2:features:coinglass:BTCUSDT:1m")
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {
            "lastPrice": "60000",
            "bidPrice": "59997",
            "askPrice": "60003",
            "closeTime": 4102444800000,
        },
    }
    # Self-declared authority is not an authenticated consumer receipt.  This
    # payload deliberately satisfies every legacy boolean so the test proves
    # strategy supply uses the receipt-gated loader rather than raw Redis.
    keys["v2:features:moralis:BTCUSDT:1m"] = {
        "schema_version": "moralis_feature_bridge_v1",
        "provider": "moralis",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "feature_cutoff": "2026-07-09T05:58:00Z",
        "available_at": "2026-07-09T05:59:00Z",
        "generated_at": "2026-07-09T05:59:00Z",
        "actual_payload_present": True,
        "provider_ready": True,
        "feature_bridge_ready": True,
        "decision_time_safe": True,
        "temporal_contract_valid": True,
        "source_temporal_contract_valid": True,
        "trainer_isolation_active": False,
        "trainer_consumption_prerequisites_bound": True,
        "consumer_receipts_bound": True,
        "features": {
            "moralis_smart_wallet_accumulation_score": 1.0,
            "moralis_smart_wallet_distribution_score": 1.0,
            "moralis_net_exchange_flow_usd": 100_000_000.0,
        },
        "missing_feature_flags": [],
        "stale_feature_flags": [],
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert {row.get("strategy_family") for row in rows}.isdisjoint(
        {
            "smart_money_accumulation",
            "smart_money_distribution",
            "exchange_inflow_risk",
        }
    )
    assert all("moralis" not in row["provider_features_used"] for row in rows)
    assert all("moralis" not in row["provider_feature_hashes"] for row in rows)
    assert all(row.get("moralis_context") is not True for row in rows)


def test_current_v1_coinglass_payload_cannot_create_paper_hypothesis() -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {
            "lastPrice": "60000",
            "bidPrice": "59997",
            "askPrice": "60003",
            "closeTime": 4102444800000,
        },
    }
    payload = _coinglass_v2_payload()
    payload["schema_version"] = "coinglass_aggregated_feature_payload_v1"
    keys["v2:features:coinglass:BTCUSDT:1m"] = payload

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert "long_short_imbalance_squeeze" not in {
        row.get("strategy_family") for row in rows
    }
    assert all("coinglass" not in row["provider_features_used"] for row in rows)
    assert all("coinglass" not in row["provider_feature_hashes"] for row in rows)


def test_stale_coinglass_v2_payload_is_optional_missing() -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    keys["v2:features:coinglass:BTCUSDT:1m"] = _coinglass_v2_payload(
        available_at=datetime.now(UTC) - timedelta(minutes=10)
    )

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert "long_short_imbalance_squeeze" not in {
        row.get("strategy_family") for row in rows
    }
    assert all(row.get("coinglass_context") is not True for row in rows)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("decision_time_safe", 1),
        ("provider_ready", "true"),
        ("symbol", "btcusdt"),
        ("features", {"coinglass_long_short_extreme_score": float("nan")}),
    ],
)
def test_adversarial_coinglass_v2_payload_is_rejected(
    field: str,
    value: object,
) -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    payload = _coinglass_v2_payload()
    payload[field] = value
    keys["v2:features:coinglass:BTCUSDT:1m"] = payload

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert "long_short_imbalance_squeeze" not in {
        row.get("strategy_family") for row in rows
    }
    assert all(row.get("coinglass_context") is not True for row in rows)


def test_fresh_valid_coinglass_v2_payload_flows_to_strategy_supply() -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {
            "lastPrice": "60000",
            "bidPrice": "59997",
            "askPrice": "60003",
            "closeTime": 4102444800000,
        },
    }
    keys["v2:features:coinglass:BTCUSDT:1m"] = _coinglass_v2_payload()

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    squeeze = next(
        row
        for row in rows
        if row.get("strategy_family") == "long_short_imbalance_squeeze"
    )

    assert squeeze["side"] == "short"
    assert squeeze["coinglass_context"] is True
    assert "coinglass" in squeeze["provider_features_used"]
    assert "coinglass" in squeeze["provider_feature_hashes"]


def test_forged_cached_confluence_cannot_create_strategy_hypothesis() -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {
            "lastPrice": "60000",
            "bidPrice": "59997",
            "askPrice": "60003",
            "closeTime": 4102444800000,
        },
    }
    keys["v2:altdata:confluence:BTCUSDT:1m"] = {
        "schema_version": "altdata_confluence_v1",
        "symbol": "BTCUSDT",
        "timeframe": "1m",
        "actual_payload_present": True,
        "decision_time_safe": True,
        "features": {"altdata_social_euphoria_risk_score": 1.0},
    }
    client = FakeRedis(keys)

    rows = generate_hypotheses(client, "BTCUSDT", "1m")

    assert "v2:altdata:confluence:BTCUSDT:1m" not in client.read_keys
    assert "social_euphoria_fade" not in {
        row.get("strategy_family") for row in rows
    }
    assert all(
        row.get("altdata_context") is not True
        or row.get("strategy_family") != "social_euphoria_fade"
        for row in rows
    )


def test_strategy_supply_caps_reference_notional_to_live_risk_profile() -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:live_gate:state"] = {
        "live_gate": "blocked_human_only",
        "risk_profile": {
            "fields": {
                "max_notional_per_trade": 64.86,
                "max_symbol_exposure": 80.0,
            }
        },
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(row["reference_notional_usd"] == 64.86 for row in directional)
    assert all(row["reference_notional_source"] == "live_gate_risk_profile_notional_cap" for row in directional)
    assert all(row["expected_gross_pnl_usd"] < 200.0 for row in directional)


def test_strategy_supply_uses_existing_microstructure_trust_key():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:microstructure:trust_score:BTCUSDT:1m"] = {
        "composite_microstructure_trust_score": 0.74,
        "trade_tape_confirmation_score": 0.71,
        "available_at": "2026-07-09T05:59:00Z",
        "generated_at": "2026-07-09T05:59:00Z",
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]
    assert directional
    assert all(row["microstructure_trust_score"] == 0.74 for row in directional)
    assert all(row["composite_microstructure_trust_score"] == 0.74 for row in directional)
    assert all(row["market_state_integrity_score"] == 74.0 for row in directional)
    assert all(row["market_state_integrity_minimum_score"] == 70.0 for row in directional)
    assert all(row["trade_tape_confirmation_score"] == 0.71 for row in directional)
    assert all(row["microstructure_trust_source"] == "v2:microstructure:trust_score:BTCUSDT:1m" for row in directional)


def test_strategy_supply_emits_regime_liquidation_context_and_buffer_proxy():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:liquidations:levels:BTCUSDT:1m"] = {
        "liquidation_is_stale": 0,
        "liquidation_levels_count_long": 3,
        "liquidation_levels_count_short": 2,
        "liquidation_cascade_risk": 0.12,
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(row["strategy_market_regime"] for row in directional)
    assert all(row["market_regime_at_entry"] == row["strategy_market_regime"] for row in directional)
    assert all(row["coinank_context"] for row in directional)
    assert all(row["coinank_context_missing_reason"] is None for row in directional)
    assert all(row["expected_liquidation_buffer_usd"] > 0 for row in directional)
    assert all(row["liquidation_buffer_signed_read_verified"] is False for row in directional)
    assert all(row["live_liquidation_buffer_requires_signed_read"] is True for row in directional)
    assert all(row["liquidation_buffer_source"] == "paper_strategy_stop_distance_proxy_not_signed_cross_margin" for row in directional)


def test_strategy_supply_accepts_fresh_no_event_liquidation_context():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:liquidations:levels:BTCUSDT:1m"] = {
        "liquidation_is_stale": 1,
        "liquidation_no_events": 1,
        "liquidation_levels_json": json.dumps({"no_events_reason": "no_liquidation_events_in_window"}),
        "liquidation_updated_ts": int(time.time() * 1000),
        "liquidation_current_price": 60000.0,
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(row["coinank_context"] for row in directional)
    assert all(row["coinank_context_missing_reason"] is None for row in directional)
    assert {
        row["coinank_context"].get("liquidation_context_status") for row in directional
    } == {"FRESH_NO_LIQUIDATION_EVENTS_IN_WINDOW"}


def test_strategy_supply_rejects_expired_no_event_liquidation_context():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:liquidations:levels:BTCUSDT:1m"] = {
        "liquidation_is_stale": 1,
        "liquidation_no_events": 1,
        "liquidation_levels_json": json.dumps({"no_events_reason": "no_liquidation_events_in_window"}),
        "liquidation_updated_ts": int(time.time() * 1000) - 3_600_000,
        "liquidation_current_price": 60000.0,
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(
        row["coinank_context_missing_reason"] == "LIQUIDATION_CONTEXT_STALE_NO_EVENTS_OBSERVATION_EXPIRED"
        for row in directional
    )


def test_strategy_supply_accepts_recent_recomputed_aged_levels_when_sweep_passed():
    now_ms = int(time.time() * 1000)
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:microstructure:trust_score:BTCUSDT:1m"].update({
        "liquidation_sweep_risk_acceptable": True,
    })
    keys["v2:liquidations:levels:BTCUSDT:1m"] = {
        "liquidation_is_stale": 1,
        "liquidation_no_events": 0,
        "liquidation_updated_ts": now_ms,
        "liquidation_last_event_ts": now_ms - 3_600_000,
        "liquidation_staleness_ms": 3_600_000,
        "liquidation_current_price": 60000.0,
        "liquidation_levels_count_long": 1,
        "liquidation_levels_count_short": 1,
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(row["coinank_context"] for row in directional)
    assert {
        row["coinank_context"].get("liquidation_context_status") for row in directional
    } == {"FRESHLY_RECOMPUTED_AGED_LEVELS_SWEEP_ACCEPTED"}


def test_strategy_supply_rejects_aged_levels_when_sweep_detector_did_not_accept():
    now_ms = int(time.time() * 1000)
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:microstructure:trust_score:BTCUSDT:1m"].update({
        "liquidation_sweep_risk_acceptable": False,
    })
    keys["v2:liquidations:levels:BTCUSDT:1m"] = {
        "liquidation_is_stale": 1,
        "liquidation_no_events": 0,
        "liquidation_updated_ts": now_ms,
        "liquidation_last_event_ts": now_ms - 3_600_000,
        "liquidation_staleness_ms": 3_600_000,
        "liquidation_current_price": 60000.0,
        "liquidation_levels_count_long": 1,
        "liquidation_levels_count_short": 1,
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(
        row["coinank_context_missing_reason"] == "LIQUIDATION_CONTEXT_STALE_SWEEP_DETECTOR_NOT_ACCEPTED"
        for row in directional
    )


def test_strategy_supply_derives_trust_from_top_book_and_trade_tape_when_explicit_absent():
    keys = _base_keys()
    keys.pop("v2:microstructure:trust_score:BTCUSDT:1m")
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:orderbook:top:binance:BTCUSDT"].update({
        "best_bid_size": 0.20,
        "best_ask_size": 0.19,
    })
    keys["v2:market:trade_tape_features:BTCUSDT"] = {
        "trade_imbalance": 0.64,
        "trade_tape_confirmation_score": 0.82,
        "available_at": "2026-07-09T05:59:00Z",
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]
    assert directional
    assert all(row["microstructure_trust_score"] is not None for row in directional)
    assert all(row["orderbook_depth_usd"] is not None and row["orderbook_depth_usd"] > 0 for row in directional)
    assert all(row["trade_tape_confirmation_score"] == 0.82 for row in directional)


def test_strategy_supply_rejects_low_microstructure_trust_before_positive_supply():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:microstructure:trust_score:BTCUSDT:1m"] = {
        "composite_microstructure_trust_score": 0.59,
        "trade_tape_confirmation_score": 0.75,
        "available_at": "2026-07-09T05:59:00Z",
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(
        row["why_rejected"] == "MICROSTRUCTURE_TRUST_BELOW_ALLOCATOR_MINIMUM"
        for row in directional
    )
    assert all(row["expected_net_pnl_usd"] is not None for row in directional)


def test_strategy_supply_lifts_capped_trust_only_with_execution_grade_evidence():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    keys["v2:microstructure:trust_score:BTCUSDT:1m"] = {
        "composite_microstructure_trust_score": 0.59,
        "microstructure_trust_score": 0.59,
        "public_orderbook_trust_score": 0.51,
        "cross_venue_confirmation_score": 0.62,
        "real_spread_depth_cost_evidence_pass": True,
        "trade_tape_confirmation_pass": True,
        "trade_tape_confirmation_score": 0.70,
        "source_availability": {"direct_binance_or_kucoin": True},
        "direct_orderbook_sources": ["binance", "kucoin"],
        "usable_source_exchanges": ["binance", "kucoin"],
        "feed_quality_fail_closed": False,
        "available_at": "2026-07-09T05:59:00Z",
        "generated_at": "2026-07-09T05:59:00Z",
    }
    keys["v2:orderbook:features:binance:BTCUSDT"] = {
        "best_bid": 60000.0,
        "best_ask": 60003.0,
        "best_bid_size": 5.0,
        "best_ask_size": 4.8,
        "orderbook_depth_usd": 300000.0,
        "depth_imbalance": 0.02,
        "spread_bps": 0.5,
        "source": "direct_binance",
    }

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(row["microstructure_trust_score"] >= 0.70 for row in directional)
    assert all(row["market_state_integrity_score"] >= 70.0 for row in directional)
    assert all(
        row["why_rejected"] != "MICROSTRUCTURE_TRUST_BELOW_ALLOCATOR_MINIMUM"
        for row in directional
    )


def test_negative_economics_rejected_not_hidden():
    keys = _base_keys()
    # Tiny ATR -> target cannot cover cost -> must be rejected with reason.
    keys["v2:features:latest:BTCUSDT:1m"] = {"features": {"atr_bps": 2.0}, "atr_bps": 2.0}
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [r for r in rows if r.get("side")]
    assert directional, "signals should still be evaluated"
    assert all(r["why_rejected"] is not None for r in directional)
