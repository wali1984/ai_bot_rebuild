"""Strategy supply engine invariants: USD-primary, honest rejections, no approval."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

from v2.backend.app.services.altdata import canonical_confluence_consumer
from v2.backend.app.services.market_state_integrity.canonical_candles import (
    canonical_from_binance_rest,
)
from v2.backend.app.services.native_trainer.ohlcv_closed_window_schema import (
    TIMEFRAME_DURATION_MS,
)
from v2.backend.app.services.strategy_supply import causal_native_ta
from v2.backend.app.services.strategy_supply import (
    edge_hypothesis_generator as edge_generator,
)
from v2.backend.app.services.strategy_supply.causal_native_ta import (
    load_causal_native_ta,
)
from v2.backend.app.services.strategy_supply.edge_hypothesis_generator import (
    generate_hypotheses,
)

_FROZEN_NATIVE_TA_NOW: datetime | None = None


@pytest.fixture(autouse=True)
def _freeze_native_ta_test_clock(monkeypatch: pytest.MonkeyPatch):
    """Keep ordinary fixtures deterministic across a candle-close boundary."""

    frozen = datetime.now(UTC)
    frozen_text = frozen.isoformat(timespec="microseconds").replace(
        "+00:00", "Z"
    )
    global _FROZEN_NATIVE_TA_NOW
    _FROZEN_NATIVE_TA_NOW = frozen
    monkeypatch.setattr(causal_native_ta, "_now", lambda: frozen)
    monkeypatch.setattr(
        canonical_confluence_consumer,
        "_utc_now",
        lambda: frozen,
    )
    monkeypatch.setattr(edge_generator, "_utc_now", lambda: frozen_text)
    yield
    _FROZEN_NATIVE_TA_NOW = None


class FakeRedis:
    def __init__(self, data: dict[str, object]) -> None:
        self._data = {
            key: value
            if type(value) in (bytes, str)
            else json.dumps(value)
            for key, value in data.items()
        }
        self.read_keys: list[str] = []

    def get(self, key: str):
        self.read_keys.append(key)
        return self._data.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self._data[key] = value


def _canonical_closed_ohlcv_bytes(
    *,
    symbol: str = "BTCUSDT",
    timeframe: str = "1m",
    count: int = 100,
    latest_interval_offset: int = 0,
    half_range_usd: float = 120.0,
    price_step_usd: float = 10.0,
    observed_at_ms: int | None = None,
) -> bytes:
    duration_ms = TIMEFRAME_DURATION_MS[timeframe]
    if observed_at_ms is None:
        assert _FROZEN_NATIVE_TA_NOW is not None
        now_ms = int(_FROZEN_NATIVE_TA_NOW.timestamp() * 1000)
    else:
        now_ms = observed_at_ms
    latest_close_ms = (
        (now_ms // duration_ms) * duration_ms
        - 1
        - latest_interval_offset * duration_ms
    )
    rows: list[dict] = []
    for index in range(count):
        close_time = latest_close_ms - (count - 1 - index) * duration_ms
        open_time = close_time - duration_ms + 1
        close_price = 60_000.0 - (count - 1 - index) * price_step_usd
        open_price = close_price - price_step_usd / 2.0
        high_price = max(open_price, close_price) + half_range_usd
        low_price = min(open_price, close_price) - half_range_usd
        volume = 1_000.0 + index
        quote_volume = volume * close_price
        taker_buy_volume = volume / 2.0
        source_row = [
            open_time,
            str(open_price),
            str(high_price),
            str(low_price),
            str(close_price),
            str(volume),
            close_time,
            str(quote_volume),
            100 + index,
            str(taker_buy_volume),
            str(taker_buy_volume * close_price),
            "0",
        ]
        rows.append(
            canonical_from_binance_rest(
                source_row,
                symbol=symbol,
                timeframe=timeframe,
                ingested_at=close_time + 1,
            ).to_dict()
        )
    return json.dumps(rows, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def _base_keys(symbol: str = "BTCUSDT") -> dict[str, object]:
    return {
        f"v2:orderbook:top:binance:{symbol}": {
            "best_bid": 60000.0, "best_ask": 60006.0,
            "event_time": "2026-07-09T05:00:00Z",
        },
        f"v2:market:ohlcv_closed:binance:{symbol}:1m": (
            _canonical_closed_ohlcv_bytes(symbol=symbol)
        ),
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

    def utc(value: datetime) -> str:
        return value.astimezone(UTC).isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        )

    return {
        "schema_version": "coinglass_aggregated_feature_payload_v2",
        "provider": "coinglass",
        "symbol": symbol,
        "timeframe": "1m",
        "feature_cutoff": utc(cutoff),
        "available_at": utc(available),
        "generated_at": utc(generated),
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


def test_price_missing_yields_exact_reason():
    rows = generate_hypotheses(FakeRedis({}), "GHOSTUSDT", "1m")
    assert len(rows) == 1
    assert rows[0]["why_rejected"].startswith("PRICE_MISSING:")
    assert rows[0]["reason_if_rejected"].startswith("PRICE_MISSING:")
    assert rows[0]["expected_net_pnl_usd"] is None
    assert rows[0]["hypothesis_id"].startswith("hyp_")
    assert rows[0]["feature_vector_hash"].startswith("strategy_supply_")
    assert rows[0]["places_real_order"] is False


def test_atr_missing_yields_exact_reason():
    keys = _base_keys()
    keys.pop("v2:market:ohlcv_closed:binance:BTCUSDT:1m")
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
        assert row["ta_temporal_contract_valid"] is True
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
    keys["v2:market:ohlcv_closed:binance:BTCUSDT:1m"] = (
        _canonical_closed_ohlcv_bytes(
            half_range_usd=1.0,
            price_step_usd=0.01,
        )
    )
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [r for r in rows if r.get("side")]
    assert directional, "signals should still be evaluated"
    assert all(r["why_rejected"] is not None for r in directional)


@pytest.mark.parametrize("timeframe", ("1m", "5m", "15m", "1h", "4h"))
def test_native_ta_uses_exact_current_closed_window_and_honest_clocks(
    timeframe: str,
) -> None:
    exact_bytes = _canonical_closed_ohlcv_bytes(timeframe=timeframe)
    key = f"v2:market:ohlcv_closed:binance:BTCUSDT:{timeframe}"

    payload, status = load_causal_native_ta(
        FakeRedis({key: exact_bytes}),
        symbol="BTCUSDT",
        timeframe=timeframe,
    )

    assert payload is not None
    assert status["state"] == "PRESENT"
    assert payload["source_exact_payload_sha256"] == hashlib.sha256(
        exact_bytes
    ).hexdigest()
    assert len(payload["in_process_ta_content_sha256"]) == 64
    assert payload["feature_cutoff"] <= payload["source_available_at"]
    assert payload["source_available_at"] <= payload["read_observed_at"]
    assert payload["read_observed_at"] <= payload["computed_available_at"]
    assert payload["candle_closed_confirmed"] is True
    assert payload["latest_completed_interval_verified"] is True
    assert payload["cached_ta_compatibility_consumed"] is False
    assert payload["latest_feature_snapshot_consumed"] is False
    assert payload["zero_fill_used"] is False
    assert payload["generic_consumer_eligible"] is False
    assert payload["live_execution_authorized"] is False


def test_unfinished_canonical_window_is_masked_without_zero_fill() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    rows = json.loads(_canonical_closed_ohlcv_bytes())
    rows[-1]["is_closed"] = False
    exact_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()

    payload, status = load_causal_native_ta(
        FakeRedis({key: exact_bytes}),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["state"] == "MASKED"
    assert status["rejection_reason"].endswith(
        "ohlcv_closed_finality_flags_invalid"
    )
    assert status["zero_fill_used"] is False


def test_decoded_canonical_window_is_not_reencoded_as_exact_bytes() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    decoded = _canonical_closed_ohlcv_bytes().decode("utf-8")

    payload, status = load_causal_native_ta(
        FakeRedis({key: decoded}),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"] == "EXACT_BINARY_CLOSED_OHLCV_UNAVAILABLE"


def test_native_ta_masks_window_that_becomes_stale_during_computation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    duration_ms = TIMEFRAME_DURATION_MS["1m"]
    read_observed = datetime.now(UTC)
    read_ms = int(read_observed.timestamp() * 1000)
    next_boundary_ms = ((read_ms // duration_ms) + 1) * duration_ms
    computed_after_boundary = datetime.fromtimestamp(
        (next_boundary_ms + 1) / 1000.0,
        tz=UTC,
    )
    observed_times = iter((read_observed, computed_after_boundary))
    monkeypatch.setattr(causal_native_ta, "_now", lambda: next(observed_times))
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"

    payload, status = load_causal_native_ta(
        FakeRedis(
            {
                key: _canonical_closed_ohlcv_bytes(
                    observed_at_ms=read_ms,
                )
            }
        ),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"] == (
        "CANONICAL_CLOSED_OHLCV_BECAME_STALE_DURING_COMPUTATION"
    )


def test_future_available_canonical_window_is_masked() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    rows = json.loads(_canonical_closed_ohlcv_bytes())
    future_ms = int(time.time() * 1000) + 60_000
    rows[-1]["ingested_at"] = future_ms
    rows[-1]["available_at"] = future_ms
    exact_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()

    payload, status = load_causal_native_ta(
        FakeRedis({key: exact_bytes}),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"] == (
        "CANONICAL_CLOSED_OHLCV_AVAILABLE_AFTER_READ_OBSERVATION"
    )


def test_strategy_decision_masks_ta_when_next_candle_closes_after_computation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    keys = _base_keys()
    source_bytes = keys["v2:market:ohlcv_closed:binance:BTCUSDT:1m"]
    assert isinstance(source_bytes, bytes)
    rows = json.loads(source_bytes)
    valid_before_ms = rows[-1]["candle_close_time"] + 60_001
    stale_decision = datetime.fromtimestamp(valid_before_ms / 1000.0, tz=UTC)
    monkeypatch.setattr(
        edge_generator,
        "_utc_now",
        lambda: stale_decision.isoformat(timespec="microseconds").replace(
            "+00:00", "Z"
        ),
    )

    hypotheses = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert hypotheses[0]["why_rejected"] == "ATR_NOISE_MISSING_NO_STOP_BASIS"
    assert hypotheses[0]["ta_input_state"] == "MASKED"
    assert hypotheses[0]["ta_input_rejection_reason"] == (
        "CANONICAL_CLOSED_OHLCV_STALE_AT_DECISION_TIME"
    )
    assert hypotheses[0]["ta_temporal_contract_valid"] is False


def test_malformed_canonical_window_is_masked() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    payload, status = load_causal_native_ta(
        FakeRedis({key: b'{"not":"a closed window"}'}),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"].endswith(
        "ohlcv_closed_top_level_requires_exact_list"
    )


def test_noncontiguous_calculation_suffix_is_masked() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    rows = json.loads(_canonical_closed_ohlcv_bytes())
    del rows[-10]
    exact_bytes = json.dumps(rows, sort_keys=True, separators=(",", ":")).encode()

    payload, status = load_causal_native_ta(
        FakeRedis({key: exact_bytes}),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"].endswith(
        "ohlcv_closed_required_contiguous_window_unavailable"
    )


def test_stale_canonical_window_is_masked_by_completed_interval_identity() -> None:
    key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    payload, status = load_causal_native_ta(
        FakeRedis(
            {
                key: _canonical_closed_ohlcv_bytes(
                    latest_interval_offset=1,
                )
            }
        ),
        symbol="BTCUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"] == (
        "CANONICAL_CLOSED_OHLCV_LATEST_COMPLETED_INTERVAL_MISMATCH"
    )


def test_canonical_window_identity_mismatch_is_masked() -> None:
    key = "v2:market:ohlcv_closed:binance:ETHUSDT:1m"
    payload, status = load_causal_native_ta(
        FakeRedis({key: _canonical_closed_ohlcv_bytes(symbol="BTCUSDT")}),
        symbol="ETHUSDT",
        timeframe="1m",
    )

    assert payload is None
    assert status["rejection_reason"].endswith(
        "ohlcv_closed_source_binding_invalid"
    )


def test_forged_ta_compatibility_and_latest_snapshots_are_never_read() -> None:
    keys = _base_keys()
    keys["v2:features:ta_closed:BTCUSDT:1m"] = {
        "consumer_eligible": True,
        "candle_closed_confirmed": True,
        "indicators": {"ta_NATR": 999.0, "ta_RSI": 1.0},
    }
    keys["v2:features:ta:BTCUSDT:1m"] = {
        "consumer_eligible": True,
        "indicators": {"ta_NATR": 999.0},
    }
    keys["v2:features:latest:BTCUSDT:1m"] = {
        "consumer_eligible": True,
        "atr_bps": 999_999.0,
        "features": {"atr_bps": 999_999.0},
    }
    client = FakeRedis(keys)

    rows = generate_hypotheses(client, "BTCUSDT", "1m")

    assert "v2:features:ta_closed:BTCUSDT:1m" not in client.read_keys
    assert "v2:features:ta:BTCUSDT:1m" not in client.read_keys
    assert "v2:features:latest:BTCUSDT:1m" not in client.read_keys
    assert rows
    assert all(row["ta_cached_compatibility_consumed"] is False for row in rows)
    assert all(row["latest_feature_snapshot_consumed"] is False for row in rows)
    assert all(
        row.get("ta_source_exact_payload_sha256")
        == row["provider_feature_hashes"]["canonical_closed_ohlcv_exact_bytes"]
        for row in rows
    )
