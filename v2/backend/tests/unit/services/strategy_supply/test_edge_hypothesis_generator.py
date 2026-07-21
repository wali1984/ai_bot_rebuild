"""Strategy supply engine invariants: USD-primary, honest rejections, no approval."""

from __future__ import annotations

import hashlib
import json
import time
from datetime import UTC, datetime, timedelta

import pytest

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


def test_mutable_price_alias_cannot_bypass_missing_canonical_window():
    keys = _base_keys()
    keys.pop("v2:market:ohlcv_closed:binance:BTCUSDT:1m")
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    client = FakeRedis(keys)

    rows = generate_hypotheses(client, "BTCUSDT", "1m")

    assert rows[0]["why_rejected"] == "PRICE_MISSING:NO_EXCHANGE_MARKET"
    assert "v2:market:prices:BTCUSDT" not in client.read_keys


def test_canonical_closed_candle_hypotheses_include_usd_economics():
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "bidPrice": "59997", "askPrice": "60003",
                         "closeTime": 4102444800000},
    }
    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    families = {r["strategy_family"] for r in rows}
    assert {"trend_continuation", "range_mean_reversion"} & families
    for row in rows:
        if row.get("side") is None:
            continue
        assert row["expected_net_pnl_usd"] is not None
        assert row["expected_max_loss_usd"] > 0
        assert row["hypothesis_id"] == row["strategy_id"]
        assert row["strategy_subtype"]
        assert row["feature_vector_hash"].startswith("strategy_supply_")
        assert row["feature_cutoff"] <= row["decision_time"]
        assert row["input_available_at"] <= row["decision_time"]
        assert row["decision_time"] <= row["generated_at"]
        assert row["available_at"] is None
        assert row["output_postcommit_readback_receipt_emitted"] is False
        assert row["output_available_at_unavailable_until_postcommit_receipt"] is True
        assert row["consumer_eligible"] is False
        assert row["trainer_consumable"] is False
        assert row["trainer_admission_granted"] is False
        assert row["ta_temporal_contract_valid"] is True
        assert isinstance(row["provider_feature_hashes"], dict)
        assert row["signal_context"] == row["strategy_subtype"]
        assert row["signal_context"] not in row["provider_features_used"]
        assert row["current_price"] == 60000.0
        assert row["reason_if_rejected"] == row["why_rejected"]
        assert row["places_real_order"] is False
        assert row["routes_to_live"] is False
        assert row["counts_as_a_plus"] is False
        assert row["confidence_calibrated"] == round(1.0 - row["loss_probability"], 6)
        assert row["loss_probability_calibration"]["allocator_grade_microstructure_required"] == 70.0
        assert row["approves_trade_alone"] is False
        assert "allocator" in row["must_pass_gates"]
        if row["side"] == "short":
            assert row["expected_short_net_edge_bps"] is not None
            assert row["short_expected_net_pnl_usd"] == row[
                "expected_net_pnl_usd"
            ]
        if row["side"] == "long":
            assert row["expected_long_net_edge_bps"] is not None
            assert row["long_expected_net_pnl_usd"] == row[
                "expected_net_pnl_usd"
            ]


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


def test_fresh_valid_but_unreceipted_coinglass_v2_payload_stays_masked() -> None:
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

    client = FakeRedis(keys)
    rows = generate_hypotheses(client, "BTCUSDT", "1m")

    assert rows
    assert "v2:features:coinglass:BTCUSDT:1m" not in client.read_keys
    assert all(row.get("coinglass_context") is not True for row in rows)
    assert all("coinglass" not in row["provider_features_used"] for row in rows)
    assert all("coinglass" not in row["provider_feature_hashes"] for row in rows)


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


def test_strategy_supply_masks_self_declared_microstructure_trust_key():
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
    assert all(
        row["why_rejected"]
        == "MICROSTRUCTURE_TRUST_EXACT_RETAINED_ARTIFACT_CONSUMER_RESOLVER_UNWIRED"
        for row in directional
    )
    assert all(row["microstructure_trust_score"] is None for row in directional)
    assert all(row["market_state_integrity_score"] is None for row in directional)
    assert all(row["trade_tape_confirmation_score"] is None for row in directional)
    assert all(row["microstructure_trust_source"] is None for row in directional)
    assert all("microstructure_trust" not in row["provider_features_used"] for row in directional)
    assert all("microstructure_trust" not in row["provider_feature_hashes"] for row in directional)
    status = directional[0]["optional_input_status"]
    assert status["boundary_state"] == "MASKED"
    assert status["retained_artifact_authenticated"] is False
    assert status["postcommit_readback_receipt_verified"] is False
    assert set(status["admitted_clocks"].values()) == {None}
    assert status["by_input"]["microstructure_trust"]["state"] == "MASKED"


@pytest.mark.parametrize(
    "liquidation_payload",
    [
        {
            "liquidation_is_stale": 0,
            "liquidation_levels_count_long": 3,
            "liquidation_levels_count_short": 2,
            "liquidation_cascade_risk": 0.12,
        },
        {
            "liquidation_is_stale": 1,
            "liquidation_no_events": 1,
            "liquidation_levels_json": json.dumps(
                {"no_events_reason": "no_liquidation_events_in_window"}
            ),
            "liquidation_updated_ts": int(time.time() * 1000),
            "liquidation_current_price": 60000.0,
        },
        {
            "liquidation_is_stale": 1,
            "liquidation_no_events": 0,
            "liquidation_updated_ts": int(time.time() * 1000),
            "liquidation_last_event_ts": int(time.time() * 1000) - 3_600_000,
            "liquidation_staleness_ms": 3_600_000,
            "liquidation_current_price": 60000.0,
            "liquidation_levels_count_long": 1,
            "liquidation_levels_count_short": 1,
        },
    ],
)
def test_unreceipted_liquidation_payload_cannot_satisfy_context_gate(
    liquidation_payload: dict,
) -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    keys["v2:microstructure:trust_score:BTCUSDT:1m"][
        "liquidation_sweep_risk_acceptable"
    ] = True
    keys["v2:liquidations:levels:BTCUSDT:1m"] = liquidation_payload

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")
    directional = [row for row in rows if row.get("side")]

    assert directional
    assert all(row["coinank_context"] is None for row in directional)
    assert all(
        row["coinank_context_missing_reason"]
        == "LIQUIDATION_LEVELS_EXACT_RETAINED_ARTIFACT_CONSUMER_RESOLVER_UNWIRED"
        for row in directional
    )
    assert all(row["liquidation_context_source"] is None for row in directional)
    assert all("liquidation_levels" not in row["provider_feature_hashes"] for row in directional)
    assert all("coinank_liquidations" not in row["provider_features_used"] for row in directional)
    assert all(row["expected_liquidation_buffer_usd"] > 0 for row in directional)
    assert all(row["liquidation_buffer_signed_read_verified"] is False for row in directional)


@pytest.mark.parametrize(
    ("key", "payload", "forbidden_family", "context_field"),
    [
        (
            "v2:market:fvg:BTCUSDT:1m",
            {"bullish_fvg_present": True},
            "fvg_retest",
            "fvg_context",
        ),
        (
            "v2:market:sweep_risk:BTCUSDT:1m",
            {"sweep_risk_long_side": 1.0},
            "liquidity_sweep_reversal",
            None,
        ),
        (
            "v2:orderbook:features:binance:BTCUSDT",
            {"depth_imbalance": 1.0, "orderbook_depth_usd": 1_000_000.0},
            "orderbook_absorption",
            "orderbook_context",
        ),
        (
            "v2:market:microstructure:BTCUSDT",
            {"tape_imbalance": 1.0, "trade_tape_confirmation_score": 1.0},
            "microstructure_momentum",
            "microstructure_context",
        ),
        (
            "v2:market:trade_tape_features:BTCUSDT",
            {"trade_imbalance": 1.0, "trade_tape_confirmation_score": 1.0},
            "microstructure_momentum",
            "trade_tape_context",
        ),
        (
            "v2:microstructure:trade_tape_confirmation:BTCUSDT",
            {"trade_imbalance": 1.0, "trade_tape_confirmation_score": 1.0},
            "microstructure_momentum",
            "trade_tape_context",
        ),
    ],
)
def test_unreceipted_optional_payload_cannot_create_strategy_family(
    key: str,
    payload: dict,
    forbidden_family: str,
    context_field: str | None,
) -> None:
    keys = _base_keys()
    keys["v2:market:prices:BTCUSDT"] = {
        "ticker_24hr": {"lastPrice": "60000", "closeTime": 4102444800000},
    }
    keys[key] = payload

    rows = generate_hypotheses(FakeRedis(keys), "BTCUSDT", "1m")

    assert forbidden_family not in {row.get("strategy_family") for row in rows}
    if context_field is not None:
        assert all(row.get(context_field) is not True for row in rows)
    optional_labels = {
        "fvg",
        "liquidity_zones",
        "liquidation_levels",
        "sweep_risk",
        "microstructure",
        "microstructure_trust",
        "orderbook",
        "orderbook_top",
        "orderbook_rest",
        "trade_tape",
        "trade_tape_confirmation",
    }
    assert all(optional_labels.isdisjoint(row["provider_feature_hashes"]) for row in rows)


def test_optional_strategy_boundary_does_not_read_raw_compatibility_keys() -> None:
    keys = _base_keys()
    candidate_keys = edge_generator._optional_raw_input_source_keys(
        "BTCUSDT",
        "1m",
    )
    for raw_key in {key for values in candidate_keys.values() for key in values}:
        keys[raw_key] = {
            "consumer_eligible": True,
            "retained_artifact_authenticated": True,
            "postcommit_readback_receipt_verified": True,
            "available_at": "2026-07-09T05:59:00Z",
            "feature_cutoff": "2026-07-09T05:58:00Z",
        }
    client = FakeRedis(keys)

    rows = generate_hypotheses(client, "BTCUSDT", "1m")

    assert rows
    raw_keys = {key for values in candidate_keys.values() for key in values}
    assert raw_keys.isdisjoint(client.read_keys)
    assert all(
        row["optional_input_status"][
            "source_payload_consumed_as_optional_strategy_evidence"
        ]
        is False
        for row in rows
    )


def test_strategy_price_and_ta_share_one_exact_closed_window_read() -> None:
    keys = _base_keys()
    poison_price_keys = {
        "v2:market:prices:BTCUSDT": {
            "mark_price": 1.0,
            "event_time": "2099-01-01T00:00:00Z",
        },
        "v2:market:mark_price:BTCUSDT": {
            "mark_price": 2.0,
            "available_at": "2099-01-01T00:00:00Z",
        },
        "v2:market:funding:BTCUSDT": {
            "markPrice": 3.0,
            "generated_at": "2099-01-01T00:00:00Z",
        },
        "v2:market:latest_trade:binance:BTCUSDT": {
            "price": 4.0,
            "event_time": "2099-01-01T00:00:00Z",
        },
        "v2:market:kline_current:binance:BTCUSDT:1m": {
            "close": 5.0,
            "close_time": "2099-01-01T00:00:00Z",
        },
        "v2:market:orderbook:binance:BTCUSDT": {
            "bids": [["6", "1"]],
            "asks": [["7", "1"]],
            "available_at": "2099-01-01T00:00:00Z",
        },
    }
    keys.update(poison_price_keys)
    client = FakeRedis(keys)
    canonical_key = "v2:market:ohlcv_closed:binance:BTCUSDT:1m"
    canonical_bytes = keys[canonical_key]
    assert isinstance(canonical_bytes, bytes)
    selected = json.loads(canonical_bytes)[-1]

    rows = generate_hypotheses(client, "BTCUSDT", "1m")

    assert rows
    assert client.read_keys.count(canonical_key) == 1
    assert set(poison_price_keys).isdisjoint(client.read_keys)
    for row in rows:
        assert row["current_price"] == float(selected["close"])
        assert row["price_source"] == (
            "canonical_closed_ohlcv_latest_selected_candle"
        )
        assert row["price_source_ohlcv_key"] == canonical_key
        assert row["price_source_exact_payload_sha256"] == hashlib.sha256(
            canonical_bytes
        ).hexdigest()
        assert row["price_selected_candle_id"] == selected["candle_id"]
        assert row["price_selected_candle_raw_payload_hash"] == selected[
            "raw_payload_hash"
        ]
        assert row["price_exact_binary_read_shared_with_ta"] is True
        assert row["price_second_source_read_performed"] is False
        assert row["price_fallback_used"] is False
        assert row["price_sizing_authority_granted"] is False
        assert row["price_available_at"] <= row["decision_time"]


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
