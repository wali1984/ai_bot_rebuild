"""Symbol-adaptive round-trip cost model tests.

Operator requirement (2026-07-17): majors (BTC/ETH/SOL) must not be blocked
by a flat 12bps round-trip cost when live orderbook evidence proves their
real cost is lower; tail symbols with wide spreads must get honestly MORE
expensive. Missing/stale evidence must fall back CONSERVATIVE (never below
the flat baseline). Paper-only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from v2.backend.app.services.paper_trade_management.adaptive_cost_model import (
    DEFAULT_TAKER_FEE_BPS_PER_SIDE,
    FLAT_BASELINE_ROUND_TRIP_BPS,
    FRESHNESS_FALLBACK_CONSERVATIVE,
    FRESHNESS_FRESH_ORDERBOOK,
    IMPACT_SOURCE_DEPTH_RATIO,
    IMPACT_SOURCE_EXCHANGE_ESTIMATE,
    SPREAD_SOURCE_LIVE_ORDERBOOK,
    SPREAD_SOURCE_MISSING,
    after_cost_for_action,
    estimate_round_trip_cost_bps,
    publish_cost_estimate,
)

NOW = datetime(2026, 7, 17, 6, 0, 0, tzinfo=timezone.utc)


def _book(
    *,
    age_seconds: float = 5.0,
    spread_bps: float = 0.016,
    estimated_price_impact_bps: float | None = 0.008,
    price_impact_notional_usd: float | None = 1000.0,
    depth_5_bid_usd: float | None = 40_000.0,
    depth_5_ask_usd: float | None = 1_000_000.0,
    depth_total_usd: float | None = 1_400_000.0,
) -> dict:
    payload = {
        "symbol": "BTCUSDT",
        "generated_at": (NOW - timedelta(seconds=age_seconds))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "spread_bps": spread_bps,
        "depth_total_usd": depth_total_usd,
        "depth_5_bid_usd": depth_5_bid_usd,
        "depth_5_ask_usd": depth_5_ask_usd,
    }
    if estimated_price_impact_bps is not None:
        payload["estimated_price_impact_bps"] = estimated_price_impact_bps
        payload["price_impact_notional_usd"] = price_impact_notional_usd
    return payload


def _getter(payload):
    return lambda key: payload


def test_fresh_major_orderbook_costs_less_than_flat_baseline() -> None:
    est = estimate_round_trip_cost_bps(
        "BTCUSDT",
        get_json=_getter(_book()),
        notional_usd=250.0,
        now_utc=NOW,
    )
    assert est.freshness_status == FRESHNESS_FRESH_ORDERBOOK
    assert est.is_fresh
    assert est.spread_source == SPREAD_SOURCE_LIVE_ORDERBOOK
    assert est.impact_source == IMPACT_SOURCE_EXCHANGE_ESTIMATE
    # 2*5 fee + 0.016 spread + 2*(0.008*250/1000) impact = 10.020 bps
    assert abs(est.round_trip_cost_bps - 10.020) < 1e-6
    assert est.round_trip_cost_bps < FLAT_BASELINE_ROUND_TRIP_BPS
    # Fees are never lowered: cost is floored above 2x per-side fee.
    assert est.round_trip_cost_bps >= 2.0 * DEFAULT_TAKER_FEE_BPS_PER_SIDE


def test_fresh_wide_spread_tail_costs_more_than_flat_baseline() -> None:
    est = estimate_round_trip_cost_bps(
        "TAILUSDT",
        get_json=_getter(
            _book(spread_bps=9.0, estimated_price_impact_bps=1.2, depth_5_bid_usd=3_000.0)
        ),
        notional_usd=250.0,
        now_utc=NOW,
    )
    assert est.is_fresh
    # 10 fee + 9 spread + 2*(1.2*0.25) = 19.6 bps: honestly ABOVE the flat 12.
    assert est.round_trip_cost_bps > FLAT_BASELINE_ROUND_TRIP_BPS
    assert abs(est.round_trip_cost_bps - 19.6) < 1e-6


def test_depth_ratio_impact_used_when_exchange_estimate_missing() -> None:
    est = estimate_round_trip_cost_bps(
        "BTCUSDT",
        get_json=_getter(
            _book(estimated_price_impact_bps=None, price_impact_notional_usd=None)
        ),
        notional_usd=250.0,
        now_utc=NOW,
    )
    assert est.is_fresh
    assert est.impact_source == IMPACT_SOURCE_DEPTH_RATIO
    # Thinner side = bid 40k; impact/side = 0.5*0.016*(250/40000)
    expected_impact = 0.5 * 0.016 * (250.0 / 40_000.0)
    assert abs((est.impact_per_side_bps or 0.0) - expected_impact) < 1e-9
    assert est.depth_used_usd == 40_000.0


def test_depth_slippage_scales_with_notional() -> None:
    small = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(_book()), notional_usd=25.0, now_utc=NOW
    )
    large = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(_book()), notional_usd=250.0, now_utc=NOW
    )
    comparable = estimate_round_trip_cost_bps(
        "BTCUSDT",
        get_json=_getter(_book()),
        notional_usd=1_000_000.0,
        now_utc=NOW,
    )
    assert (small.impact_per_side_bps or 0.0) < (large.impact_per_side_bps or 0.0)
    assert (large.impact_per_side_bps or 0.0) < (comparable.impact_per_side_bps or 0.0)
    # Near-zero when notional << depth.
    assert (small.impact_per_side_bps or 0.0) < 0.001
    # Notional comparable to book depth pays a real impact cost.
    assert comparable.round_trip_cost_bps > small.round_trip_cost_bps + 10.0


def test_stale_orderbook_falls_back_conservative_at_flat_baseline() -> None:
    est = estimate_round_trip_cost_bps(
        "BTCUSDT",
        get_json=_getter(_book(age_seconds=300.0)),
        notional_usd=250.0,
        now_utc=NOW,
    )
    assert est.freshness_status == FRESHNESS_FALLBACK_CONSERVATIVE
    assert not est.is_fresh
    assert est.round_trip_cost_bps >= FLAT_BASELINE_ROUND_TRIP_BPS
    assert est.conservative_floor_applied
    assert any(note.startswith("orderbook_stale_age_") for note in est.notes)


def test_missing_orderbook_falls_back_conservative_never_optimistic() -> None:
    est = estimate_round_trip_cost_bps(
        "NEWUSDT", get_json=_getter(None), notional_usd=250.0, now_utc=NOW
    )
    assert est.freshness_status == FRESHNESS_FALLBACK_CONSERVATIVE
    assert est.round_trip_cost_bps == FLAT_BASELINE_ROUND_TRIP_BPS
    assert est.spread_source == SPREAD_SOURCE_MISSING
    assert "orderbook_payload_missing" in est.notes


def test_wide_observed_spread_proxy_raises_fallback_above_flat() -> None:
    est = estimate_round_trip_cost_bps(
        "TAILUSDT",
        get_json=_getter(None),
        notional_usd=250.0,
        observed_spread_proxy_bps=14.0,
        now_utc=NOW,
    )
    # 10 fee + 14 proxy spread + 2*1 reserve = 26 > 12 flat.
    assert est.round_trip_cost_bps == 26.0
    assert est.freshness_status == FRESHNESS_FALLBACK_CONSERVATIVE


def test_reader_exception_is_contained_and_conservative() -> None:
    def _boom(key: str):
        raise RuntimeError("redis down")

    est = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_boom, notional_usd=250.0, now_utc=NOW
    )
    assert est.freshness_status == FRESHNESS_FALLBACK_CONSERVATIVE
    assert est.round_trip_cost_bps >= FLAT_BASELINE_ROUND_TRIP_BPS
    assert any(note.startswith("orderbook_read_failed") for note in est.notes)


def test_after_cost_sign_convention_matches_trainer() -> None:
    # long: move - cost; short: move + cost; hold: None (caller keeps trainer value)
    assert after_cost_for_action(9.96, "long", 10.02) == 9.96 - 10.02
    assert after_cost_for_action(-13.19, "short", 10.02) == -13.19 + 10.02
    assert after_cost_for_action(9.96, "hold", 10.02) is None
    assert after_cost_for_action(None, "long", 10.02) is None
    assert after_cost_for_action(9.96, "long", None) is None


def test_publish_cost_estimate_prefers_client_with_ttl() -> None:
    calls = {}

    class _Client:
        def set(self, key, value, ex=None):
            calls["key"] = key
            calls["ex"] = ex
            calls["value"] = value

    est = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(_book()), notional_usd=250.0, now_utc=NOW
    )
    assert publish_cost_estimate(est, client=_Client()) is True
    assert calls["key"] == "v2:costs:round_trip_bps:BTCUSDT"
    assert calls["ex"] == 600
    assert '"spread_source"' in calls["value"]
    assert '"freshness_status"' in calls["value"]


def test_publish_cost_estimate_never_raises() -> None:
    class _Broken:
        def set(self, key, value, ex=None):
            raise RuntimeError("write refused")

    est = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(None), notional_usd=250.0, now_utc=NOW
    )
    assert publish_cost_estimate(est, client=_Broken()) is False
