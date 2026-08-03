"""Symbol-adaptive round-trip cost model tests.

Operator requirement (2026-07-17): majors (BTC/ETH/SOL) must not be blocked
by a flat 12bps round-trip cost when live orderbook evidence proves their
real cost is lower; tail symbols with wide spreads must get honestly MORE
expensive. Missing/stale evidence must fall back CONSERVATIVE (never below
the flat baseline). Paper-only.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from v2.backend.app.services.native_trainer.hybrid_cuda_trainer.on_policy_behavior import (
    EXACT_COST_PROVENANCE_SCHEMA_VERSION,
    build_exact_cost_provenance,
)
from v2.backend.app.services.paper_trade_management import (
    adaptive_cost_model as adaptive_cost_module,
)
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

NOW = datetime(2026, 7, 17, 6, 0, 0, tzinfo=UTC)


def test_default_cost_fee_schedule_identity_matches_paper_entry_contract(
    monkeypatch,
) -> None:
    from v2.backend.app.cli import v2_trade_management_paper_loop as paper_loop

    monkeypatch.delenv("V2_COST_TAKER_FEE_BPS_PER_SIDE", raising=False)
    estimate = estimate_round_trip_cost_bps(
        "BTCUSDT",
        get_json=lambda _key: None,
        now_utc=NOW,
    )
    assert estimate.fee_schedule_evidence_sha256 == (
        paper_loop._fee_schedule_evidence_sha256(  # noqa: SLF001
            fee_bps_per_side=estimate.taker_fee_bps_per_side,
            fee_source=paper_loop.PAPER_CONFIGURED_FEE_SCHEDULE_SOURCE,
        )
    )


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
    available_at = NOW - timedelta(seconds=age_seconds)
    payload = {
        "schema_version": "v2_orderbook_features_v1",
        "symbol": "BTCUSDT",
        "event_time": (available_at - timedelta(milliseconds=100))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "available_at": available_at.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "generated_at": NOW.isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        ),
        "sequence_gap_flag": 0,
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


def test_adaptive_freshness_uses_robust_recent_cadence_and_binds_expiry() -> None:
    adaptive_cost_module._ORDERBOOK_AVAILABILITY_STATE.clear()  # noqa: SLF001

    def observed_book(now: datetime, available: datetime) -> dict:
        row = _book()
        row.update(
            {
                "event_time": (available - timedelta(milliseconds=100))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "available_at": available.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "generated_at": now.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
            }
        )
        return row

    observations = (
        (NOW, NOW - timedelta(seconds=1)),
        (NOW + timedelta(seconds=60), NOW + timedelta(seconds=59)),
        (NOW + timedelta(seconds=120), NOW + timedelta(seconds=119)),
        # One long source outage must not inflate the robust median+MAD window.
        (NOW + timedelta(seconds=720), NOW + timedelta(seconds=719)),
    )
    estimate = None
    for now, available in observations:
        estimate = estimate_round_trip_cost_bps(
            "BTCUSDT",
            get_json=_getter(observed_book(now, available)),
            notional_usd=250.0,
            now_utc=now,
        )
    assert estimate is not None
    assert estimate.adaptive_freshness_proven is True
    assert estimate.adaptive_freshness_sample_count == 3
    assert estimate.adaptive_freshness_method == (
        "RECENT_DISTINCT_SOURCE_INTERVAL_MEDIAN_PLUS_MAD"
    )
    assert estimate.adaptive_max_age_seconds == 60.0
    assert estimate.expires_at == "2026-07-17T06:12:59.000000Z"


def test_adaptive_freshness_proof_is_not_vetoed_by_legacy_static_max_age() -> None:
    adaptive_cost_module._ORDERBOOK_AVAILABILITY_STATE.clear()  # noqa: SLF001
    estimate = None
    for offset in (0, 10, 20, 30):
        now = NOW + timedelta(seconds=offset)
        available = now - timedelta(seconds=1)
        book = _book(age_seconds=1.0)
        book.update(
            {
                "event_time": (available - timedelta(milliseconds=100))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "available_at": available.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "generated_at": now.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
            }
        )
        estimate = estimate_round_trip_cost_bps(
            "BTCUSDT",
            get_json=_getter(book),
            notional_usd=250.0,
            max_orderbook_age_seconds=0.1,
            now_utc=now,
        )

    assert estimate is not None
    assert estimate.spread_age_seconds == 1.0
    assert estimate.spread_age_seconds > 0.1
    assert estimate.adaptive_freshness_proven is True
    assert estimate.adaptive_max_age_seconds == 10.0
    assert estimate.freshness_status == FRESHNESS_FRESH_ORDERBOOK
    assert estimate.conservative_floor_applied is False


def test_future_orderbook_clock_is_never_clamped_to_fresh() -> None:
    future = _book(age_seconds=-1.0)
    estimate = estimate_round_trip_cost_bps(
        "FUTUREUSDT",
        get_json=_getter(future),
        notional_usd=250.0,
        now_utc=NOW,
    )
    assert estimate.freshness_status == FRESHNESS_FALLBACK_CONSERVATIVE
    assert estimate.source_future_clock_invalid is True
    assert "orderbook_source_clock_in_future" in estimate.notes


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
            return True

    est = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(_book()), notional_usd=250.0, now_utc=NOW
    )
    assert publish_cost_estimate(est, client=_Client()) is True
    assert calls["key"] == "v2:costs:round_trip_bps:BTCUSDT"
    assert calls["ex"] == 600
    assert '"spread_source"' in calls["value"]
    assert '"freshness_status"' in calls["value"]


def test_published_adaptive_cost_is_directly_consumable_by_exact_ppo() -> None:
    adaptive_cost_module._ORDERBOOK_AVAILABILITY_STATE.clear()  # noqa: SLF001
    estimate = None
    for offset in (0, 10, 20, 30):
        now = NOW + timedelta(seconds=offset)
        available = now - timedelta(seconds=1)
        book = _book(age_seconds=1.0)
        book.update(
            {
                "event_time": (available - timedelta(milliseconds=100))
                .isoformat(timespec="milliseconds")
                .replace("+00:00", "Z"),
                "available_at": available.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
                "generated_at": now.isoformat(timespec="milliseconds").replace(
                    "+00:00", "Z"
                ),
            }
        )
        estimate = estimate_round_trip_cost_bps(
            "BTCUSDT",
            get_json=_getter(book),
            notional_usd=250.0,
            funding_bps_at_decision_time=0.25,
            funding_source="v2:features:latest:BTCUSDT:5m",
            now_utc=now,
        )

    assert estimate is not None
    published: dict[str, object] = {}

    class _Client:
        def set(self, key: str, value: str, ex: int | None = None) -> bool:
            published.update(
                {
                    "key": key,
                    "payload": json.loads(value),
                    "ttl": ex,
                }
            )
            return True

    assert publish_cost_estimate(estimate, client=_Client()) is True
    consumer_observed_at = (
        NOW + timedelta(seconds=30, milliseconds=500)
    ).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    provenance = build_exact_cost_provenance(
        source_key=str(published["key"]),
        source_payload=published["payload"],  # type: ignore[arg-type]
        consumer_observed_at=consumer_observed_at,
    )

    assert provenance["schema_version"] == EXACT_COST_PROVENANCE_SCHEMA_VERSION
    assert provenance["source_payload"]["publication_ttl_seconds"] == published[
        "ttl"
    ]
    assert provenance["orderbook_source_payload_sha256"] == (
        estimate.orderbook_source_payload_sha256
    )
    payload = published["payload"]
    assert isinstance(payload, dict)
    assert payload["source_event_time"] <= payload["producer_generated_at"]
    assert payload["producer_generated_at"] == payload["record_available_at"]
    assert payload["record_available_at"] < payload["expires_at"]
    assert payload["fee_bps_per_side"] == estimate.taker_fee_bps_per_side
    assert payload["slippage_bps_per_side"] == estimate.impact_per_side_bps
    assert payload["funding_bps_at_decision_time"] == 0.25
    assert payload["source_payload_sha256"] == payload["source_readback_sha256"]
    assert payload["source_readback_verified"] is True


def test_published_exact_cost_preserves_submillisecond_age_identity() -> None:
    adaptive_cost_module._ORDERBOOK_AVAILABILITY_STATE.clear()  # noqa: SLF001
    estimate = None
    base = NOW.replace(microsecond=987654)
    for offset in (0, 10, 20, 30):
        now = base + timedelta(seconds=offset)
        available = now - timedelta(seconds=1, microseconds=123456)
        book = _book(age_seconds=1.0)
        book.update(
            {
                "event_time": (available - timedelta(milliseconds=100))
                .isoformat(timespec="microseconds")
                .replace("+00:00", "Z"),
                "available_at": available.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                ),
                "generated_at": now.isoformat(timespec="microseconds").replace(
                    "+00:00", "Z"
                ),
            }
        )
        estimate = estimate_round_trip_cost_bps(
            "BTCUSDT",
            get_json=_getter(book),
            notional_usd=250.0,
            now_utc=now,
        )

    assert estimate is not None
    payload = estimate.to_payload()
    payload["publication_ttl_seconds"] = 9
    provenance = build_exact_cost_provenance(
        source_key="v2:costs:round_trip_bps:BTCUSDT",
        source_payload=payload,
        consumer_observed_at=(base + timedelta(seconds=30, milliseconds=100))
        .isoformat(timespec="microseconds")
        .replace("+00:00", "Z"),
    )
    assert provenance["schema_version"] == EXACT_COST_PROVENANCE_SCHEMA_VERSION
    assert payload["spread_age_seconds"] == 1.123456


def test_publish_cost_estimate_never_raises() -> None:
    class _Broken:
        def set(self, key, value, ex=None):
            raise RuntimeError("write refused")

    est = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(None), notional_usd=250.0, now_utc=NOW
    )
    assert publish_cost_estimate(est, client=_Broken()) is False


def test_publish_cost_estimate_rejects_unacknowledged_or_non_ttl_writer() -> None:
    class _Unacknowledged:
        def set(self, _key, _value, ex=None):
            del ex
            return None

    est = estimate_round_trip_cost_bps(
        "BTCUSDT", get_json=_getter(None), notional_usd=250.0, now_utc=NOW
    )

    assert publish_cost_estimate(est, client=_Unacknowledged()) is False
    assert publish_cost_estimate(est, set_json=lambda _key, _payload: True) is False
